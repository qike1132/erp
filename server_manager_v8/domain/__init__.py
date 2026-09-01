"""L2 领域层 — 纯业务逻辑，零 I/O，100% 可单测。

硬约束（由 server_manager_v8._guard 守护，CI / pytest / CLI 三处强制）：
    - R1 禁止 import adapters / application / presentation
    - R2 禁止 import subprocess / psutil / tkinter / socket / urllib / requests
      禁止 open() / os.system / eval / exec
    - R3 禁止空 except-pass 与 contextlib.suppress
    - R4 文件 ≤800 行 / 函数 ≤80 行 / 类方法 ≤20 个
    所有对外 I/O 一律经 ports.py 中定义的 Protocol 抽象。
"""
from __future__ import annotations

from . import alert_rules, health, mode_machine, models, permissions, ports
from .alert_rules import AlertCenter, AlertDecision, AlertRule, Inhibition, RuleEvaluator, Silence, SilenceBook
from .health import (
    BudgetVerdict,
    FailureTracker,
    MetricGrade,
    ProbePolicy,
    budget_severity,
    fast_burn,
    golden_four,
    grade_metric,
    overall_grade,
    slow_burn,
)
from .mode_machine import ModeAction, ModeMachine, ModeTransitionError, Startup, SwitchPlan, Teardown
from .models import (
    GENESIS_HASH,
    Alert,
    AuditEntry,
    DangerLevel,
    HealthSample,
    HealthTarget,
    KillResult,
    MetricsSample,
    OpResult,
    ProcessHandle,
    Role,
    RunMode,
    ServiceKind,
    ServiceSpec,
    ServiceState,
    Severity,
    SpawnError,
    SpawnSpec,
    canonical_json,
    compute_entry_hash,
)
from .permissions import CONTROL_BY_DANGER, DANGER, Action, Authorization, AuthPolicy, Session
from .ports import AuditPort, ClockPort, HealthPort, MetricsPort, NotifyPort, ProcessPort, ServicePort, StoragePort

__all__ = [
    'CONTROL_BY_DANGER',
    'DANGER',
    'DEFAULT_PROBES',
    'GENESIS_HASH',
    'Action',
    'Alert',
    'AlertCenter',
    'AlertDecision',
    'AlertRule',
    'AuditEntry',
    'AuditPort',
    'AuthPolicy',
    'Authorization',
    'BudgetVerdict',
    'ClockPort',
    'DangerLevel',
    'FailureTracker',
    'HealthPort',
    'HealthSample',
    'HealthTarget',
    'Inhibition',
    'KillResult',
    'MetricGrade',
    'MetricsPort',
    'MetricsSample',
    'ModeAction',
    'ModeMachine',
    'ModeTransitionError',
    'NotifyPort',
    'OpResult',
    'ProbePolicy',
    'ProcessHandle',
    'ProcessPort',
    'Role',
    'RuleEvaluator',
    'RunMode',
    'ServiceKind',
    'ServicePort',
    'ServiceSpec',
    'ServiceState',
    'Session',
    'Severity',
    'Silence',
    'SilenceBook',
    'SpawnError',
    'SpawnSpec',
    'Startup',
    'StoragePort',
    'SwitchPlan',
    'Teardown',
    'alert_rules',
    'budget_severity',
    'canonical_json',
    'compute_entry_hash',
    'fast_burn',
    'golden_four',
    'grade_metric',
    'health',
    'mode_machine',
    'models',
    'overall_grade',
    'permissions',
    'ports',
    'slow_burn',
]

# health.DEFAULT_PROBES 经 from .health import ... 引入后再挂到命名空间
DEFAULT_PROBES = health.DEFAULT_PROBES
