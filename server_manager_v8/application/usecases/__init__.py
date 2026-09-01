"""UseCase 包 — 每个文件一个业务用例，构造注入 Port（测试用 Fake 替换）。"""
from __future__ import annotations

from .alert_ops import AlertOpsUseCase
from .backup_ops import BackupOpsUseCase, BackupSpec
from .config_ops import CONFIG_SCHEMA_VERSION, ConfigOpsUseCase
from .install_services import (
    InstallServicesUseCase,
    InstallSpec,
    UninstallServicesUseCase,
)
from .kill_port import KillPortUseCase
from .log_ops import KeywordRule, LogOpsUseCase, validate_keyword_rule
from .start_dev import DevStartSpec, StartDevUseCase
from .start_prod import ProdStartSpec, StartProdUseCase
from .stop_all import StopAllUseCase
from .switch_mode import InvalidTargetError, SwitchModeUseCase

__all__ = [
    'CONFIG_SCHEMA_VERSION',
    'AlertOpsUseCase',
    'BackupOpsUseCase',
    'BackupSpec',
    'ConfigOpsUseCase',
    'DevStartSpec',
    'InstallServicesUseCase',
    'InstallSpec',
    'InvalidTargetError',
    'KeywordRule',
    'KillPortUseCase',
    'LogOpsUseCase',
    'ProdStartSpec',
    'StartDevUseCase',
    'StartProdUseCase',
    'StopAllUseCase',
    'SwitchModeUseCase',
    'UninstallServicesUseCase',
    'validate_keyword_rule',
]
