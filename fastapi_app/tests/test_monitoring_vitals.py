"""Web Vitals 端点单元测试（api/v1/endpoints/monitoring.py）

覆盖三块：
1. 进程内统计（`_remember` / `_summarize_from_memory`）—— 降级数据源的正确性；
2. 落库失败兜底与**自愈熔断** —— 本端点最关键的安全属性：
   上报链路（未认证、fire-and-forget）在任何数据库异常下都不得返回 5xx；
3. 保留期清理节流 —— 防止未认证端点把 DELETE 放大成每请求一次。
"""
import time
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit

from fastapi_app.api.v1.endpoints import monitoring
from fastapi_app.api.v1.endpoints.monitoring import (
    _MAX_KEYS,
    VitalEntry,
    _summarize_from_memory,
)


class _FakeSessionCtx:
    """`get_async_db_context()` 的替身：异步上下文管理器，产出 AsyncMock 会话。"""

    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _reset_monitoring_state():
    """模块级全局（内存统计 / 节流 / 熔断）逐测试隔离，避免相互污染。"""
    def _reset():
        monitoring._vital_stats.clear()
        monitoring._last_cleanup_at = 0.0
        monitoring._persist_disabled_until = 0.0

    _reset()
    yield
    _reset()


def _entry(name='LCP', value=2500.0, rating='good', nav='navigate') -> VitalEntry:
    return VitalEntry(
        name=name, value=value, rating=rating, delta=value,
        navigationType=nav, timestamp=1_700_000_000_000,
    )


class TestMemoryStats:
    """进程内统计（/summary 的降级数据源）"""

    def test_remember_accumulates(self):
        for v in (100.0, 200.0, 300.0):
            monitoring._remember(_entry(value=v))
        assert list(monitoring._vital_stats['LCP:good']) == [100.0, 200.0, 300.0]

    def test_summary_computes_count_avg_p95(self):
        for v in range(1, 101):          # 1..100
            monitoring._remember(_entry(value=float(v)))
        m = _summarize_from_memory()['LCP']['good']
        assert m['count'] == 100
        assert m['avg'] == 50.5
        # int(100*0.95)-1 = 94 → 升序第 95 个元素 = 95.0
        assert m['p95'] == 95.0

    def test_summary_separates_by_rating(self):
        monitoring._remember(_entry(value=100.0, rating='good'))
        monitoring._remember(_entry(value=9000.0, rating='poor'))
        assert set(_summarize_from_memory()['LCP']) == {'good', 'poor'}

    def test_key_cap_prevents_unbounded_growth(self):
        """key 数量上限：超出后新 key 被丢弃，不无限增长。"""
        for i in range(_MAX_KEYS + 20):
            monitoring._remember(_entry(name=f'M{i}', value=1.0))
        assert len(monitoring._vital_stats) <= _MAX_KEYS


class TestVitalInputBounds:
    def test_overlong_and_non_finite_values_are_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _entry(name='x' * 17)
        with pytest.raises(ValidationError):
            _entry(rating='r' * 25)
        with pytest.raises(ValidationError):
            _entry(nav='n' * 25)
        with pytest.raises(ValidationError):
            _entry(value=float('nan'))


class TestPersistFailSafe:
    """落库失败必须不影响上报链路"""

    @pytest.mark.asyncio
    async def test_persist_returns_false_when_db_unavailable(self):
        with patch.object(
            monitoring, 'get_async_db_context',
            side_effect=RuntimeError('数据库引擎未初始化'),
        ):
            ok = await monitoring._persist([_entry()], '/some/page')
        assert ok is False

    @pytest.mark.asyncio
    async def test_failure_does_not_raise(self):
        """关键属性：sendBeacon 上报端点绝不能因 DB 异常抛错（否则 500）。"""
        with patch.object(
            monitoring, 'get_async_db_context',
            side_effect=RuntimeError('boom'),
        ):
            await monitoring._persist([_entry()], '')   # 不应抛异常

    @pytest.mark.asyncio
    async def test_persist_success_writes_all_entries(self):
        session = AsyncMock()
        with patch.object(
            monitoring, 'get_async_db_context',
            return_value=_FakeSessionCtx(session),
        ), patch.object(monitoring, '_maybe_cleanup', new=AsyncMock()):
            ok = await monitoring._persist([_entry(), _entry()], '/p')
        assert ok is True
        assert session.add_all.call_count == 1
        assert len(session.add_all.call_args.args[0]) == 2

    @pytest.mark.asyncio
    async def test_cleanup_failure_does_not_break_persist(self):
        """保留期清理失败不应让落库被判定为失败。"""
        session = AsyncMock()
        with patch.object(
            monitoring, 'get_async_db_context',
            return_value=_FakeSessionCtx(session),
        ), patch.object(
            monitoring, '_maybe_cleanup',
            new=AsyncMock(side_effect=RuntimeError('cleanup boom')),
        ):
            ok = await monitoring._persist([_entry()], '')
        assert ok is True


