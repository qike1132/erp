"""订单流水多 SKU 口径：一行 = 一个 (订单 × SKU)，数量取该 SKU 自身。

回归 2026-10-12（生产 MINISO国内 2026-10-12 案例）：
多 SKU 订单的 Order.product_id/quantity 是「首个 SKU / 全部 SKU 之和」兼容值，
旧实现直接聚合这两列，导致：
  · 产品名取首个 SKU（"3寸墩Dun鸡毛绒挂件"），却挂了整单合计 125520；
  · 第二个 SKU（"墩椰毛绒挂件" 19680）整行消失。
正确口径须按 order_item 展开（与备货/出货/退货流水一致）。
"""
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.services import report_service
from fastapi_app.shared_models import Order, OrderItem, Product

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


async def _make_product(db, name: str, barcode: str) -> Product:
    product = Product(name=name, barcode=barcode, current_stock=0, initial_stock=0)
    db.add(product)
    await db.flush()
    return product


async def test_multi_sku_order_expands_to_one_row_per_sku(db):
    """多 SKU 订单：每个 SKU 各占一行，数量为该 SKU 自身，合计为各 SKU 之和。"""
    p_dun = await _make_product(db, '3寸墩Dun鸡毛绒挂件', 'MSKU-DUN-001')
    p_ye = await _make_product(db, '墩椰毛绒挂件', 'MSKU-YE-001')

    customer = '多SKU回归客户'
    # 兼容值：product_id 取首个 SKU，quantity 取全部 SKU 之和（与 order_batch_create 一致）
    order = Order(
        order_no='ORD-MSKU-001', customer=customer,
        product_id=p_dun.id, quantity=105840 + 19680,
        order_date=datetime.now(UTC), status='待备货',
    )
    db.add(order)
    await db.flush()
    db.add_all([
        OrderItem(order_id=order.id, product_id=p_dun.id, product_name=p_dun.name,
                  product_barcode=p_dun.barcode, quantity=105840),
        OrderItem(order_id=order.id, product_id=p_ye.id, product_name=p_ye.name,
                  product_barcode=p_ye.barcode, quantity=19680),
    ])
    await db.flush()

    result = await report_service.get_order_logs.__wrapped__(
        db, customer=customer, page=1, per_page=50)

    rows = {r['product_name']: r for r in result['logs']}
    assert set(rows) == {'3寸墩Dun鸡毛绒挂件', '墩椰毛绒挂件'}, \
        f'两个 SKU 都应各占一行，实际: {sorted(rows)}'
    assert rows['3寸墩Dun鸡毛绒挂件']['quantity'] == 105840
    assert rows['墩椰毛绒挂件']['quantity'] == 19680
    # 整单合计不变（不重复、不丢失）
    assert result['stats']['total_quantity'] == 125520
    # 两行同属一张订单
    assert rows['墩椰毛绒挂件']['order_nos'] == 'ORD-MSKU-001'
    assert rows['墩椰毛绒挂件']['order_count'] == 1


async def test_multi_sku_order_product_filter_matches_non_first_sku(db):
    """按第二个 SKU 的产品名筛选，必须命中该订单（旧实现只看首个 SKU，会漏）。"""
    p_dun = await _make_product(db, '墩Dun筛选A', 'MSKU-FA-001')
    p_ye = await _make_product(db, '墩椰筛选B', 'MSKU-FB-001')

    customer = '多SKU筛选客户'
    order = Order(
        order_no='ORD-MSKU-FILTER', customer=customer,
        product_id=p_dun.id, quantity=300, order_date=datetime.now(UTC), status='待备货',
    )
    db.add(order)
    await db.flush()
    db.add_all([
        OrderItem(order_id=order.id, product_id=p_dun.id, product_name=p_dun.name,
                  product_barcode=p_dun.barcode, quantity=100),
        OrderItem(order_id=order.id, product_id=p_ye.id, product_name=p_ye.name,
                  product_barcode=p_ye.barcode, quantity=200),
    ])
    await db.flush()

    result = await report_service.get_order_logs.__wrapped__(
        db, customer=customer, product='墩椰筛选B', page=1, per_page=50)

    assert [r['product_name'] for r in result['logs']] == ['墩椰筛选B']
    assert result['logs'][0]['quantity'] == 200


