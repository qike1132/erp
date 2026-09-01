"""UseCase 层测试：Fake Port 注入（不触碰真实进程/服务）。"""
from __future__ import annotations

import pytest

from server_manager_v8.application import AuthGuard, EventBus, RuntimeState
from server_manager_v8.application.usecases import (
    AlertOpsUseCase,
    ConfigOpsUseCase,
    DevStartSpec,
    InstallServicesUseCase,
    InstallSpec,
    KillPortUseCase,
    StartDevUseCase,
    StartProdUseCase,
    StopAllUseCase,
    SwitchModeUseCase,
    UninstallServicesUseCase,
)
from server_manager_v8.domain import (
    Action,
    Alert,
    AlertCenter,
    AuthPolicy,
    HealthSample,
    HealthTarget,
    KillResult,
    ModeAction,
    ModeMachine,
    OpResult,
    ProcessHandle,
    Role,
    ServiceSpec,
    ServiceState,
    Session,
    Severity,
    SilenceBook,
    SpawnError,
    SpawnSpec,
)

# ===================== Fake Ports =====================


class FakeProcess:
    """进程 Port Fake：记录调用 + 受控行为。"""

    def __init__(self) -> None:
        self.spawned: list[SpawnSpec] = []
        self.killed: list[int] = []
        self._next_pid = 1000
        self.spawn_error: str | None = None

    def find_port_pids(self, port: int) -> list[int]:
        return []

    def kill_tree(self, pid: int, *, timeout_s: float = 5.0) -> KillResult:
        self.killed.append(pid)
        return KillResult.done(killed_pids=(pid,))

    def kill_port(self, port: int, *, rounds: int = 3) -> KillResult:
        return KillResult.done()

    def spawn(self, spec: SpawnSpec) -> ProcessHandle:
        if self.spawn_error:
            raise SpawnError(self.spawn_error)
        self.spawned.append(spec)
        handle = ProcessHandle(pid=self._next_pid)
        self._next_pid += 1
        return handle

    def handle(self, pid: int) -> ProcessHandle | None:
        return ProcessHandle(pid=pid) if pid not in self.killed else None


class FakeHealth:
    """健康 Port Fake：默认全健康，可注入失败。"""

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.probed: list[HealthTarget] = []

    def probe(self, target: HealthTarget) -> HealthSample:
        self.probed.append(target)
        return HealthSample.healthy(latency_ms=5) if self.ok else HealthSample.unhealthy('fake down')

    def probe_until_ready(self, target: HealthTarget, timeout_s: float) -> HealthSample:
        return self.probe(target)


class FakeService:
    """服务 Port Fake：记录控制与安装调用。"""

    def __init__(self) -> None:
        self.state_map: dict[str, ServiceState] = {}
        self.controls: list[tuple[str, str]] = []
        self.installs: list[ServiceSpec] = []
        self.uninstalls: list[str] = []
        self.install_ok = True

    def state(self, name: str) -> ServiceState:
        return self.state_map.get(name, ServiceState.ABSENT)

    def pid(self, name: str) -> int | None:
        return None

    def install(self, spec: ServiceSpec) -> OpResult:
        self.installs.append(spec)
        return OpResult.success() if self.install_ok else OpResult.failure('nssm 缺失')

    def uninstall(self, name: str) -> OpResult:
        self.uninstalls.append(name)
        return OpResult.success()

    def control(self, name: str, cmd: str) -> OpResult:
        self.controls.append((name, cmd))
        if cmd == 'start':
            self.state_map[name] = ServiceState.RUNNING
        elif cmd == 'stop':
            self.state_map[name] = ServiceState.STOPPED
        return OpResult.success()

    def wait_state(self, name: str, want: ServiceState, timeout_s: float) -> bool:
        return self.state_map.get(name) is want

    def detect_dependencies(self) -> list[str]:
        return []


class FakeStorage:
    def __init__(self, data: dict | None = None) -> None:
        self.data = data or {}
        self.saved: dict | None = None

    def load(self) -> dict:
        return self.data

    def save(self, data: dict) -> OpResult:
        self.saved = data
        return OpResult.success()

    def migrate(self, data: dict) -> tuple[dict, bool]:
        return data, False


# ===================== 测试 =====================


def _make_env(dev_fail_at: str = ''):
    """装配最小 usecase 环境。dev_fail_at: 'api'|'web'|'' 指定健康探测失败。"""
    process = FakeProcess()
    service = FakeService()
    health = FakeHealth()
    machine = ModeMachine()
    bus = EventBus()
    state = RuntimeState()
    if dev_fail_at:
        health.ok = False  # 全部探测失败 → api 步骤（第 3 步）中止
    start_dev = StartDevUseCase(process, health, service, machine, bus, state)
    start_prod = StartProdUseCase(process, service, health, machine, state)
    stop_all = StopAllUseCase(process, service, machine, state)
    switch = SwitchModeUseCase(start_dev, start_prod, stop_all, machine)
    return {
        'process': process, 'service': service, 'health': health,
        'machine': machine, 'state': state, 'start_dev': start_dev,
        'start_prod': start_prod, 'stop_all': stop_all, 'switch': switch,
    }


