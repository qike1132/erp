"""readiness 模块单测。

全部使用**注入的假时钟**，测试是确定性的、毫秒级完成，不依赖真实时间。
这是把「时间」抽象为可注入依赖的直接收益 —— 原实现含 time.sleep 完全无法单测。
"""

from __future__ import annotations

import pytest

from server_manager_v8.domain.readiness import (
    POLICY_HTTP_BACKEND,
    POLICY_REDIS_SERVICE,
    POLICY_SERVICE_RUNNING,
    POLICY_SERVICE_STOPPED,
    WaitOutcome,
    WaitPolicy,
    WaitStatus,
    combine_all,
    combine_all_cached,
    combine_any,
    is_not_conservatively_running,
    is_running_predicate,
    is_stopped_predicate,
    wait_until,
)


# ═══════════════════════════════════════════════════════════════════
# 测试替身：虚拟时钟
# ═══════════════════════════════════════════════════════════════════


class FakeClock:
    """确定性虚拟时钟。sleep 直接推进时间，不真实等待。"""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


# ═══════════════════════════════════════════════════════════════════
# WaitPolicy
# ═══════════════════════════════════════════════════════════════════


class TestWaitPolicy:
    def test_defaults(self):
        p = WaitPolicy()
        assert p.timeout_s == 30.0
        assert p.interval_s == 1.0
        assert p.consecutive_ok == 1

    def test_rejects_non_positive_timeout(self):
        with pytest.raises(ValueError, match='timeout_s'):
            WaitPolicy(timeout_s=0)
        with pytest.raises(ValueError, match='timeout_s'):
            WaitPolicy(timeout_s=-5)

    def test_rejects_non_positive_interval(self):
        with pytest.raises(ValueError, match='interval_s'):
            WaitPolicy(interval_s=0)

    def test_rejects_invalid_consecutive_ok(self):
        with pytest.raises(ValueError, match='consecutive_ok'):
            WaitPolicy(consecutive_ok=0)

    def test_max_attempts(self):
        assert WaitPolicy(timeout_s=30, interval_s=1).max_attempts == 31
        assert WaitPolicy(timeout_s=45, interval_s=1).max_attempts == 46

    def test_max_attempts_at_least_one(self):
        """极短超时也必须至少探测一次。"""
        assert WaitPolicy(timeout_s=0.1, interval_s=1.0).max_attempts == 1

    def test_policy_constants_match_legacy_defaults(self):
        """★ 策略常量必须与原实现的硬编码默认值一致（迁移保真）。"""
        assert POLICY_SERVICE_STOPPED.timeout_s == 45.0   # _wait_service_stopped(timeout=45)
        assert POLICY_SERVICE_RUNNING.timeout_s == 60.0   # _wait_service_running(timeout=60)
        assert POLICY_REDIS_SERVICE.timeout_s == 30.0     # _wait_redis_svc_running(timeout=30)
        assert POLICY_HTTP_BACKEND.timeout_s == 30.0      # _wait_http(attempts=30)
        assert POLICY_HTTP_BACKEND.interval_s == 1.0

    def test_policy_is_frozen(self):
        p = WaitPolicy()
        with pytest.raises(Exception):
            p.timeout_s = 99  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════
# wait_until —— 时序边界（核心）
# ═══════════════════════════════════════════════════════════════════


