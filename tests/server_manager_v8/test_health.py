"""健康判定测试：连续失败追踪、黄金四指标、错误预算燃烧率、探针策略。"""
from __future__ import annotations

import pytest

from server_manager_v8.domain import (
    DEFAULT_PROBES,
    FailureTracker,
    Severity,
    budget_severity,
    fast_burn,
    golden_four,
    overall_grade,
    slow_burn,
)


class TestFailureTracker:
    def test_requires_consecutive_failures(self) -> None:
        """连续失败 3 次才判 down（天然防抖）。"""
        t = FailureTracker(threshold=3, startup_grace_s=0)
        t.record(False, ts=1.0)
        t.record(False, ts=2.0)
        assert not t.is_down()
        t.record(False, ts=3.0)
        assert t.is_down() and t.consecutive_fail == 3

    def test_success_resets(self) -> None:
        t = FailureTracker(threshold=3)
        t.record(False, 1.0)
        t.record(False, 2.0)
        t.record(True, 3.0)
        assert not t.is_down() and t.consecutive_fail == 0
        assert t.record(False, 4.0).consecutive_fail == 1

    def test_startup_grace(self) -> None:
        """从未成功过 + 宽限期内 → 不判 down（覆盖最坏启动时间）。"""
        t = FailureTracker(threshold=3, startup_grace_s=60.0)
        for i in range(5):
            t.record(False, ts=float(i))
        assert not t.is_down(now=30.0)  # 仍在 60s 宽限内
        assert t.is_down(now=61.0)  # 超过宽限期

    def test_grace_not_applied_after_first_success(self) -> None:
        t = FailureTracker(threshold=2, startup_grace_s=60.0)
        t.record(True, 1.0)  # 曾经成功过
        t.record(False, 2.0)
        t.record(False, 3.0)
        assert t.is_down()  # 不再享宽限

    def test_invalid_threshold_rejected(self) -> None:
        with pytest.raises(ValueError):
            FailureTracker(threshold=0)

    def test_sample_carries_details(self) -> None:
        t = FailureTracker()
        s = t.record(False, 1.0, error='connect refused', latency_ms=0, status_code=0)
        assert s.ok is False and s.error == 'connect refused' and s.consecutive_fail == 1
        s2 = t.record(True, 2.0, latency_ms=42, status_code=200)
        assert s2.latency_ms == 42 and s2.status_code == 200


class TestGoldenFour:
    def test_arms_thresholds(self) -> None:
        """阈值取 ARMS 默认：错误率 1%/5%、耗时 100/500ms、饱和度 60/85%。"""
        grades = golden_four(latency_p95_ms=120, qps=1000, error_rate=0.02, saturation=50)
        by_name = {g.name: g for g in grades}
        assert by_name['latency_ms'].grade == 'warn'
        assert by_name['error_rate'].grade == 'warn'
        assert by_name['saturation'].grade == 'ok'

    def test_crit_boundaries(self) -> None:
        grades = golden_four(latency_p95_ms=600, qps=0, error_rate=0.06, saturation=90)
        by_name = {g.name: g for g in grades}
        assert all(by_name[n].grade == 'crit'
                   for n in ('latency_ms', 'error_rate', 'saturation'))

    def test_qps_informational_only(self) -> None:
        """流量只展示不分级。"""
        g = golden_four(latency_p95_ms=10, qps=99_999, error_rate=0, saturation=0)
        assert next(x for x in g if x.name == 'qps').grade == 'ok'

    def test_overall_is_worst(self) -> None:
        grades = golden_four(latency_p95_ms=600, qps=1, error_rate=0.0, saturation=10)
        assert overall_grade(grades) == 'crit'
        ok_all = golden_four(latency_p95_ms=10, qps=1, error_rate=0.0, saturation=10)
        assert overall_grade(ok_all) == 'ok'


class TestErrorBudget:
    def test_fast_burn_p1(self) -> None:
        """15min 内失败 > 3min → P1。"""
        assert fast_burn(fail_minutes=3.5).severity is Severity.P1
        assert fast_burn(fail_minutes=2.9).severity is Severity.P4

    def test_slow_burn_p2(self) -> None:
        """6h 内失败 > 30min → P2。"""
        assert slow_burn(fail_minutes=31).severity is Severity.P2
        assert slow_burn(fail_minutes=29).severity is Severity.P4

    def test_combined_fast_wins(self) -> None:
        v = budget_severity(fail_minutes_15m=5, fail_minutes_6h=40)
        assert v.severity is Severity.P1  # 快烧优先

    def test_combined_slow_fallback(self) -> None:
        v = budget_severity(fail_minutes_15m=1, fail_minutes_6h=45)
        assert v.severity is Severity.P2

    def test_burn_ratio(self) -> None:
        v = fast_burn(fail_minutes=6)
        assert v.burn_ratio == pytest.approx(2.0)  # 6/3 = 2 倍燃烧率
        assert v.tripped


class TestProbePolicy:
    def test_k8s_defaults(self) -> None:
        """默认值对齐 K8s 官方：period 10s / timeout 1s / failure 3 / success 1。"""
        for kind, probe in DEFAULT_PROBES.items():
            assert probe.period_s == 10 and probe.timeout_s == 1
            assert probe.validate() == (True, ''), kind
        assert DEFAULT_PROBES['startup'].failure_threshold == 30  # 300s 覆盖最坏启动
        assert DEFAULT_PROBES['liveness'].failure_threshold == 3

    def test_liveness_success_threshold_must_be_one(self) -> None:
        from server_manager_v8.domain import ProbePolicy
        bad = ProbePolicy(kind='liveness', success_threshold=3)
        ok, msg = bad.validate()
        assert not ok and 'successThreshold' in msg
        # readiness 允许多次成功
        assert ProbePolicy(kind='readiness', success_threshold=3).validate()[0]

    def test_min_periods(self) -> None:
        from server_manager_v8.domain import ProbePolicy
        assert not ProbePolicy(kind='liveness', period_s=0.5).validate()[0]
        assert not ProbePolicy(kind='liveness', timeout_s=0.5).validate()[0]
        assert not ProbePolicy(kind='unknown').validate()[0]

    def test_max_startup_wait(self) -> None:
        assert DEFAULT_PROBES['startup'].max_startup_wait_s == 300.0
