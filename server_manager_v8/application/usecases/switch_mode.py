"""模式切换 UseCase — 期望态收敛（互斥由 ModeMachine 保证）。

目标模式参数化：target='dev' → StartDevUseCase；'prod' → StartProdUseCase；
'idle' → StopAllUseCase。切换前对侧已由各 UseCase 的 teardown 展开停止。
"""

from __future__ import annotations

from server_manager_v8.domain import ModeMachine, OpResult, RunMode

from .start_dev import DevStartSpec, StartDevUseCase
from .start_prod import ProdStartSpec, StartProdUseCase
from .stop_all import StopAllUseCase

__all__ = ['InvalidTargetError', 'SwitchModeUseCase']


class InvalidTargetError(Exception):
    """未知的目标模式。"""


class SwitchModeUseCase:
    def __init__(
        self,
        start_dev: StartDevUseCase,
        start_prod: StartProdUseCase,
        stop_all: StopAllUseCase,
        machine: ModeMachine,
    ) -> None:
        self._start_dev = start_dev
        self._start_prod = start_prod
        self._stop_all = stop_all
        self._machine = machine

    def run(self, target: str | RunMode, **spec) -> OpResult:
        if isinstance(target, str):
            try:
                target_mode = RunMode(target)
            except ValueError as exc:
                raise InvalidTargetError(f'未知目标模式: {target}') from exc
        else:
            target_mode = target
        if target_mode is RunMode.DEV:
            return self._start_dev.run(spec.get('dev', DevStartSpec()))  # type: ignore[arg-type]
        if target_mode is RunMode.PROD:
            return self._start_prod.run(spec.get('prod', ProdStartSpec()))  # type: ignore[arg-type]
        if target_mode is RunMode.IDLE:
            return self._stop_all.run()
        raise InvalidTargetError(f'未知目标模式: {target_mode}')