class TestWaitUntilBasic:
    def test_immediate_success(self, clock):
        """首次即满足 → 不 sleep。"""
        out = wait_until(lambda: True, clock=clock.time, sleep=clock.sleep)
        assert out.ok
        assert out.attempts == 1
        assert clock.sleeps == []
        assert out.elapsed_s == 0.0

    def test_success_after_n_polls(self, clock):
        """第 3 次才满足 → 前两次各 sleep 一次。"""
        calls = {'n': 0}

        def probe() -> bool:
            calls['n'] += 1
            return calls['n'] >= 3

        out = wait_until(probe, clock=clock.time, sleep=clock.sleep)
        assert out.ok
        assert out.attempts == 3
        assert clock.sleeps == [1.0, 1.0]

    def test_timeout_when_never_satisfied(self, clock):
        out = wait_until(
            lambda: False,
            WaitPolicy(timeout_s=5.0, interval_s=1.0),
            clock=clock.time,
            sleep=clock.sleep,
        )
        assert out.timed_out
        assert not out.ok
        # ★ 对齐原实现（while now < deadline）：t=0..4 各探一次 = 5 次
        assert out.attempts == 5
        assert out.elapsed_s == 5.0

    def test_short_timeout_still_probes_once(self, clock):
        """★ 超时预算短于间隔时仍会探测一次（对齐原实现）。

        timeout=0.5, interval=1.0 → 仅 t=0 满足 `0 < 0.5`，探测 1 次即超时。
        由于 WaitPolicy 禁止非正 timeout，本原语不可能零次探测。
        """
        probes = {'n': 0}

        def probe() -> bool:
            probes['n'] += 1
            return False

        out = wait_until(
            probe,
            WaitPolicy(timeout_s=0.5, interval_s=1.0),
            clock=clock.time,
            sleep=clock.sleep,
        )
        assert out.timed_out
        assert probes['n'] == 1, '短预算下也必须探测至少一次'

    @pytest.mark.parametrize('timeout,expected_attempts', [
        (5.0, 5), (3.0, 3), (1.0, 1), (0.5, 1), (10.0, 10),
    ])
    def test_attempt_count_matches_legacy_semantics(self, timeout, expected_attempts):
        """★ 迁移保真：探测次数必须与原 `while now < deadline` 结构一致。"""
        c = FakeClock()
        out = wait_until(
            lambda: False,
            WaitPolicy(timeout_s=timeout, interval_s=1.0),
            clock=c.time,
            sleep=c.sleep,
        )
        assert out.attempts == expected_attempts

    def test_polls_at_expected_interval(self, clock):
        wait_until(
            lambda: False,
            WaitPolicy(timeout_s=3.0, interval_s=0.5),
            clock=clock.time,
            sleep=clock.sleep,
        )
        assert all(s == 0.5 for s in clock.sleeps)


class TestWaitUntilAbort:
    def test_abort_takes_priority(self, clock):
        """中止检查优先于其它分支。"""
        out = wait_until(
            lambda: True,
            aborted=lambda: True,
            clock=clock.time,
            sleep=clock.sleep,
        )
        assert out.aborted
        assert not out.ok

    def test_abort_after_some_polls(self, clock):
        state = {'n': 0}

        def aborted() -> bool:
            return state['n'] >= 3

        def probe() -> bool:
            state['n'] += 1
            return False

        out = wait_until(probe, aborted=aborted, clock=clock.time, sleep=clock.sleep)
        assert out.aborted
        assert out.attempts == 3


class TestConsecutiveOk:
    """consecutive_ok > 1 的去抖动语义（借鉴 uptime-kuma）。"""

    def test_requires_consecutive_successes(self, clock):
        """需连续 2 次成功：成功、成功 → 达成（第 2 次即返回）。"""
        seq = iter([True, True])
        out = wait_until(
            lambda: next(seq),
            WaitPolicy(timeout_s=10, interval_s=1, consecutive_ok=2),
            clock=clock.time,
            sleep=clock.sleep,
        )
        assert out.ok
        assert out.attempts == 2

    def test_streak_reset_on_failure(self, clock):
        """成功、失败、成功、成功 → 4 次才达成（中途失败清零）。"""
        seq = iter([True, False, True, True])
        out = wait_until(
            lambda: next(seq),
            WaitPolicy(timeout_s=10, interval_s=1, consecutive_ok=2),
            clock=clock.time,
            sleep=clock.sleep,
        )
        assert out.ok
        assert out.attempts == 4

    def test_times_out_if_streak_never_reaches(self, clock):
        """交替成功/失败永不达标 → 超时。"""
        toggle = {'v': False}

        def probe() -> bool:
            toggle['v'] = not toggle['v']
            return toggle['v']

        out = wait_until(
            probe,
            WaitPolicy(timeout_s=4, interval_s=1, consecutive_ok=3),
            clock=clock.time,
            sleep=clock.sleep,
        )
        assert out.timed_out