async def test_order_without_items_falls_back_to_compat_columns(db):
    """无 order_item 的历史订单回退到 order 兼容列（不被 LEFT JOIN 丢掉）。"""
    p = await _make_product(db, '无明细回退产品', 'MSKU-NOITEM-001')

    customer = '无明细客户'
    order = Order(
        order_no='ORD-MSKU-NOITEM', customer=customer,
        product_id=p.id, quantity=777, order_date=datetime.now(UTC), status='待备货',
    )
    db.add(order)
    await db.flush()

    result = await report_service.get_order_logs.__wrapped__(
        db, customer=customer, page=1, per_page=50)

    assert len(result['logs']) == 1
    assert result['logs'][0]['product_name'] == '无明细回退产品'
    assert result['logs'][0]['quantity'] == 777


# ---------------------------------------------------------------------------
# 导出路径（report_data_service._get_order_logs）：同一缺陷的第二份实现。
# 导出走独立同步连接，须先 commit 才能跨连接可见，故单独用提交型夹具并在收尾清理。
# ---------------------------------------------------------------------------

_EXP_ORDER_NO = 'ORD-EXP-MSKU-001'


@pytest_asyncio.fixture
async def committed_multi_sku_order(test_engine):
    """提交一张多 SKU 订单（product_id=首个 SKU、quantity=各 SKU 之和）。"""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        p_a = Product(name='导出SKU-A', barcode='EXP-MSKU-A', current_stock=0, initial_stock=0)
        p_b = Product(name='导出SKU-B', barcode='EXP-MSKU-B', current_stock=0, initial_stock=0)
        session.add_all([p_a, p_b])
        await session.flush()
        order = Order(
            order_no=_EXP_ORDER_NO, customer='导出多SKU客户',
            product_id=p_a.id, quantity=1000 + 2000,
            order_date=datetime.now(UTC), status='待备货',
        )
        session.add(order)
        await session.flush()
        session.add_all([
            OrderItem(order_id=order.id, product_id=p_a.id, product_name=p_a.name,
                      product_barcode=p_a.barcode, quantity=1000),
            OrderItem(order_id=order.id, product_id=p_b.id, product_name=p_b.name,
                      product_barcode=p_b.barcode, quantity=2000),
        ])
        await session.commit()
        ids = (order.id, p_a.id, p_b.id)

    yield ids

    async with factory() as session:
        await session.execute(delete(OrderItem).where(OrderItem.order_id == ids[0]))
        await session.execute(delete(Order).where(Order.id == ids[0]))
        await session.execute(delete(Product).where(Product.id.in_([ids[1], ids[2]])))
        await session.commit()


@pytest.fixture
def sync_session():
    """测试库同步会话（psycopg3 驱动）。

    conftest 把 settings.DATABASE_URL 的 `+asyncpg` 抹掉后是裸 `postgresql://`，
    SQLAlchemy 会去找 psycopg2（未安装）；而导出路径真实运行环境用的是 psycopg3，
    故此处显式指定驱动，避免环境差异掩盖被测逻辑（应用侧已统一 psycopg3）。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SyncSessionCls

    from fastapi_app.core.config import settings

    engine = create_engine(settings.ASYNC_DATABASE_URL.replace('+asyncpg', '+psycopg'))
    with SyncSessionCls(engine) as session:
        yield session
    engine.dispose()


async def test_export_order_logs_expands_multi_sku(committed_multi_sku_order, sync_session):
    """导出：多 SKU 订单逐 SKU 一行，数量取该 SKU 自身（非整单合计）。"""
    from fastapi_app.shared.report_data_service import _get_order_logs

    logs, stats = _get_order_logs(sync_session, '导出多SKU客户', '', '', '', '')

    rows = {r['product_name']: r for r in logs}
    assert set(rows) == {'导出SKU-A', '导出SKU-B'}
    assert rows['导出SKU-A']['quantity'] == 1000
    assert rows['导出SKU-B']['quantity'] == 2000
    assert stats['total_quantity'] == 3000


async def test_export_order_logs_product_filter_matches_non_first_sku(
        committed_multi_sku_order, sync_session):
    """导出按第二个 SKU 的产品名筛选也必须命中（旧实现只看首个 SKU）。"""
    from fastapi_app.shared.report_data_service import _get_order_logs

    logs, _ = _get_order_logs(sync_session, '', '导出SKU-B', '', '', '')

    assert [r['product_name'] for r in logs] == ['导出SKU-B']
    assert logs[0]['quantity'] == 2000