class TestSelfHealingBreaker:
    """熔断应为自愈式：迁移执行后无需重启进程"""

    @pytest.mark.asyncio
    async def test_failure_opens_breaker(self):
        with patch.object(
            monitoring, 'get_async_db_context',
            side_effect=RuntimeError('boom'),
        ):
            await monitoring._persist([_entry()], '')
        assert monitoring._persist_disabled_until > time.monotonic()

    @pytest.mark.asyncio
    async def test_breaker_short_circuits_without_touching_db(self):
        """冷却期内应短路，连 DB 上下文都不再进入（避免失败风暴）。"""
        monitoring._persist_disabled_until = time.monotonic() + 300
        with patch.object(monitoring, 'get_async_db_context') as ctx:
            ok = await monitoring._persist([_entry()], '')
        assert ok is False
        ctx.assert_not_called()

    @pytest.mark.asyncio
    async def test_breaker_retries_after_cooldown(self):
        """冷却期结束后应重新尝试 —— 这是「自愈」的核心断言。"""
        monitoring._persist_disabled_until = time.monotonic() - 1  # 已过期
        session = AsyncMock()
        with patch.object(
            monitoring, 'get_async_db_context',
            return_value=_FakeSessionCtx(session),
        ) as ctx, patch.object(monitoring, '_maybe_cleanup', new=AsyncMock()):
            ok = await monitoring._persist([_entry()], '')
        ctx.assert_called_once()
        assert ok is True


class TestCleanupThrottle:
    """保留期清理节流"""

    @pytest.mark.asyncio
    async def test_cleanup_throttled_within_interval(self):
        monitoring._last_cleanup_at = time.monotonic()   # 刚跑过
        with patch.object(monitoring, 'get_async_db_context') as ctx:
            await monitoring._maybe_cleanup()
        ctx.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_runs_when_interval_elapsed(self):
        monitoring._last_cleanup_at = (
            time.monotonic() - monitoring._CLEANUP_INTERVAL_SECONDS - 1
        )
        session = AsyncMock()
        with patch.object(
            monitoring, 'get_async_db_context',
            return_value=_FakeSessionCtx(session),
        ) as ctx:
            await monitoring._maybe_cleanup()
        ctx.assert_called_once()
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cleanup_throttle_flag_set_before_await(self):
        """节流标志须在 await 之前置位，否则并发请求会同时触发清理（惊群）。"""
        # 用**负哨兵**而非 0.0：`_maybe_cleanup` 里 now=time.monotonic()，
        # 而 Windows 上 monotonic 是"开机以来的秒数"。若设 0.0，则机器开机不足
        # _CLEANUP_INTERVAL_SECONDS(3600) 时 now-0 < 3600 → 节流提前返回 →
        # 标志不被置位 → 本测试必红（与产品代码无关，纯环境相关 flake）。
        # 负哨兵使 now - _last_cleanup_at 恒 >= 间隔，与开机时长无关。
        monitoring._last_cleanup_at = -1_000_000.0
        session = AsyncMock()
        with patch.object(
            monitoring, 'get_async_db_context',
            return_value=_FakeSessionCtx(session),
        ):
            await monitoring._maybe_cleanup()
        assert monitoring._last_cleanup_at > 0.0


class TestSummaryFallback:
    """/vitals/summary 在落库不可用时回退进程内统计"""

    @pytest.mark.asyncio
    async def test_falls_back_to_memory_when_db_unavailable(self):
        monitoring._remember(_entry(value=1234.0))
        with patch.object(
            monitoring, 'get_async_db_context',
            side_effect=RuntimeError('数据库引擎未初始化'),
        ):
            resp = await monitoring.vitals_summary(hours=24, _current_user_id=1)
        assert resp['metrics']['LCP']['good']['count'] == 1
        assert '进程内' in resp['note']

    @pytest.mark.asyncio
    async def test_returns_db_note_on_success(self):
        metrics = {'LCP': {'good': {'count': 5, 'avg': 1.0, 'p95': 2.0}}}
        with patch.object(
            monitoring, '_summarize_from_db',
            new=AsyncMock(return_value=metrics),
        ):
            resp = await monitoring.vitals_summary(hours=6, _current_user_id=1)
        assert resp['metrics']['LCP']['good']['count'] == 5
        assert 'web_vital' in resp['note']
