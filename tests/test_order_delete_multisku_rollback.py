"""多 SKU 订单删除的库存回滚必须逐 SKU 归位（P0-1 回归，2026-10-18 审计）。

背景：``_rollback_order_stock_deduction``（直删）与 ``_rollback_deduction_for_approval``
（审批删）原先把「整张订单全部 SKU 的净扣减量」一次性加回 ``order.product_id``
（首 SKU 兼容值）锁定的单行 Product 上，InventoryLog 也全记首 SKU——
每删一张多 SKU 订单必然导致：首 SKU 库存虚增、其余 SKU 漏回滚、
流水无法还原真实变动。本文件锁定**逐 SKU 回滚**语义：
按 ``stockout.product_id`` 分组，各自加回净扣减量并记各自流水。

五件套：
- 文件:行号：services/order/commands.py::_rollback_order_stock_deduction（直删）、
  services/approval_service.py::_rollback_deduction_for_approval（审批删）
- 根因：回滚目标取 order.product_id（首 SKU 兼容值），与多 SKU 出库行的
  真实 product 归属（StockOut.product_id 非空 FK）不一致
- 触发：删除任一含 OrderItem 明细 + 多 SKU 抵扣出库的订单（直删或审批删）
- 复现：2 SKU 各抵扣 10 → 删除订单 → 旧实现首 SKU +20、次 SKU +0
- 修法：按 stockout.product_id 分组逐行回滚，InventoryLog 逐产品记录
"""
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from fastapi_app.services.approval_service import approve_request
from fastapi_app.services.order.commands import delete_order
from fastapi_app.shared_models import (
    ApprovalLog,
    ApprovalRequest,
    InventoryLog,
    Order,
    OrderItem,
    Product,
    StockOut,
)

pytestmark = pytest.mark.integration

_ORDER_PREFIX = 'MSRB-O-'
_BARCODE_A = 'MSRB-PA'
_BARCODE_B = 'MSRB-PB'
_QUANTITY = 10


def _make_products(session):
    """两个产品（多 SKU 订单的 SKU-A / SKU-B），库存各 100。"""
    pa = Product(name='MSRB 产品A', barcode=_BARCODE_A, current_stock=100, initial_stock=100)
    pb = Product(name='MSRB 产品B', barcode=_BARCODE_B, current_stock=100, initial_stock=100)
    session.add_all([pa, pb])
    return pa, pb


async def _make_multi_sku_order(session, pa, pb, order_no, customer):
    """一张双 SKU 订单：order.product_id 兼容值取首 SKU；出库行各挂各的产品。"""
    order = Order(
        order_no=order_no, customer=customer, order_date=datetime.now(UTC),
        product_id=pa.id, quantity=_QUANTITY * 2, status='部分备货',
    )
    session.add(order)
    await session.flush()
    session.add_all([
        OrderItem(order_id=order.id, product_id=pa.id, quantity=_QUANTITY),
        OrderItem(order_id=order.id, product_id=pb.id, quantity=_QUANTITY),
        StockOut(stockout_no=f'{order_no}-A', product_id=pa.id, order_id=order.id,
                 customer=customer, quantity=_QUANTITY, stockout_date=datetime.now(UTC)),
        StockOut(stockout_no=f'{order_no}-B', product_id=pb.id, order_id=order.id,
                 customer=customer, quantity=_QUANTITY, stockout_date=datetime.now(UTC)),
    ])
    return order


@pytest_asyncio.fixture
async def msrb_cleanup(async_db_session):
    """清掉本文件造的行（共享测试库只在会话开始整库重置）。

    删产品前先清其 InventoryLog（裸删，不走 service）——否则外键
    ON DELETE SET NULL 会留下无主孤儿流水污染后续用例。
    """
    yield
    order_ids = select(Order.id).where(Order.order_no.like(f'{_ORDER_PREFIX}%'))
    approval_ids = select(ApprovalRequest.id).where(ApprovalRequest.order_id.in_(order_ids))
    await async_db_session.execute(
        delete(ApprovalLog).where(ApprovalLog.approval_request_id.in_(approval_ids)))
    await async_db_session.execute(
        delete(ApprovalRequest).where(ApprovalRequest.order_id.in_(order_ids)))
    await async_db_session.execute(
        delete(StockOut).where(StockOut.order_id.in_(order_ids)))
    await async_db_session.execute(
        delete(OrderItem).where(OrderItem.order_id.in_(order_ids)))
    await async_db_session.execute(
        delete(Order).where(Order.id.in_(order_ids)))
    product_ids = select(Product.id).where(
        Product.barcode.in_([_BARCODE_A, _BARCODE_B]))
    await async_db_session.execute(
        delete(InventoryLog).where(InventoryLog.product_id.in_(product_ids)))
    await async_db_session.execute(
        delete(Product).where(Product.barcode.in_([_BARCODE_A, _BARCODE_B])))
    await async_db_session.commit()


