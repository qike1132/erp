"""症状化告警引擎 — 纯逻辑，替代 v6 的 AlertEngine（阈值 + 60s 冷却）。

设计依据（Google SRE + 蓝鲸 + Alertmanager，详见 docs/ui-redesign/v8 方案 §2.4）：

    - **告警症状而非原因**：规则面向「API 健康检查连续失败 ≥ 3 次」这类症状，
      CPU/内存/磁盘只是 P3 饱和度预警
    - **持续周期防抖**（阿里云口径）：条件须持续 for_s 才触发，单点毛刺不告警
    - **runbook 强制绑定 + 可行动性**：P0–P2 规则必须带 runbook 与 suggested_action
    - **抑制**（蓝鲸口径）：存在高级别告警时，同服务低级别不再产生；
      另支持显式依赖链规则（如 pg_down 抑制 api_5xx）
    - **静默**：维护窗口内告警**只记不通知**（不能变黑洞，UI 顶部须展示生效中的静默数）
    - **收敛存储**：同键未确认合并（count+1）+ 60s 冷却 + 上限 100（优先淘汰已恢复）

全部时间经 ClockPort 注入，可单测。
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .models import Alert, OpResult, Severity

__all__ = [
    'AlertCenter',
    'AlertDecision',
    'AlertRule',
    'Inhibition',
    'RuleEvaluator',
    'Silence',
    'SilenceBook',
]

# 比较算子 -> 谓词
_OPS = {
    'ge': lambda v, t: v >= t,
    'gt': lambda v, t: v > t,
    'le': lambda v, t: v <= t,
    'lt': lambda v, t: v < t,
    'eq': lambda v, t: v == t,
    'ne': lambda v, t: v != t,
}


@dataclass(frozen=True)
class AlertRule:
    """告警规则。expr 语义：``metric <op> threshold`` 持续 ``for_s`` 秒触发。

    family 用于分组与抑制（如 'availability' / 'saturation' / 'queue'）。
    service 为空表示对任意服务生效（如全局饱和度规则）。
    """

    id: str
    metric: str
    op: str  # ge / gt / le / lt / eq / ne
    threshold: float
    severity: Severity
    family: str = 'availability'
    service: str = ''  # 空 = 任意服务
    for_s: float = 30.0  # 持续周期（阿里云：1/3/5/10/15/30/60 周期裁剪为秒）
    title: str = ''
    runbook: str = ''
    suggested_action: str = ''
    enabled: bool = True

    def validate(self) -> OpResult:
        """配置期校验。P0–P2 强制 runbook + suggested_action（SRE 可行动性）。"""
        if self.op not in _OPS:
            return OpResult.failure(f'规则 {self.id}: 未知比较算子 {self.op!r}')
        if self.for_s < 0:
            return OpResult.failure(f'规则 {self.id}: for_s 不能为负')
        if self.severity in (Severity.P0, Severity.P1, Severity.P2):
            if not self.runbook:
                return OpResult.failure(f'规则 {self.id}: {self.severity.value} 级必须绑定 runbook')
            if not self.suggested_action:
                return OpResult.failure(f'规则 {self.id}: {self.severity.value} 级必须给出 suggested_action')
        return OpResult.success()

    def matches(self, value: float) -> bool:
        return _OPS[self.op](value, self.threshold)

    def alert_key(self, service: str) -> str:
        """去重键。全局规则按服务区分实例。"""
        return self.id if self.service else f'{self.id}@{service or "global"}'

    def to_alert(self, service: str, value: float, ts: float) -> Alert:
        return Alert(
            key=self.alert_key(service),
            severity=self.severity,
            title=self.title or f'{self.metric} {self.op} {self.threshold}',
            desc=f'{service or "global"} · {self.metric}={value:g}（阈值 {self.op} {self.threshold:g}，持续 {self.for_s:g}s）',
            service=service,
            family=self.family,
            ts=ts,
            runbook=self.runbook,
            suggested_action=self.suggested_action,
        )


class RuleEvaluator:
    """滑动窗口求值：条件须持续 for_s 才产出告警（毛刺防抖）。

    实现按「首次越界时间戳」而非保留完整窗口：任一不越界样本即重置。
    持续越界期间每次 feed 都会产出候选，由 AlertCenter 冷却/合并收敛。
    """

    def __init__(self, rules: Sequence[AlertRule]) -> None:
        invalid = [r.id for r in rules if r.validate().ok is False]
        if invalid:
            raise ValueError(f'存在校验不通过的规则: {invalid}')
        self._rules = tuple(r for r in rules if r.enabled)
        self._breach_since: dict[str, float] = {}

    def feed(self, service: str, metric: str, value: float, ts: float) -> list[Alert]:
        """喂入一个采样点，返回触发的告警候选（可能为空）。"""
        fired: list[Alert] = []
        for rule in self._rules:
            if rule.metric != metric or (rule.service and rule.service != service):
                continue
            key = (rule.id, service)
            if rule.matches(value):
                first = self._breach_since.setdefault(key, ts)
                if ts - first >= rule.for_s:
                    fired.append(rule.to_alert(service, value, ts))
            else:
                self._breach_since.pop(key, None)
        return fired

    def reset(self, rule_id: str | None = None, service: str | None = None) -> None:
        """清除越界状态（服务恢复时调用）。"""
        if rule_id is None:
            self._breach_since.clear()
            return
        self._breach_since.pop((rule_id, service or ''), None)


@dataclass(frozen=True)
class Silence:
    """静默单。静默期内告警只记不通知。"""

    id: str
    start_ts: float
    end_ts: float
    service: str = ''  # 空 = 全部服务
    family: str = ''  # 空 = 全部告警族
    reason: str = ''
    created_by: str = ''


class SilenceBook:
    """静默登记簿。UI 须常驻展示 active_count，避免静默变黑洞。"""

    def __init__(self, items: Sequence[Silence] = ()) -> None:
        self._items: list[Silence] = list(items)

    def add(self, silence: Silence) -> OpResult:
        if silence.end_ts <= silence.start_ts:
            return OpResult.failure('静默结束时间必须晚于开始时间')
        self._items.append(silence)
        return OpResult.success()

    def remove(self, silence_id: str) -> OpResult:
        before = len(self._items)
        self._items = [s for s in self._items if s.id != silence_id]
        if len(self._items) == before:
            return OpResult.failure(f'静默单 {silence_id} 不存在')
        return OpResult.success()

    def prune(self, now: float) -> int:
        """清除已过期静默，返回清除数。"""
        keep = [s for s in self._items if s.end_ts > now]
        removed = len(self._items) - len(keep)
        self._items = keep
        return removed

    def match(self, service: str, family: str, ts: float) -> Silence | None:
        """返回命中的静默单（未过期的最先匹配项）。"""
        for s in self._items:
            if not (s.start_ts <= ts < s.end_ts):
                continue
            if s.service and s.service != service:
                continue
            if s.family and s.family != family:
                continue
            return s
        return None

    @property
    def active_count(self) -> int:
        return len(self._items)

    @property
    def items(self) -> tuple[Silence, ...]:
        return tuple(self._items)


class Inhibition:
    """告警抑制。

    两类规则：
        1. 显式依赖链：``(source_family, (target_families...))``，
           同服务存在 firing 的 source 族告警时，target 族不再产生
        2. 隐式等级压制（蓝鲸口径，可关）：同服务存在更高严重级的 firing 告警时，
           低级别不再产生
    """

    def __init__(
        self,
        chain_rules: Sequence[tuple[str, tuple[str, ...]]] = (),
        implicit_severity: bool = True,
    ) -> None:
        self._chain = tuple(chain_rules)
        self._implicit = implicit_severity

    def find_suppressor(self, candidate: Alert, firing: Iterable[Alert]) -> str:
        """返回抑制方描述；无抑制返回空串。"""
        live = [a for a in firing if a.firing and a.key != candidate.key]
        # 隐式等级压制要求双方 service 非空且相同 —— service='' 的全局告警
        # 不属于任何具体服务，不参与同服务压制（否则会误抑制一切低级别告警）
        same_service = [a for a in live if a.service and a.service == candidate.service]
        # 1) 显式依赖链：跨服务生效（如 PG 服务挂 → 抑制 api 的连接类告警）
        for src_family, targets in self._chain:
            if candidate.family not in targets:
                continue
            for a in live:
                if a.family == src_family:
                    return f'{a.key}({src_family})'
        # 2) 隐式等级压制：仅同服务（蓝鲸口径）
        if self._implicit:
            for a in same_service:
                if a.severity.value < candidate.severity.value:  # P0 < P1 < ... 数值越小级别越高
                    return f'{a.key}({a.severity.value})'
        return ''


@dataclass(frozen=True)
class AlertDecision:
    """一次 ingest 的裁决结果，驱动 UI 通知与列表刷新。"""

    action: str  # raised / merged / cooled / silenced / inhibited
    alert: Alert | None
    notify: bool = False
    suppressed_by: str = ''
    silence_id: str = ''

    @property
    def raised_now(self) -> bool:
        return self.action == 'raised'


class AlertCenter:
    """告警中心（纯内存）。替代 v6 AlertEngine，持久化由 Adapter 层负责。

    收敛语义（对齐 v6 行为并升级）：
        - 60s 冷却：冷却期内同键重复触发直接忽略（cooled）
        - 未确认合并：冷却期满且同键仍在 firing 未确认 → count+1、刷新 last_ts（merged）
        - 已恢复的同键告警不阻塞重新触发
        - 上限 100：溢出时优先淘汰最早恢复的，再淘汰最早的
    """

    COOLDOWN_S = 60.0
    MAX_ALERTS = 100

    def __init__(
        self,
        evaluator: RuleEvaluator | None = None,
        inhibition: Inhibition | None = None,
        silences: SilenceBook | None = None,
    ) -> None:
        self.evaluator = evaluator
        self.inhibition = inhibition or Inhibition()
        self.silences = silences or SilenceBook()
        self._alerts: dict[str, Alert] = {}
        self._last_raise: dict[str, float] = {}
        self.suppressed_total = 0

    # ---- 写侧 ----

    def ingest(self, candidate: Alert, ts: float | None = None) -> AlertDecision:
        """告警入口：静默 → 抑制 → 冷却/合并 → 入库。"""
        now = ts if ts is not None else time.time()
        hit = self.silences.match(candidate.service, candidate.family, now)
        if hit is not None:
            stored = self._store(candidate, now, force_record=True)
            return AlertDecision(action='silenced', alert=stored, silence_id=hit.id)
        suppressor = self.inhibition.find_suppressor(candidate, self._alerts.values())
        if suppressor:
            self.suppressed_total += 1
            return AlertDecision(action='inhibited', alert=None, suppressed_by=suppressor)
        stored, action = self._store(candidate, now)
        # 仅新触发才通知；冷却期内忽略、合并不重复打扰（对齐 v6 行为）
        notify = bool(candidate.severity.notify_channels) and action == 'raised'
        return AlertDecision(action=action, alert=stored, notify=notify)

    def ack(self, key: str, by: str = '', ts: float | None = None) -> OpResult:
        """确认单条。"""
        a = self._alerts.get(key)
        if a is None:
            return OpResult.failure(f'告警 {key} 不存在')
        if not a.firing:
            return OpResult.failure(f'告警 {key} 已不是 firing 态')
        self._alerts[key] = a.ack(by=by, ts=ts if ts is not None else time.time())
        return OpResult.success()

    def ack_all(self, by: str = '', ts: float | None = None) -> int:
        """全部确认，返回确认条数。"""
        now = ts if ts is not None else time.time()
        n = 0
        for key, a in self._alerts.items():
            if a.firing:
                self._alerts[key] = a.ack(by=by, ts=now)
                n += 1
        return n

    def resolve(self, key: str, reason: str = '', ts: float | None = None) -> OpResult:
        """恢复关闭（健康恢复 / 服务回到期望态时由编排层调用）。"""
        a = self._alerts.get(key)
        if a is None:
            return OpResult.failure(f'告警 {key} 不存在')
        self._alerts[key] = a.resolve(reason=reason, ts=ts if ts is not None else time.time())
        return OpResult.success()

    def resolve_matching(self, prefix: str, reason: str = '', ts: float | None = None) -> int:
        """按前缀批量恢复（如规则 ID 对应的多个服务实例）。"""
        n = 0
        for key in [k for k in self._alerts if k == prefix or k.startswith(prefix + '@')]:
            self.resolve(key, reason=reason, ts=ts)
            n += 1
        return n

    # ---- 读侧 ----

    @property
    def alerts(self) -> tuple[Alert, ...]:
        """新→旧排序。"""
        return tuple(sorted(self._alerts.values(), key=lambda a: a.last_ts or a.ts, reverse=True))

    def firing(self) -> tuple[Alert, ...]:
        return tuple(a for a in self._alerts.values() if a.firing)

    def unconfirmed_count(self) -> int:
        """v6 兼容语义：firing 未确认数（驱动角标）。"""
        return sum(1 for a in self._alerts.values() if a.firing)

    def get(self, key: str) -> Alert | None:
        return self._alerts.get(key)

    def stats(self) -> dict[str, float]:
        """MTTA / MTTR（秒）与总量。无样本时对应值为 -1。"""
        acked = [a for a in self._alerts.values() if a.ack_ts]
        resolved = [a for a in self._alerts.values() if a.resolve_ts]
        mtta = sum(a.ack_ts - a.ts for a in acked) / len(acked) if acked else -1.0
        mttr = sum(a.resolve_ts - a.ts for a in resolved) / len(resolved) if resolved else -1.0
        return {
            'total': len(self._alerts),
            'firing': len(self.firing()),
            'suppressed': self.suppressed_total,
            'mtta_s': round(mtta, 1),
            'mttr_s': round(mttr, 1),
        }

    # ---- 内部 ----

    def _store(self, candidate: Alert, now: float, *, force_record: bool = False) -> tuple[Alert, str]:
        """冷却 + 合并 + 上限，返回 (入库后的告警, 动作)。

        动作语义：
            raised  新触发（首次或已恢复后重现）
            cooled  冷却期内重复触发（只刷新 last_ts，不计数不通知）
            merged  冷却期满且既有条目仍在 firing 未确认（count+1）
        """
        key = candidate.key
        last = self._last_raise.get(key, 0.0)
        in_cooldown = key in self._last_raise and (now - last) < self.COOLDOWN_S
        existing = self._alerts.get(key)
        if in_cooldown and not force_record:
            if existing is not None and existing.firing:
                refreshed = Alert(**{**existing.__dict__, 'last_ts': now})
                self._alerts[key] = refreshed
                return refreshed, 'cooled'
            return candidate, 'cooled'
        self._last_raise[key] = now
        if existing is not None and existing.firing and not force_record:
            merged = Alert(**{
                **existing.__dict__,
                'count': existing.count + 1,
                'last_ts': now,
                'desc': candidate.desc or existing.desc,
            })
            self._alerts[key] = merged
            self._enforce_cap()
            return merged, 'merged'
        self._alerts[key] = Alert(**{**candidate.__dict__, 'last_ts': now})
        self._enforce_cap()
        return self._alerts[key], 'raised'

    def _enforce_cap(self) -> None:
        """上限 100：先淘汰最早恢复的，再淘汰最早的 firing。"""
        while len(self._alerts) > self.MAX_ALERTS:
            resolved = [k for k, a in self._alerts.items() if a.resolve_ts]
            if resolved:
                oldest = min(resolved, key=lambda k: self._alerts[k].resolve_ts)
            else:
                oldest = min(self._alerts, key=lambda k: self._alerts[k].ts)
            del self._alerts[oldest]
            self._last_raise.pop(oldest, None)
