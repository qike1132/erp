"""出货流水「数量」口径：出货毛量（不扣退货），退货在「退货流水」tab 单独呈现（2026-10-08 业务裁定）。"""
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.services import report_service
from fastapi_app.shared_models import Product, StockOut

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


async def test_stockout_log_quantity_is_gross(db):
    """出货 5000、退 3000 → 出货流水仍显示 5000，且该行不因退货消失。

    回归 2026-10-08：旧口径 SUM(quantity − returned_quantity) 会显示 2000，
    退满时该行还会整行消失。
    """
    product = Product(name='出货毛量产品', barcode='SO-GROSS-001', current_stock=0, initial_stock=0)
    db.add(product)
    await db.flush()
    db.add(StockOut(stockout_no='SO-GROSS-1', product_id=product.id, quantity=5000,
                    returned_quantity=3000, customer='毛量客户',
                    stockout_date=datetime.now(UTC)))
    await db.flush()

    result = await report_service.get_stockout_logs.__wrapped__(
        db, product='出货毛量产品', page=1, per_page=50)

    rows = [r for r in result['logs'] if r['customer'] == '毛量客户']
    assert rows, '退 3000 后该出货单仍应出现在出货流水'
    assert rows[0]['quantity'] == 5000
    assert result['stats']['total_quantity'] == 5000
