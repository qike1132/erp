"""缓存失效的 post-commit 兜底回归测试（2026-09-28）

背景：订单/备货/出货/退货的写路径此前只在**提交前**失效缓存。并发请求若在
本次提交前读到旧数据并回写缓存，提交后不再失效，脏值会留存至 TTL。

``schedule_post_commit_invalidation`` 把失效登记为「提交成功后」执行的回调，
消除该竞态；原有提交前失效保留作广覆盖（不走 db_transaction 的调用方仍需它）。
"""
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.core.cache_invalidation import cache_mgr, schedule_post_commit_invalidation
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.services import stock_out_service
from fastapi_app.shared_models import Product, StockOut

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def db(test_engine):
    """事务回滚隔离的会话（供会写库的用例）。"""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()


@pytest_asyncio.fixture
async def raw_db(test_engine):
    """不带外层事务的会话。

    db_transaction 会真的 commit —— 若套在 session.begin() 里，夹具收尾的
    transaction.rollback() 会失去事务而报错。验证提交/回滚语义必须用裸会话。
    """
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


def test_helper_registers_callback_into_session_info():
    """helper 把回调追加进 db.info['post_commit_callbacks']（可注册多个）。"""
    class _Stub:
        def __init__(self):
            self.info: dict = {}

    async def cb() -> None:
        return None

    session = _Stub()
    schedule_post_commit_invalidation(session, cb)
    schedule_post_commit_invalidation(session, cb)
    assert session.info['post_commit_callbacks'] == [cb, cb]


async def test_db_transaction_runs_callback_after_commit(raw_db):
    """提交成功后回调必须执行。"""
    ran: list[int] = []

    async def cb() -> None:
        ran.append(1)

    async with db_transaction(raw_db):
        schedule_post_commit_invalidation(raw_db, cb)

    assert ran == [1]


async def test_db_transaction_skips_callback_on_rollback(raw_db):
    """事务回滚时回调必须不执行（否则会对未提交的数据做失效）。"""
    ran: list[int] = []

    async def cb() -> None:
        ran.append(1)

    with pytest.raises(HTTPException):
        async with db_transaction(raw_db):
            schedule_post_commit_invalidation(raw_db, cb)
            raise ValueError('boom')

    assert ran == []


async def test_delete_stockout_registers_post_commit_invalidation(db):
    """写路径接线：出货删除后必须登记 post-commit 失效回调。

    选这条路径是因为它不经过编号分配（不需要全局引擎初始化），
    能在纯夹具会话里跑通。
    """
    product = Product(name='PCI-出库产品', barcode='PCI-STOCKOUT', current_stock=10, initial_stock=10)
    db.add(product)
    await db.flush()
    stockout = StockOut(stockout_no='PCI-SO-001', product_id=product.id, quantity=3, customer='PCI客户')
    db.add(stockout)
    await db.flush()

    await stock_out_service.delete_stockout(db, stockout.id)

    callbacks = db.info.get('post_commit_callbacks', [])
    assert cache_mgr.invalidate_stock_and_order in callbacks
