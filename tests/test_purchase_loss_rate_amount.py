"""采购单「损耗率 → 行金额 / 订单金额」的传导口径回归测试。

2026-10-21 OCR 评审（分支 fix/audit-2026-10-18）发现两处口径断裂：

1. **只改订单级损耗率，金额不动**：``save_factory_summary_edits`` 把订单级
   ``spare_rate`` 写进采购单，却不重算该单的行金额 —— 而行金额的有效损耗率
   回退链正是「逐行 loss_rate → 订单级 spare_rate」，于是该单的行金额停留在
   旧口径，「明细金额之和 ≠ 采购单金额」。
2. **同一张单混着两种口径**：重算只覆盖被编辑的那几行，采购单总金额却按
   **全部**行求和 —— 一行按新率、一行按旧率，合计既不是旧口径也不是新口径。

本文件锁住三件事：

1. 改订单级损耗率（哪怕一行布料都没改）→ 该单**每一行**的金额都重算；
2. 重算后采购单总金额 == 各行金额之和（同一口径）；
3. 已完成订单的 Excel 导出里，「数量 × 单价 == 金额」（数量用计价数量）。

走真实测试库（``async_db_session``），因为这三件事都要过真实的 SELECT/UPDATE。
"""
from decimal import Decimal

import pytest
from sqlalchemy import select

from fastapi_app.services.purchase_order_crud import (
    _recalc_item_total_price,
    save_factory_summary_edits,
)
from fastapi_app.services.purchase_order_query import export_completed_orders
from fastapi_app.shared_models import PurchaseOrder, PurchaseOrderItem, PurchaseOrderStatus


async def _make_order(db, *, order_no='CR-0001', spare_rate=None, product_quantity=100):
    order = PurchaseOrder(
        order_no=order_no,
        supplier_name='供应商A',
        customer_name='客户A',
        status=PurchaseOrderStatus.PENDING,
        product_quantity=product_quantity,
        spare_rate=Decimal(str(spare_rate)) if spare_rate is not None else None,
        total_amount=Decimal('0'),
    )
    db.add(order)
    await db.flush()
    return order


async def _make_item(db, order, *, material_name='布料A', quantity='100',
                     unit_price='5', loss_rate=None, total_price=None):
    item = PurchaseOrderItem(
        order_id=order.id,
        material_name=material_name,
        unit='码',
        quantity=Decimal(quantity),
        unit_price=Decimal(unit_price),
        total_price=Decimal(total_price) if total_price is not None else Decimal('0'),
        loss_rate=Decimal(str(loss_rate)) if loss_rate is not None else None,
    )
    db.add(item)
    await db.flush()
    return item


async def _reload_item(db, item_id: int) -> PurchaseOrderItem:
    return (await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.id == item_id)
    )).scalars().one()


class TestOrderLevelRateReachesLineAmounts:
    """F1：订单级损耗率改了，行金额与订单金额必须跟着走"""

    @pytest.mark.asyncio
    async def test_rate_only_edit_recalculates_line_amounts(self, async_db_session):
        """只改订单级损耗率、没改任何布料行 → 该单的行金额仍要重算。

        旧实现只在「有编辑项」时才重算，且只重算被编辑的那几行：
        用户在汇总弹窗里只动损耗率时，采购单金额是旧口径，供应商金额汇总随之失真。
        """
        order = await _make_order(async_db_session, order_no='CR-F1-1')
        item = await _make_item(async_db_session, order, total_price='500')  # 100 × 5，旧口径

        await save_factory_summary_edits(
            async_db_session, [], spare_rate=1000, order_ids=[order.id],
        )

        # 100 × (1 + 1000‰) = 200 → 200 × 5 = 1000
        assert item.total_price == Decimal('1000.00'), item.total_price
        assert order.total_amount == Decimal('1000.00'), order.total_amount
        assert Decimal(str(order.spare_rate)) == Decimal('1000')
        # 落库值也要是 1000（不是只在内存里算对）
        assert (await _reload_item(async_db_session, item.id)).total_price == Decimal('1000.00')

    @pytest.mark.asyncio
    async def test_untouched_lines_share_the_new_caliber(self, async_db_session):
        """改了订单级损耗率 → 该单**全部**行都按新率计价，不能一行新一行旧。

        旧实现只重算被编辑的行，订单总金额却按全部行求和 —— 合计是两种口径的混合。
        """
        order = await _make_order(async_db_session, order_no='CR-F2-1')
        a = await _make_item(async_db_session, order, material_name='布料A',
                             quantity='100', unit_price='5', total_price='500')
        b = await _make_item(async_db_session, order, material_name='布料B',
                             quantity='200', unit_price='2', total_price='400')

        await save_factory_summary_edits(
            async_db_session, [], spare_rate=1000, order_ids=[order.id],
        )

        # A: 100 × 2 = 200 → × 5 = 1000；B: 200 × 2 = 400 → × 2 = 800
        assert a.total_price == Decimal('1000.00'), a.total_price
        assert b.total_price == Decimal('800.00'), b.total_price
        # 订单总金额 == 同一口径下各行之和（不是「新旧混合」）
        assert order.total_amount == Decimal('1800.00'), order.total_amount
        assert order.total_amount == (a.total_price + b.total_price)

    @pytest.mark.asyncio
    async def test_line_rate_edit_keeps_order_total_consistent(self, async_db_session):
        """逐行损耗率编辑 → 该单所有行按各自有效率重算，总金额 = 各行之和。"""
        order = await _make_order(async_db_session, order_no='CR-F2-2')
        a = await _make_item(async_db_session, order, material_name='布料A',
                             quantity='100', unit_price='5', loss_rate=1000, total_price='500')
        b = await _make_item(async_db_session, order, material_name='布料B',
                             quantity='200', unit_price='2', total_price='400')

        await save_factory_summary_edits(
            async_db_session,
            [{'item_ids': [a.id], 'loss_rate': 1000}],
            order_ids=[order.id],
        )

        # A 逐行率 1000‰：100 × 2 = 200 → × 5 = 1000
        assert a.total_price == Decimal('1000.00'), a.total_price
        # B 无逐行率、订单级也无率 → 保持 200 × 2 = 400
        assert b.total_price == Decimal('400.00'), b.total_price
        assert order.total_amount == Decimal('1400.00'), order.total_amount
        assert order.total_amount == (a.total_price + b.total_price)

    @pytest.mark.asyncio
    async def test_no_rate_and_no_edit_leaves_amount_untouched(self, async_db_session):
        """既没有损耗率、也没有编辑 → 不该动金额（零回归）。"""
        order = await _make_order(async_db_session, order_no='CR-F2-3')
        item = await _make_item(async_db_session, order, total_price='500')

        await save_factory_summary_edits(async_db_session, [], order_ids=[order.id])

        assert item.total_price == Decimal('500'), item.total_price
        assert order.total_amount == Decimal('0'), order.total_amount


