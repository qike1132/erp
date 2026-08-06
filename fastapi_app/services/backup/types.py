"""数据库恢复生命周期中的值对象与枚举。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class RestorePhase(Enum):
    """恢复过程中的主要阶段，用于日志、进度和可观测性。"""

    ACQUIRE_LOCK = "acquire_lock"
    PRE_RESTORE_BACKUP = "pre_restore_backup"
    DECRYPT_ARCHIVE = "decrypt_archive"
    RESTORE_DATABASE = "restore_database"
    RESTORE_COMPONENTS = "restore_components"
    REBUILD_POOL = "rebuild_pool"
    INVALIDATE_CACHES = "invalidate_caches"
    VERIFY = "verify"
    COMPLETED = "completed"
    FAILED = "failed"


class RestoreStatus(Enum):
    """恢复结果状态。"""

    OK = "ok"
    PARTIAL = "partial"
    ERROR = "error"


@dataclass(frozen=True)
class RestoreManifest:
    """从备份 manifest.json 解析出的关键信息。"""

    version: str | None
    exported_at: str | None
    exported_by: str | None
    remark: str
    tables: dict[str, dict[str, Any]]
    fingerprints: dict[str, Any] | None
    checksums: dict[str, str]
    encrypted: bool


@dataclass
class DatabaseRestoreResult:
    """数据库恢复策略返回的结果。"""

    status: str
    message: str
    errors: list[str] = field(default_factory=list)
    strategy: str = "unknown"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ComponentsRestoreResult:
    """非依赖组件恢复结果。"""

    filestore: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    redis: dict[str, Any] = field(default_factory=dict)
    meilisearch: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class VerificationResult:
    """恢复后验证结果。"""

    overall_pass: bool = False
    l0_global_checksum: dict[str, Any] = field(default_factory=dict)
    l1_row_count: dict[str, Any] = field(default_factory=dict)
    l2_fingerprint: dict[str, Any] = field(default_factory=dict)
    l3_id_sampling: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class RestoreOutcome:
    """整个恢复生命周期的最终结果。"""

    status: RestoreStatus
    phase: RestorePhase
    message: str
    database: DatabaseRestoreResult = field(default_factory=lambda: DatabaseRestoreResult(status="unknown", message=""))
    components: ComponentsRestoreResult = field(default_factory=ComponentsRestoreResult)
    verification: VerificationResult = field(default_factory=VerificationResult)
    pre_restore_backup: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    journal: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RestoreContext:
    """恢复执行期间的运行时上下文。"""

    zip_bytes: bytes
    decrypt_password: str | None
    task_id: str | None
    confirm_sensitive: bool
    reporter: Any | None = None
    journal: list[dict[str, Any]] = field(default_factory=list)
    runtime: dict[str, Any] = field(default_factory=dict)

    def log(self, phase: RestorePhase, action: str, success: bool, detail: str = "") -> None:
        """记录阶段日志。"""
        self.journal.append(
            {
                "phase": phase.value,
                "action": action,
                "success": success,
                "detail": detail,
            }
        )
