"""P1-4 编号计数单调性：counter 落后 seed 时不倒退、不重号（真实库集成）。

修复背景
--------
numbering_sequence 的 UPSERT 冲突分支原为 last_seq + 1。当计数水位落后于当日
已落库最大编号 seed（历史编号更大、计数行被重建、手工导入/清理）时，冲突分支
会把序号拉回到历史编号之下：轻则跳回已用号段撞唯一约束报错，重则直接重号。
现改为 GREATEST(numbering_counter.last_seq, seed) + 1（range 版再 + count），
任何 counter/seed 组合下序号都只前进。

测试边界
--------
自包含函数级 fixture（与 tests/test_numbering_sequence_integration.py 同款）：
把 core.database._AsyncSessionLocal 指向测试库引擎，allocate_sequence 内部建的
独立短事务会话因此落在测试库，全程不触碰生产库。用例只用 MONO* 前缀，
前后各清理一次。
"""
import os
from urllib.parse import urlparse, urlunparse

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fastapi_app.services.numbering import generate_number_async
from fastapi_app.services.numbering_sequence import (
    allocate_sequence,
    allocate_sequence_range,
    business_date_str,
)
from fastapi_app.shared_models import Base, Order

pytestmark = [pytest.mark.integration, pytest.mark.db]

#: 固定日期段：不依赖真实时钟，避免跨零点时的假失败。
DATE = '20991231'


def _test_db_url() -> str:
    override = os.getenv('TEST_DATABASE_URL')
    if override:
        return override
    from fastapi_app.core.config import settings
    db_name = os.getenv('DB_NAME', 'erp_system')
    parsed = urlparse(settings.ASYNC_DATABASE_URL)
    # 幂等：conftest 的 session 级 app_on_test_db 可能已把 URL 指向 *_test
    if parsed.path.rstrip('/').endswith('_test'):
        return settings.ASYNC_DATABASE_URL
    new_path = parsed.path.replace(f'/{db_name}', f'/{db_name}_test', 1)
    return urlunparse(parsed._replace(path=new_path))


