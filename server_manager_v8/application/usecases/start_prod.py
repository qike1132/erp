"""生产模式启动 UseCase — NSSM 服务启动 + 业务就绪确认。

与 start_dev 复用 teardown 语义；startup 走 ServicePort（nssm start →
RUNNING → /api/health 就绪），成功后 ModeMachine.commit(PROD)。
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
)

from ..runtime import RuntimeState

__all__ = ['ProdStartSpec', 'StartProdUseCase']


@dataclass(frozen=True)
class ProdStartSpec:
    """生产模式启动参数。"""

    api_port: int = 5002
    service_names: tuple[str, ...] = ('erp-prod', 'erp-arq')
    ready_s: float = 60.0


class StartProdUseCase:
    def __init__(
        self,
        process: ProcessPort,
        service: ServicePort,
        health: HealthPort,
        machine: ModeMachine,
        state: RuntimeState,
    ) -> None:
        self._process = process
        self._service = service
        self._health = health
        self._machine = machine
        self._state = state

    def run(self, spec: ProdStartSpec, trace_id: str = '') -> OpResult:
        check = self._machine.can(ModeAction.START_PROD)
        if not check.ok:
            return check
        plan = self._machine.begin(ModeAction.START_PROD)
        self._teardown(plan.teardown.value)
        result = self._start_services(spec)
        if not result.ok:
            self._machine.rollback()
            return result
        self._machine.commit()
        return OpResult.success(detail='生产模式已启动')

    # ---- 内部 ----

    def _teardown(self, teardown_kind: str) -> None:
        if teardown_kind == 'dev_procs':
            for key in ('api', 'web', 'redis'):
                handle = self._state.unregister(key)
                if handle:
                    self._process.kill_tree(handle.pid)

    def _start_services(self, spec: ProdStartSpec) -> OpResult:
        for name in spec.service_names:
            state = self._service.state(name)
            if state is ServiceState.ABSENT:
                return OpResult.failure(f'{name} 未安装，请先执行 install-services')
            if state is not ServiceState.RUNNING:
                start = self._service.control(name, 'start')
                if not start.ok:
                    return start
                if not self._service.wait_state(name, ServiceState.RUNNING, timeout_s=spec.ready_s):
                    return OpResult.failure(f'{name} 未能在 {spec.ready_s:g}s 内 RUNNING')
        # 全部服务 RUNNING 后再做业务就绪（v6 _wait_service_running 语义）
        target = HealthTarget(name='api', kind='http', port=spec.api_port,
                              path='/api/health', timeout_s=2.0)
        sample = self._health.probe_until_ready(target, timeout_s=spec.ready_s)
        if not sample.ok:
            return OpResult.failure(f'生产服务未就绪: {sample.error}')
        return OpResult.success()