async def _assert_per_sku_rollback(session, order_no, pa, pb):
    """断言逐 SKU 回滚：两个产品各 +10，流水各记自己的 product_id。"""
    await session.refresh(pa)
    await session.refresh(pb)
    assert pa.current_stock == 100 + _QUANTITY, (
        f'SKU-A 库存应 +{_QUANTITY}（原 100），实际 {pa.current_stock}——'
        '多 SKU 订单删除不得把全部净扣减量回滚到首 SKU')
    assert pb.current_stock == 100 + _QUANTITY, (
        f'SKU-B 库存应 +{_QUANTITY}（原 100），实际 {pb.current_stock}——'
        '次 SKU 的净扣减量不得在删除时丢失')

    for product, name in ((pa, 'SKU-A'), (pb, 'SKU-B')):
        log_rows = (await session.execute(
            select(InventoryLog.change_quantity).where(
                InventoryLog.product_id == product.id,
                InventoryLog.change_type == '抵扣回滚',
                InventoryLog.related_id == order_no,
            ))).scalars().all()
        assert sum(log_rows) == _QUANTITY, (
            f'{name} 的抵扣回滚流水应记净 {_QUANTITY} 件，实际 {log_rows}——'
            '流水 product_id 必须与被回滚的 SKU 一致，否则账实无法还原')


async def _order_summary_rows(session, order_no, change_type):
    """取本订单某 change_type 的汇总流水 change_quantity 列表。"""
    return (await session.execute(
        select(InventoryLog.change_quantity).where(
            InventoryLog.change_type == change_type,
            InventoryLog.related_id == order_no,
        ))).scalars().all()


async def _assert_single_summary(session, order_no, expected_total):
    """断言订单级汇总：恰好一条「订单删除」汇总且值=实际回滚量（直删路径）。"""
    rows = await _order_summary_rows(session, order_no, '订单删除')
    assert rows == [expected_total], (
        f'直删应恰写一条「订单删除」汇总（值 {expected_total}），实际 {rows}——'
        '多写或漏写都会让按 product 聚合 change_quantity 的对账口径失真')


async def _assert_approval_summary_only(session, order_no, expected_total):
    """断言审批删的汇总口径（2026-10-19 OCR 第二轮 M3）。

    审批路径自写一条「订单删除(审批)」（值=实际回滚量），共享实现传
    write_summary=False 不再写「订单删除」——否则同一笔回滚两条汇总，
    inventory_reconcile 按 product 聚合 change_quantity 会重复计数。
    """
    rows = await _order_summary_rows(session, order_no, '订单删除(审批)')
    assert rows == [expected_total], (
        f'审批删应恰写一条「订单删除(审批)」汇总（值=实际回滚量 '
        f'{expected_total}），实际 {rows}')
    plain = await _order_summary_rows(session, order_no, '订单删除')
    assert plain == [], (
        f'审批删不得再写「订单删除」汇总（write_summary=False），实际 {plain}——'
        '双汇总会让按 product 聚合的对账重复计数')


class TestDirectDeleteMultiSkuRollback:
    """直删路径（超管 delete_order → _delete_order_directly）。"""

    async def test_direct_delete_rolls_back_each_sku(
        self, async_db_session, admin_user, test_customer, msrb_cleanup,
    ):
        pa, pb = _make_products(async_db_session)
        await async_db_session.flush()
        order = await _make_multi_sku_order(
            async_db_session, pa, pb, f'{_ORDER_PREFIX}001', test_customer.name)
        await async_db_session.flush()

        await delete_order(async_db_session, order.id, admin_user)
        await async_db_session.flush()

        assert order.is_deleted is True, '订单应被软删除'
        await _assert_per_sku_rollback(
            async_db_session, f'{_ORDER_PREFIX}001', pa, pb)
        # 直删汇总（write_summary 默认 True）：恰一条「订单删除」，值=实际回滚量
        await _assert_single_summary(
            async_db_session, f'{_ORDER_PREFIX}001', _QUANTITY * 2)


class TestApprovalDeleteMultiSkuRollback:
    """审批删路径（approve_request → _handle_delete_approval）。"""

    async def test_approval_delete_rolls_back_each_sku(
        self, async_db_session, admin_user, normal_user, test_customer, msrb_cleanup,
    ):
        pa, pb = _make_products(async_db_session)
        await async_db_session.flush()
        order = await _make_multi_sku_order(
            async_db_session, pa, pb, f'{_ORDER_PREFIX}002', test_customer.name)
        await async_db_session.flush()
        approval = ApprovalRequest(
            order_id=order.id, requester_id=normal_user.id,
            operation_type=ApprovalRequest.OPERATION_DELETE,
            status=ApprovalRequest.STATUS_PENDING,
        )
        async_db_session.add(approval)
        await async_db_session.flush()

        await approve_request(async_db_session, approval.id, admin_user)
        await async_db_session.flush()

        assert order.is_deleted is True, '审批通过后订单应被软删除'
        await _assert_per_sku_rollback(
            async_db_session, f'{_ORDER_PREFIX}002', pa, pb)
        # 审批删汇总口径（M3）：仅一条「订单删除(审批)」（值=实际回滚量），
        # 不得再有「订单删除」——双汇总会让 inventory_reconcile 重复计数
        await _assert_approval_summary_only(
            async_db_session, f'{_ORDER_PREFIX}002', _QUANTITY * 2)
