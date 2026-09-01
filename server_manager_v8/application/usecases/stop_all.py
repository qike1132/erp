"""停止全部服务 UseCase — 期望态收敛到 IDLE。

teardown 展开（plan 驱动）：DEV_PROCS → 清理开发进程树；PROD_SERVICES →
NSSM 停止并确认 STOPPED（v6 语义：STOP_PENDING 期间强杀会被 AppExit 复活）。
"""

from __future__ import annotations

from server_manager_v8.domain import (
    ModeAction,
    ModeMachine,
    OpResult,
    ProcessPort,
    ServicePort,
    ServiceState,
)

from ..runtime import RuntimeState

__all__ = ['StopAllUseCase']


class StopAllUseCase:
    def __init__(
        self,
        process: ProcessPort,
        service: ServicePort | None,
        machine: ModeMachine,
        state: RuntimeState,
    ) -> None:
        self._process = process
        self._service = service
        self._machine = machine
        self._state = state

    def run(self, trace_id: str = '') -> OpResult:
        check = self._machine.can(ModeAction.STOP_ALL)
        if not check.ok:
            return check
        plan = self._machine.begin(ModeAction.STOP_ALL)
        self._teardown(plan.teardown.value)
        self._state.clear()
        self._machine.commit()
        return OpResult.success(detail='全部服务已停止')

    def _teardown(self, teardown_kind: str) -> None:
        if teardown_kind == 'dev_procs':
            for key in ('api', 'web', 'redis'):
                handle = self._state.unregister(key)
                if handle:
                    self._process.kill_tree(handle.pid)
        elif teardown_kind == 'prod_services' and self._service is not None:
            for name in ('erp-prod', 'erp-arq'):
                if self._service.state(name) is ServiceState.RUNNING:
                    self._service.control(name, 'stop')
                    self._service.wait_state(name, ServiceState.STOPPED, timeout_s=45.0)
