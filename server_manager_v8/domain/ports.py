"""Domain Ports —— 依赖倒置的契约层。仅 Protocol，无任何实现。

═══════════════════════════════════════════════════════════════════
这层存在的意义
═══════════════════════════════════════════════════════════════════

没有它的时候，Application 层要做事只能 `import adapters` —— 于是

    L3 Application  →  L1 Adapter        （具体依赖具体）

一旦这样，L3 就无法在没有 Windows / 没有真实服务的环境（CI）里测试，
而且换一种实现（比如把 sc 换成 WMI、把 http 换成 socket）要动 L3。

有了 Ports 之后：

    L3 Application  →  L2 Domain(Protocol)  ←  L1 Adapter

L3 只认 Protocol，测试时塞 Fake，生产时塞真 adapter。这就是依赖倒置。

═══════════════════════════════════════════════════════════════════
本模块的硬约束（由 scripts/check_domain_purity.py 强制）
═══════════════════════════════════════════════════════════════════

    · 只能 import 本层（domain.*）与标准库 typing / abc
    · 禁止任何 I/O 导入（subprocess / psutil / socket / os …）
    · 禁止 import adapters / application / presentation
    · **不写任何实现**：方法体只能是 `...`

本模块出现的所有类型（OpResult / KillResult / HealthSample …）都定义在
`domain/results.py`，而不是 adapters 层 —— 否则 Protocol 的返回类型会把
依赖方向重新拉回 L2→L1，而门禁对「返回类型」这种隐性依赖无能为力。

═══════════════════════════════════════════════════════════════════
与 v8 方案 §3.4 的差异（如实登记）
═══════════════════════════════════════════════════════════════════

方案写的 `ProcessPort.kill_tree(pid) -> KillResult` 与
`find_port_pids(port) -> list[int]`，实际落地为：

    find_port_pids(port, *, listening_only=True) -> list[int]
        ↑ 旧实现有两种口径（仅 LISTENING 用于杀 / 含 ESTABLISHED 用于留痕），
          必须显式暴露，否则「用留痕口径去杀人」这类事故无法在类型层预防。

    kill_tree(pid, *, timeout_s=5.0) -> KillResult
        ↑ 保持方案原样。

另新增方案未列出的 `ClockPort` —— 领域层的时间注入契约需要它显式化
（旧代码直接调 `time.monotonic()`，是全部时序逻辑不可测的根因）。
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar, runtime_checkable

from .models import HealthProbe, ServiceSnapshot, Service
from .results import (
    AuditEntry,
    AuditFilter,
    ChainVerifyResult,
    HealthSample,
    KillResult,
    MetricsSample,
    OpResult,
    ServiceCmd,
    Severity,
)
from .service_state import ServiceStatus

T = TypeVar('T')

# ═══════════════════════════════════════════════════════════════════
# 时间
# ═══════════════════════════════════════════════════════════════════


@runtime_checkable
class ClockPort(Protocol):
    """时间与睡眠。

    ★ 为什么时间也要成 Port：旧代码里 `time.sleep(1)` 直接写在重试循环里，
      导致「3 轮 × 0.5s 重试」这类逻辑只能靠真实等待 1.5 秒来测试，
      而超时边界（第 2 轮成功 / 第 3 轮才成功）几乎无法被覆盖。
      把 clock 与 sleep **打包成同一个对象**注入，还有个额外好处：
      防止只注入 clock 而漏注入 sleep，导致「假时钟 + 真睡眠」的忙等。
    """

    def monotonic(self) -> float:
        """单调时钟（不受系统时间调整影响）—— 所有超时判定必须用它。"""
        ...

    def sleep(self, seconds: float) -> None:
        """睡眠。注入后测试可立即返回，同时断言「睡了几次、每次多久」。"""
        ...


# ═══════════════════════════════════════════════════════════════════
# 进程 / 端口
# ═══════════════════════════════════════════════════════════════════


@runtime_checkable
class ProcessPort(Protocol):
    """进程与端口的查询、终止。

    实现方必须遵守五条安全约定（见 `adapters/process_win.py` docstring）：
    ① 绝无 shell 参与 ② 绝不向上杀祖先链
    ③ psutil 路径与 `taskkill /T` 同语义 ④ 绝不做宽特征兜底
    ⑤ 宁可漏杀不可误杀
    """

    def find_port_pids(self, port: int, *, listening_only: bool = True) -> list[int]:
        """查询占用某端口的 PID。

        `listening_only=True`（默认）用于**决定杀谁**；
        `False` 时含 ESTABLISHED，用于**给用户看的留痕**。

        ★ 这两个口径绝不可混用：用留痕口径去杀人会杀掉所有连进来的客户端。
        """
        ...

    def kill_tree(self, pid: int, *, timeout_s: float = 5.0) -> KillResult:
        """终止进程树（自身 + 全部后代）。

        ★ 绝不包含祖先链 —— 否则会杀掉调用者自己。
        """
        ...

    def resolve_process_name(self, pid: int) -> str:
        """PID → 进程名（留痕用）。查不到返回空串而非抛异常。"""
        ...

    def has_psutil(self) -> bool:
        """psutil 是否可用。

        暴露这个是为了让上层能区分「扫描了没发现」与「根本没扫描」——
        缺 psutil 时残留清理会 skip，上层须如实告知用户，不得静默。
        """
        ...


# ═══════════════════════════════════════════════════════════════════
# 服务
# ═══════════════════════════════════════════════════════════════════


@runtime_checkable
class ServicePort(Protocol):
    """Windows 服务（NSSM 托管 + 原生 SCM）的查询与控制。"""

    def snapshot(self, name: str) -> ServiceSnapshot:
        """一次性取回「状态 + PID + 原始文本」。

        ★ 为什么不是分开的 `state()` + `pid()`：两次 `sc` 查询之间服务状态
          可能已改变，拼起来会得到自相矛盾的假快照。旧实现分两次调用，
          正是这个隐患的来源。
        """
        ...

    def state(self, name: str) -> ServiceStatus:
        """只查状态（用于不需要 PID 的轻量场景）。"""
        ...

    def pid(self, name: str) -> int | None:
        """只查 PID（未运行 / 查询失败返回 None）。"""
        ...

    def control(self, name: str, cmd: ServiceCmd) -> OpResult:
        """施加控制命令（start / stop / restart / install / uninstall）。"""
        ...

    def request_stop(self, name: str) -> OpResult:
        """只**发出**停止请求，不等待完成。

        与 `control(name, STOP)` 的区别：这个是「告诉它停」，
        停下来与否由调用方用 `wait_state` 轮询确认 —— 旧实现把「发请求」
        和「等结果」混在一起，导致超时语义含混。
        """
        ...

    def wait_state(self, name: str, want: ServiceStatus, timeout_s: float,
                   clock: ClockPort) -> bool:
        """轮询等待服务到达目标状态，超时返回 False。"""
        ...

    def set_restart_guard(self, kind: str, *, nssm_path: str | None = None) -> OpResult:
        """设置 / 解除 NSSM AppExit 崩溃重启守卫。

        ★ 只对 NSSM 托管服务（erp-prod / erp-arq）有效，
          对原生 Windows 服务（erp-redis）**完全没有作用**（D6 语义）。
          实现方不得对原生服务调用此方法后假装成功。
        """
        ...

    def detect_installed(self, names: tuple[str, ...] = ()) -> dict[str, bool]:
        """批量探测哪些服务已安装。"""
        ...


# ═══════════════════════════════════════════════════════════════════
# 健康
# ═══════════════════════════════════════════════════════════════════


@runtime_checkable
class HealthPort(Protocol):
    """健康探针执行器。"""

    def probe(self, target: HealthProbe, *, timeout_s: float = 2.0) -> HealthSample:
        """执行一次探针。

        ★ 实现方注意：HTTP 探针**不检查状态码** —— 拿到响应即 ok。
          状态码由 `HealthSample.status_code` 承载。
        """
        ...


# ═══════════════════════════════════════════════════════════════════
# 指标
# ═══════════════════════════════════════════════════════════════════


@runtime_checkable
class MetricsPort(Protocol):
    """系统指标采集。"""

    def sample(self) -> MetricsSample | None:
        """采一次指标；**采集器不可用时返回 None**（不是抛异常、也不是全 0）。

        返回 None 与返回「cpu=0 的样本」是两件完全不同的事 ——
        前者是「我不知道」，后者是「我观测到 0」。前端展示与告警判定都依赖这个区分。
        """
        ...

    def available(self) -> bool:
        """采集器是否可用（psutil 是否装了）。"""
        ...


# ═══════════════════════════════════════════════════════════════════
# 存储
# ═══════════════════════════════════════════════════════════════════


@runtime_checkable
class StoragePort(Protocol):
    """配置读写（含 schema 校验与版本迁移）。"""

    def load_raw(self) -> dict[str, Any]:
        """读取原始 JSON。文件不存在时返回空 dict（不是抛异常）。"""
        ...

    def save_raw(self, data: dict[str, Any]) -> OpResult:
        """写回原始 JSON。"""
        ...

    def migrate(self, data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """按 schema_version 迁移；返回 (迁移后数据, 是否发生过迁移)。"""
        ...

    def backup(self, suffix: str = '.bak') -> OpResult:
        """备份当前配置文件。"""
        ...


# ═══════════════════════════════════════════════════════════════════
# 审计
# ═══════════════════════════════════════════════════════════════════


@runtime_checkable
class AuditPort(Protocol):
    """审计留痕（append-only + hash 链）。"""

    def record(self, entry: AuditEntry) -> None:
        """追加一条审计。

        ★ **永不抛出** —— 审计失败不能阻断业务操作，但必须内部留痕
          （写 stderr / 降级日志），不得静默吞掉。这是「审计不阻塞主流程」
          与「不许静默失败」两条原则的折中。
        """
        ...

    def query(self, flt: AuditFilter) -> list[AuditEntry]:
        """按条件查询。"""
        ...

    def verify_chain(self) -> ChainVerifyResult:
        """校验 hash 链完整性。"""
        ...


# ═══════════════════════════════════════════════════════════════════
# 通知
# ═══════════════════════════════════════════════════════════════════


@runtime_checkable
class NotifyPort(Protocol):
    """用户通知（托盘气泡 / 声音 / 弹窗）。"""

    def notify(self, level: Severity, title: str, body: str) -> None:
        """发一条通知。★ 同样**永不抛出** —— 通知失败不能影响业务。"""
        ...


__all__ = [
    'ClockPort',
    'ProcessPort',
    'ServicePort',
    'HealthPort',
    'MetricsPort',
    'StoragePort',
    'AuditPort',
    'NotifyPort',
]
