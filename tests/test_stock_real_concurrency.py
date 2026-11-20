"""真实 PostgreSQL 库存竞争：独立事务、独立连接、确定性对账。"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.core.exceptions import ConflictError, db_transaction
from fastapi_app.services import stock_in_service, stock_out_service, stock_return_service, stock_service
from fastapi_app.services.stock_out_service import batch_create_stockouts
from fastapi_app.shared_models import (
    DailyProductionRecord,
    InventoryLog,
    Order,
    Product,
    StockIn,
    StockOut,
    StockReturn,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest_asyncio.fixture(autouse=True)
async def _numbering_factory_on_test_db():
    """编号分配使用全局 session factory；独立并发连接前显式指向测试库。"""
    from fastapi_app.core.database import ensure_engine_for_current_loop

    await ensure_engine_for_current_loop()


async def _seed_competition(db: AsyncSession, *, stock: int = 10, order_qty: int = 20):
    """准备足量订单但有限实物，确保竞争发生在库存写入口而非订单准入。"""
    tag = uuid4().hex[:10]
    customer = f"并发客户-{tag}"
    product = Product(
        name=f"并发产品-{tag}",
        barcode=f"RACE-{tag}",
        current_stock=stock,
        initial_stock=stock,
    )
    db.add(product)
    await db.flush()
    db.add(DailyProductionRecord(
        department="packaging",
        product_id=product.id,
        product_name=product.name,
        barcode=product.barcode,
        quantity=stock,
        production_date=datetime.now(UTC).date(),
    ))
    order = Order(
        order_no=f"RACE-{tag}"[:20],
        customer=customer,
        product_id=product.id,
        quantity=order_qty,
        status="待备货",
        order_date=datetime.now(UTC),
    )
    db.add(order)
    await db.flush()
    await db.commit()
    return product.id, order.id, customer


async def _single_stockout(factory, product_id: int, customer: str) -> bool:
    async with factory() as session:
        try:
            async with db_transaction(session):
                await stock_out_service.create_stockout(
                    session,
                    product_id=product_id,
                    quantity=8,
                    customer=customer,
                    stockout_date_str=datetime.now(UTC).date().isoformat(),
                    note="真实并发单条出库",
                )
            return True
        except (ValueError, ConflictError, HTTPException):
            await session.rollback()
            return False


async def _batch_stockout(factory, product_id: int, customer: str) -> bool:
    async with factory() as session:
        try:
            async with db_transaction(session):
                result = await batch_create_stockouts(
                    session,
                    [{
                        "id": "race-batch",
                        "product_id": product_id,
                        "customer": customer,
                        "quantity": 8,
                        "note": "真实并发批量出库",
                    }],
                )
            return bool(result["success"] and result["results"][0]["success"])
        except (ValueError, ConflictError, HTTPException):
            await session.rollback()
            return False


@pytest.mark.parametrize("competitor", ["single", "batch"])
async def test_concurrent_stockouts_never_oversell(
    async_db_session, test_engine, competitor
):
    """库存 10、订单余量 20，两路各出 8：只能一路成功，且全账一致。"""
    product_id, order_id, customer = await _seed_competition(async_db_session)
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    second = _single_stockout if competitor == "single" else _batch_stockout

    first_result, second_result = await asyncio.gather(
        _single_stockout(factory, product_id, customer),
        second(factory, product_id, customer),
    )

    assert {first_result, second_result} == {True, False}, (
        f"两路出库结果必须一成一败，实际 {first_result=}, {second_result=}"
    )
    async with factory() as check:
        product = await check.get(Product, product_id)
        order = await check.get(Order, order_id)
        rows = list((await check.execute(
            select(StockOut).where(StockOut.product_id == product_id)
        )).scalars().all())
        net_log = await check.scalar(
            select(func.coalesce(func.sum(InventoryLog.change_quantity), 0)).where(
                InventoryLog.product_id == product_id,
                InventoryLog.change_type == "出库",
            )
        )

    assert product.current_stock == 2
    assert len(rows) == 1
    assert rows[0].quantity == 8
    assert rows[0].order_id == order_id, "成功出库必须完成 FIFO 订单绑定"
    assert rows[0].stockin_id is None
    assert net_log == -8
    assert product.current_stock == 10 + net_log
    assert order.status == "待出货"


async def _cancel_return(factory, return_id: int) -> bool:
    async with factory() as session:
        try:
            async with db_transaction(session):
                await stock_return_service.cancel_stockreturn(session, return_id)
            return True
        except (ValueError, ConflictError, HTTPException):
            await session.rollback()
            return False


async def test_concurrent_cancel_same_return_applies_only_once(
    async_db_session, test_engine
):
    """重复取消同一退货：只回冲一次，另一路找不到记录且无副作用。"""
    product_id, order_id, customer = await _seed_competition(
        async_db_session, stock=20, order_qty=10,
    )
    db = async_db_session
    async with db_transaction(db):
        await stock_out_service.create_stockout(
            db,
            product_id=product_id,
            quantity=10,
            customer=customer,
            stockout_date_str=datetime.now(UTC).date().isoformat(),
            note="并发取消退货的原始出库",
        )
        stockout = await db.scalar(
            select(StockOut).where(StockOut.product_id == product_id).order_by(StockOut.id.desc())
        )
        stockreturn = await stock_return_service.create_stockreturn_core(
            db,
            stockout_id=stockout.id,
            quantity=5,
            return_date=datetime.now(UTC),
            reason="并发取消测试",
        )
    return_id = stockreturn.id
    stockout_id = stockout.id
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    first, second = await asyncio.gather(
        _cancel_return(factory, return_id),
        _cancel_return(factory, return_id),
    )

    assert {first, second} == {True, False}, f"重复取消必须一成一败：{first=}, {second=}"
    async with factory() as check:
        product = await check.get(Product, product_id)
        order = await check.get(Order, order_id)
        stockout = await check.get(StockOut, stockout_id)
        remaining_return = await check.get(StockReturn, return_id)
        net_log = await check.scalar(
            select(func.coalesce(func.sum(InventoryLog.change_quantity), 0)).where(
                InventoryLog.product_id == product_id,
                InventoryLog.change_type.in_(["出库", "退货", "退货取消"]),
            )
        )

    assert remaining_return is None
    assert stockout.returned_quantity == 0
    assert product.current_stock == 10
    assert net_log == -10
    assert product.current_stock == 20 + net_log
    assert order.status == "已出货"


def _install_precheck_barrier(monkeypatch, service_module) -> None:
    """让两路并发都完成幂等预检后，再同时进入库存写入。

    预检只能拦住「先提交、后到达」；栅栏确保两路都看到「尚未登记」，随后由
    Product 行锁自然串行化：先提交者成功，后提交者撞 uq_inventory_log_idem。
    这样并发窗口不依赖调度运气，也不会像「持锁方在应用层等待」那样制造死锁。
    """
    barrier = asyncio.Barrier(2)

    async def synchronized(_db, _request_id, _message):
        await asyncio.wait_for(barrier.wait(), timeout=10)

    monkeypatch.setattr(service_module, 'assert_request_not_processed', synchronized)


async def _seed_stockin_product(db: AsyncSession) -> tuple[int, str]:
    tag = uuid4().hex[:10]
    customer = f"并发入库客户-{tag}"
    product = Product(
        name=f"并发入库产品-{tag}",
        barcode=f"RACE-IN-{tag}",
        current_stock=0,
        initial_stock=0,
    )
    db.add(product)
    await db.flush()
    await db.commit()
    return product.id, customer


async def _stockin_status(factory, product_id: int, customer: str, token: str) -> int:
    async with factory() as session:
        try:
            async with db_transaction(session):
                await stock_in_service.create_stockin_core(
                    session, product_id, 5, customer, datetime.now(UTC), '',
                    request_id=token,
                )
            return 200
        except HTTPException as exc:
            return exc.status_code


async def _stockout_status(factory, product_id: int, customer: str, token: str) -> int:
    async with factory() as session:
        try:
            async with db_transaction(session):
                await stock_out_service.create_stockout_core(
                    session, product_id, 10, customer, datetime.now(UTC), '',
                    request_id=token,
                )
            return 200
        except HTTPException as exc:
            return exc.status_code


async def test_concurrent_same_request_id_stockin_returns_409(
    async_db_session, test_engine, monkeypatch,
):
    """L-1：同 request_id 的并发入库必须一成一 409，且只留一条记录/流水。

    两路各用不同产品：既排除「同一产品 FOR UPDATE + FK KEY SHARE」的既有
    死锁形态，又能让两事务真正同时通过预检、同时写同一个 idem_key。
    """
    product_a, customer_a = await _seed_stockin_product(async_db_session)
    product_b, customer_b = await _seed_stockin_product(async_db_session)
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    _install_precheck_barrier(monkeypatch, stock_in_service)
    counter = 0
    tag = uuid4().hex[:8]

    async def gen(_db):
        nonlocal counter
        counter += 1
        return f'BH-{tag}-{counter:03d}'

    monkeypatch.setattr(stock_service, 'generate_stockin_number', gen)
    token = f'race-in-{uuid4().hex}'  # secret-scan:allow（并发测试用随机幂等令牌，非凭据）

    statuses = await asyncio.gather(
        _stockin_status(factory, product_a, customer_a, token),
        _stockin_status(factory, product_b, customer_b, token),
    )

    assert sorted(statuses) == [200, 409], f"并发重复入库必须一成一 409：{statuses=}"
    async with factory() as check:
        total_stock = await check.scalar(
            select(func.coalesce(func.sum(Product.current_stock), 0)).where(
                Product.id.in_([product_a, product_b])
            )
        )
        stockins = await check.scalar(
            select(func.count()).select_from(StockIn).where(
                StockIn.product_id.in_([product_a, product_b])
            )
        )
        logs = await check.scalar(
            select(func.count()).select_from(InventoryLog).where(InventoryLog.idem_key == token)
        )
    assert total_stock == 5
    assert stockins == 1
    assert logs == 1


async def test_concurrent_same_request_id_stockout_returns_409(
    async_db_session, test_engine, monkeypatch,
):
    """L-1：同 request_id 的并发出库必须一成一 409，且只扣一次库存。"""
    product_a, order_a, customer_a = await _seed_competition(
        async_db_session, stock=100, order_qty=50,
    )
    product_b, order_b, customer_b = await _seed_competition(
        async_db_session, stock=100, order_qty=50,
    )
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    _install_precheck_barrier(monkeypatch, stock_out_service)
    counter = 0
    tag = uuid4().hex[:8]

    async def gen(_db):
        nonlocal counter
        counter += 1
        return f'SO-{tag}-{counter:03d}'

    monkeypatch.setattr(stock_service, 'generate_stockout_number', gen)
    token = f'race-out-{uuid4().hex}'  # secret-scan:allow（并发测试用随机幂等令牌，非凭据）

    statuses = await asyncio.gather(
        _stockout_status(factory, product_a, customer_a, token),
        _stockout_status(factory, product_b, customer_b, token),
    )

    assert sorted(statuses) == [200, 409], f"并发重复出库必须一成一 409：{statuses=}"
    async with factory() as check:
        total_stock = await check.scalar(
            select(func.coalesce(func.sum(Product.current_stock), 0)).where(
                Product.id.in_([product_a, product_b])
            )
        )
        stockouts = await check.scalar(
            select(func.count()).select_from(StockOut).where(
                StockOut.product_id.in_([product_a, product_b])
            )
        )
        logs = await check.scalar(
            select(func.count()).select_from(InventoryLog).where(InventoryLog.idem_key == token)
        )
        orders = list((await check.execute(
            select(Order).where(Order.id.in_([order_a, order_b]))
        )).scalars().all())
    assert total_stock == 190
    assert stockouts == 1
    assert logs == 1
    assert len(orders) == 2
