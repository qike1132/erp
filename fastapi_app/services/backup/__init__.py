"""备份服务包。

包含两类组件：
1. 原有新架构：数据库恢复生命周期相关类型与编排器（ports/adapters 模式）。
2. 从原 backup_service.py 拆分而来的 12 个子模块（加密/分块/快照/dump/JSON/文件存储/缓存恢复/验证/增量/编排/记录/异常）。

调用方统一从包根导入（原 backup_service.py 薄壳已在域收敛提交中删除）：
    from fastapi_app.services.backup import create_full_backup
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
from ._constants import *  # noqa: F403

# 显式导入常量（from ._constants import * 不包含下划线开头的名称）
from ._constants import (
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
from .cache_restore import *  # noqa: F403
from .chunks import *  # noqa: F403
from .crypto import *  # noqa: F403
from .dump import *  # noqa: F403
from .exceptions import *  # noqa: F403
from .filestore import *  # noqa: F403
from .json_backup import *  # noqa: F403
from .orchestration import *  # noqa: F403
from .records import *  # noqa: F403
from .settings_service import (
    BackupSettingsError,
    get_settings,
    save_settings,
    validate_path,
)
from .snapshot import *  # noqa: F403
from .verify import *  # noqa: F403

# P0 审计修正(2026-08-24): Redis 还原锁三件套必须放在所有星号导入之后——
# .verify 经星号导入会带入 query_service 的同名 advisory 版
# release_restore_lock(db)，曾遮蔽 Redis 版导致端点 finally TypeError。
# 注：本文件已在 ruff.toml 的 per-file-ignores 中关闭 I001，以保护此顺序不被 isort 打乱。
from .restore import (
    acquire_restore_lock,
    clear_stale_restore_lock,
    get_restore_lock_info,
    is_restore_in_progress,
    is_stale_restore_lock,
    release_restore_lock,
    renew_restore_lock,
    restore_from_zip,
    restore_non_dependent_components,
)

# 按模块分组排列（每组带说明注释），故意不做 isort 全局排序：
# 全局排序会把同模块的名字拆散、注释失去意义，而 __all__ 顺序无语义作用。
# ruff 亦将该修复标记为 unsafe（--unsafe-fixes 才会应用），故此处显式豁免。
__all__ = [  # noqa: RUF022
    "BACKUP_CHUNK_SIZE",
    # 常量
    "BACKUP_DIR",
    "BACKUP_ENCRYPTION_ENABLED",
    "BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED",
    "BACKUP_ENCRYPTION_KEY",
    "BACKUP_ENCRYPTION_PASSWORD",
    "BACKUP_FORMAT_VERSION",
    "BACKUP_LOCK_ID",
    "BACKUP_MAX_CHUNKS",
    "BACKUP_MAX_COUNT",
    "BACKUP_OPERATION_TIMEOUT",
    "BACKUP_RETENTION_DAYS",
    "CONFIG_DIR",
    "ENV_FILE",
    "MAX_BACKUP_FILE_SIZE",
    "MEILI_HOST",
    "MEILI_MASTER_KEY",
    "PRE_RESTORE_DIR",
    "PROJECT_ROOT",
    "REDIS_DUMP",
    "RESTORE_LOCK_ID",
    "UPLOADS_DIR",
    # 端口
    "AdvisoryLock",
    "ArchiveDecryptor",
    "ArchiveEntry",
    "BackupArchive",
    "BackupArtifact",
    "BackupChunk",
    # 异常（从原 backup_service.py 拆分）
    "BackupError",
    "BackupFileError",
    "BackupFormatError",
    # 格式策略
    "BackupFormatStrategy",
    "BackupInfo",
    "BackupLockError",
    # 适配器
    "BackupProgressReporterAdapter",
    "BackupStorage",
    "BinaryLogError",
    "CacheInvalidator",
    "ComponentRestorePort",
    # 类型
    "ComponentsRestoreResult",
    # 编排器（新架构）
    "DatabaseRestoreOrchestrator",
    "DatabaseRestoreResult",
    "DatabaseRestoreStrategy",
    "DatabaseSnapshotError",
    "DefaultArchiveDecryptorAdapter",
    "DefaultBackupFormatStrategy",
    "EngineLifecycle",
    "ExistingCacheInvalidatorAdapter",
    "ExistingComponentRestoreAdapter",
    "ExistingEngineLifecycleAdapter",
    "ExistingRestoreVerifierAdapter",
    "ExistingSafetyBackupAdapter",
    "JsonRestoreStrategy",
    "LocalBackupStorage",
    "PackOptions",
    "PostgresAdvisoryLockAdapter",
    "ProgressReporter",
    # 策略
    "PsqlRestoreStrategy",
    "RestoreContext",
    "RestoreError",
    "RestoreManifest",
    "RestoreOutcome",
    "RestorePhase",
    "RestoreStatus",
    "RestoreVerifier",
    "RestoredBackupArchive",
    "SafetyBackupProvider",
    "StrategySelector",
    "UnpackOptions",
    "VerificationResult",
    "ZipBackupArchive",
    "ZipBackupArchiveView",
    # settings_service (M1)
    "BackupSettingsError",
    "get_settings",
    "save_settings",
    "validate_path",
    # orchestration
    "acquire_backup_lock",
    "acquire_restore_lock",
    "build_column_type_map",
    "cleanup_pre_restore_backups",
    "clear_stale_restore_lock",
    "combine_backup_chunks",
    "create_backup_chunks",
    "create_binary_log_backup",
    "create_database_snapshot_backup",
    "create_full_backup",
    "create_full_backup_to_file",
    "create_pre_restore_backup",
    "delete_backup_file",
    "deserialize_value",
    # records
    "ensure_backup_dir",
    "ensure_pre_restore_dir",
    "execute_legacy_backup_to_bytes",
    "find_timestamp_column",
    "generate_encryption_key",
    "get_backup_encryption_password",
    "get_backup_status",
    "get_checksum_tables",
    "get_pg_version",
    "get_postgres_lsn",
    # snapshot
    "get_postgres_snapshot",
    "get_postgres_wal_info",
    "get_restore_lock_info",
    "is_restore_in_progress",
    "is_stale_restore_lock",
    "list_backup_files",
    "query_table_rows",
    # verify
    "quote_table",
    "release_backup_lock",
    "release_restore_lock",
    "renew_restore_lock",
    "restore_config",
    "restore_database_from_json",
    "restore_database_via_psql",
    "restore_database_via_psql_from_bytes",
    # filestore
    "restore_filestore",
    "restore_from_binary_log",
    "restore_from_chunks",
    "restore_from_zip",
    "restore_legacy_json",
    "restore_meilisearch",
    "restore_non_dependent_components",
    # cache_restore
    "restore_redis_rdb",
    # dump
    "run_pg_dump",
    # json_backup
    "serialize_value",
    "set_transaction_isolation_serializable",
    # crypto
    "sha256_bytes",
    "sha256_file",
    "should_exclude_file",
    # chunks
    "split_backup_into_chunks",
    "validate_backup_file",
    "verify_restore",
    "write_backup_meta_file",
    "write_backup_record",
    "sync_backup_records",
    # S4 备份完整性判据（状态不许默认成功）
    "STATUS_FAILED",
    "STATUS_PARTIAL",
    "STATUS_RUNNING",
    "STATUS_SUCCESS",
    "STATUS_UNKNOWN",
    "compose_remark",
    "evaluate_backup_completeness",
    # P1-2 表级备份范围校验
    "resolve_backup_table_scope",
]
