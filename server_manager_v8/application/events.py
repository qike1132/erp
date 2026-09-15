"""应用层事件定义 —— 类型化事件，替代 12 种裸 tuple。

═══════════════════════════════════════════════════════════════════
迁移来源：server_manager.py v5.40 的 `_msg_queue`
═══════════════════════════════════════════════════════════════════

旧实现用 `queue.Queue` 传 `(type: str, data: dict)` 二元组，共 9 种类型、
109 处投递点：

| 旧 type | 次数 | 新事件类 |
|---|---|---|
| `log` | 76 | `LogAppended` |
| `log_batch` | 4 | `LogBatchAppended` |
| `toast` | 7 | `ToastRequested` |
| `state_set` | 7 | `StateChanged` |
| `startup_progress` | 5 | `StartupProgressed` |
| `dual_failed` | 5 | `DevStartupFailed` |
| `hosting_refresh` | 3 | `ServiceListChanged` |
| `hosting_apply` | 1 | `ServiceApplied` |
| `dual_started` | 1 | `DevStarted` |

**这套机制的四个真实痛点**（v8 方案 §3.5 要求替代它的理由）：

1. **消费端靠字符串匹配 + `.get()` 取值**
   ```
   msg_type, data = q.get_nowait()
   if msg_type == 'log':
       text = data.get('text', '')      # ← 拼错 key 不报错，静默拿到默认值
   ```
   投递端改一个 key 名，消费端不会报错，只是那个字段永远为空。

2. **无类型约束**：`data` 是裸 dict，IDE 无法补全，重命名无法追踪。

3. **`.get()` 的默认值掩盖契约违反**：`data.get('text', '')` 让「忘记传 text」
   看起来像「text 是空字符串」。

4. **无法表达事件之间的结构**：`startup_progress` 与 `dual_failed` 都带
   `trace_id`，但类型系统看不出它们属于同一次启动流程。

新设计用 frozen dataclass：字段名由类型固定，漏字段在**构造时**就报错，
消费端拿到的是强类型对象。

═══════════════════════════════════════════════════════════════════
设计要点
═══════════════════════════════════════════════════════════════════

**全部 `frozen=True`** —— 事件是不可变的事实陈述，发布后不应被修改。
若某个 handler 改了事件内容，后续 handler 看到的就是被篡改的历史。

**`ts` 字段统一放第一位且必填** —— 由发布方注入时钟提供，不用领域层的
`time.time()`（事件属于应用层，可以碰时间，但注入便于测试确定性）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..domain.models import RunMode
from ..domain.results import HealthSample, MetricsSample, Severity, UndoToken
from ..domain.service_state import ServiceStatus


# ═══════════════════════════════════════════════════════════════════
# 基础
# ═══════════════════════════════════════════════════════════════════


class Event:
    """所有事件的基类（仅用于类型标注与通配订阅，不含字段）。

    用普通 class 而非 Protocol：事件要能被 `isinstance` 检查，
    而 Protocol 的 isinstance 对 `Event` 这种「无方法」的基类没有意义。
    """

    __slots__ = ()

    #: 事件类型名（用于日志与调试，避免 `type(e).__name__` 到处写）
    @property
    def kind(self) -> str:
        return type(self).__name__


class LogLevel(Enum):
    """日志级别（对齐旧实现用到的级别字符串）。"""

    DEBUG = 'DEBUG'
    INFO = 'INFO'
    WARNING = 'WARNING'
    ERROR = 'ERROR'

    @property
    def is_problem(self) -> bool:
        return self in (LogLevel.WARNING, LogLevel.ERROR)


# ═══════════════════════════════════════════════════════════════════
# 日志
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class LogAppended(Event):
    """一行日志（替代 `('log', {...})`，76 处投递点）。

    `text` 是唯一必填字段 —— 旧实现里 `data.get('text', '')` 的默认值
    掩盖了「忘记传文本」这类错误，新版本在构造时就拒绝空文本。
    """

    ts: float
    text: str
    level: LogLevel = LogLevel.INFO
    source: str = ''

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError('LogAppended.text 不能为空')


@dataclass(frozen=True)
class LogBatchAppended(Event):
    """一批日志（替代 `('log_batch', {...})`，4 处投递点）。

    批量投递是为了避免高频日志把队列打爆（旧实现主线程每轮最多处理 30 条）。
    """

    ts: float
    lines: tuple[str, ...] = ()
    level: LogLevel = LogLevel.INFO


# ═══════════════════════════════════════════════════════════════════
# 指标与状态
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class MetricsUpdated(Event):
    """一次指标采样。

    ★ `sample` 允许为 None —— 表示**采集器不可用**，与「采到全 0」严格区分
      （见 `adapters/metrics_psutil` docstring）。消费端必须分支处理。
    """

    ts: float
    sample: MetricsSample | None = None


@dataclass(frozen=True)
class StateChanged(Event):
    """运行模式变化（替代 `('state_set', {...})`，7 处投递点）。"""

    ts: float
    old: RunMode
    new: RunMode
    trace_id: str = ''


@dataclass(frozen=True)
class ServiceListChanged(Event):
    """服务列表需要刷新（替代 `('hosting_refresh', {...})`，3 处投递点）。

    旧实现是「通知 UI 自己去重新查询 sc」—— 新设计改为**事件带数据**，
    避免 UI 层反向依赖服务查询能力。
    """

    ts: float
    snapshots: tuple[tuple[str, ServiceStatus], ...] = ()


@dataclass(frozen=True)
class ServiceApplied(Event):
    """服务配置已应用（替代 `('hosting_apply', {...})`）。"""

    ts: float
    service: str
    ok: bool = True
    detail: str = ''


# ═══════════════════════════════════════════════════════════════════
# 启动流程
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class StartupProgressed(Event):
    """启动流程进度（替代 `('startup_progress', {...})`，5 处投递点）。"""

    ts: float
    trace_id: str
    step: str
    index: int = 0
    total: int = 0
    detail: str = ''

    @property
    def percent(self) -> int:
        """进度百分比。total 为 0 时返回 0（而不是除零崩溃）。"""
        if self.total <= 0:
            return 0
        return min(100, max(0, int(self.index * 100 / self.total)))


@dataclass(frozen=True)
class DevStarted(Event):
    """开发模式已启动（替代 `('dual_started', {...})`）。"""

    ts: float
    trace_id: str
    pids: tuple[int, ...] = ()


@dataclass(frozen=True)
class DevStartupFailed(Event):
    """开发模式启动失败（替代 `('dual_failed', {...})`，5 处投递点）。

    `reason` 必填 —— 旧实现的失败消息有时只带一个 status 字符串，
    用户看不出到底哪一步出了问题。
    """

    ts: float
    reason: str
    trace_id: str = ''
    step: str = ''
    detail: str = ''

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError('DevStartupFailed.reason 不能为空（禁止空洞的失败）')


# ═══════════════════════════════════════════════════════════════════
# 流水线步骤
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class StepStarted(Event):
    """一个流水线步骤开始。"""

    ts: float
    trace_id: str
    pipeline: str
    step: str
    index: int = 0
    total: int = 0


@dataclass(frozen=True)
class StepFinished(Event):
    """一个流水线步骤结束。

    ★ `ok=False` 时 `detail` 必填 —— 否则一次失败的步骤只会留下一行
      「某步失败」，运维无从下手（D5 静默失败的同类问题）。
    """

    ts: float
    trace_id: str
    step: str
    ok: bool
    duration_ms: int = 0
    detail: str = ''

    def __post_init__(self) -> None:
        if not self.ok and not self.detail:
            raise ValueError('StepFinished 失败时必须提供 detail')


@dataclass(frozen=True)
class PipelineAborted(Event):
    """流水线中止（某个步骤失败且策略要求中止）。"""

    ts: float
    trace_id: str
    pipeline: str
    failed_step: str
    reason: str
    completed: int = 0
    total: int = 0

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError('PipelineAborted.reason 不能为空')


# ═══════════════════════════════════════════════════════════════════
# 告警 / 通知 / 权限
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class AlertRaised(Event):
    """告警触发。"""

    ts: float
    alert_id: str
    severity: Severity
    title: str
    detail: str = ''
    service: str = ''
    runbook: str = ''
    suggested_action: str = ''

    def __post_init__(self) -> None:
        if not self.alert_id:
            raise ValueError('AlertRaised.alert_id 不能为空')


@dataclass(frozen=True)
class AlertResolved(Event):
    """告警恢复。"""

    ts: float
    alert_id: str
    reason: str = ''


@dataclass(frozen=True)
class ToastRequested(Event):
    """请求弹一条提示（替代 `('toast', {...})`，7 处投递点）。"""

    ts: float
    text: str
    level: Severity = Severity.INFO
    undo: UndoToken | None = None

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError('ToastRequested.text 不能为空')


@dataclass(frozen=True)
class AuthChanged(Event):
    """权限会话变化（登录 / 提权 / 超时 / 登出）。"""

    ts: float
    role: str
    expires_at: float | None = None
    detail: str = ''


@dataclass(frozen=True)
class OperationDenied(Event):
    """操作因权限不足被拒。

    ★ 这个事件**必须存在**，且被拒时必须发 —— 堡垒机 4A 要求
      「谁在什么权限下被拦下」必须留痕。旧实现直接 `messagebox` 一句
      「权限不足」就完了，事后无法审计「有多少次越权尝试」。
    """

    ts: float
    action: str
    required: str
    actor_role: str
    detail: str = ''


@dataclass(frozen=True)
class OperationFailed(Event):
    """通用操作失败（替代静默 `except: pass`）。

    对齐 v8 方案 §3.3 第 3 条「禁止静默」：
        `except Exception: pass`
        → `except SpecificError as e: audit.record_failure(...); bus.emit(OperationFailed(...))`
    """

    ts: float
    action: str
    reason: str
    detail: str = ''
    trace_id: str = ''

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError('OperationFailed.reason 不能为空（禁止空洞的失败）')


@dataclass(frozen=True)
class PortReleased(Event):
    """端口释放流程结束。"""

    ts: float
    port: int
    ok: bool
    rounds: int = 0
    remaining_pids: tuple[int, ...] = ()
    detail: str = ''


__all__ = [
    'AlertRaised',
    'AlertResolved',
    'AuthChanged',
    'DevStarted',
    'DevStartupFailed',
    'Event',
    'LogAppended',
    'LogBatchAppended',
    'LogLevel',
    'MetricsUpdated',
    'OperationDenied',
    'OperationFailed',
    'PipelineAborted',
    'PortReleased',
    'ServiceApplied',
    'ServiceListChanged',
    'StartupProgressed',
    'StateChanged',
    'StepFinished',
    'StepStarted',
    'ToastRequested',
]