class TestLineTotalQuantization:
    """行金额按落库列精度（Numeric(12,2)）取整，方向与 PG 一致"""

    def test_rounds_half_up_like_postgres(self):
        """PG 的 numeric 是「逢五进位」；Python 默认的银行家舍入会差 0.01。"""
        item = PurchaseOrderItem(material_name='X', quantity=Decimal('1'),
                                  unit_price=Decimal('2.665'))
        _recalc_item_total_price(item, None)
        assert item.total_price == Decimal('2.67'), item.total_price

    def test_keeps_two_decimals(self):
        item = PurchaseOrderItem(material_name='X', quantity=Decimal('3'),
                                  unit_price=Decimal('2.5'))
        _recalc_item_total_price(item, None)
        assert item.total_price == Decimal('7.50'), item.total_price


class TestCompletedOrdersExportCaliber:
    """F3：导出表里「数量 × 单价 == 金额」"""

    @pytest.mark.asyncio
    async def test_export_quantity_matches_amount(self, async_db_session):
        """导出的「数量」用计价数量，与同一行的「金额」同源。

        旧实现给的是落库原值：损耗率 > 0 时导出表里必然出现
        「数量 × 单价 ≠ 金额」，对账时分不清是导出错了还是单价错了。
        """
        from datetime import UTC, datetime

        order = await _make_order(async_db_session, order_no='CR-EXP-1', spare_rate=1000)
        order.status = PurchaseOrderStatus.COMPLETED
        order.completed_at = datetime.now(UTC).replace(tzinfo=None)
        await async_db_session.flush()
        # 金额已按 1000‰ 加放后落库（200 × 5 = 1000）
        await _make_item(async_db_session, order, quantity='100', unit_price='5',
                         total_price='1000')

        rows = await export_completed_orders(async_db_session)

        assert rows, '导出应有明细行'
        row = rows[0]
        assert row['quantity'] == pytest.approx(200), row
        assert row['amount'] == pytest.approx(1000), row
        assert row['quantity'] * row['unit_price'] == pytest.approx(row['amount']), row

    @pytest.mark.asyncio
    async def test_export_without_loss_rate_keeps_raw_quantity(self, async_db_session):
        """没有损耗率时，计价数量 == 落库数量（零回归）。"""
        from datetime import UTC, datetime

        order = await _make_order(async_db_session, order_no='CR-EXP-2')
        order.status = PurchaseOrderStatus.COMPLETED
        order.completed_at = datetime.now(UTC).replace(tzinfo=None)
        await async_db_session.flush()
        await _make_item(async_db_session, order, quantity='100', unit_price='5',
                         total_price='500')

        rows = await export_completed_orders(async_db_session)

        row = rows[0]
        assert row['quantity'] == pytest.approx(100), row
        assert row['amount'] == pytest.approx(500), row
