"""L2 领域端口 — 仅 Protocol 定义，零实现。

依赖倒置的核心：Domain 只定义「需要什么能力」，Adapter 负责「怎么做到」。
因此 Domain 可以 100% 单测（测试时传入 Fake 实现即可）。

契约要点：
    - 全部返回**显式结果对象**（OpResult / KillResult / 具体 Sample），
      不用 bool、不用异常传递业务失败、绝不静默
    - 采集类不可用返回 None（如 MetricsPort.sample），由调用方决定降级策略
    - Protocol 用 @runtime_checkable 便于测试期 isinstance 校验
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .models import (
    AuditEntry,
    HealthSample,
    HealthTarget,
    KillResult,
    MetricsSample,
    OpResult,
    ProcessHandle,
    ServiceSpec,
    ServiceState,
    SpawnSpec,
)

__all__ = [
    'AuditPort',
    'ClockPort',
    'HealthPort',
    'MetricsPort',
    'NotifyPort',
    'ProcessPort',
    'ServicePort',
    'StoragePort',
]


@runtime_checkable
class ProcessPort(Protocol):
    """进程与端口操作。对应 v6 的 _kill_process_tree / _kill_port_sync / _find_port_pids。"""

    def find_port_pids(self, port: int) -> Sequence[int]:
        """查找占用指定端口的 PID 列表。无占用返回空序列。"""
        ...

    def kill_tree(self, pid: int, *, timeout_s: float = 5.0) -> KillResult:
        """杀掉进程树（含子进程）。survivors 非空必须上报。"""
        ...

    def kill_port(self, port: int, *, rounds: int = 3) -> KillResult:
        """清理端口占用。多 PID 场景需多轮重试（沿用 v6 的 3 轮策略）。"""
        ...

    def spawn(self, spec: SpawnSpec) -> ProcessHandle:
        """启动子进程，返回进程句柄（含 PID，供后续 kill_tree 与存活查询）。

        启动失败（OSError 等）抛 ``SpawnError``（reason 面向 UI）——
        这是技术性环境失败；业务性失败不在此接口发生。
        """
        ...

    def handle(self, pid: int) -> ProcessHandle | None:
        """查询进程是否仍存活，返回句柄或 None。"""
        ...


@runtime_checkable
class ServicePort(Protocol):
    """Windows 服务（NSSM）操作。对应 v6 的 _svc_state / _svc_pid / _nssm_install 等。"""

    def state(self, name: str) -> ServiceState:
        """查询服务状态。探测失败返回 UNKNOWN（**不得**降级为 STOPPED，
        否则会误判为「已停止」而漏停服务）。"""
        ...

    def pid(self, name: str) -> int | None:
        """服务主进程 PID，服务未运行返回 None。"""
        ...

    def install(self, spec: ServiceSpec) -> OpResult:
        """安装服务（L3 高危）。需写入依赖探测结果到 DependOnService。"""
        ...

    def uninstall(self, name: str) -> OpResult:
        """卸载服务（L3 高危）。"""
        ...

    def control(self, name: str, cmd: str) -> OpResult:
        """服务控制：start / stop / restart。"""
        ...

    def wait_state(self, name: str, want: ServiceState, timeout_s: float) -> bool:
        """等待服务到达目标状态。

        语义要点（v6 踩坑）：停止时必须等到确认 STOPPED 才算完成，
        在 STOP_PENDING 期间强杀会被 AppExit Default Restart 判定为崩溃而自动重启。
        """
        ...

    def detect_dependencies(self) -> Sequence[str]:
        """扫描本机「开机自启且运行中」的 PostgreSQL / Redis / Memurai 服务名。

        用于写入 NSSM DependOnService，避免开机时数据库慢启动导致
        后端健康检查失败、监督器反复 kill/重启（开机重启风暴）。
        """
        ...


@runtime_checkable
class HealthPort(Protocol):
    """健康探测。语义对标 K8s 三类探针。"""

    def probe(self, target: HealthTarget) -> HealthSample:
        """单次探测。返回含 latency_ms / status_code / error 的样本。"""
        ...

    def probe_until_ready(self, target: HealthTarget, timeout_s: float) -> HealthSample:
        """轮询探测直到就绪或超时（startup / readiness 语义）。"""
        ...


@runtime_checkable
class MetricsPort(Protocol):
    """资源指标采集。psutil 缺失时 sample() 返回 None，由调用方降级。"""

    def sample(self) -> MetricsSample | None:
        """采集一次。采集器不可用返回 None（**不抛异常**）。"""
        ...

    def available(self) -> bool:
        """采集器是否可用（用于 UI 展示引导空状态而非报错）。"""
        ...


@runtime_checkable
class StoragePort(Protocol):
    """配置持久化。带 schema 校验与版本迁移。"""

    def load(self) -> dict:
        """读取配置。缺失或损坏时返回默认配置并备份原文件。"""
        ...

    def save(self, data: dict) -> OpResult:
        """写入配置（原子写：先写临时文件再替换）。"""
        ...

    def migrate(self, data: dict) -> tuple[dict, bool]:
        """版本迁移，返回 (迁移后的数据, 是否发生了迁移)。"""
        ...


@runtime_checkable
class AuditPort(Protocol):
    """审计流水。append-only + 哈希链，永不抛出。"""

    def record(self, entry: AuditEntry) -> None:
        """追加一条审计记录。**本方法永不抛出异常**（审计失败不能影响主流程）。"""
        ...

    def query(self, **filters: object) -> Sequence[AuditEntry]:
        """按条件查询审计记录。"""
        ...

    def verify_chain(self) -> OpResult:
        """端到端重算哈希链，检测中间篡改。detail 携带首个断裂位置。"""
        ...


@runtime_checkable
class NotifyPort(Protocol):
    """通知渠道：托盘气泡 / 系统弹窗 / 声音。"""

    def notify(self, severity: object, title: str, body: str = '') -> None:
        """按告警等级决定通知方式（见 Severity.notify_channels）。"""
        ...


@runtime_checkable
class ClockPort(Protocol):
    """时间源。抽象出来是为了让状态机的 TTL / 冷却逻辑可单测（测试注入假时钟）。"""

    def now(self) -> float:
        ...

    def sleep(self, seconds: float) -> None:
        ...
