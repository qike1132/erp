"""Application 层测试的公共夹具。

与 adapters 层不同，应用层**不含真实 I/O** —— 它依赖的都是注入的 Protocol。
所以这里的夹具主要是 Fake Port 实现，用于在无 Windows 环境下测试用例编排。

设计原则（延续 adapters/conftest.py）：
    · Fake 记录**收到的调用参数**，而不仅返回预设值 ——
      应用层最容易出的错是「参数传错」，不是「返回值没处理」
    · 未登记的方法调用**抛出异常**，让「实现调了没预期的东西」立刻暴露
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from server_manager_v8.domain.models import HealthProbe, ServiceSnapshot
from server_manager_v8.domain.results import (
    HealthSample,
    KillResult,
    OpResult,
    ServiceCmd,
)
from server_manager_v8.domain.service_state import ServiceStatus


# ═══════════════════════════════════════════════════════════════════
# 时钟
# ═══════════════════════════════════════════════════════════════════


@dataclass
class FakeClock:
    """可控时钟：`advance()` 手动推进，`sleep` 记录而非真睡。

    这样「3 轮 × 0.5s 重试」「30s 超时」这类逻辑可以在**毫秒内**测完，
    且能精确断言「睡了几次、每次多久」。
    """

    _now: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._now += seconds

    # 兼容旧名字（见 adapters/clock.py 的迁移期别名说明）
    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        """只推进时间，不记录 sleep（用于模拟「真实耗时流逝」）。"""
        self._now += seconds

    @property
    def sleep_count(self) -> int:
        return len(self.sleeps)


# ═══════════════════════════════════════════════════════════════════
# 服务
# ═══════════════════════════════════════════════════════════════════


@dataclass
class FakeService:
    """伪造 `ServicePort`。

    `states` 是「服务名 → 状态」的可变字典，测试可直接改它来模拟状态变化。

    ★ `control_results` 按**具体动词**给不同结果（键为 `ServiceCmd`）。
      为什么需要它：`control_result` 是「所有动词同一个结果」，
      于是「停止成功但卸载失败」这类真实场景没法构造 ——
      而「停不掉」与「卸不掉」在排障时指向完全不同的方向，
      必须能分开测。
    """

    states: dict[str, ServiceStatus] = field(default_factory=dict)
    pids: dict[str, int] = field(default_factory=dict)
    calls: list[tuple[str, Any]] = field(default_factory=list)
    control_result: OpResult | None = None
    control_results: dict[Any, OpResult] = field(default_factory=dict)
    guard_result: OpResult | None = None
    missing: set[str] = field(default_factory=set)

    def snapshot(self, name: str) -> ServiceSnapshot:
        self.calls.append(('snapshot', name))
        status = self.states.get(name, ServiceStatus.STOPPED)
        return ServiceSnapshot(service=name, status=status,
                               raw_state=status.value, pid=self.pids.get(name))

    def state(self, name: str) -> ServiceStatus:
        self.calls.append(('state', name))
        return self.states.get(name, ServiceStatus.STOPPED)

    def pid(self, name: str) -> int | None:
        self.calls.append(('pid', name))
        return self.pids.get(name)

    def control(self, name: str, cmd: ServiceCmd) -> OpResult:
        self.calls.append(('control', (name, cmd)))
        if cmd in self.control_results:
            return self.control_results[cmd]
        if self.control_result is not None:
            return self.control_result
        return OpResult.success(f'{cmd.label} {name} 成功')

    def request_stop(self, name: str) -> OpResult:
        self.calls.append(('request_stop', name))
        return OpResult.success(f'已请求停止 {name}')

    def wait_state(self, name: str, want: ServiceStatus, timeout_s: float,
                   clock: Any) -> bool:
        self.calls.append(('wait_state', (name, want)))
        return self.states.get(name, ServiceStatus.STOPPED) is want

    def set_restart_guard(self, kind: str, *, nssm_path: str | None = None) -> OpResult:
        self.calls.append(('set_restart_guard', kind))
        if self.guard_result is not None:
            return self.guard_result
        return OpResult.success(f'guard={kind}')

    def detect_installed(self, names: tuple[str, ...] = ()) -> dict[str, bool]:
        self.calls.append(('detect_installed', names))
        return {n: (n not in self.missing) for n in names}


# ═══════════════════════════════════════════════════════════════════
# 进程
# ═══════════════════════════════════════════════════════════════════


@dataclass
class FakeProcess:
    """伪造 `ProcessPort`。

    ★ `port_pids` 用**双键**区分两种口径（这是本 Fake 最重要的一条设计）：
        正数键  `{5002: [...]}`   → `listening_only=True` 时返回
        负数键  `{-6379: [...]}`  → `listening_only=False` 时返回

      为什么必须分开：两种口径混用会导致「杀掉所有客户端」这类事故，
      而「混用了」这件事本身无法从返回值看出来。分开后，
      调用方选错口径会在测试里立刻暴露（拿到的是另一份名单）。

      若只给了正数键而调用方要宽口径，回退返回正数键的内容 ——
      这样「宽口径 ⊇ 窄口径」的直觉在测试里也成立（多数场景够用）。

    ★ `release_on_kill=True` 时，`kill_tree` 成功的 PID 会从 `port_pids`
      中移除 —— 模拟「进程被杀后端口真的释放了」。

      不加这个行为的话，「端口释放」这一整个分支无法测试：
      `kill_port` 的第 ④ 步复查永远看到端口仍被占，永远返回失败。
      而这一步恰恰是旧实现缺失（直接报成功）的部分，必须能测。
    """

    port_pids: dict[int, list[int]] = field(default_factory=dict)
    names: dict[int, str] = field(default_factory=dict)
    calls: list[tuple[str, Any]] = field(default_factory=list)
    psutil_ok: bool = True
    kill_result: KillResult | None = None
    release_on_kill: bool = True
    #: 宽口径的独立名单（含 ESTABLISHED 的连接方）。
    #:
    #: ★ 这是测试「口径混用」的关键字段：把客户端 PID 只放进这里、
    #:   不放 `port_pids`，于是「调用方选错口径」会立刻在断言里暴露
    #:   （杀掉了一堆本不该动的进程）。
    port_pids_all: dict[int, list[int]] = field(default_factory=dict)

    def find_port_pids(self, port: int, *, listening_only: bool = True) -> list[int]:
        self.calls.append(('find_port_pids', (port, listening_only)))
        if listening_only:
            return list(self.port_pids.get(port, []))
        # 宽口径：优先取显式的 port_pids_all；否则回退 port_pids（宽 ⊇ 窄）
        return list(self.port_pids_all.get(port, self.port_pids.get(port, [])))

    def kill_tree(self, pid: int, *, timeout_s: float = 5.0) -> KillResult:
        self.calls.append(('kill_tree', pid))
        if self.kill_result is not None:
            # ★ 只有「真的杀掉了目标」才释放端口。
            #   targeted == 0 表示没找到可杀进程 → 进程还活着 → 端口仍被占。
            #   若此处也释放，`KillPort` 的复查步骤就永远看不到「杀不死」
            #   这个场景，而那恰恰是必须被发现的失败形态。
            if self.kill_result.ok and self.kill_result.targeted > 0:
                self._release(pid)
            return self.kill_result
        self._release(pid)
        return KillResult(targeted=1)

    def _release(self, pid: int) -> None:
        """把 PID 从所有端口的占用名单里移除（模拟进程已死）。"""
        if not self.release_on_kill:
            return
        for mapping in (self.port_pids, self.port_pids_all):
            for key in list(mapping):
                if pid in mapping[key]:
                    mapping[key] = [p for p in mapping[key] if p != pid]

    def resolve_process_name(self, pid: int) -> str:
        return self.names.get(pid, '')

    def has_psutil(self) -> bool:
        return self.psutil_ok


# ═══════════════════════════════════════════════════════════════════
# 健康探针
# ═══════════════════════════════════════════════════════════════════


@dataclass
class FakeHealth:
    """伪造 `HealthPort`。

    `results` 按**调用序号**返回；用尽后重复最后一个。
    这便于模拟「前 2 次失败、第 3 次成功」这类就绪判定场景。
    """

    results: list[HealthSample] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    def probe(self, target: HealthProbe, *, timeout_s: float = 2.0) -> HealthSample:
        index = len(self.calls)
        self.calls.append(target.name)
        if not self.results:
            return HealthSample(ok=True, detail='')
        if index < len(self.results):
            return self.results[index]
        return self.results[-1]


# ═══════════════════════════════════════════════════════════════════
# 存储 / 审计 / 通知
# ═══════════════════════════════════════════════════════════════════


@dataclass
class FakeStorage:
    """伪造 `StoragePort`（内存字典）。"""

    data: dict[str, Any] = field(default_factory=dict)
    saved: list[dict[str, Any]] = field(default_factory=list)

    def load_raw(self) -> dict[str, Any]:
        return dict(self.data)

    def save_raw(self, data: dict[str, Any]) -> OpResult:
        self.saved.append(data)
        self.data = dict(data)
        return OpResult.success('已保存')

    def migrate(self, data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        if 'schema_version' in data:
            return data, False
        return {**data, 'schema_version': 2}, True

    def backup(self, suffix: str = '.bak') -> OpResult:
        return OpResult.success(f'已备份{suffix}')


@dataclass
class FakeAudit:
    """伪造 `AuditPort`。"""

    entries: list[Any] = field(default_factory=list)
    fail_on_record: bool = False

    def record(self, entry: Any) -> None:
        if self.fail_on_record:
            raise RuntimeError('模拟审计写入失败')
        self.entries.append(entry)

    def query(self, flt: Any) -> list[Any]:
        return list(self.entries)

    def verify_chain(self) -> Any:
        from server_manager_v8.domain.results import ChainVerifyResult
        return ChainVerifyResult(ok=True, total=len(self.entries))

    @property
    def actions(self) -> list[str]:
        return [e.action for e in self.entries]

    @property
    def last(self) -> Any:
        return self.entries[-1] if self.entries else None


@dataclass
class FakeNotify:
    """伪造 `NotifyPort`。"""

    sent: list[tuple[str, str, str]] = field(default_factory=list)

    def notify(self, level: Any, title: str, body: str) -> None:
        self.sent.append((getattr(level, 'value', str(level)), title, body))


# ═══════════════════════════════════════════════════════════════════
# fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def service() -> FakeService:
    return FakeService()


@pytest.fixture
def process() -> FakeProcess:
    return FakeProcess()


@pytest.fixture
def health() -> FakeHealth:
    return FakeHealth()


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def audit() -> FakeAudit:
    return FakeAudit()


@pytest.fixture
def notify() -> FakeNotify:
    return FakeNotify()
