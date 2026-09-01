"""健康判定 — 连续失败追踪、黄金四指标分级、错误预算燃烧率、探针策略。

依据（v8 方案 §2.4 与附录 A）：

    - 黄金四信号（Google SRE）：延迟 / 流量 / 错误 / 饱和度。
      分级阈值取 ARMS 默认口径：错误率 warn 1% / crit 5%，
      平均耗时 warn 100ms / crit 500ms，饱和度 warn 60% / crit 85%
    - 防抖：连续失败达到 failure_threshold（默认 3）才判不健康（K8s 语义）
    - 错误预算：单机裁剪为 24h 可用性预算，双窗口燃烧率——
      快烧（15min 内失败 > 3min）→ P1；慢烧（6h 内失败 > 30min）→ P2
    - 探针默认值对齐 Kubernetes 官方：period 10s / timeout 1s /
      failureThreshold 3；liveness 与 startup 的 successThreshold 必须为 1
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import HealthSample, Severity

__all__ = [
    'DEFAULT_PROBES',
    'GOLDEN_FOUR_THRESHOLDS',
    'BudgetVerdict',
    'FailureTracker',
    'MetricGrade',
    'ProbePolicy',
    'budget_severity',
    'fast_burn',
    'golden_four',
    'grade_metric',
    'slow_burn',
]


class FailureTracker:
    """单目标连续失败追踪。

    - 连续失败达到 threshold 才判 down（单点毛刺天然防抖）
    - startup_grace_s：从未成功过且距首个样本不足宽限期时，不判 down
      （覆盖服务最坏启动时间，语义对齐 K8s startupProbe）
    - 任一次成功即清零
    """

    def __init__(self, threshold: int = 3, startup_grace_s: float = 60.0) -> None:
        if threshold < 1:
            raise ValueError('threshold 必须 >= 1')
        self.threshold = threshold
        self.startup_grace_s = startup_grace_s
        self._consecutive = 0
        self._first_ts: float | None = None
        self._ever_ok = False

    def record(self, ok: bool, ts: float, *, error: str = '', latency_ms: int = 0,
               status_code: int = 0) -> HealthSample:
        """记录一次探测结果，返回携带连续失败数的样本。"""
        if self._first_ts is None:
            self._first_ts = ts
        if ok:
            self._consecutive = 0
            self._ever_ok = True
        else:
            self._consecutive += 1
        return HealthSample(
            ok=ok,
            latency_ms=latency_ms,
            status_code=status_code,
            error=error,
            consecutive_fail=self._consecutive,
        )

    @property
    def consecutive_fail(self) -> int:
        return self._consecutive

    def is_down(self, now: float | None = None) -> bool:
        """是否已判不健康。now 用于启动宽限判定。"""
        if self._consecutive < self.threshold:
            return False
        if self._ever_ok:
            return True
        # 从未成功过：处于启动宽限期内不判 down
        if now is not None and self._first_ts is not None:
            return now - self._first_ts > self.startup_grace_s
        return True

    def reset(self) -> None:
        self._consecutive = 0
        self._first_ts = None
        self._ever_ok = False


# ===================== 黄金四指标 =====================

GRADE_OK, GRADE_WARN, GRADE_CRIT = 'ok', 'warn', 'crit'

# (warn_at, crit_at) —— ARMS 默认口径
GOLDEN_FOUR_THRESHOLDS: dict[str, tuple[float, float]] = {
    'latency_ms': (100.0, 500.0),
    'error_rate': (0.01, 0.05),
    'saturation': (60.0, 85.0),
}


@dataclass(frozen=True)
class MetricGrade:
    """单指标分级结果。"""

    name: str
    value: float
    grade: str  # ok / warn / crit
    warn_at: float
    crit_at: float


def grade_metric(name: str, value: float, warn_at: float, crit_at: float) -> MetricGrade:
    """越高越糟的指标分级。流量类指标（QPS）无阈值，不进此函数。"""
    if value >= crit_at:
        grade = GRADE_CRIT
    elif value >= warn_at:
        grade = GRADE_WARN
    else:
        grade = GRADE_OK
    return MetricGrade(name=name, value=value, grade=grade, warn_at=warn_at, crit_at=crit_at)


def golden_four(
    latency_p95_ms: float,
    qps: float,
    error_rate: float,
    saturation: float,
) -> tuple[MetricGrade, ...]:
    """黄金四指标分级。流量（QPS）仅展示不分级，饱和度取 CPU/内存/磁盘最大值。"""
    return (
        grade_metric('latency_ms', latency_p95_ms, *GOLDEN_FOUR_THRESHOLDS['latency_ms']),
        MetricGrade(name='qps', value=qps, grade=GRADE_OK, warn_at=0.0, crit_at=0.0),
        grade_metric('error_rate', error_rate, *GOLDEN_FOUR_THRESHOLDS['error_rate']),
        grade_metric('saturation', saturation, *GOLDEN_FOUR_THRESHOLDS['saturation']),
    )


def overall_grade(grades: tuple[MetricGrade, ...]) -> str:
    """整体健康 = 最差分级（crit > warn > ok）。"""
    order = {GRADE_OK: 0, GRADE_WARN: 1, GRADE_CRIT: 2}
    return max(grades, key=lambda g: order[g.grade]).grade


# ===================== 错误预算燃烧率 =====================


@dataclass(frozen=True)
class BudgetVerdict:
    """可用性预算裁决。severity 为 None 表示未触发。"""

    window_minutes: float
    fail_minutes: float
    threshold_minutes: float
    severity: Severity | None

    @property
    def burn_ratio(self) -> float:
        """燃烧倍率 = 失败分钟 / 阈值分钟。"""
        return self.fail_minutes / self.threshold_minutes if self.threshold_minutes else 0.0

    @property
    def tripped(self) -> bool:
        """是否触发。P4 表示未触发仅记录，不是真触发。"""
        return self.severity is not None and self.severity is not Severity.P4


def fast_burn(fail_minutes: float, window_minutes: float = 15.0, threshold_minutes: float = 3.0) -> BudgetVerdict:
    """快烧：15min 窗口内失败超过 3min → P1（立即处理）。"""
    tripped = fail_minutes > threshold_minutes
    return BudgetVerdict(
        window_minutes=window_minutes,
        fail_minutes=fail_minutes,
        threshold_minutes=threshold_minutes,
        severity=Severity.P1 if tripped else Severity.P4,
    )


def slow_burn(fail_minutes: float, window_minutes: float = 360.0, threshold_minutes: float = 30.0) -> BudgetVerdict:
    """慢烧：6h 窗口内失败超过 30min → P2（建单跟进）。"""
    tripped = fail_minutes > threshold_minutes
    return BudgetVerdict(
        window_minutes=window_minutes,
        fail_minutes=fail_minutes,
        threshold_minutes=threshold_minutes,
        severity=Severity.P2 if tripped else Severity.P4,
    )


def budget_severity(fail_minutes_15m: float, fail_minutes_6h: float) -> BudgetVerdict:
    """双窗口燃烧率合成：快烧优先于慢烧，两者都未触发则 P4（仅记录）。"""
    fast = fast_burn(fail_minutes_15m)
    if fast.tripped:
        return fast
    return slow_burn(fail_minutes_6h)


# ===================== 探针策略（K8s 三类探针默认值） =====================


@dataclass(frozen=True)
class ProbePolicy:
    """探针策略。kind: startup / liveness / readiness。"""

    kind: str
    period_s: float = 10.0
    timeout_s: float = 1.0
    failure_threshold: int = 3
    success_threshold: int = 1

    def validate(self) -> tuple[bool, str]:
        """K8s 语义校验：liveness / startup 的 successThreshold 必须为 1。"""
        if self.kind not in ('startup', 'liveness', 'readiness'):
            return False, f'未知探针类型 {self.kind}'
        if self.period_s < 1:
            return False, 'period_s 最小为 1'
        if self.timeout_s < 1:
            return False, 'timeout_s 最小为 1'
        if self.kind in ('startup', 'liveness') and self.success_threshold != 1:
            return False, f'{self.kind} 探针的 successThreshold 必须为 1'
        return True, ''

    @property
    def max_startup_wait_s(self) -> float:
        """startup 探针覆盖的最坏启动时间 = period × failureThreshold。"""
        return self.period_s * self.failure_threshold


DEFAULT_PROBES: dict[str, ProbePolicy] = {
    # startup：30×10=300s 覆盖最坏启动时间
    'startup': ProbePolicy(kind='startup', period_s=10, timeout_s=1, failure_threshold=30),
    'liveness': ProbePolicy(kind='liveness'),  # 3×10
    'readiness': ProbePolicy(kind='readiness'),  # 3×10
}