class TestObserve:
    def test_observation_recorded_on_failure(self, clock):
        out = wait_until(
            lambda: False,
            WaitPolicy(timeout_s=2, interval_s=1),
            clock=clock.time,
            sleep=clock.sleep,
            observe=lambda: '3 STOP_PENDING',
        )
        assert out.timed_out
        assert out.last_observation == '3 STOP_PENDING'

    def test_observation_exception_never_breaks_wait(self, clock):
        """★ 诊断异常绝不能打断等待（v5.38 D15 教训）。"""

        def bad_observe() -> str:
            raise AttributeError("'NoneType' object has no attribute 'x'")

        out = wait_until(
            lambda: True,
            clock=clock.time,
            sleep=clock.sleep,
            observe=bad_observe,
        )
        assert out.ok, '观测函数抛异常不应影响等待结果'
        assert out.last_observation is None


class TestFailureReason:
    def test_reason_includes_subject_elapsed_attempts(self, clock):
        out = wait_until(
            lambda: False,
            WaitPolicy(timeout_s=3, interval_s=1),
            clock=clock.time,
            sleep=clock.sleep,
            observe=lambda: '4 RUNNING',
        )
        reason = out.failure_reason('erp-prod')
        assert 'erp-prod' in reason
        assert '3s' in reason
        assert '4 RUNNING' in reason

    def test_reason_none_on_success(self, clock):
        out = wait_until(lambda: True, clock=clock.time, sleep=clock.sleep)
        assert out.failure_reason('erp-prod') is None

    def test_reason_for_aborted(self, clock):
        out = wait_until(lambda: False, aborted=lambda: True, clock=clock.time, sleep=clock.sleep)
        assert '中止' in out.failure_reason('erp-prod')


# ═══════════════════════════════════════════════════════════════════
# 谓词组合
# ═══════════════════════════════════════════════════════════════════


class TestCombineAll:
    def test_all_true(self):
        assert combine_all([lambda: True, lambda: True])() is True

    def test_one_false(self):
        assert combine_all([lambda: True, lambda: False])() is False

    def test_empty_is_true(self):
        assert combine_all([])() is True

    def test_no_short_circuit(self):
        """★ 无短路：所有谓词都会被调用（对齐 _wait_service_running 语义）。"""
        calls = []
        combine_all([
            lambda: calls.append('a') or True,
            lambda: calls.append('b') or True,
        ])()
        assert calls == ['a', 'b']


class TestCombineAllCached:
    """★ 带缓存的三项全过语义 —— 精确迁移 _wait_service_running。"""

    def test_caches_successful_probe(self):
        """已成功的探针不再重探（节省超时预算）。"""
        api_calls, web_calls = [], []
        state = {'api': False, 'web': False}

        def api_probe() -> bool:
            api_calls.append(1)
            state['api'] = True          # 首次即成功
            return True

        def web_probe() -> bool:
            web_calls.append(1)
            return len(web_calls) >= 3   # 第 3 次才成功

        check, st = combine_all_cached([('api', api_probe), ('web', web_probe)])

        assert check() is False   # api=ok, web 未就绪
        assert check() is False
        assert check() is True    # web 第 3 次成功
        assert len(api_calls) == 1, 'api 已就绪后不应重探'
        assert len(web_calls) == 3
        assert st == {'api': True, 'web': True}

    def test_both_must_succeed(self):
        check, _ = combine_all_cached([('a', lambda: True), ('b', lambda: False)])
        assert check() is False

    def test_integration_with_wait_until(self, clock):
        """端到端：模拟 erp-prod 需 RUNNING + /api/health + /nginx-health 三项全过。"""
        web_calls = {'n': 0}

        def web_probe() -> bool:
            web_calls['n'] += 1
            return web_calls['n'] >= 3

        check, _ = combine_all_cached([
            ('running', lambda: True),   # 服务已 RUNNING
            ('api', lambda: True),        # API 已就绪
            ('web', web_probe),           # 前端第 3 次才就绪
        ])
        out = wait_until(check, WaitPolicy(timeout_s=10), clock=clock.time, sleep=clock.sleep)
        assert out.ok
        assert out.attempts == 3


class TestCombineAny:
    def test_any_true(self):
        assert combine_any([lambda: False, lambda: True])() is True

    def test_all_false(self):
        assert combine_any([lambda: False, lambda: False])() is False

    def test_short_circuits(self):
        calls = []
        combine_any([
            lambda: True,
            lambda: calls.append('b') or False,
        ])()
        assert calls == []


