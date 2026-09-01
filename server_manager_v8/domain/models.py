"""L2 领域模型 — 纯数据结构与值对象，零 I/O。

设计原则：
    - 全部为 frozen / 不可变 dataclass（除显式需要变更的状态机内部字段）
    - **所有操作结果一律返回显式结果对象**（OpResult / KillResult），
      不再使用 bool + 静默失败 —— 这是解决 v6「148 处静默吞错」的根本手段
    - 枚举统一继承 str，便于 JSON 序列化与配置读写
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    'GENESIS_HASH',
    'Alert',
    'AuditEntry',
    'DangerLevel',
    'HealthSample',
    'HealthTarget',
    'KillResult',
    'MetricsSample',
    'OpResult',
    'ProcessHandle',
    'Role',
    'RunMode',
    'ServiceKind',
    'ServiceSpec',
    'ServiceState',
    'Severity',
    'SpawnSpec',
    'canonical_json',
    'compute_entry_hash',
]


# ===================== 枚举 =====================


class RunMode(StrEnum):
    """全局运行模式。不变式：DEV 与 PROD 互斥。"""

    IDLE = 'idle'
    DEV = 'dev'
    PROD = 'prod'
    SWITCHING = 'switching'


class ServiceState(StrEnum):
    """单个服务的运行状态。"""

    RUNNING = 'running'
    STOPPED = 'stopped'
    PAUSED = 'paused'
    ABSENT = 'absent'  # 未安装（NSSM 服务不存在）
    UNKNOWN = 'unknown'  # 探测失败，不可当作 stopped 处理


class ServiceKind(StrEnum):
    """服务的托管方式。"""

    PROCESS = 'process'  # 管理器直接 spawn 的子进程（开发模式）
    NSSM = 'nssm'  # Windows 服务（生产模式）
    EXTERNAL = 'external'  # 外部托管，仅观测（如独立部署的 ARQ worker）


class Severity(StrEnum):
    """告警等级。P0 最高，与国内运维故障分级一致（火山引擎 VMP 口径）。

    注意：阿里云 ARMS 使用 P1 最高（P1~P4），两套口径都在流通。
    本项目采用 P0 最高，UI 上必须同时显示中文标签，不能只显示 P0/P1。
    """

    P0 = 'P0'  # 致命 · 弹窗 + 托盘 + 声音
    P1 = 'P1'  # 严重 · 托盘 + 声音
    P2 = 'P2'  # 警告 · 托盘气泡
    P3 = 'P3'  # 提示 · 仅角标
    P4 = 'P4'  # 记录 · 仅审计流水

    @property
    def label(self) -> str:
        return {
            'P0': '致命',
            'P1': '严重',
            'P2': '警告',
            'P3': '提示',
            'P4': '记录',
        }[self.value]

    @property
    def color(self) -> str:
        """Ant Design 色板，供 UI 与前端复用。"""
        return {
            'P0': '#F5222D',
            'P1': '#FA8C16',
            'P2': '#FAAD14',
            'P3': '#1890FF',
            'P4': '#8C8C8C',
        }[self.value]

    @property
    def notify_channels(self) -> tuple[str, ...]:
        """通知渠道分级（阿里云云监控口径裁剪）。"""
        return {
            'P0': ('modal', 'tray', 'sound'),
            'P1': ('tray', 'sound'),
            'P2': ('tray',),
            'P3': ('badge',),
            'P4': (),
        }[self.value]


class Role(StrEnum):
    """本地角色（单机桌面工具，不引入账号体系）。"""

    VIEWER = 'viewer'  # 只读
    OPERATOR = 'operator'  # 运维
    ADMIN = 'admin'  # 管理员


class DangerLevel(StrEnum):
    """高危操作分级（堡垒机 4A 裁剪）。"""

    L0 = 'L0'  # 低危 · 全角色，仅审计流水
    L1 = 'L1'  # 中危 · Operator+，轻确认（Toast 内撤销）
    L2 = 'L2'  # 高危 · Operator+，二次确认弹窗（列出影响面）
    L3 = 'L3'  # 极高危 · Admin 专属，键入操作名 + 强制填写变更原因

    @property
    def label(self) -> str:
        return {'L0': '低危', 'L1': '中危', 'L2': '高危', 'L3': '极高危'}[self.value]


# ===================== 规格对象（操作的输入） =====================


@dataclass(frozen=True)
class HealthTarget:
    """健康检查目标（K8s 三类探针语义 + Redis RESP 探测）。"""

    name: str
    kind: str  # 'http' | 'tcp' | 'redis'
    port: int
    path: str = '/api/health'
    timeout_s: float = 3.0
    period_s: float = 10.0
    failure_threshold: int = 3  # 连续失败 N 次才判定不健康（天然防抖）
    startup_grace_s: float = 60.0  # 启动宽限，期内失败不计入 threshold
    password: str = ''  # 仅 kind='redis'：NOAUTH 时用于 AUTH


@dataclass(frozen=True)
class SpawnSpec:
    """启动子进程的规格。

    安全约定（沿用 v6，Mimosa 合规）：argv 必须是列表形式，
    可执行文件绝对路径经 executable 参数传入，全程无 shell 参与。
    """

    argv: tuple[str, ...]
    cwd: str = ''
    env_extra: tuple[tuple[str, str], ...] = ()
    executable: str = ''  # 运行时解析的绝对路径，经 subprocess 的 executable= 传入


@dataclass(frozen=True)
class ProcessHandle:
    """已启动进程的句柄（不含 subprocess.Popen，保持 Domain 零平台依赖）。"""

    pid: int
    started_at: float = field(default_factory=time.time)


class SpawnError(Exception):
    """进程启动失败（技术异常）。reason 面向 UI 展示。

    与 OpResult 的分工：spawn 的启动失败是**环境性技术失败**（OSError 等），
    用异常携带原因；业务性失败（权限/状态）仍走 OpResult。二者都不静默。
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ServiceSpec:
    """服务定义：名称、托管方式、端口、健康检查、依赖关系。

    executable / params / env_extra / directory 仅 NSSM 安装时使用
    （适配层消费；查询态服务可省略）。
    """

    name: str
    kind: ServiceKind
    port: int | None = None
    health: HealthTarget | None = None
    depends_on: tuple[str, ...] = ()  # 依赖的服务名，用于抑制链与启动顺序
    startup_type: str = 'manual'  # 'auto' | 'manual'（仅 NSSM 有意义）
    executable: str = ''  # NSSM 安装：可执行文件绝对路径
    params: tuple[str, ...] = ()  # NSSM 安装：AppParameters
    env_extra: tuple[tuple[str, str], ...] = ()  # NSSM 安装：AppEnvironmentExtra
    directory: str = ''  # NSSM 安装：AppDirectory（默认取适配器 project_dir）


