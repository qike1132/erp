"""退货「修改」路径（cancel + 重建）的回归。

背景（2026-10-09）：取消退货由「软取消保留记录」改为**直接删除该行**。
而 ``edit_stockreturn`` 的语义正是「取消旧行 + 按同一出货明细重建」——本次改动
触及该路径，此前无任何测试覆盖。锁定：编辑后旧行已删除、新行存在、
出货已退量按净变化对称调整（旧量回减、新量累加）。
"""
import uuid
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.services.stock_return_service import edit_stockreturn
from fastapi_app.shared_models import DailyProductionRecord, Product, StockOut, StockReturn

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def db(test_engine):
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()


async def test_edit_stockreturn_deletes_old_row_and_rebuilds(db):
    suffix = uuid.uuid4().hex[:8]
    product = Product(name=f"EDITPROBE-{suffix}", barcode=f"EDITPROBE-{suffix}",
                      current_stock=1000, initial_stock=1000)
    db.add(product)
    await db.flush()
    # 2026-10-24：编辑退货 = 取消旧退货 + 建新退货，取消那一步走结余闸门
    # （可出库存 = 包装部入库 − 已出货，口径见 get_inventory_balance 的 docstring）。
    # 夹具原先只给 current_stock 就直接插 StockOut，结余恒 0 → 取消被拒；
    # 真实链路里这批货必经 create_stockout_core，故补一条包装部入库记录。
    db.add(DailyProductionRecord(
        department='packaging', product_id=product.id, product_name=product.name,
        barcode=product.barcode or '', quantity=1000, production_date=date.today(),
    ))
    await db.flush()
    stockout = StockOut(stockout_no=f"SO-EDIT-{suffix}", product_id=product.id,
                        quantity=100, customer="客户E", returned_quantity=10)
    db.add(stockout)
    await db.flush()
    old = StockReturn(
        return_no=f"SR-EDIT-{suffix}", product_id=product.id, quantity=10,
        customer="客户E", stockout_id=stockout.id, reason="其他",
        return_date=datetime.now(UTC),
    )
    db.add(old)
    await db.flush()
    old_id = old.id

    created = await edit_stockreturn(
        db, return_id=old_id, quantity=7, return_date_str=None, reason=None,
        note=None, operator_id=None,
    )
    await db.flush()

    assert created['return_no'] != old.return_no
    assert (await db.execute(
        select(StockReturn).where(StockReturn.id == old_id)
    )).scalar_one_or_none() is None, "旧退货行应已被删除（不再软取消保留）"
    new_row = (await db.execute(
        select(StockReturn).where(StockReturn.return_no == created['return_no'])
    )).scalar_one()
    assert new_row.quantity == 7
    # 净变化对称：旧 10 回减 → 0，新 7 累加 → 7
    refreshed = await db.get(StockOut, stockout.id)
    assert refreshed.returned_quantity == 7
