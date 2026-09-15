"""Port 层结果类型 —— 显式结果对象，杜绝 bool + 静默失败。

═══════════════════════════════════════════════════════════════════
为什么这些类型必须放在 domain 层，而不是 adapters 层
═══════════════════════════════════════════════════════════════════

依赖倒置要求：L2 Domain 定义契约（含契约里出现的类型），L1 Adapter 实现它。
如果 `KillResult` 定义在 adapters 层、Protocol 又返回它，就会形成

    domain/ports.py  →  import adapters   （违规：L2 依赖 L1）

依赖方向立刻颠倒，门禁也拦不住（因为「返回类型」这种依赖不体现在函数体里）。

所以：**凡是出现在 Port 签名里的类型，定义权一律在 domain 层。**
adapters 从 domain 导入使用（adapters → domain 是允许的方向）。

═══════════════════════════════════════════════════════════════════
设计原则：显式结果对象（解决 v8 方案 D5「静默失败」）
═══════════════════════════════════════════════════════════════════

旧实现用 `bool` 表达成败：

    if self._kill_pid(pid):        # False 是什么意思？
        ...                         # 是「没找到」还是「拒绝访问」还是「已死」？

调用点无法区分，只能靠日志猜；日志又被吞掉（`except Exception: pass`），
最终表现为「点了没反应」。D5 的根因就在这里。

新契约统一返回带 `ok / reason / detail` 的结果对象，且**失败必须有 reason**
（`__post_init__` 强校验）—— 从类型层面杜绝空洞的失败。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# ═══════════════════════════════════════════════════════════════════
# 通用操作结果
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class OpResult:
    """通用操作结果 —— 替代裸 `bool` 返回值。

    全项目所有「做事」的操作（启停服务、安装卸载、写配置）统一用这个。
    """

    ok: bool
    reason: str | None = None
    detail: str = ''
    duration_ms: int = 0

    def __post_init__(self) -> None:
        # 失败必须带真实原因 —— 禁止空洞的失败（v5.33「停不掉但不说为什么」的教训）
        if not self.ok and not self.reason:
            raise ValueError('OpResult 失败时必须提供 reason（禁止空洞的失败）')

    @staticmethod
    def success(detail: str = '', duration_ms: int = 0) -> OpResult:
        return OpResult(True, None, detail, duration_ms)

    @staticmethod
    def failure(reason: str, detail: str = '', duration_ms: int = 0) -> OpResult:
        return OpResult(False, reason, detail, duration_ms)


@dataclass(frozen=True)
class KillResult:
    """一次进程终止尝试的结果。

    对应旧 `_kill_pid()` 返回的 bool。`targeted` 是**尝试终止**的 PID 数
    （不代表已死）；进程是否真的退出必须由调用方**重新查询**确认 ——
    这是 `kill_port_sync` 的 3 轮重试语义成立的前提。
    """

    targeted: int = 0
    rounds: int = 1
    backend: str = 'taskkill'
    error: str | None = None

    @property
    def did_attempt(self) -> bool:
        return self.targeted > 0

    @property
    def ok(self) -> bool:
        """是否「没有出错」—— 注意这**不等于**进程已死。"""
        return self.error is None


# ═══════════════════════════════════════════════════════════════════
# 健康探针
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class HealthSample:
    """一次健康探针的观测结果。

    ★ 保真要点：`ok` **不检查 HTTP 状态码** —— 5xx / 404 仍算 ok。
      这是旧 `_probe_http()` 的真实语义（只看「有没有拿到响应」），
      状态码由 `status_code` 单独承载，供上层另作判断。

      迁移时若「顺手优化」成 `ok = 200 <= code < 300`，
      会让 nginx 的 404 探针页面在服务已就绪时持续报不健康 —— 行为漂移。
    """

    ok: bool
    latency_ms: float = 0.0
    status_code: int | None = None
    detail: str = ''

    def __post_init__(self) -> None:
        if not self.ok and not self.detail:
            raise ValueError('HealthSample 失败时必须提供 detail')


# ═══════════════════════════════════════════════════════════════════
# 指标采样
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class MetricsSample:
    """一次系统指标采样。

    对标 v8 方案 §2.4「黄金四指标」中本机可采的部分。
    `None`（整个对象缺失）表示**采集器不可用**，与「采到了 0」严格区分 ——
    这个区分沿用 `ResidualScan.skipped_reason` 的同一原则。
    """

    ts: float
    cpu_percent: float = 0.0
    mem_percent: float = 0.0
    mem_rss_mb: float = 0.0
    procs: int = 0
    detail: str = ''


# ═══════════════════════════════════════════════════════════════════
# 审计
# ═══════════════════════════════════════════════════════════════════


class AuditOutcome(Enum):
    """审计条目结果。"""

    OK = 'ok'
    FAILED = 'failed'
    DENIED = 'denied'
    """权限不足被拒 —— 必须留痕（v8 方案 §2.5 堡垒机 4A 要求）。"""


@dataclass(frozen=True)
class AuditEntry:
    """一条审计记录。

    对标 v8 方案 §2.5「4A：认证 / 授权 / 账号 / 审计」与 §2.4 告警工程。
    `prev_hash` 构成 append-only 的 sha256 链（`audit.hash_chain = true` 时）。
    """

    ts: float
    actor: str
    action: str
    target: str = ''
    outcome: AuditOutcome = AuditOutcome.OK
    reason: str = ''
    trace_id: str = ''
    detail: str = ''
    prev_hash: str = ''
    entry_hash: str = ''

    def __post_init__(self) -> None:
        if not self.action:
            raise ValueError('审计条目必须有 action')
        if self.outcome is AuditOutcome.DENIED and not self.reason:
            raise ValueError('被拒的审计条目必须记录 reason（谁在什么权限下被拦）')


@dataclass(frozen=True)
class AuditFilter:
    """审计查询条件。字段为 None 表示不限制。"""

    since: float | None = None
    until: float | None = None
    actor: str | None = None
    action: str | None = None
    outcome: AuditOutcome | None = None
    limit: int | None = None


@dataclass(frozen=True)
class ChainVerifyResult:
    """hash 链完整性校验结果。

    对标 v8 方案 §2.5「审计不可篡改」。`broken_at` 给出第一个断链的序号，
    便于人工定位 —— 只说「链断了」而不说断在哪，运维无法处置。
    """

    ok: bool
    total: int = 0
    broken_at: int | None = None
    reason: str = ''

    def __post_init__(self) -> None:
        if not self.ok and not self.reason:
            raise ValueError('链校验失败必须说明 reason')


# ═══════════════════════════════════════════════════════════════════
# 服务控制命令
# ═══════════════════════════════════════════════════════════════════


class ServiceCmd(Enum):
    """对服务可施加的控制命令。"""

    START = 'start'
    STOP = 'stop'
    RESTART = 'restart'
    INSTALL = 'install'
    UNINSTALL = 'uninstall'

    @property
    def label(self) -> str:
        return {'start': '启动', 'stop': '停止', 'restart': '重启',
                'install': '安装', 'uninstall': '卸载'}[self.value]


class Severity(Enum):
    """告警/通知级别（对齐 Google SRE 分级）。"""

    P0 = 'P0'
    P1 = 'P1'
    P2 = 'P2'
    P3 = 'P3'
    INFO = 'info'

    @property
    def is_page(self) -> bool:
        """是否该「叫人起床」—— P0/P1 需要立即人工介入。"""
        return self in (Severity.P0, Severity.P1)


class UndoToken:
    """可撤销操作的令牌。

    保留为类占位：v8 方案的 `ToastRequested.undo` 字段需要它，
    但撤销机制本身（快照 + 反向操作）属于 P4 交互层，本阶段不实现。

    不做成 dataclass 是有意的 —— 让人无法误以为「构造出来就能撤销」。
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return 'UndoToken(未实现，见 v8 方案 §5.3)'


__all__ = [
    'OpResult',
    'KillResult',
    'HealthSample',
    'MetricsSample',
    'AuditOutcome',
    'AuditEntry',
    'AuditFilter',
    'ChainVerifyResult',
    'ServiceCmd',
    'Severity',
    'UndoToken',
]
