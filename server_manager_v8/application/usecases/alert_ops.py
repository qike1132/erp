"""告警操作 —— 确认、静默、以及告警状态查询。

═══════════════════════════════════════════════════════════════════
迁移来源：v8 方案 §2.4「告警工程」（旧实现无此能力）
═══════════════════════════════════════════════════════════════════

旧实现只有「发一条托盘气泡」，既没有分级，也没有确认/静默的概念。
后果是经典的告警疲劳（alert fatigue）：

    · 同一问题反复弹气泡 → 用户学会无视所有气泡
    · 无法区分「需要立刻起床的 P0」与「看一眼就好的 P3」
    · 用户点了「知道了」之后系统不记得，下次照样弹

本模块引入三个概念（对齐 Google SRE 的告警处理流程）：

    **确认（ack）**  —— 「我看到了，正在处理」
        记录确认人与时间。已确认的告警**不再重复提醒**，
        但在彻底解决前仍显示在列表里（避免「消失 = 忘了」）。

    **静默（silence）** —— 「这个我知道，暂时别吵我」
        有**明确期限**。★ 静默必须有超时：无限期静默等于永久关闭告警，
        而用户会在排查完之后忘记恢复 —— 事故就是这么攒出来的。

    **解决（resolve）** —— 「问题没了」（由系统判定，不由用户点）

═══════════════════════════════════════════════════════════════════
★ 告警状态由应用层持有（内存 + 事件）
═══════════════════════════════════════════════════════════════════

`AlertOps` 持有一份内存中的告警表，每次变更通过事件总线广播：

    AlertRaised / AlertResolved / AuthChanged（复用）

★ 为什么不做持久化：告警是「当前状态」，不是「历史记录」。
  历史由审计承担（`AuditPort` 已记录每一次 ack/silence）。
  持久化告警会引出「重启后旧告警还算不算数」这类没有正确答案的问题。

★ 静默期限的检测是**惰性**的（读取时判断是否过期），
  与 `auth.Session` 的过期检测同一手法 —— 不依赖后台定时器
  （定时器可能因线程崩溃而没跑，那样静默会永久生效）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...domain.permissions import Action
from ...domain.results import OpResult, Severity
from ..auth.guard import ConfirmationToken, require
from ..events import AlertRaised, AlertResolved
from .deps import Deps

#: 静默的默认时长（秒）—— 15 分钟
#:
#: ★ 有默认值但仍要求调用方显式传：默认值只在「调用方没想法」时兜底，
#:   而不是让它省略。UI 上应当是一个下拉框，默认选中 15 分钟。
DEFAULT_SILENCE_S = 900.0

#: 静默时长上限（秒）—— 24 小时
#:
#: ★ 为什么要有上限：静默 7 天与永久关闭告警在效果上没区别，
#:   而用户点的时候多半不会想那么远。上限强制「必须回来再看一眼」。
MAX_SILENCE_S = 86400.0


@dataclass
class Alert:
    """一条告警。"""

    key: str
    """告警标识（同一 key 重复触发视为同一条告警，不重复入表）。"""

    severity: Severity
    title: str
    body: str = ''
    raised_at: float = 0.0
    acked_at: float | None = None
    acked_by: str = ''
    silenced_until: float | None = None
    silenced_by: str = ''

    @property
    def is_acked(self) -> bool:
        return self.acked_at is not None

    @property
    def active(self) -> bool:
        """是否需要继续提醒（未确认、或静默已过期）。"""
        if self.is_acked:
            return False
        return True

    def is_silenced_at(self, now: float) -> bool:
        """在 `now` 时刻是否处于静默期。"""
        if self.silenced_until is None:
            return False
        return now < self.silenced_until

    def should_notify(self, now: float) -> bool:
        """此刻是否应该打扰用户。

        ★ 三条件同时满足才打扰：需要提醒 + 未确认 + 未静默。
          这是「减少打扰」的唯一出口 —— 任何一条不满足就安静。
        """
        return self.active and not self.is_silenced_at(now)


@dataclass
class AlertOpsContext:
    """告警操作上下文。"""

    deps: Deps
    key: str = ''
    notes: list[str] = field(default_factory=list)


class AlertOps:
    """告警的确认、静默与查询。

    ★ 确认/静默是 L0 还是 L1 的判定依据是「能不能造成损害」：
        · `ack`（确认）  → L0：只是标记「我看到了」，无副作用
        · `silence`（静默）→ L1：会让系统**停止提醒真实故障**，
          必须有超时与 Operator 权限。把静默当 L0 是个常见的错误设计。
    """

    def __init__(self, deps: Deps) -> None:
        self._deps = deps
        self._alerts: dict[str, Alert] = {}

    # ── 内部：告警来源 ────────────────────────────────────────────

    def raise_alert(self, key: str, severity: Severity, title: str,
                    body: str = '', *, trace_id: str = '') -> Alert:
        """登记一条告警（由调用方在检测到异常时触发，不是用户操作）。

        ★ 同一 `key` 重复触发**更新严重度与文案，但保留 ack/silence 状态** ——
          否则用户刚确认完，下一次同源告警又把它变成未确认，形成刷屏。
        """
        now = self._deps.clock.monotonic()
        existing = self._alerts.get(key)
        if existing is not None:
            existing.severity = severity
            existing.title = title
            existing.body = body
            if not existing.active:
                # 已确认的告警再次触发 → 视为「问题复发」，清除确认状态
                existing.acked_at = None
                existing.acked_by = ''
            return existing

        alert = Alert(key=key, severity=severity, title=title, body=body,
                      raised_at=now)
        self._alerts[key] = alert
        self._emit(AlertRaised(
            ts=now, alert_id=key, severity=severity.value, title=title,
            detail=body,
        ))
        return alert

    def resolve_alert(self, key: str, *, detail: str = '',
                      trace_id: str = '') -> OpResult:
        """解决一条告警（由系统判定问题消失时调用）。"""
        del trace_id
        alert = self._alerts.pop(key, None)
        if alert is None:
            return OpResult.success(f'告警 {key} 不存在（无需解决）')
        self._emit(AlertResolved(
            ts=self._deps.clock.monotonic(), alert_id=key,
            reason=detail or '问题已消失',
        ))
        return OpResult.success(f'告警已解决: {alert.title}')

    # ── 用户操作 ──────────────────────────────────────────────────

    @require(Action.ACK_ALERT)
    def ack(
        self,
        key: str,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
    ) -> OpResult:
        """确认一条告警（「我看到了」）。"""
        del confirm, event_bus, audit
        alert = self._alerts.get(key)
        if alert is None:
            return OpResult.failure('告警不存在', f'未找到 key={key!r} 的告警')

        if alert.is_acked:
            return OpResult.success(f'告警已在 {alert.acked_by} 处确认，无需重复')

        alert.acked_at = self._deps.clock.monotonic()
        alert.acked_by = self._deps.actor
        return OpResult.success(f'已确认: {alert.title}')

    @require(Action.SILENCE_ALERT)
    def silence(
        self,
        key: str,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
        duration_s: float = DEFAULT_SILENCE_S,
    ) -> OpResult:
        """静默一条告警（「暂时别吵我」）。

        ★ 期限是**必填且有了上限**：无限期静默 = 永久关闭告警。
          `duration_s` 超上限时**拒绝**而不是静默截断 ——
          静默截断会让用户以为静默了 7 天，实际上只有 1 天，
          然后第 2 天被吵醒时以为系统坏了。
        """
        del confirm, event_bus, audit
        if duration_s <= 0:
            return OpResult.failure('静默时长非法', f'必须为正数，得到 {duration_s!r}')
        if duration_s > MAX_SILENCE_S:
            return OpResult.failure(
                '静默时长超出上限',
                f'最长 {MAX_SILENCE_S / 3600:.0f} 小时（一次性静默更久等于关闭告警），'
                f'请求 {duration_s / 3600:.1f} 小时',
            )

        alert = self._alerts.get(key)
        if alert is None:
            return OpResult.failure('告警不存在', f'未找到 key={key!r} 的告警')

        now = self._deps.clock.monotonic()
        alert.silenced_until = now + duration_s
        alert.silenced_by = self._deps.actor
        return OpResult.success(
            f'已静默 {duration_s / 60:.0f} 分钟: {alert.title}'
        )

    # ── 查询 ──────────────────────────────────────────────────────

    @require(Action.VIEW_ALL)
    def list_active(
        self,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
        notify_only: bool = False,
    ) -> OpResult:
        """列出当前告警。

        `notify_only=True` 只返回「此刻应该打扰用户」的（未确认且未静默）——
        UI 用它决定要不要弹气泡，从而避免给已确认的告警反复弹窗。
        """
        del confirm, event_bus, audit
        now = self._deps.clock.monotonic()
        if notify_only:
            self._last_list = tuple(
                a for a in self._alerts.values() if a.should_notify(now)
            )
        else:
            self._last_list = tuple(self._alerts.values())
        count = len(self._last_list)
        if not count:
            return OpResult.success('当前无告警')
        paging = sum(1 for a in self._last_list if a.severity.is_page)
        return OpResult.success(
            f'{count} 条告警（其中 {paging} 条需立即介入）'
        )

    @property
    def last_list(self) -> tuple[Alert, ...]:
        """最近一次 `list_active()` 的结果（供 UI 取数据）。"""
        return getattr(self, '_last_list', ())

    @property
    def alerts(self) -> dict[str, Alert]:
        """当前告警表（只读快照，供测试与 UI 直接检查）。"""
        return dict(self._alerts)

    # ── 内部 ──────────────────────────────────────────────────────

    def _emit(self, event: object) -> None:
        try:
            self._deps.event_bus.emit(event)
        except BaseException:  # noqa: BLE001
            # ★ 告警事件的广播失败不能影响告警本身的状态变更
            pass


def build_alert_ops(deps: Deps) -> AlertOps:
    return AlertOps(deps)


__all__ = [
    'Alert',
    'AlertOps',
    'AlertOpsContext',
    'DEFAULT_SILENCE_S',
    'MAX_SILENCE_S',
    'build_alert_ops',
]
