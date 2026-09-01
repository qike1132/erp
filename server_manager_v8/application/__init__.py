"""L3 应用层 — 用例编排、事务边界、权限校验、事件发布、审计写入。

依赖 Domain 模型与 Adapter 的 Protocol 实现，不直接触碰平台 I/O。

**分层约定（门禁 R1 强制）**：L4 表现层不得直接 import domain，
所需的 Domain 类型统一经本层 re-export（如下方 Action/OpResult/Alert 等）。
"""
from __future__ import annotations

# ---- 供 L4 使用的 Domain 类型 re-export（门禁 R1：L4 只允许 import application） ----
from server_manager_v8.domain import (
    Action,
    Alert,
    AuditEntry,
    DangerLevel,
    HealthSample,
    HealthTarget,
    MetricsSample,
    OpResult,
    Role,
    RunMode,
    ServiceState,
    Session,
    Severity,
    Silence,
    SpawnSpec,
)

from . import auth, events, pipeline, runtime, usecases
from .auth.guard import AuthGuard, PermissionDeniedError, danger_of
from .event_bus import EventBus
from .events import (
    AlertRaised,
    AlertResolved,
    AuditRecorded,
    AuthChanged,
    Event,
    HealthChanged,
    LogAppended,
    MetricsUpdated,
    ModeChanged,
    PipelineFinished,
    PipelineStarted,
    StepUpdated,
    ToastRequested,
)
from .pipeline import Pipeline, PipelineAbortedError, Step, StepResult, op_step
from .runtime import RuntimeState

__all__ = [
    'Action',
    'Alert',
    'AlertRaised',
    'AlertResolved',
    'AuditEntry',
    'AuditRecorded',
    'AuthChanged',
    'AuthGuard',
    'DangerLevel',
    'Event',
    'EventBus',
    'HealthChanged',
    'HealthSample',
    'HealthTarget',
    'LogAppended',
    'MetricsSample',
    'MetricsUpdated',
    'ModeChanged',
    'OpResult',
    'PermissionDeniedError',
    'Pipeline',
    'PipelineAbortedError',
    'PipelineFinished',
    'PipelineStarted',
    'Role',
    'RunMode',
    'RuntimeState',
    'ServiceState',
    'Session',
    'Severity',
    'Silence',
    'SpawnSpec',
    'Step',
    'StepResult',
    'StepUpdated',
    'ToastRequested',
    'auth',
    'danger_of',
    'events',
    'op_step',
    'pipeline',
    'runtime',
    'usecases',
]
