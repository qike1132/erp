"""M-4 / M-5 回归（2026-11-21 全量审计）。

M-4：cleanup_orphan_pending_purchase_orders 的 JSON 数组兜底路径（b 路径）此前
无「id 同存于 order 与 stockin 表视为歧义不采信」守卫（c 路径有）——存量无 SKU
快照的 pending 单把备货 id 存进 source_order_ids，删同号客户订单时误删备货来源单。
M-5：purchase_plan_service 的库存事件重算 handler 此前吞异常不冒泡——dispatcher
不知道 handler 失败、不落 stage=handler 死信，计划 shipped_qty 静默停留旧值。
"""
import json

import pytest
from sqlalchemy import func, select

from fastapi_app.services import purchase_plan_service as pps
from fastapi_app.shared_models import Order, Product, PurchaseOrder, StockIn


async def test_cleanup_json_path_skips_ambiguous_ids(app_on_test_db, async_db_session):
    """备货 id 同时存在于 order 与 stockin 表 → JSON 兜底不得采信它删单。"""
    db = async_db_session
    product = Product(name='M4产品甲', current_stock=10)
    db.add(product)
    await db.flush()
    # 同一个 id 同时作为 Order 与 StockIn 存在（歧义 id）
    db.add(Order(id=990001, order_no='M4-ORD-1', customer='客户甲', quantity=1))
    db.add(StockIn(id=990001, product_id=product.id, quantity=1, stockin_no='M4-SI-1',
                   customer='客户甲'))
    await db.flush()
    po = PurchaseOrder(order_no='M4-PO-1', supplier_name='供应商甲', customer_name='客户甲',
                       status='pending', source_order_ids=json.dumps([990001]))
    db.add(po)
    await db.flush()

    from fastapi_app.services.purchase_order_crud import (
        cleanup_orphan_pending_purchase_orders,
    )
    await cleanup_orphan_pending_purchase_orders(db, order_ids=[990001])
    await db.flush()  # 函数契约不 flush（交给事务层），断言前显式刷

    left = (await db.execute(
        select(func.count()).select_from(PurchaseOrder)
        .where(PurchaseOrder.order_no == 'M4-PO-1')
    )).scalar()
    assert left == 1, '歧义 id 不应触发 JSON 兜底删单（修复前误删）'


async def test_cleanup_json_path_still_cleans_unambiguous_stockin_id(app_on_test_db, async_db_session):
    """防修复误伤：id 只存在于 stockin 表（典型备货来源）时 JSON 兜底仍清理。"""
    db = async_db_session
    product = Product(name='M4产品乙', current_stock=10)
    db.add(product)
    await db.flush()
    db.add(StockIn(id=990003, product_id=product.id, quantity=1, stockin_no='M4-SI-3',
                   customer='客户甲'))
    await db.flush()
    po = PurchaseOrder(order_no='M4-PO-3', supplier_name='供应商甲', customer_name='客户甲',
                       status='pending', source_order_ids=json.dumps([990003]))
    db.add(po)
    await db.flush()

    from fastapi_app.services.purchase_order_crud import (
        cleanup_orphan_pending_purchase_orders,
    )
    await cleanup_orphan_pending_purchase_orders(db, stockin_ids=[990003])
    await db.flush()  # 同上

    left = (await db.execute(
        select(func.count()).select_from(PurchaseOrder)
        .where(PurchaseOrder.order_no == 'M4-PO-3')
    )).scalar()
    assert left == 0, '非歧义的备货来源单应被正常清理'


async def test_stock_handler_reraises_for_deadletter(monkeypatch):
    """M-5：重算失败必须冒泡给 dispatcher（落死信），不得吞成一行日志。"""
    async def _boom(db, customer_name, product_name):
        raise RuntimeError('重算炸了')

    monkeypatch.setattr(pps, 'recalc_plans_after_stockout_create', _boom)
    handler = pps._make_stock_handler('TEST_EVENT', need_recalc_create=True,
                                      need_recalc_delete=False)

    event = type('E', (), {'payload': {'customer': '客户甲', 'product_name': '产品甲'}})()
    with pytest.raises(RuntimeError, match='重算炸了'):
        await handler(event)
