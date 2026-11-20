"""外发状态筛选：SQL 下推后的行为回归（审计 M-05 / 评审 M-1）。"""
import uuid

import pytest

from fastapi_app.services.outsource import _queries


async def _session(tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from fastapi_app.shared_models import (
        Order,
        OrderItem,
        OrderOutsourceProcess,
        Product,
        StockIn,
        User,
    )

    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "outsource_status.db"}')
    async with engine.begin() as conn:
        for table in (
            User.__table__, Product.__table__, Order.__table__,
            OrderItem.__table__, OrderOutsourceProcess.__table__, StockIn.__table__,
        ):
            await conn.run_sync(lambda c, t=table: t.create(c, checkfirst=True))
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session, customer: str):
    from datetime import UTC, datetime

    from fastapi_app.shared_models import Order, OrderItem, OrderOutsourceProcess, Product

    session.add(Product(id=1, name='M1产品', barcode='M1-SKU', factory='湖北'))
    for i, (shipped, received) in enumerate(((0, 0), (5, 0), (5, 5)), start=1):
        session.add(Order(
            id=i, order_no=f'PO-M1-{i}', customer=customer, product_id=1,
            quantity=10, order_date=datetime.now(UTC), status='待备货',
        ))
        session.add(OrderItem(
            id=10 + i, order_id=i, product_id=1, product_name='M1产品',
            product_barcode='M1-SKU', quantity=10,
        ))
        session.add(OrderOutsourceProcess(
            id=20 + i, order_id=i, order_item_id=10 + i, product_id=1,
            product_name='M1产品', process_type='电绣', sort_order=1,
            status='pending', shipped_quantity=shipped, received_quantity=received,
        ))
    await session.commit()


@pytest.mark.asyncio
async def test_process_status_is_pushed_to_beile_query(monkeypatch):
    """状态筛选必须把 SQL 条件下推，且排除备货行（评审 M-1）。"""
    calls: list[dict] = []

    async def fake_beile(db, **kwargs):
        calls.append(kwargs)
        return {'items': [], 'total': 0, 'page': 1, 'per_page': 50}

    monkeypatch.setattr(
        'fastapi_app.services.order_crud.get_beile_orders_with_stockins',
        fake_beile,
    )

    await _queries.list_outsource_orders(None, process_status='pending')

    assert len(calls) == 1, '不得再逐页扫描'
    kwargs = calls[0]
    assert kwargs['include_stockins'] is False
    assert kwargs['order_filter'] is not None
    assert kwargs['cache_variant'] == 'process_status:pending'
    assert kwargs['skip_po_maps'] is True


@pytest.mark.asyncio
async def test_process_status_is_filtered_and_paginated_in_sql(tmp_path):
    engine, factory = await _session(tmp_path)
    customer = f'M1-{uuid.uuid4().hex}'
    try:
        async with factory() as session:
            await _seed(session, customer)
            pending = await _queries.list_outsource_orders(
                session, page=1, per_page=50, customer=customer,
                process_status='pending',
            )
            in_progress = await _queries.list_outsource_orders(
                session, page=1, per_page=50, customer=customer,
                process_status='in_progress',
            )
            completed = await _queries.list_outsource_orders(
                session, page=1, per_page=50, customer=customer,
                process_status='completed',
            )
            all_rows = await _queries.list_outsource_orders(
                session, page=1, per_page=50, customer=customer,
            )

        assert [r['order_no'] for r in pending['items']] == ['PO-M1-1']
        assert pending['total'] == 1
        assert [r['order_no'] for r in in_progress['items']] == ['PO-M1-2']
        assert in_progress['total'] == 1
        assert [r['order_no'] for r in completed['items']] == ['PO-M1-3']
        assert completed['total'] == 1
        assert {r['order_no'] for r in all_rows['items']} == {
            'PO-M1-1', 'PO-M1-2', 'PO-M1-3',
        }
    finally:
        await engine.dispose()