def _dev_spec() -> DevStartSpec:
    return DevStartSpec(
        python_exe=r'C:\Python\python.exe', project_dir=r'D:\erp',
        frontend_dir=r'D:\erp\frontend-vite',
        redis_exe=r'C:\Redis\redis-server.exe',
    )


class TestStartDev:
    def test_success_commits_dev(self) -> None:
        env = _make_env()
        result = env['start_dev'].run(_dev_spec())
        assert result.ok
        assert env['machine'].mode.value == 'dev'
        # FakeHealth 全健康 → Redis 探测通过即跳过 spawn；api/web 登记
        assert {'api', 'web'} <= set(env['state'].snapshot())
        assert len(env['process'].spawned) == 2  # api + web
        assert 'redis' in [t.name for t in env['health'].probed]

    def test_api_failure_rolls_back(self) -> None:
        env = _make_env(dev_fail_at='api')
        result = env['start_dev'].run(_dev_spec())
        assert not result.ok and '健康检查' in result.reason
        # 回滚：模式回到 IDLE，登记进程全部清理
        assert env['machine'].mode.value == 'idle'
        assert env['state'].snapshot() == {}
        assert len(env['process'].killed) >= 1

    def test_already_in_dev_rejected(self) -> None:
        env = _make_env()
        assert env['start_dev'].run(_dev_spec()).ok
        second = env['start_dev'].run(_dev_spec())
        assert not second.ok and '已在运行' in second.reason

    def test_switch_from_prod_stops_prod_first(self) -> None:
        env = _make_env()
        # 先进入 PROD（互斥切换的出发侧）
        env['service'].state_map.update({'erp-prod': ServiceState.RUNNING,
                                         'erp-arq': ServiceState.RUNNING})
        env['machine'].begin(ModeAction.START_PROD)
        env['machine'].commit()
        assert env['start_dev'].run(_dev_spec()).ok  # PROD → DEV 切换
        stopped = [c for c in env['service'].controls if c[1] == 'stop']
        assert ('erp-prod', 'stop') in stopped  # 互斥切换先停生产
        assert env['machine'].mode.value == 'dev'

    def test_redis_missing_only_warns(self) -> None:
        env = _make_env()
        spec = DevStartSpec(
            python_exe='py', project_dir='p', frontend_dir='f',  # redis_exe 为空
        )
        result = env['start_dev'].run(spec)
        assert result.ok  # Redis 缺失不中止


class TestStopAndSwitch:
    def test_stop_all_from_dev(self) -> None:
        env = _make_env()
        env['start_dev'].run(_dev_spec())
        assert env['stop_all'].run().ok
        assert env['machine'].mode.value == 'idle'
        assert env['state'].snapshot() == {}

    def test_switch_to_idle(self) -> None:
        env = _make_env()
        env['start_dev'].run(_dev_spec())
        assert env['switch'].run('idle').ok
        assert env['machine'].mode.value == 'idle'

    def test_switch_invalid_target(self) -> None:
        from server_manager_v8.application.usecases import InvalidTargetError

        env = _make_env()
        with pytest.raises(InvalidTargetError):
            env['switch'].run('nonsense')

    def test_stop_prod_services(self) -> None:
        env = _make_env()
        env['service'].state_map.update({'erp-prod': ServiceState.RUNNING,
                                         'erp-arq': ServiceState.RUNNING})
        env['machine'].begin(ModeAction.START_PROD)
        env['machine'].commit()
        assert env['stop_all'].run().ok
        assert env['machine'].mode.value == 'idle'
        assert ('erp-prod', 'stop') in env['service'].controls


class TestStartProd:
    def test_requires_installed_services(self) -> None:
        from server_manager_v8.application.usecases import ProdStartSpec

        env = _make_env()
        result = env['start_prod'].run(ProdStartSpec())
        assert not result.ok and '未安装' in result.reason
        assert env['machine'].mode.value == 'idle'  # 失败回滚

    def test_success_path(self) -> None:
        from server_manager_v8.application.usecases import ProdStartSpec

        env = _make_env()
        env['service'].state_map.update({'erp-prod': ServiceState.RUNNING,
                                         'erp-arq': ServiceState.RUNNING})
        assert env['start_prod'].run(ProdStartSpec()).ok
        assert env['machine'].mode.value == 'prod'


class TestKillPort:
    def test_valid(self) -> None:
        env = _make_env()
        assert KillPortUseCase(env['process']).run(5002).ok

    def test_invalid_port(self) -> None:
        env = _make_env()
        assert not KillPortUseCase(env['process']).run(0).ok
        assert not KillPortUseCase(env['process']).run(99999).ok


