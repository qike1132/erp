"""M-2（评审补充）回归：批量下单抵扣量按实扣回写（2026-11-21 全量审计）。

M-1 修复本体：``_create_order_items`` 落库的 ``OrderItem.deduct_quantity`` 只按
订单量收口，而实扣在 ``process_order_deduction`` 再按可用备货收口——备货不足时
「落库抵扣量 ≠ 实扣」，purchase/_unprocessed 把该列当「已抵扣」展示。修复=
``_process_deductions`` 取实扣量回写明细（order_batch_create.py:313）。

本测试走真实 DB：可用备货 2、下单填抵扣 5 → 实扣 2，明细列必须被回写成 2
（修复前落 5）。变异检查：删掉回写行此测试必红。
"""
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from fastapi_app.services.order_batch_create import batch_create_orders
from fastapi_app.shared_models import OrderItem, Product, StockIn


async def test_deduct_quantity_writeback_clamped_to_available(app_on_test_db, async_db_session):
    """app_on_test_db：编号内核独立短事务走全局引擎——先 ensure 重定向后的引擎。"""
    from fastapi_app.core.database import ensure_engine_for_current_loop
    await ensure_engine_for_current_loop()
    db = async_db_session
    suffix = uuid4().hex[:8]
    product = Product(name=f'回写产品-{suffix}', current_stock=100)
    db.add(product)
    await db.flush()
    # 可用备货 = 2（备货入库 2 件）；订单填抵扣意愿 5 → 实扣收口到 2
    db.add(StockIn(
        stockin_no=f'SI-WB-{suffix}', product_id=product.id, quantity=2,
        customer='客户甲', stockin_date=datetime(2026, 11, 21, tzinfo=UTC),
    ))
    await db.flush()

    result = await batch_create_orders(db, [{
        'customer': '客户甲', 'product_id': product.id, 'quantity': 5,
        'deduct_stock': True, 'deduct_quantity': 5,
    }])
    assert result['success'] is True, result

    # CI 教训：全量跑时其他测试会留 OrderItem 行（次序与本地不同）——按本单产品过滤
    item = (await db.execute(
        select(OrderItem).where(OrderItem.product_id == product.id)
    )).scalars().first()
    assert item is not None
    assert item.deduct_quantity == 2, (
        '落库抵扣量应按实扣收口为 2（修复前落意愿值 5，M-1 分叉复现）')
    # 库存实扣也对：current_stock 只被抵扣路径动 2 件（100-2）
    db.expire(product)
    await db.refresh(product)
    assert product.current_stock == 98
