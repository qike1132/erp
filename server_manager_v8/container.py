"""依赖装配容器 — Adapter → UseCase 的显式接线（对齐项目 core/container.py 惯例）。

职责：
    - 只做装配，不含业务逻辑
    - 测试用 override 替换任意组件（Fake Adapter 注入）
    - 配置来源：JsonConfigStorage（schema v2）
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from server_manager_v8.adapters.audit_jsonl import AuditJsonlStore
from server_manager_v8.adapters.health_http import HttpHealthAdapter
from server_manager_v8.adapters.metrics_psutil import PsutilMetricsAdapter
from server_manager_v8.adapters.notify_win import WinNotifyAdapter
from server_manager_v8.adapters.process_win import ProcessWinAdapter
from server_manager_v8.adapters.service_nssm import NssmServiceAdapter
from server_manager_v8.adapters.storage_json import JsonConfigStorage
from server_manager_v8.application import AuthGuard, EventBus, RuntimeState
from server_manager_v8.application.usecases import (
    AlertOpsUseCase,
    BackupOpsUseCase,
    ConfigOpsUseCase,
    InstallServicesUseCase,
    KillPortUseCase,
    LogOpsUseCase,
    StartDevUseCase,
    StartProdUseCase,
    StopAllUseCase,
    SwitchModeUseCase,
    UninstallServicesUseCase,
)
from server_manager_v8.domain import (
    AlertCenter,
    AuthPolicy,
    Inhibition,
    ModeMachine,
    SilenceBook,
)

__all__ = ['Container', 'build_container']


@dataclass
class Container:
    """装配产物。usecase 字段按需取用。"""

    # 基础设施
    bus: EventBus = field(default_factory=EventBus)
    machine: ModeMachine = field(default_factory=ModeMachine)
    state: RuntimeState = field(default_factory=RuntimeState)
    guard: AuthGuard = field(default_factory=lambda: AuthGuard(AuthPolicy()))
    center: AlertCenter = field(default_factory=AlertCenter)
    silences: SilenceBook = field(default_factory=SilenceBook)
    config: ConfigOpsUseCase | None = None
    process: ProcessWinAdapter | None = None
    service: NssmServiceAdapter | None = None
    health: HttpHealthAdapter | None = None
    metrics: PsutilMetricsAdapter | None = None
    notify: WinNotifyAdapter | None = None
    audit: AuditJsonlStore | None = None

    # 用例
    start_dev: StartDevUseCase | None = None
    start_prod: StartProdUseCase | None = None
    stop_all: StopAllUseCase | None = None
    switch: SwitchModeUseCase | None = None
    install_services: InstallServicesUseCase | None = None
    uninstall_services: UninstallServicesUseCase | None = None
    kill_port: KillPortUseCase | None = None
    alerts: AlertOpsUseCase | None = None
    logs: LogOpsUseCase | None = None
    backup: BackupOpsUseCase | None = None


def _resolve_python_exe() -> str:
    """定位 Python 解释器（配置优先，回落 sys.executable）。"""
    return sys.executable


def build_container(
    project_dir: str | Path = '',
    config_path: str | Path = '',
    nssm_path: str = '',
    python_exe: str = '',
    logs_dir: str | Path = '',
) -> Container:
    """装配真实生产容器。所有默认值可从配置覆盖。"""
    proj = str(project_dir or Path.cwd())
    cfg_path = str(config_path or Path(proj) / 'server_manager_v8_config.json')
    log_dir = str(logs_dir or Path(proj) / 'logs')

    from server_manager_v8.domain.config_schema import CONFIG_V2_DEFAULTS

    storage = JsonConfigStorage(cfg_path, CONFIG_V2_DEFAULTS)
    config = ConfigOpsUseCase(storage, CONFIG_V2_DEFAULTS)

    bus = EventBus()
    machine = ModeMachine()
    state = RuntimeState()
    guard = AuthGuard(AuthPolicy())
    silences = SilenceBook()
    inhibition = Inhibition(chain_rules=(('pg_down', ('api_5xx', 'api_health_fail')),))
    center = AlertCenter(silences=silences, inhibition=inhibition)

    process = ProcessWinAdapter()
    service = NssmServiceAdapter(nssm_path=nssm_path, project_dir=proj)
    health = HttpHealthAdapter()
    metrics = PsutilMetricsAdapter(project_dir=proj)
    notify = WinNotifyAdapter()
    audit = AuditJsonlStore(Path(log_dir) / 'audit.jsonl')

    start_dev = StartDevUseCase(process, health, service, machine, bus, state)
    start_prod = StartProdUseCase(process, service, health, machine, state)
    stop_all = StopAllUseCase(process, service, machine, state)
    switch = SwitchModeUseCase(start_dev, start_prod, stop_all, machine)
    install_services = InstallServicesUseCase(service, machine)
    uninstall_services = UninstallServicesUseCase(service)
    kill_port = KillPortUseCase(process)
    alerts = AlertOpsUseCase(center, silences)
    logs = LogOpsUseCase(log_dir)
    backup = BackupOpsUseCase()

    return Container(
        bus=bus, machine=machine, state=state, guard=guard,
        center=center, silences=silences, config=config,
        process=process, service=service, health=health, metrics=metrics,
        notify=notify, audit=audit,
        start_dev=start_dev, start_prod=start_prod, stop_all=stop_all,
        switch=switch, install_services=install_services,
        uninstall_services=uninstall_services, kill_port=kill_port,
        alerts=alerts, logs=logs, backup=backup,
    )
