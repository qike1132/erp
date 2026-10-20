"""P1-6：外发单旧订单工序「面板可见、发货必拒」回归。

面板（list_shippable_processes）用 ``coalesce(order_item.quantity, order.quantity)``
展示目标量并计入剩余，发货（ship_order_process → _process_target_quantity）却因
order_item_id 为空直接 fail-closed——旧单工序可点、提交必拒。修复后两端口径一致：
仅当订单确实没有 SKU 明细（真正的单 SKU 旧订单）时回退整单数量；订单已有 SKU
明细却挂空 order_item_id（脏数据）时仍 fail-closed，防止按整单量超发。
"""
from unittest.mock import patch

import pytest

from fastapi_app.shared_models import (
    Order,
    OrderItem,
    OrderOutsourceProcess,
    OrderOutsourceProcessFlow,
    Product,
)


@pytest.fixture
async def session_factory(tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "legacy-ship.db"}')
    async with engine.begin() as conn:
        for table in (
            Product.__table__, Order.__table__, OrderItem.__table__,
            OrderOutsourceProcess.__table__, OrderOutsourceProcessFlow.__table__,
        ):
            await conn.run_sync(lambda c, t=table: t.create(c, checkfirst=True))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_order_process_ships_with_order_quantity(session_factory):
    from fastapi_app.services.outsource_service import list_shippable_processes, ship_order_process

    async with session_factory() as session:
        session.add(Product(id=1, name='旧款单SKU', factory='湖北'))
        session.add(Order(id=1, order_no='PO-OLD', customer='C', product_id=1, quantity=100))
        session.add(OrderOutsourceProcess(
            id=1, order_id=1, order_item_id=None, product_id=1, product_name='旧款单SKU',
            process_type='电绣', sort_order=1, status='pending',
        ))
        await session.commit()

    async with session_factory() as session:
        rows = await list_shippable_processes(session)
    # 面板可见：目标量回退订单数量（修复前也可见，这正是缺陷的另一半）
    assert [(r['target_qty'], r['remaining']) for r in rows] == [(100, 100)]

    async with session_factory() as session:
        shipped = await ship_order_process(session, 1, 40, username='admin')
        await session.commit()
    assert shipped['shipped_quantity'] == 40

    async with session_factory() as session:
        rows = await list_shippable_processes(session)
    assert [(r['target_qty'], r['remaining']) for r in rows] == [(100, 60)]


@pytest.mark.asyncio
async def test_multi_sku_order_with_null_item_still_fails_closed(session_factory):
    """有 SKU 明细却挂空 order_item_id（脏数据）时不得按整单量放行。"""
    from fastapi_app.services.outsource_service import ship_order_process

    async with session_factory() as session:
        session.add(Product(id=1, name='SKU1', factory='湖北'))
        session.add(Order(id=1, order_no='PO-1', customer='C', product_id=1, quantity=100))
        session.add(OrderItem(id=10, order_id=1, product_id=1, quantity=30))
        session.add(OrderOutsourceProcess(
            id=1, order_id=1, order_item_id=None, product_id=1, product_name='SKU1',
            process_type='电绣', sort_order=1, status='pending',
        ))
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(ValueError, match='无法解析目标数量'):
            await ship_order_process(session, 1, 40, username='admin')


@pytest.mark.asyncio
async def test_target_qty_falls_back_only_when_order_has_no_sku(session_factory):
    """单元层锁定回退条件：无 SKU → 整单量；有 SKU 但空 item → 抛错。"""
    from fastapi_app.services.outsource._queries import _process_target_quantity

    async with session_factory() as session:
        session.add(Product(id=1, name='P', factory='湖北'))
        session.add(Order(id=1, order_no='PO-LEGACY', customer='C', product_id=1, quantity=77))
        session.add(OrderOutsourceProcess(
            id=1, order_id=1, order_item_id=None, product_id=1, product_name='P',
            process_type='电绣', sort_order=1, status='pending',
        ))
        await session.commit()
        proc = await session.get(OrderOutsourceProcess, 1)
        assert await _process_target_quantity(session, proc) == 77

    async with session_factory() as session:
        session.add(Order(id=2, order_no='PO-MULTI', customer='C', product_id=1, quantity=100))
        session.add(OrderItem(id=20, order_id=2, product_id=1, quantity=30))
        session.add(OrderOutsourceProcess(
            id=2, order_id=2, order_item_id=None, product_id=1, product_name='P',
            process_type='电绣', sort_order=1, status='pending',
        ))
        await session.commit()
        proc = await session.get(OrderOutsourceProcess, 2)
        with patch('fastapi_app.services.outsource._queries.logger'):
            with pytest.raises(ValueError, match='无法解析目标数量'):
                await _process_target_quantity(session, proc)
