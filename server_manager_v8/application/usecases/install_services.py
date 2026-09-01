"""服务安装/卸载 UseCase（L3 极高危：Admin 专属 + 变更原因强校验）。"""

from __future__ import annotations

from dataclasses import dataclass

from server_manager_v8.domain import (
    ModeMachine,
    OpResult,
    RunMode,
    ServicePort,
    ServiceSpec,
    ServiceState,
)

__all__ = ['InstallServicesUseCase', 'InstallSpec', 'UninstallServicesUseCase']


@dataclass(frozen=True)
class InstallSpec:
    """生产服务安装规格（容器装配）。"""

    python_exe: str
    project_dir: str
    api_port: int = 5002
    workers: str = '4'
    service_names: tuple[str, str] = ('erp-prod', 'erp-arq')


class InstallServicesUseCase:
    def __init__(self, service: ServicePort, machine: ModeMachine) -> None:
        self._service = service
        self._machine = machine

    def run(self, spec: InstallSpec, reason: str = '') -> OpResult:
        # 安装前必须处于 IDLE（v6：先停止手动服务再装，防端口/服务冲突）
        if self._machine.mode is not RunMode.IDLE:
            return OpResult.failure('请先停止当前运行中的服务（开发/生产），再安装 Windows 服务')
        env_extra = (
            ('APP_ENV', 'production'),
            ('FASTAPI_DEBUG', 'false'),
            ('PYTHONPATH', spec.project_dir),
            ('PYTHONUTF8', '1'),
            ('PYTHONUNBUFFERED', '1'),
            ('UVICORN_WORKERS', spec.workers),
        )
        prod = ServiceSpec(
            name='erp-prod', kind='nssm', startup_type='auto',
            executable=spec.python_exe,
            params=('-m', 'fastapi_app.core.prod_runner', '--no-arq'),
            env_extra=env_extra, directory=spec.project_dir,
        )
        arq = ServiceSpec(
            name='erp-arq', kind='nssm', startup_type='auto',
            executable=spec.python_exe,
            params=('-m', 'arq', 'fastapi_app.core.arq_app.WorkerSettings'),
            env_extra=env_extra, directory=spec.project_dir,
        )
        for svc in (prod, arq):
            result = self._service.install(svc)
            if not result.ok:
                return OpResult.failure(f'{svc.name} 安装失败: {result.reason}')
        return OpResult.success(detail='erp-prod / erp-arq 已注册为 Windows 服务')


class UninstallServicesUseCase:
    def __init__(self, service: ServicePort) -> None:
        self._service = service

    def run(self, names: tuple[str, ...] = ('erp-prod', 'erp-arq'), reason: str = '') -> OpResult:
        for name in names:
            if self._service.state(name) is ServiceState.RUNNING:
                stop = self._service.control(name, 'stop')
                if not stop.ok:
                    return stop
                self._service.wait_state(name, ServiceState.STOPPED, timeout_s=45.0)
            result = self._service.uninstall(name)
            if not result.ok:
                return OpResult.failure(f'{name} 卸载失败: {result.reason}')
        return OpResult.success(detail=f'已卸载: {", ".join(names)}')
