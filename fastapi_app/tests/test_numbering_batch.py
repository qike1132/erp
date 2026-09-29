"""ITER-2 T1/T2：批量取号的编号格式与边界。

真实库的并发不重号验证会写库，放在 ``docs/tickets/tools/verify_iter2_numbering.py``
（跑完自清理）；本文件只覆盖不依赖数据库的取号逻辑，供 CI 常驻。
"""
from __future__ import annotations

from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services import numbering as nb
from fastapi_app.services.numbering_sequence import allocate_sequence_range

#: 本文件把「取号」与「当日种子读取」整体打桩，会话对象根本不会被使用。
#: 用 cast 给出一个签名合法的占位值，而不是为迁就测试去放宽生产代码的类型。
_STUB_SESSION = cast(AsyncSession, None)


@pytest.fixture
def stubbed_numbering(monkeypatch):
    """替换取号与种子读取，只验 generate_number_batch 自身的逻辑。"""
    calls: list[tuple] = []
    state = {'start': 901, 'seed': 900}

    async def fake_range(prefix, date_str, count, seed=0):
        calls.append((prefix, date_str, count, seed))
        return state['start']

    async def fake_daily_max(db, model, number_field, date_str):
        return state['seed']

    monkeypatch.setattr(nb, 'allocate_sequence_range', fake_range)
    monkeypatch.setattr(nb, 'read_daily_max', fake_daily_max)
    return calls, state


async def _batch(
    count: int,
    prefix: str = 'PO',
    number_field: str = 'order_no',
) -> list[str]:
    return await nb.generate_number_batch(
        prefix, None, number_field, _STUB_SESSION, count
    )


@pytest.mark.asyncio
async def test_returns_contiguous_numbers(stubbed_numbering):
    numbers = await _batch(4)
    assert len(numbers) == 4
    assert [n.rsplit('-', 1)[1] for n in numbers] == ['0901', '0902', '0903', '0904']


@pytest.mark.asyncio
async def test_number_format_is_prefix_date_seq(stubbed_numbering):
    numbers = await _batch(2, prefix='BH', number_field='stockin_no')
    for raw in numbers:
        prefix, date_str, seq = raw.split('-')
        assert prefix == 'BH'
        assert len(date_str) == 8 and date_str.isdigit()
        assert len(seq) == 4


@pytest.mark.asyncio
async def test_count_and_prefix_are_forwarded_to_allocator(stubbed_numbering):
    calls, _ = stubbed_numbering
    await _batch(7, prefix='SO')
    assert len(calls) == 1
    prefix, _date_str, count, seed = calls[0]
    assert prefix == 'SO'
    assert count == 7
    assert seed == 900            # 透传 read_daily_max 的结果，保证与历史编号连续


@pytest.mark.asyncio
async def test_single_allocator_call_per_batch(stubbed_numbering):
    """批量化要点：一次导入只应调用一次取号 —— 循环取号等于没优化。"""
    calls, _ = stubbed_numbering
    await _batch(5000)
    assert len(calls) == 1, '每行取一次号会让批量化的收益归零'


@pytest.mark.asyncio
@pytest.mark.parametrize('count', [0, -1, -100])
async def test_non_positive_count_is_noop(stubbed_numbering, count):
    calls, _ = stubbed_numbering
    assert await _batch(count) == []
    assert calls == [], 'count<=0 不应触达取号层'


@pytest.mark.asyncio
async def test_sequence_beyond_9999_is_not_truncated(stubbed_numbering):
    """zfill 只补齐不截断，超过 9999 仍唯一（编号变 5 位）。"""
    _, state = stubbed_numbering
    state['start'] = 9998
    numbers = await _batch(3)
    assert [n.rsplit('-', 1)[1] for n in numbers] == ['9998', '9999', '10000']


@pytest.mark.asyncio
async def test_numbers_are_unique_within_batch(stubbed_numbering):
    numbers = await _batch(1000)
    assert len(set(numbers)) == 1000


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', [0, -1])
async def test_allocate_sequence_range_rejects_non_positive_count(bad):
    """count<1 属调用方逻辑错误 —— 静默返回会让「导入 0 条」与「忘了取号」无法区分。"""
    with pytest.raises(ValueError, match='count'):
        await allocate_sequence_range('ITERTEST', '19700101', bad)
