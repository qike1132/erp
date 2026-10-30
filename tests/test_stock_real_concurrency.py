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
from fastapi_app.services import stock_out_service, stock_return_service
from fastapi_app.services.stock_out_service import batch_create_stockouts
from fastapi_app.shared_models import (
    DailyProductionRecord,
    InventoryLog,
    Order,
    Product,
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
