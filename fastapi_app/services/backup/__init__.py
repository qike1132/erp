"""备份服务新架构包。

当前仅暴露数据库恢复生命周期相关类型与编排器。
后续可随候选 1/2/4/5 的推进继续扩展。
"""

from fastapi_app.services.backup.adapters import (
    BackupProgressReporterAdapter,
    DefaultArchiveDecryptorAdapter,
    ExistingCacheInvalidatorAdapter,
    ExistingComponentRestoreAdapter,
    ExistingEngineLifecycleAdapter,
    ExistingRestoreVerifierAdapter,
    ExistingSafetyBackupAdapter,
    PostgresAdvisoryLockAdapter,
)
from fastapi_app.services.backup.format_storage import BackupStorage, LocalBackupStorage
from fastapi_app.services.backup.format_strategy import (
    BackupFormatError,
    BackupFormatStrategy,
    DefaultBackupFormatStrategy,
    ZipBackupArchiveView,
)
from fastapi_app.services.backup.format_types import (
    ArchiveEntry,
    BackupArtifact,
    BackupChunk,
    BackupInfo,
    PackOptions,
    RestoredBackupArchive,
    UnpackOptions,
)
from fastapi_app.services.backup.orchestrator import (
    DatabaseRestoreOrchestrator,
    RestoreError,
    StrategySelector,
    ZipBackupArchive,
)
from fastapi_app.services.backup.ports import (
    AdvisoryLock,
    ArchiveDecryptor,
    BackupArchive,
    CacheInvalidator,
    ComponentRestorePort,
    DatabaseRestoreStrategy,
    EngineLifecycle,
    ProgressReporter,
    RestoreVerifier,
    SafetyBackupProvider,
)
from fastapi_app.services.backup.strategies import JsonRestoreStrategy, PsqlRestoreStrategy
from fastapi_app.services.backup.types import (
    ComponentsRestoreResult,
    DatabaseRestoreResult,
    RestoreContext,
    RestoreManifest,
    RestoreOutcome,
    RestorePhase,
    RestoreStatus,
    VerificationResult,
)

__all__ = [
    # 编排器
    "DatabaseRestoreOrchestrator",
    "StrategySelector",
    "RestoreError",
    "ZipBackupArchive",
    # 策略
    "PsqlRestoreStrategy",
    "JsonRestoreStrategy",
    # 格式策略
    "BackupFormatStrategy",
    "DefaultBackupFormatStrategy",
    "BackupFormatError",
    "ZipBackupArchiveView",
    "BackupStorage",
    "LocalBackupStorage",
    "ArchiveEntry",
    "BackupArtifact",
    "BackupChunk",
    "BackupInfo",
    "PackOptions",
    "RestoredBackupArchive",
    "UnpackOptions",
    # 端口
    "AdvisoryLock",
    "ArchiveDecryptor",
    "BackupArchive",
    "CacheInvalidator",
    "ComponentRestorePort",
    "DatabaseRestoreStrategy",
    "EngineLifecycle",
    "ProgressReporter",
    "RestoreVerifier",
    "SafetyBackupProvider",
    # 类型
    "ComponentsRestoreResult",
    "DatabaseRestoreResult",
    "RestoreContext",
    "RestoreManifest",
    "RestoreOutcome",
    "RestorePhase",
    "RestoreStatus",
    "VerificationResult",
    # 适配器
    "BackupProgressReporterAdapter",
    "DefaultArchiveDecryptorAdapter",
    "ExistingCacheInvalidatorAdapter",
    "ExistingComponentRestoreAdapter",
    "ExistingEngineLifecycleAdapter",
    "ExistingRestoreVerifierAdapter",
    "ExistingSafetyBackupAdapter",
    "PostgresAdvisoryLockAdapter",
]
