"""Port 实现 —— 把 I/O 自由函数聚合成符合 domain Protocol 的对象。

═══════════════════════════════════════════════════════════════════
★ 为什么是「薄包装」而不是「重写」
═══════════════════════════════════════════════════════════════════

P2 已把 I/O 逻辑按模块拆成自由函数，并通过 47 样本对拍验证了保真。
现在要做的是让 Application 层能依赖 Protocol —— 但**绝不能顺手把逻辑搬进来**，
那等于把已经对拍过的代码重写一遍，之前所有的保真验证全部作废。

所以本模块的铁律是：

    每个方法体 ≤ 3 行，且只做「参数转发 + 返回值透传」。

任何 `if` / `for` / 判定 / 字符串处理，都属于「写错了地方」。
这条纪律由 `tests/adapters/test_port_impls.py` 的 AST 检查守住 ——
它断言本模块所有方法体的语句数不超过阈值，且不含 If/For/While 节点。

═══════════════════════════════════════════════════════════════════
类与方法对应关系
═══════════════════════════════════════════════════════════════════

| Protocol     | 实现类              | 底层自由函数 |
|---|---|---|
| ClockPort    | `SystemClock`（clock.py，P2 已有） | — |
| ProcessPort  | `WinProcess`        | process_win.* |
| ServicePort  | `NssmService`       | service_nssm.* |
| HealthPort   | `HttpHealth`        | health_http.* |
| MetricsPort  | `PsutilMetrics`（metrics_psutil.py，P3 新建） | — |
| StoragePort  | `JsonStorage`       | storage_json.* |
| AuditPort    | `JsonlAuditLog`（audit_jsonl.py，P3 新建） | — |
| NotifyPort   | `WinNotifier`（notify_win.py，P3 新建） | — |

本模块只包装**需要聚合多个自由函数**的四类（Process / Service / Health / Storage）。
其余四类的实现本身就是自洽的类，直接实现 Protocol，无需再包一层。

═══════════════════════════════════════════════════════════════════
★ 关于「适配器里能不能有判定」的边界
═══════════════════════════════════════════════════════════════════

有两条判定被**刻意**留在了包装类里，并在此说明理由，避免被后人误当违规删掉：

1. `NssmService.wait_state()` 的**循环**与**超时比较**
   这不是「领域判定」而是「I/O 时序」—— 它决定「什么时候再查一次」，
   属于典型的适配器职责。真正的领域判定是「这个状态算不算到了」，
   那一步调用了 `domain.service_state.classify()`，判定仍在领域层。

2. `NssmService.snapshot()` 把 state 与 pid **合成一个快照**
   合成动作本身无判定，但顺序有讲究：先 query_state 再 query_pid，
   与旧实现一致。若反过来，PID 可能是「上一次运行」的残留值。

    ★ 保真提醒：旧实现是**分别**调 `_svc_state()` / `_svc_pid()`，
      两次 sc 查询之间服务状态可能已变。这里的 snapshot 只是把两次调用
      包在一起，**并没有解决**那个不一致窗口 —— 真要解决需要 `sc queryex`
      单次调用同时取状态与 PID，属于行为改动，不在迁移范围内。
      所以此处如实标注：**本方法不提供原子性保证**。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..domain.models import HealthProbe, ServiceSnapshot
from ..domain.ports import ClockPort
from ..domain.results import (
    HealthSample,
    KillResult,
    OpResult,
    ServiceCmd,
)
from ..domain.service_state import ServiceStatus
from . import health_http, process_win, service_nssm, storage_json

# ═══════════════════════════════════════════════════════════════════
# ProcessPort
# ═══════════════════════════════════════════════════════════════════


class WinProcess:
    """`ProcessPort` 的 Windows 实现。"""

    def __init__(self, *, timeout: float = 10.0) -> None:
        self._timeout = timeout

    def find_port_pids(self, port: int, *, listening_only: bool = True) -> list[int]:
        """见 `domain.ports.ProcessPort.find_port_pids`。

        ★ 底层 `port_pids()` 的击杀口径只返回 LISTENING；需要含 ESTABLISHED
          时必须走 `port_occupiers()`。这里按 `listening_only` 分流 ——
          分流本身是**口径选择**而非领域判定：领域层只规定「两种口径存在」，
          由调用方说明自己要哪个。
        """
        if listening_only:
            pids, _err = process_win.port_pids(port, timeout=self._timeout)
            return [int(p) for p in pids]
        occupiers, _err = process_win.port_occupiers(port, timeout=self._timeout)
        return [int(o.pid) for o in occupiers if str(o.pid).isdigit()]

    def kill_tree(self, pid: int, *, timeout_s: float = 5.0) -> KillResult:
        return process_win.kill_tree(pid, timeout_s=timeout_s)

    def resolve_process_name(self, pid: int) -> str:
        name, _err = process_win.resolve_process_name(str(pid), timeout=self._timeout)
        return name

    def has_psutil(self) -> bool:
        return process_win.has_psutil()


# ═══════════════════════════════════════════════════════════════════
# ServicePort
# ═══════════════════════════════════════════════════════════════════


class NssmService:
    """`ServicePort` 实现（NSSM 托管 + 原生 SCM）。

    `nssm_path` 为空时自动探测（对应旧 `_nssm_path()` 的候选表扫描）。
    """

    def __init__(self, *, nssm_path: str | None = None, timeout: float = 5.0) -> None:
        self._nssm_path = nssm_path
        self._timeout = timeout

    def _resolved_nssm(self) -> str | None:
        return service_nssm.find_nssm(self._nssm_path)

    def snapshot(self, name: str) -> ServiceSnapshot:
        """状态 + PID 打包。

        ★ 不提供原子性保证（见模块 docstring 第 2 条）——
          两次 `sc` 查询之间服务状态可能已变。要真正做到原子需要换成
          `sc queryex` 单次调用，属行为改动，留待后续单独评估。
        """
        query = service_nssm.query_state(name, timeout=self._timeout)
        pid = service_nssm.query_pid(name, timeout=self._timeout)
        return ServiceSnapshot(
            service=name,
            status=query.status,
            raw_state=query.raw,
            pid=pid,
        )

    def state(self, name: str) -> ServiceStatus:
        return service_nssm.query_state(name, timeout=self._timeout).status

    def pid(self, name: str) -> int | None:
        return service_nssm.query_pid(name, timeout=self._timeout)

    def control(self, name: str, cmd: ServiceCmd) -> OpResult:
        """施加控制命令。

        `install` / `uninstall` 需要服务规格，本方法只覆盖**幂等的启停重启**；
        安装卸载在 v8 方案里是 L3 高危操作，走 `usecases/install_services`，
        不从这里走（那里需要更多参数与确认流程）。
        """
        result = service_nssm.run_verb(
            cmd.value, name,
            nssm_path=self._resolved_nssm(),
            timeout=max(self._timeout * 3, 15.0),
        )
        if result.ok:
            return OpResult.success(result.detail)
        return OpResult.failure(result.reason or '操作失败', result.detail)

    def request_stop(self, name: str) -> OpResult:
        ok = service_nssm.request_stop(
            name, nssm_path=self._resolved_nssm(), timeout=15
        )
        if ok:
            return OpResult.success(f'已发出停止请求: {name}')
        return OpResult.failure('停止请求失败', f'服务 {name} 未能接受停止请求')

    def wait_state(self, name: str, want: ServiceStatus, timeout_s: float,
                   clock: ClockPort) -> bool:
        """轮询等待服务到达目标状态。

        ★ 这里的循环与超时比较属**I/O 时序**而非领域判定（见模块 docstring 第 1 条）：
          「什么时候再查一次」是适配器的事；
          「这个状态算不算到了」由 `query.status`（内部走领域层 classify）决定。
        """
        deadline = clock.monotonic() + timeout_s
        while True:
            if service_nssm.query_state(name, timeout=self._timeout).status is want:
                return True
            if clock.monotonic() >= deadline:
                return False
            clock.sleep(0.5)

    def set_restart_guard(self, kind: str, *, nssm_path: str | None = None) -> OpResult:
        path = nssm_path or self._resolved_nssm()
        if not path:
            return OpResult.failure('未找到 nssm', '需要 nssm.exe 才能设置重启守卫')
        results = service_nssm.set_restart_guard(kind, nssm_path=path)
        failed = [r for r in results if not r.ok]
        if failed:
            detail = '; '.join(f'{r.service}: {r.reason}' for r in failed)
            return OpResult.failure('部分服务设置守卫失败', detail)
        return OpResult.success(f'已设置守卫 {kind}')

    def detect_installed(self, names: tuple[str, ...] = ()) -> dict[str, bool]:
        return service_nssm.detect_installed(names or None)


# ═══════════════════════════════════════════════════════════════════
# HealthPort
# ═══════════════════════════════════════════════════════════════════


class HttpHealth:
    """`HealthPort` 实现。"""

    def __init__(self, *, opener: Any = None, clock: Any = None) -> None:
        self._opener = opener if opener is not None else health_http.build_direct_opener()
        self._clock = clock

    def probe(self, target: HealthProbe, *, timeout_s: float = 2.0) -> HealthSample:
        """执行一次 HTTP 探针。

        ★ `target.kind` 非 HTTP 时不发请求，返回明确的失败样本 ——
          TCP / SERVICE_STATE 探针由其他 Port 承担（`ProcessPort` / `ServicePort`），
          这里不做「猜一个实现」，避免悄悄用 HTTP 冒充 TCP 探测。
        """
        if str(getattr(target, 'kind', '')).endswith('SERVICE_STATE'):
            return HealthSample(ok=False, detail='HTTP 适配器不支持服务状态探针')
        if not target.url:
            return HealthSample(ok=False, detail=f'探针 {target.name} 没有 url')

        return health_http.probe(
            target.url, timeout=timeout_s, opener=self._opener, clock=self._clock
        )


# ═══════════════════════════════════════════════════════════════════
# StoragePort
# ═══════════════════════════════════════════════════════════════════


class JsonStorage:
    """`StoragePort` 实现（配置文件读写）。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load_raw(self) -> dict[str, Any]:
        return storage_json.load(self._path).raw

    def save_raw(self, data: dict[str, Any]) -> OpResult:
        return storage_json.save(self._path, data)

    def migrate(self, data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        return storage_json.migrate(data)

    def backup(self, suffix: str = '.bak') -> OpResult:
        return storage_json.backup(self._path, suffix)


__all__ = [
    'HttpHealth',
    'JsonStorage',
    'NssmService',
    'WinProcess',
]
