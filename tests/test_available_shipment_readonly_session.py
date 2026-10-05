"""可出货量展示计算的只读会话兼容回归（2026-10-05）

事故：/api/v1/aux/available-shipment 的会话来自只读副本
（get_async_read_db → 流复制热备，天然只读），而
``calculate_available_shipment_quantity`` 无条件对订单行加锁，
副本上直接 500：ReadOnlySQLTransactionError。

掩盖因素：副本不可达时 get_async_read_db 会在 2s 内降级主库，
故障因此表现为"时好时坏"而非稳定复现。

回归口径（用 server_settings 复刻副本的 default_transaction_read_only=on，
与热备行为一致，避免在测试里拼接会话级 SET 语句）：
1. 只读会话中 lock_orders=False 必须可用（展示端点口径）；
2. 默认 lock_orders=True 在只读会话中必须被拒绝（出货提交
   路径依赖该行锁防超量竞态，不允许被无意放开）。
"""
import pytest
import pytest_asyncio
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from fastapi_app.services.inventory_service import calculate_available_shipment_quantity

pytestmark = pytest.mark.integration

NO_SUCH_CUSTOMER = '只读会话回归_不存在的客户'


@pytest_asyncio.fixture
async def readonly_session_factory(test_engine):
    """与 test_engine 同库、但会话默认只读的会话工厂（复刻热备副本）。"""
    url = test_engine.url.render_as_string(hide_password=False)
    engine = create_async_engine(
        url,
        echo=False,
        poolclass=NullPool,  # 同 test_engine：连接不跨事件循环存活
        connect_args={"server_settings": {"default_transaction_read_only": "on"}},
    )
    try:
        yield async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
        )
    finally:
        await engine.dispose()


async def test_display_calculation_runs_in_readonly_session(readonly_session_factory):
    """lock_orders=False 在只读会话中可用（副本 500 事故的回归）。"""
    async with readonly_session_factory() as session:
        info = await calculate_available_shipment_quantity(
            session, 999999999, NO_SUCH_CUSTOMER, lock_orders=False,
        )
    assert info['available_quantity'] == 0
    assert info['orders'] == []


async def test_default_lock_still_rejected_in_readonly_session(readonly_session_factory):
    """默认仍加行锁：只读会话中必须报错，防止写路径的锁被无意放开。"""
    async with readonly_session_factory() as session:
        with pytest.raises(DBAPIError) as excinfo:
            await calculate_available_shipment_quantity(session, 999999999, NO_SUCH_CUSTOMER)
    # SQLAlchemy asyncpg 方言会把原始异常包一层 wrapper，只能按原始类名文本断言
    assert 'ReadOnlySQLTransactionError' in str(excinfo.value.orig)