# ═══════════════════════════════════════════════════════════════════
# 领域谓词
# ═══════════════════════════════════════════════════════════════════


class TestDomainPredicates:
    def test_is_running(self):
        state = {'v': '1 STOPPED'}
        pred = is_running_predicate(lambda: state['v'])
        assert pred() is False
        state['v'] = '4 RUNNING'
        assert pred() is True

    def test_is_running_rejects_pending(self):
        """STOP_PENDING 不该被当成就绪。"""
        assert is_running_predicate(lambda: '3 STOP_PENDING')() is False
        assert is_running_predicate(lambda: '2 START_PENDING')() is False

    def test_is_running_rejects_unknown_and_absent(self):
        assert is_running_predicate(lambda: '未知')() is False
        assert is_running_predicate(lambda: '未安装')() is False

    def test_is_stopped(self):
        assert is_stopped_predicate(lambda: '1 STOPPED')() is True
        assert is_stopped_predicate(lambda: '4 RUNNING')() is False
        assert is_stopped_predicate(lambda: '3 STOP_PENDING')() is False

    def test_is_stopped_does_not_accept_absent(self):
        """严格 STOPPED 判定不把「未安装」算作停止。"""
        assert is_stopped_predicate(lambda: '未安装')() is False


class TestIsNotConservativelyRunning:
    """★ 模式切换前置守卫的核心安全性质。"""

    def test_stopped_releases(self):
        assert is_not_conservatively_running(lambda: '1 STOPPED')() is True

    def test_absent_releases(self):
        """服务不存在，自然无需停止 → 放行。"""
        assert is_not_conservatively_running(lambda: '未安装')() is True

    def test_running_blocks(self):
        assert is_not_conservatively_running(lambda: '4 RUNNING')() is False

    def test_pending_blocks(self):
        assert is_not_conservatively_running(lambda: '3 STOP_PENDING')() is False

    def test_unknown_blocks(self):
        """★ 未知必须阻断 —— 这是互杀事故的核心防线。

        若「未知」被放行，_ensure_production_stopped 会静默跳过仍在运行的生产服务，
        开发模式随即抢占 5002/3000 与生产互相厮杀。
        """
        assert is_not_conservatively_running(lambda: '未知')() is False


# ═══════════════════════════════════════════════════════════════════
# 端到端场景：迁移自真实等待路径
# ═══════════════════════════════════════════════════════════════════


class TestMigrationScenarios:
    def test_service_stopped_after_pending(self, clock):
        """模拟 _wait_service_stopped：STOP_PENDING 若干轮后变 STOPPED。"""
        states = iter(['3 STOP_PENDING'] * 3 + ['1 STOPPED'] * 5)

        def provider() -> str:
            try:
                return next(states)
            except StopIteration:
                return '1 STOPPED'

        out = wait_until(
            is_stopped_predicate(provider),
            POLICY_SERVICE_STOPPED,
            clock=clock.time,
            sleep=clock.sleep,
        )
        assert out.ok
        assert out.attempts == 4

    def test_service_stop_timeout_with_observation(self, clock):
        """模拟服务始终 STOP_PENDING → 超时并保留最后观测。"""
        out = wait_until(
            is_stopped_predicate(lambda: '3 STOP_PENDING'),
            WaitPolicy(timeout_s=5),
            clock=clock.time,
            sleep=clock.sleep,
            observe=lambda: '3 STOP_PENDING',
        )
        assert out.timed_out
        assert 'STOP_PENDING' in out.last_observation
        # 失败原因可供 UI 展示真实原因（而非空洞的「失败」）
        assert 'STOP_PENDING' in out.failure_reason('erp-prod')

    def test_unknown_service_cannot_be_confirmed_stopped(self, clock):
        """★ 端到端安全性质：查询失败 → 无法确认停止 → 守卫不放行。

        对应 v5.40 交付报告自证断言 A5：
            状态未知且无法确认停止 → ok=False，切换被中止（不释放端口、不启动）
        """
        out = wait_until(
            is_not_conservatively_running(lambda: '未知'),
            WaitPolicy(timeout_s=3),
            clock=clock.time,
            sleep=clock.sleep,
        )
        assert not out.ok, '状态未知时绝不能让守卫放行'