# ===================== 结果对象（消灭 bool + 静默失败） =====================


@dataclass(frozen=True)
class OpResult:
    """通用操作结果。所有 Port 方法统一返回此类型或其子类。

    替代 v6 中「返回 bool，失败时静默吞掉异常」的模式。
    """

    ok: bool
    reason: str = ''  # 失败原因（人类可读，UI 直接展示）
    detail: str = ''  # 技术细节（日志用）
    duration_ms: int = 0

    @classmethod
    def success(cls, detail: str = '', duration_ms: int = 0) -> OpResult:
        return cls(ok=True, detail=detail, duration_ms=duration_ms)

    @classmethod
    def failure(cls, reason: str, detail: str = '', duration_ms: int = 0) -> OpResult:
        """失败构造。**reason 为必填** —— 强制调用方说明失败原因，杜绝静默失败。"""
        return cls(ok=False, reason=reason, detail=detail, duration_ms=duration_ms)

    def __bool__(self) -> bool:
        """允许 if result: 简洁判断，但信息不丢失。"""
        return self.ok


@dataclass(frozen=True)
class KillResult(OpResult):
    """进程清理结果。额外携带被杀与残留的 PID，便于 UI 展示清理明细。"""

    killed_pids: tuple[int, ...] = ()
    survivors: tuple[int, ...] = ()  # 重试后仍存活的 PID —— 必须上报，不能静默

    @classmethod
    def done(
        cls,
        killed_pids: tuple[int, ...] = (),
        survivors: tuple[int, ...] = (),
        detail: str = '',
        duration_ms: int = 0,
    ) -> KillResult:
        """清理完成。

        注意：方法名刻意不叫 ``success`` —— 父类 ``OpResult.success(detail, duration_ms)``
        签名不同，覆写会违反里氏替换原则。
        有残留视为**部分成功**：ok 仍为 True，但 survivors 非空必须由上层处理。
        """
        return cls(
            ok=True,
            killed_pids=killed_pids,
            survivors=survivors,
            detail=detail,
            duration_ms=duration_ms,
        )

    @property
    def partial(self) -> bool:
        """是否存在未清理干净的残留进程。"""
        return bool(self.survivors)


# ===================== 采样数据 =====================


@dataclass(frozen=True)
class MetricsSample:
    """资源采样（psutil 适配器产出）。饱和度一律归一化到百分比。"""

    cpu: float = 0.0
    mem: float = 0.0
    disk: float = 0.0
    net_dn_mb: float = 0.0
    net_up_kb: float = 0.0
    procs: tuple[tuple[str, float, float], ...] = ()  # (name, cpu%, mem%)

    @property
    def saturation(self) -> float:
        """饱和度取 CPU / 内存 / 磁盘最大值（Google SRE 黄金第四指标）。"""
        return max(self.cpu, self.mem, self.disk)


