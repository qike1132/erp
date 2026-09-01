"""开发模式启动 UseCase — 5 步 Pipeline（v6 _start_dual_thread 的显式化迁移）。

步骤（对齐 v6，勿改顺序）::

    clear_ports → start_redis → start_api(健康检查) → start_web(探测) → commit

语义要点（v6 踩坑保留）：
    - Redis 启动失败仅警告**不中止**（部分功能不可用但开发可继续）
    - API 健康检查 30×1s；Web 探测 60×1s；任一失败 → 回滚已启动进程 + ModeMachine.rollback
    - 全部成功后 ModeMachine.commit(DEV)，否则 rollback 回切换前模式
"""

from __future__ import annotations

from dataclasses import dataclass

from server_manager_v8.domain import (
    HealthPort,
    HealthTarget,
    ModeAction,
    ModeMachine,
    OpResult,
    ProcessPort,
    ServicePort,
    ServiceState,
    SpawnSpec,
)

from ..event_bus import EventBus
from ..events import LogAppended
from ..pipeline import Pipeline, PipelineAbortedError, Step
from ..runtime import RuntimeState

__all__ = ['DevStartSpec', 'StartDevUseCase']


@dataclass(frozen=True)
class DevStartSpec:
    """开发模式启动参数（容器从配置装配）。"""

    python_exe: str
    project_dir: str
    frontend_dir: str
    api_port: int = 5002
    web_port: int = 3000
    redis_port: int = 6379
    redis_exe: str = ''
    redis_conf: str = ''
    redis_password: str = ''
    npm_cmd: str = 'npm.cmd'


class StartDevUseCase:
    """开发模式一键启动。构造注入全部 Port（测试传入 Fake）。"""

    API_READY_S = 30.0
    WEB_READY_S = 60.0

    def __init__(
        self,
        process: ProcessPort,
        health: HealthPort,
        service: ServicePort | None,
        machine: ModeMachine,
        bus: EventBus,
        state: RuntimeState,
    ) -> None:
        self._process = process
        self._health = health
        self._service = service
        self._machine = machine
        self._bus = bus
        self._state = state

    def run(self, spec: DevStartSpec, trace_id: str = '') -> OpResult:
        check = self._machine.can(ModeAction.START_DEV)
        if not check.ok:
            return check
        plan = self._machine.begin(ModeAction.START_DEV)
        try:
            self._teardown(plan.teardown.value)
            pipeline = self._build_pipeline(spec, trace_id)
            pipeline.run()
        except PipelineAbortedError as exc:
            self._rollback_handles()
            self._machine.rollback()
            return OpResult.failure(str(exc))
        self._machine.commit()
        return OpResult.success(detail='开发模式已启动')

    # ---- 内部 ----

    def _teardown(self, teardown_kind: str) -> None:
        """plan.teardown 展开：DEV_PROCS → 杀开发进程；PROD_SERVICES → 停生产。"""
        if teardown_kind == 'dev_procs':
            for key in ('api', 'web'):
                handle = self._state.unregister(key)
                if handle:
                    self._process.kill_tree(handle.pid)
        elif teardown_kind == 'prod_services' and self._service is not None:
            # v6 语义：停止必须确认 STOPPED（STOP_PENDING 强杀会被 AppExit 复活）
            for name in ('erp-prod', 'erp-arq'):
                if self._service.state(name) is ServiceState.RUNNING:
                    self._service.control(name, 'stop')
                    self._service.wait_state(name, ServiceState.STOPPED, timeout_s=45.0)

    def _build_pipeline(self, spec: DevStartSpec, trace_id: str) -> Pipeline:
        pipe = Pipeline(name='start_dev', bus=self._bus, trace_id=trace_id)
        pipe.add(Step('清理端口', self._step_clear_ports(spec), retries=1))
        pipe.add(Step('启动 Redis', self._step_redis(spec)))
        pipe.add(Step('启动后端', self._step_api(spec)))
        pipe.add(Step('启动前端', self._step_web(spec)))
        return pipe

    def _step_clear_ports(self, spec: DevStartSpec) -> object:
        def run() -> OpResult:
            first = self._process.kill_port(spec.api_port, rounds=2)
            second = self._process.kill_port(spec.web_port, rounds=2)
            if first.partial or second.partial:
                return OpResult.failure('端口清理后仍有残留进程')
            return OpResult.success()
        return run

    def _step_redis(self, spec: DevStartSpec) -> object:
        def run() -> OpResult:
            target = HealthTarget(name='redis', kind='redis', port=spec.redis_port,
                                  timeout_s=1.0, password=spec.redis_password)
            if self._health.probe(target).ok:
                return OpResult.success(detail='Redis 已在运行')
            if not spec.redis_exe:
                self._bus.publish(LogAppended(level='WARNING', text='Redis 未配置，跳过启动'))
                return OpResult.success(detail='Redis 跳过（未配置）')
            handle = self._process.spawn(SpawnSpec(
                argv=('redis-server', spec.redis_conf) if spec.redis_conf else ('redis-server',),
                executable=spec.redis_exe,
            ))
            self._state.register('redis', handle)
            sample = self._health.probe_until_ready(target, timeout_s=8.0)
            if not sample.ok:
                self._bus.publish(LogAppended(level='WARNING',
                                              text=f'Redis 启动但未就绪: {sample.error}'))
            return OpResult.success(detail='Redis 启动')
        return run

    def _step_api(self, spec: DevStartSpec) -> object:
        def run() -> OpResult:
            handle = self._process.spawn(SpawnSpec(
                argv=('python', '-u', '-m', 'uvicorn', 'fastapi_app.main:app',
                      '--host', '0.0.0.0', '--port', str(spec.api_port),
                      '--log-level', 'info', '--reload', '--reload-dir', 'fastapi_app'),
                executable=spec.python_exe,
                cwd=spec.project_dir,
                env_extra=(('PYTHONUNBUFFERED', '1'), ('PYTHONIOENCODING', 'utf-8'),
                           ('PYTHONUTF8', '1'), ('PYTHONPATH', spec.project_dir)),
            ))
            self._state.register('api', handle)
            target = HealthTarget(name='api', kind='http', port=spec.api_port,
                                  path='/api/health', timeout_s=2.0)
            sample = self._health.probe_until_ready(target, timeout_s=self.API_READY_S)
            if not sample.ok:
                return OpResult.failure(f'后端启动失败或健康检查未通过: {sample.error}')
            return OpResult.success()
        return run

    def _step_web(self, spec: DevStartSpec) -> object:
        def run() -> OpResult:
            handle = self._process.spawn(SpawnSpec(
                argv=(spec.npm_cmd, 'run', 'dev', '--', '--port', str(spec.web_port)),
                cwd=spec.frontend_dir,
                env_extra=(('BACKEND_INTERNAL_URL', f'http://127.0.0.1:{spec.api_port}'),),
            ))
            self._state.register('web', handle)
            target = HealthTarget(name='web', kind='http', port=spec.web_port, path='/',
                                  timeout_s=2.0)
            sample = self._health.probe_until_ready(target, timeout_s=self.WEB_READY_S)
            if not sample.ok:
                return OpResult.failure(f'前端启动失败或探测未通过: {sample.error}')
            return OpResult.success()
        return run

    def _rollback_handles(self) -> None:
        """失败回滚：清理本流程登记的所有进程（API/Web/Redis）。"""
        for key in ('api', 'web', 'redis'):
            handle = self._state.unregister(key)
            if handle:
                self._process.kill_tree(handle.pid)
