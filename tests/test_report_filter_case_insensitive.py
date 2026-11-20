"""报表产品/客户筛选大小写不敏感回归（审计 data-M-3）。

五类流水报表的筛选原先是大小写敏感的 PG ``LIKE``，与同分区库存页
（stock_inventory_service._resolve_products 的 ilike，2026-10-17 OCR 复审
已修）口径分叉：条码/产品名/客户名含字母时，``m01`` 搜不到 ``M01``、
``abc`` 客户搜不到 ``ABC`` 客户，页面结果集比真实数据少。改 ``ILIKE``
后假阴性消失。

口径#1：report_service（屏幕）与 report_data_service（导出）必须同一
改动集——两条路径各测一条，防止只改一半。
"""
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.services import report_service
from fastapi_app.shared_models import Product, StockIn

pytestmark = pytest.mark.integration

_SUFFIX = uuid4().hex[:8].upper()
_CUSTOMER_UPPER = f'报表ABC客户{_SUFFIX}'
_NAME_UPPER = f'报表产品M01X{_SUFFIX}'
_BARCODE_UPPER = f'M01-{_SUFFIX}'


@pytest_asyncio.fixture
async def db(test_engine):
    """函数级会话：复用会话级引擎 + 事务回滚隔离（屏幕路径够用）。"""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()


async def test_screen_stockin_logs_match_case_insensitive(db):
    """屏幕（report_service.get_stockin_logs）：小写 m01/abc 必须搜到 M01/ABC 数据。"""
    product = Product(name=_NAME_UPPER, barcode=_BARCODE_UPPER, current_stock=0, initial_stock=0)
    db.add(product)
    await db.flush()
    db.add(StockIn(
        stockin_no=f'SI-CASE-{_SUFFIX}', product_id=product.id, customer=_CUSTOMER_UPPER,
        quantity=10, stockin_date=datetime.now(UTC),
    ))
    await db.flush()

    # 阳性对照：精确大小写必须命中（改 ILIKE 不得破坏原有匹配）
    exact = await report_service.get_stockin_logs.__wrapped__(
        db, customer=_CUSTOMER_UPPER, product=_BARCODE_UPPER, page=1, per_page=50)
    assert len(exact['logs']) == 1, '精确大小写应命中（阳性对照）'

    # 修复目标：全小写关键词同样命中（旧 LIKE 恒为空 → 假阴性）
    lower = await report_service.get_stockin_logs.__wrapped__(
        db, customer=_CUSTOMER_UPPER.lower(), product=_BARCODE_UPPER.lower(),
        page=1, per_page=50)
    assert len(lower['logs']) == 1, (
        f'小写 m01/abc 客户应搜到 M01/ABC 数据（ILIKE 口径），实际 {len(lower["logs"])} 行'
    )
    assert lower['logs'][0]['product_barcode'] == _BARCODE_UPPER


# ---------------------------------------------------------------------------
# 导出路径（report_data_service._get_stockin_logs）：走独立同步连接，
# 须先 commit 才能跨连接可见，单独用提交型夹具并在收尾清理。
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def committed_stockin(test_engine):
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        product = Product(name=_NAME_UPPER, barcode=_BARCODE_UPPER, current_stock=0, initial_stock=0)
        session.add(product)
        await session.flush()
        stockin = StockIn(
            stockin_no=f'SI-CASE-EXP-{_SUFFIX}', product_id=product.id,
            customer=_CUSTOMER_UPPER, quantity=10, stockin_date=datetime.now(UTC),
        )
        session.add(stockin)
        await session.commit()
        ids = (stockin.id, product.id)

    yield ids

    async with factory() as session:
        await session.execute(delete(StockIn).where(StockIn.id == ids[0]))
        await session.execute(delete(Product).where(Product.id == ids[1]))
        await session.commit()


@pytest.fixture
def sync_session():
    """测试库同步会话（psycopg3 驱动），与 test_report_order_logs_multi_sku 同款。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SyncSessionCls

    from fastapi_app.core.config import settings

    engine = create_engine(settings.ASYNC_DATABASE_URL.replace('+asyncpg', '+psycopg'))
    with SyncSessionCls(engine) as session:
        yield session
    engine.dispose()


def test_export_stockin_logs_match_case_insensitive(committed_stockin, sync_session):
    """导出（report_data_service._get_stockin_logs）：小写关键词必须搜到 M01/ABC 数据。"""
    from fastapi_app.shared.report_data_service import _get_stockin_logs

    # 阳性对照
    logs, _stats = _get_stockin_logs(sync_session, _CUSTOMER_UPPER, _BARCODE_UPPER, '', '')
    assert len(logs) == 1, '导出精确大小写应命中（阳性对照）'

    logs_lower, _stats = _get_stockin_logs(
        sync_session, _CUSTOMER_UPPER.lower(), _BARCODE_UPPER.lower(), '', '')
    assert len(logs_lower) == 1, (
        f'导出小写 m01/abc 客户应搜到 M01/ABC 数据（ILIKE 口径），实际 {len(logs_lower)} 行'
    )
    assert logs_lower[0]['product_barcode'] == _BARCODE_UPPER