@dataclass(frozen=True)
class HealthSample:
    """单次健康探测结果。"""

    ok: bool
    latency_ms: int = 0
    status_code: int = 0
    error: str = ''
    consecutive_fail: int = 0  # 连续失败次数，达到 threshold 才告警

    @classmethod
    def healthy(cls, latency_ms: int, status_code: int = 200) -> HealthSample:
        return cls(ok=True, latency_ms=latency_ms, status_code=status_code)

    @classmethod
    def unhealthy(cls, error: str, consecutive_fail: int = 1, status_code: int = 0) -> HealthSample:
        return cls(ok=False, error=error, consecutive_fail=consecutive_fail, status_code=status_code)


# ===================== 告警与审计 =====================


@dataclass(frozen=True)
class Alert:
    """告警实例。

    group_key 用于收敛：按 (service, family) 分组，同组在时间窗内合并。
    suggested_action 必填（配置期校验）—— SRE「可行动性」原则：
    收到告警若无需人工动作，则该告警不该存在。

    生命周期：firing → ack（确认）→ resolved（恢复）。
    ack_ts / resolve_ts 用于计算 MTTA（平均确认时间）与 MTTR（平均修复时间）。
    """

    STATUS_FIRING = 'firing'
    STATUS_ACK = 'ack'
    STATUS_RESOLVED = 'resolved'

    key: str  # 规则 ID，用于冷却去重
    severity: Severity
    title: str
    desc: str = ''
    service: str = ''
    family: str = ''  # 告警族，用于分组与抑制
    ts: float = field(default_factory=time.time)
    status: str = STATUS_FIRING
    count: int = 1  # 同键合并计数
    last_ts: float = 0.0  # 最近一次触发时间（合并时刷新）
    runbook: str = ''
    suggested_action: str = ''
    ack_ts: float = 0.0
    ack_by: str = ''
    resolve_ts: float = 0.0
    resolve_reason: str = ''

    @property
    def group_key(self) -> tuple[str, str]:
        """告警收敛的分组键（蓝鲸维度哈希的简化版）。"""
        return (self.service, self.family)

    @property
    def confirmed(self) -> bool:
        """v6 兼容视图：已确认 = 离开 firing 态。"""
        return self.status != self.STATUS_FIRING

    @property
    def firing(self) -> bool:
        return self.status == self.STATUS_FIRING

    def ack(self, by: str = '', ts: float = 0.0) -> Alert:
        """确认。返回新实例（frozen，不改原对象）。"""
        return Alert(**{
            **self.__dict__,
            'status': self.STATUS_ACK,
            'ack_ts': ts or self.ack_ts or time.time(),
            'ack_by': by or self.ack_by,
        })

    def resolve(self, reason: str = '', ts: float = 0.0) -> Alert:
        """恢复关闭。返回新实例。"""
        return Alert(**{
            **self.__dict__,
            'status': self.STATUS_RESOLVED,
            'resolve_ts': ts or self.resolve_ts or time.time(),
            'resolve_reason': reason,
        })


GENESIS_HASH = 'sha256:' + '0' * 64


def canonical_json(obj: Any) -> str:
    """规范化 JSON：键排序 + 无空格 + 非 ASCII 保留，保证哈希可复现。"""
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def compute_entry_hash(entry: dict[str, Any], prev_hash: str) -> str:
    """计算审计条目哈希：sha256(canonical_json(entry) + prev_hash)。"""
    payload = canonical_json(entry) + prev_hash
    return 'sha256:' + hashlib.sha256(payload.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class AuditEntry:
    """审计流水条目（append-only + 哈希链，字节 Romaster 裁剪）。

    字段：ts / actor / role / action / target / params_digest / result /
          duration_ms / trace_id / reason / prev_hash / hash
    """

    ts: float
    actor: str
    role: Role
    action: str
    target: str = ''
    params_digest: str = ''
    result: str = 'ok'  # 'ok' | 'fail' | 'denied'
    duration_ms: int = 0
    trace_id: str = ''
    reason: str = ''  # L3 操作的强制变更原因
    prev_hash: str = GENESIS_HASH
    hash: str = ''

    def sealed(self) -> AuditEntry:
        """计算并封印哈希，返回新实例。"""
        body = {
            'ts': self.ts,
            'actor': self.actor,
            'role': self.role.value,
            'action': self.action,
            'target': self.target,
            'params_digest': self.params_digest,
            'result': self.result,
            'duration_ms': self.duration_ms,
            'trace_id': self.trace_id,
            'reason': self.reason,
        }
        return AuditEntry(**{**self.__dict__, 'hash': compute_entry_hash(body, self.prev_hash)})

    def verify(self) -> bool:
        """校验自身哈希是否被篡改。"""
        return self.sealed().hash == self.hash

    def to_line(self) -> str:
        """序列化为 JSONL 一行（不含换行符）。"""
        data = {**self.__dict__, 'role': self.role.value}
        return canonical_json(data)
