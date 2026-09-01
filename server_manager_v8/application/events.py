"""类型化事件 — 替代 v6 的 12 种裸 tuple（('log', {...}) / ('metric', {...})）。

全部为 frozen dataclass。事件沿 event_bus 分发：Application 层发布，
Presentation 层（bridge/UI）订阅渲染。trace_id 串联「一次操作 → N 个子步骤 →
M 条日志 → K 条告警」（字节 Argos 统一可观测的轻量版）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Event:
    """事件基类（仅类型标记）。"""

    trace_id: str = ''


# ===================== 日志 =====================


@dataclass(frozen=True)
class LogAppended(Event):
    level: str = 'INFO'  # DEBUG / INFO / WARNING / ERROR
    source: str = 'manager'  # api / web / redis / manager / cli
    text: str = ''
    ts: float = 0.0


# ===================== 指标与健康 =====================


@dataclass(frozen=True)
class MetricsUpdated(Event):
    """采样更新（cpu/mem/disk/net/procs 见 domain.MetricsSample 序列化）。"""

    sample: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HealthChanged(Event):
    """服务健康状态变化（down 开始/恢复）。"""

    service: str = ''
    ok: bool = True
    consecutive_fail: int = 0
    latency_ms: int = 0


# ===================== 运行模式 =====================


@dataclass(frozen=True)
class ModeChanged(Event):
    """运行模式变更（IDLE/DEV/PROD/SWITCHING）。"""

    old: str = ''
    new: str = ''


@dataclass(frozen=True)
class PipelineStarted(Event):
    """一次 Pipeline 编排开始。"""

    name: str = ''
    steps: int = 0


@dataclass(frozen=True)
class StepUpdated(Event):
    """Pipeline 某步状态更新（驱动 Stepper 渲染）。"""

    pipeline: str = ''
    step: str = ''
    index: int = 0
    total: int = 0
    state: str = 'pending'  # pending / running / done / failed / skipped
    detail: str = ''


@dataclass(frozen=True)
class PipelineFinished(Event):
    """Pipeline 编排结束（成功或失败）。"""

    name: str = ''
    ok: bool = True
    reason: str = ''
    duration_ms: int = 0


# ===================== 告警 =====================


@dataclass(frozen=True)
class AlertRaised(Event):
    key: str = ''
    severity: str = ''
    title: str = ''
    desc: str = ''


@dataclass(frozen=True)
class AlertResolved(Event):
    key: str = ''
    reason: str = ''


# ===================== 权限与审计 =====================


@dataclass(frozen=True)
class AuthChanged(Event):
    """角色/提权状态变化（驱动顶栏 TTL 倒计时）。"""

    role: str = ''
    elevated: str = ''
    expires_at: float = 0.0


@dataclass(frozen=True)
class AuditRecorded(Event):
    entry: dict[str, Any] = field(default_factory=dict)


# ===================== UI 提示 =====================


@dataclass(frozen=True)
class ToastRequested(Event):
    """轻确认（L1 撤销窗口）/ 结果提示。"""

    level: str = 'info'  # info / success / warn / error
    text: str = ''
    undo_token: str = ''
    undo_ttl_s: float = 5.0
