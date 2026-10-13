"""四个非订单流水 tab：一行一记录（去跨记录聚合）、带单号与时间到分。

2026-10-13 改造：备货/出货/备货抵扣/退货四个 tab 由「按 (日期,客户,产品) 分组聚合」
改为「一行 = 一条记录」，单号因此逐行有意义、行内编辑/删除可直连单条记录。
"""
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.services import report_service

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def db(test_engine):
    """函数级会话：复用会话级引擎 + 事务回滚隔离。"""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()


async def _product(db, name: str, barcode: str):
    from fastapi_app.shared_models import Product
    product = Product(name=name, barcode=barcode, current_stock=0, initial_stock=0)
    db.add(product)
    await db.flush()
    return product


async def test_stockin_logs_one_row_per_record(db):
    """同日同客户同产品的两条备货记录不再合并：各占一行、各带单号、时间到分。"""
    from fastapi_app.shared_models.stock_in import StockIn

    p = await _product(db, '备货流水产品', 'RPT-SI-001')
    customer = '备货流水客户'
    db.add_all([
        StockIn(stockin_no='SI-RPT-1', product_id=p.id, customer=customer,
                quantity=10, stockin_date=datetime.now(UTC)),
        StockIn(stockin_no='SI-RPT-2', product_id=p.id, customer=customer,
                quantity=20, stockin_date=datetime.now(UTC)),
    ])
    await db.flush()

    result = await report_service.get_stockin_logs.__wrapped__(
        db, customer=customer, page=1, per_page=50)
    logs = result['logs']

    assert len(logs) == 2, '同日同客户同产品应各占一行（旧实现合并成 1 行）'
    assert {r['record_no'] for r in logs} == {'SI-RPT-1', 'SI-RPT-2'}
    assert all(':' in r['stockin_date'] for r in logs), '时间应到分'
    assert all(r['product_barcode'] == 'RPT-SI-001' for r in logs)
    assert result['pagination']['total'] == 2


async def test_stockout_logs_one_row_per_record(db):
    """出货流水：一行一记录，带出货单号、条码、时间到分。"""
    from fastapi_app.shared_models.stock_out import StockOut

    p = await _product(db, '出货流水产品', 'RPT-SO-001')
    customer = '出货流水客户'
    db.add_all([
        StockOut(stockout_no='SO-RPT-1', product_id=p.id, customer=customer,
                 quantity=5, returned_quantity=0, stockout_date=datetime.now(UTC)),
        StockOut(stockout_no='SO-RPT-2', product_id=p.id, customer=customer,
                 quantity=7, returned_quantity=0, stockout_date=datetime.now(UTC)),
    ])
    await db.flush()

    result = await report_service.get_stockout_logs.__wrapped__(
        db, customer=customer, page=1, per_page=50)
    logs = result['logs']

    assert len(logs) == 2
    assert {r['record_no'] for r in logs} == {'SO-RPT-1', 'SO-RPT-2'}
    assert all(':' in r['stockout_date'] for r in logs)
    assert all(r['product_barcode'] == 'RPT-SO-001' for r in logs)
