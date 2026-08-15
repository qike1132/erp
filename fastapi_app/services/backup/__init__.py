"""备份服务包。

包含两类组件：
1. 原有新架构：数据库恢复生命周期相关类型与编排器（ports/adapters 模式）。
2. 从原 backup_service.py 拆分而来的 12 个子模块（加密/分块/快照/dump/JSON/文件存储/缓存恢复/验证/增量/编排/记录/异常）。

通过重新导出保持调用方兼容：
    from fastapi_app.services.backup_service import create_full_backup
    from fastapi_app.services.backup import create_full_backup
两者均可工作。
"""

# ---------------------------------------------------------------------------
# 新架构（ports/adapters 模式）— 原有导出保持不变
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# 从原 backup_service.py 拆分的子模块
# ---------------------------------------------------------------------------
from ._constants import *  # noqa: F401,F403
from .exceptions import *  # noqa: F401,F403
from .crypto import *  # noqa: F401,F403
from .verify import *  # noqa: F401,F403
from .chunks import *  # noqa: F401,F403
from .snapshot import *  # noqa: F401,F403
from .dump import *  # noqa: F401,F403
from .json_backup import *  # noqa: F401,F403
from .filestore import *  # noqa: F401,F403
from .cache_restore import *  # noqa: F401,F403
from .records import *  # noqa: F401,F403
from .incremental import *  # noqa: F401,F403
from .orchestration import *  # noqa: F401,F403
from .restore import (  # noqa: F401
    restore_non_dependent_components,
    restore_from_zip,
    acquire_restore_lock,
    release_restore_lock,
    is_restore_in_progress,
)

# 显式导入常量（from ._constants import * 不包含下划线开头的名称）
from ._constants import (  # noqa: F401
    BACKUP_CHUNK_SIZE,
    BACKUP_DIR,
    BACKUP_ENCRYPTION_ENABLED,
    BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED,
    BACKUP_ENCRYPTION_KEY,
    BACKUP_ENCRYPTION_PASSWORD,
    BACKUP_FORMAT_VERSION,
    BACKUP_LOCK_ID,
    BACKUP_MAX_CHUNKS,
    BACKUP_MAX_COUNT,
    BACKUP_OPERATION_TIMEOUT,
    BACKUP_RETENTION_DAYS,
    CONFIG_DIR,
    ENV_FILE,
    MAX_BACKUP_FILE_SIZE,
    MEILI_HOST,
    MEILI_MASTER_KEY,
    PRE_RESTORE_DIR,
    PROJECT_ROOT,
    REDIS_DUMP,
    RESTORE_LOCK_ID,
    UPLOADS_DIR,
)

__all__ = [
    # 编排器（新架构）
    "DatabaseRestoreOrchestrator",
    "StrategySelector",
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
    # 异常（从原 backup_service.py 拆分）
    "BackupError",
    "BackupLockError",
    "BackupFileError",
    "DatabaseSnapshotError",
    "BinaryLogError",
    "RestoreError",
    # 常量
    "BACKUP_DIR",
    "MAX_BACKUP_FILE_SIZE",
    "RESTORE_LOCK_ID",
    "BACKUP_LOCK_ID",
    "BACKUP_OPERATION_TIMEOUT",
    "PROJECT_ROOT",
    "UPLOADS_DIR",
    "CONFIG_DIR",
    "ENV_FILE",
    "REDIS_DUMP",
    "MEILI_HOST",
    "MEILI_MASTER_KEY",
    "BACKUP_FORMAT_VERSION",
    "PRE_RESTORE_DIR",
    "BACKUP_ENCRYPTION_ENABLED",
    "BACKUP_ENCRYPTION_PASSWORD",
    "BACKUP_ENCRYPTION_KEY",
    "BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED",
    "BACKUP_CHUNK_SIZE",
    "BACKUP_MAX_CHUNKS",
    "BACKUP_RETENTION_DAYS",
    "BACKUP_MAX_COUNT",
    # crypto
    "sha256_bytes",
    "sha256_file",
    "generate_encryption_key",
    "get_backup_encryption_password",
    # verify
    "quote_table",
    "get_checksum_tables",
    "find_timestamp_column",
    "query_table_rows",
    "find_last_backup_timestamp",
    "verify_restore",
    # chunks
    "split_backup_into_chunks",
    "combine_backup_chunks",
    "create_backup_chunks",
    "restore_from_chunks",
    # snapshot
    "get_postgres_snapshot",
    "set_transaction_isolation_serializable",
    "create_database_snapshot_backup",
    "get_postgres_lsn",
    "get_postgres_wal_info",
    "create_binary_log_backup",
    "restore_from_binary_log",
    "get_pg_version",
    # dump
    "run_pg_dump",
    "restore_database_via_psql",
    "restore_database_via_psql_from_bytes",
    # json_backup
    "serialize_value",
    "build_column_type_map",
    "deserialize_value",
    "execute_legacy_backup_to_bytes",
    "restore_database_from_json",
    "restore_legacy_json",
    # filestore
    "restore_filestore",
    "restore_config",
    "should_exclude_file",
    # cache_restore
    "restore_redis_rdb",
    "restore_meilisearch",
    # records
    "ensure_backup_dir",
    "ensure_pre_restore_dir",
    "write_backup_record",
    "list_backup_files",
    "get_backup_status",
    "validate_backup_file",
    "delete_backup_file",
    "cleanup_old_backups",
    "cleanup_pre_restore_backups",
    # incremental
    "create_incremental_backup",
    "create_wal_incremental_backup",
    "restore_incremental",
    # orchestration
    "acquire_backup_lock",
    "release_backup_lock",
    "create_full_backup",
    "create_full_backup_to_file",
    "create_pre_restore_backup",
    "restore_non_dependent_components",
    "restore_from_zip",
    "acquire_restore_lock",
    "release_restore_lock",
    "is_restore_in_progress",
]