@pytest_asyncio.fixture
async def factory(monkeypatch):
    """测试库引擎 + 会话工厂，并把核心模块的会话工厂指向它。"""
    from fastapi_app.core import database as core_db

    engine = create_async_engine(_test_db_url(), echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(core_db, '_AsyncSessionLocal', maker)

    await _clear_counters(maker)
    try:
        yield maker
    finally:
        await _clear_counters(maker)
        await engine.dispose()


async def _clear_counters(maker) -> None:
    async with maker() as session:
        await session.execute(text("DELETE FROM numbering_counter WHERE prefix LIKE 'MONO%'"))
        await session.commit()


async def _set_counter(maker, prefix: str, last_seq: int, date_str: str = DATE) -> None:
    """预置计数水位（模拟 counter 落后/领先 seed 的历史状态）。"""
    async with maker() as session:
        await session.execute(
            text(
                'INSERT INTO numbering_counter (prefix, number_date, last_seq) '
                'VALUES (:prefix, :number_date, :last_seq) '
                'ON CONFLICT (prefix, number_date) '
                'DO UPDATE SET last_seq = EXCLUDED.last_seq'
            ),
            {'prefix': prefix, 'number_date': date_str, 'last_seq': last_seq},
        )
        await session.commit()


async def _read_counter(maker, prefix: str, date_str: str = DATE) -> int:
    async with maker() as session:
        row = await session.execute(
            text(
                'SELECT last_seq FROM numbering_counter '
                'WHERE prefix = :prefix AND number_date = :number_date'
            ),
            {'prefix': prefix, 'number_date': date_str},
        )
        return int(row.scalar_one())


# ---------------- 单号版 ----------------

async def test_single_counter_behind_seed_jumps_to_seed_plus_one(factory):
    """counter=5、seed=100 → 101（旧实现在这里返回 6，直接重号）。"""
    prefix = 'MONO1'
    await _set_counter(factory, prefix, 5)
    seq = await allocate_sequence(prefix, DATE, seed=100)
    assert seq == 101, f'counter 落后 seed 时必须追平 seed 再递增，实际 {seq}'
    assert await _read_counter(factory, prefix) == 101


async def test_single_allocation_keeps_advancing(factory):
    """追平后继续单调递增：同一 seed 重复传入不会把水位拉回。"""
    prefix = 'MONO2'
    await _set_counter(factory, prefix, 5)
    first = await allocate_sequence(prefix, DATE, seed=100)
    second = await allocate_sequence(prefix, DATE, seed=100)
    assert (first, second) == (101, 102)
    assert await _read_counter(factory, prefix) == 102


async def test_single_counter_ahead_of_seed_never_goes_backwards(factory):
    """counter=200、seed=100 → 201（不回退、不重号）。"""
    prefix = 'MONO3'
    await _set_counter(factory, prefix, 200)
    seq = await allocate_sequence(prefix, DATE, seed=100)
    assert seq == 201
    assert seq > 200, '水位不得回退到已用号段'


async def test_single_counter_equal_to_seed_advances_by_one(factory):
    prefix = 'MONO4'
    await _set_counter(factory, prefix, 100)
    assert await allocate_sequence(prefix, DATE, seed=100) == 101


async def test_single_first_use_without_row_starts_at_seed_plus_one(factory):
    """首次使用语义不变：无计数行时以 seed+1 落库。"""
    prefix = 'MONO5'
    assert await allocate_sequence(prefix, DATE, seed=100) == 101
    assert await _read_counter(factory, prefix) == 101


# ---------------- 批量（range）版 ----------------

async def test_range_counter_behind_seed_starts_at_seed_plus_one(factory):
    """counter=5、seed=100、count=10 → 101..110（旧实现在这里返回 6..15）。"""
    prefix = 'MONO6'
    await _set_counter(factory, prefix, 5)
    start = await allocate_sequence_range(prefix, DATE, count=10, seed=100)
    assert start == 101
    assert list(range(start, start + 10)) == list(range(101, 111))
    assert await _read_counter(factory, prefix) == 110


async def test_range_counter_ahead_of_seed_never_goes_backwards(factory):
    prefix = 'MONO7'
    await _set_counter(factory, prefix, 200)
    start = await allocate_sequence_range(prefix, DATE, count=5, seed=100)
    assert start == 201
    assert await _read_counter(factory, prefix) == 205


async def test_range_first_use_without_row_starts_at_seed_plus_one(factory):
    prefix = 'MONO8'
    start = await allocate_sequence_range(prefix, DATE, count=3, seed=100)
    assert start == 101
    assert await _read_counter(factory, prefix) == 103


async def test_mixed_single_and_range_stay_unique_and_increasing(factory):
    """单号版与批量版混用（counter 落后 seed）也不重号、不回退。"""
    prefix = 'MONO9'
    await _set_counter(factory, prefix, 5)
    issued = [await allocate_sequence(prefix, DATE, seed=100)]
    start = await allocate_sequence_range(prefix, DATE, count=4, seed=100)
    issued.extend(range(start, start + 4))
    issued.append(await allocate_sequence(prefix, DATE, seed=100))
    assert issued == [101, 102, 103, 104, 105, 106]
    assert len(set(issued)) == len(issued)
    assert all(number > 100 for number in issued), '不得占用 <= seed 的历史号段'


# ---------------- 格式/前缀不变 ----------------

async def test_formatted_number_keeps_prefix_date_and_padding(factory):
    """走完整取号路径：前缀、北京口径日期段、zfill(4) 格式均不变。"""
    prefix = 'MONOF'
    date_str = business_date_str()
    await _set_counter(factory, prefix, 100, date_str)
    async with factory() as db:
        first = await generate_number_async(prefix, Order, 'order_no', db)
        second = await generate_number_async(prefix, Order, 'order_no', db)
    assert first == f'{prefix}-{date_str}-0101'
    assert second == f'{prefix}-{date_str}-0102'
