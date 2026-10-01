"""编号计数表（numbering_counter）并发分配集成测试

验证 2026-08-22 编号器改造：
- allocate_sequence 并发分配序号全不重复（原子 upsert）
- generate_number_async 批内连续、格式正确

自包含 fixture（函数级引擎）：不依赖 root conftest 的 session 级
test_engine（与本机 pytest-asyncio 1.x 存在 ScopeMismatch）。

安全边界：allocate_sequence 内部经 core.database._AsyncSessionLocal 建独立
会话——测试用 monkeypatch 将其指向测试库引擎，全程不触碰生产库。
"""
import asyncio
import os
from urllib.parse import urlparse, urlunparse

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fastapi_app.services.numbering import generate_number_async
from fastapi_app.services.numbering_sequence import allocate_sequence, business_date_str
from fastapi_app.shared_models import Base, Order

pytestmark = pytest.mark.integration


def _test_db_url() -> str:
    override = os.getenv('TEST_DATABASE_URL')
    if override:
        return override
    from fastapi_app.core.config import settings
    db_name = os.getenv('DB_NAME', 'erp_system')
    parsed = urlparse(settings.ASYNC_DATABASE_URL)
    # 幂等：conftest 的 session 级 app_on_test_db 已把 settings.ASYNC_DATABASE_URL
    # 重定向到 erp_system_test，此处再替换会生成不存在的 erp_system_test_test
    if parsed.path.rstrip('/').endswith('_test'):
        return settings.ASYNC_DATABASE_URL
    new_path = parsed.path.replace(f'/{db_name}', f'/{db_name}_test', 1)
    return urlunparse(parsed._replace(path=new_path))


@pytest_asyncio.fixture
async def db_and_factory(monkeypatch):
    """函数级：测试库建表 + 事务回滚会话；同时把 _AsyncSessionLocal 指向测试引擎。

    monkeypatch 在 fixture 结束时自动还原，生产配置不受影响。
    """
    from fastapi_app.core import database as core_db

    engine = create_async_engine(_test_db_url(), echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(core_db, '_AsyncSessionLocal', factory)

    async with factory() as session:
        async with session.begin() as transaction:
            yield session, factory
            await transaction.rollback()
    await engine.dispose()


async def _clear_counter(factory, prefix):
    async with factory() as s:
        await s.execute(
            text('DELETE FROM numbering_counter WHERE prefix = :p'),
            {'p': prefix},
        )
        await s.commit()


async def test_concurrent_allocation_unique(db_and_factory):
    _, factory = db_and_factory
    prefix = 'XAL'
    await _clear_counter(factory, prefix)

    # 期望日期段与被测实现同源：UTC 与北京业务日在本地 00:00–08:00 窗口
    # 必差一天（0b2b124f 统一北京口径），用 UTC 推导会假红。
    date_str = business_date_str()
    seqs = await asyncio.gather(*[
        allocate_sequence(prefix, date_str, seed=0) for _ in range(50)
    ])
    assert len(seqs) == 50
    assert len(set(seqs)) == 50, f'并发分配出现重号: {sorted(seqs)}'
    assert sorted(seqs) == list(range(1, 51))


async def test_generate_number_async_batch_unique_and_continuous(db_and_factory):
    db, factory = db_and_factory
    prefix = 'XGN'
    await _clear_counter(factory, prefix)

    # 同 test_concurrent_allocation_unique：期望日期段与产品同源
    # （UTC 与北京业务日在本地 00:00–08:00 窗口必差一天，0b2b124f 统一北京口径）。
    date_str = business_date_str()
    numbers = [
        await generate_number_async(prefix, Order, 'order_no', db)
        for _ in range(5)
    ]
    suffixes = [int(n.rsplit('-', 1)[1]) for n in numbers]
    # 批内不重复且严格递增（同日同前缀、种子为 0 时即 1..5）
    assert len(set(numbers)) == 5
    assert suffixes == sorted(suffixes)
    assert suffixes == list(range(1, 6))
    assert all(n.startswith(f'{prefix}-{date_str}-') for n in numbers)