class TestInstallUninstall:
    def _install_spec(self) -> InstallSpec:
        return InstallSpec(python_exe=r'C:\Python\python.exe', project_dir=r'D:\erp')

    def test_install_records_specs(self) -> None:
        env = _make_env()
        service: FakeService = env['service']
        result = InstallServicesUseCase(service, env['machine']).run(self._install_spec())
        assert result.ok
        assert [s.name for s in service.installs] == ['erp-prod', 'erp-arq']
        assert service.installs[0].params == ('-m', 'fastapi_app.core.prod_runner', '--no-arq')
        assert service.installs[0].startup_type == 'auto'

    def test_install_rejected_when_running(self) -> None:
        env = _make_env()
        env['start_dev'].run(_dev_spec())
        result = InstallServicesUseCase(env['service'], env['machine']).run(self._install_spec())
        assert not result.ok and '停止' in result.reason

    def test_install_failure_reported(self) -> None:
        env = _make_env()
        service: FakeService = env['service']
        service.install_ok = False
        result = InstallServicesUseCase(service, env['machine']).run(self._install_spec())
        assert not result.ok and 'nssm 缺失' in result.reason

    def test_uninstall_stops_then_removes(self) -> None:
        env = _make_env()
        service: FakeService = env['service']
        service.state_map.update({'erp-prod': ServiceState.RUNNING})
        result = UninstallServicesUseCase(service).run()
        assert result.ok
        assert ('erp-prod', 'stop') in service.controls
        assert 'erp-prod' in service.uninstalls


class TestAlertOps:
    def test_ack_flow(self) -> None:
        center = AlertCenter()
        ops = AlertOpsUseCase(center)
        center.ingest(Alert(key='k', severity=Severity.P2, title='t', ts=0.0), ts=0.0)
        assert ops.ack('k', by='cli').ok
        assert center.unconfirmed_count() == 0

    def test_silence_add_remove(self) -> None:
        center = AlertCenter()
        silences = SilenceBook()
        ops = AlertOpsUseCase(center, silences)
        assert ops.add_silence(service='api', duration_s=300, reason='维护').ok
        assert silences.active_count == 1
        silence_id = silences.items[0].id
        assert ops.remove_silence(silence_id).ok
        assert silences.active_count == 0


class TestConfigOps:
    def test_save_patch_merges(self) -> None:
        storage = FakeStorage({'schema_version': 2, 'app': {'theme': 'light'}})
        ops = ConfigOpsUseCase(storage, {})
        assert ops.save({'app': {'theme': 'dark'}}).ok
        assert storage.saved == {'schema_version': 2, 'app': {'theme': 'dark'}}

    def test_validate_port(self) -> None:
        ops = ConfigOpsUseCase(FakeStorage({}), {})
        assert ops.validate_port(5002).ok
        assert not ops.validate_port(0).ok
        assert not ops.validate_port('5002').ok


class TestGuardDecorator:
    """@require 装饰器 + Fake UseCase。"""

    def test_viewer_denied_stop(self) -> None:
        guard = AuthGuard(AuthPolicy(), clock=lambda: 0.0)
        guard.set_session(Session(
            base_role=Role.VIEWER,
        ))
        calls = {'n': 0}

        class Stop:
            @guard.require(Action.STOP_SERVICE)
            def run(self) -> OpResult:
                calls['n'] += 1
                return OpResult.success()

        result = Stop().run()
        assert not result.ok and '权限不足' in result.reason
        assert calls['n'] == 0  # 业务未执行

    def test_operator_allowed_stop(self) -> None:
        guard = AuthGuard(AuthPolicy(), clock=lambda: 0.0)
        guard.set_session(Session(
            base_role=Role.OPERATOR,
        ))

        class Stop:
            @guard.require(Action.STOP_SERVICE)
            def run(self) -> OpResult:
                return OpResult.success()

        assert Stop().run().ok

    def test_l3_requires_reason(self) -> None:
        guard = AuthGuard(AuthPolicy(), clock=lambda: 0.0)
        guard.set_session(Session(
            base_role=Role.ADMIN,
        ))

        class Uninstall:
            @guard.require(Action.UNINSTALL_SERVICES)
            def run(self, reason: str = '') -> OpResult:
                return OpResult.success()

        assert not Uninstall().run().ok  # 未填原因
        assert Uninstall().run(reason='服务器迁移').ok

    def test_elevate_and_degrade(self) -> None:
        guard = AuthGuard(AuthPolicy(), clock=lambda: 0.0)
        assert guard.elevate(Role.OPERATOR).ok
        assert guard.role is Role.OPERATOR
        guard.degrade()
        assert guard.role is Role.VIEWER
