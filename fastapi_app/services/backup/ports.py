"""数据库恢复生命周期使用的端口（Protocol）。

所有基础设施依赖都通过端口注入，便于测试和替换实现。
"""

from __future__ import annotations

from typing import Any, BinaryIO, Protocol, Sequence
import zipfile

from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.backup.types import (
    ComponentsRestoreResult,
    DatabaseRestoreResult,
    RestoreManifest,
    RestorePhase,
)


class ProgressReporter(Protocol):
    """进度报告端口。"""

    async def report(self, phase: RestorePhase | str, sub: float, detail: str = "") -> None:
        """报告进度。

        Args:
            phase: 当前阶段名称或 RestorePhase 枚举。
            sub: 阶段内进度，0.0 ~ 1.0。
            detail: 进度详情描述。
        """
        ...


class BackupArchive(Protocol):
    """备份归档抽象端口。

    不暴露具体 ZIP/TAR 等实现类型，调用方只通过文件名进行读写。
    需要底层实现的适配器可通过 `raw_bytes` 自行构造。
    """

    @property
    def raw_bytes(self) -> bytes:
        """返回归档原始字节内容。"""
        ...

    def has(self, name: str) -> bool:
        """检查归档中是否包含指定文件。"""
        ...

    def read(self, name: str) -> bytes:
        """读取归档中指定文件的内容。"""
        ...

    def namelist(self) -> Sequence[str]:
        """返回归档中所有文件列表。"""
        ...


class AdvisoryLock(Protocol):
    """Advisory lock 端口，用作异步上下文管理器。"""

    async def __aenter__(self) -> AdvisoryLock:
        ...

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool | None:
        ...


class SafetyBackupProvider(Protocol):
    """恢复前安全备份提供者端口。"""

    async def create(self) -> dict[str, Any]:
        """创建当前数据的安全备份。失败时不应阻塞恢复，返回包含 error 的字典。"""
        ...


class DatabaseRestoreStrategy(Protocol):
    """数据库恢复策略端口。psql 和 JSON 两种路径分别实现此协议。"""

    @property
    def needs_pool_rebuild(self) -> bool:
        """执行此策略后是否需要重建数据库连接池。"""
        ...

    @property
    def name(self) -> str:
        """策略名称。"""
        ...

    async def restore(
        self,
        archive: BackupArchive,
        manifest: RestoreManifest,
        engine_lifecycle: EngineLifecycle,
        reporter: ProgressReporter | None = None,
        task_id: str | None = None,
    ) -> DatabaseRestoreResult:
        """执行数据库恢复。

        Args:
            archive: 备份归档。
            manifest: 备份清单。
            engine_lifecycle: 数据库连接池生命周期，用于获取新会话。
            reporter: 进度报告器。
            task_id: 任务 ID，用于底层进度上报。
        """
        ...


class EngineLifecycle(Protocol):
    """数据库连接池生命周期管理端口。"""

    async def dispose_engine(self) -> None:
        """关闭并释放当前应用的数据库引擎/连接池。"""
        ...

    async def rebuild_pool(self) -> None:
        """重建数据库连接池。"""
        ...

    async def new_session(self) -> AsyncSession:
        """创建一个新的数据库会话。"""
        ...


class ComponentRestorePort(Protocol):
    """非依赖组件恢复端口（文件存储、配置、Redis、MeiliSearch）。"""

    async def restore(
        self,
        archive: BackupArchive,
        confirm_sensitive: bool,
        reporter: ProgressReporter | None,
    ) -> ComponentsRestoreResult:
        """并行恢复所有非数据库组件。"""
        ...


class CacheInvalidator(Protocol):
    """缓存失效端口。"""

    async def invalidate_all(self) -> None:
        """失效所有应用缓存。"""
        ...


class RestoreVerifier(Protocol):
    """恢复后验证端口。"""

    async def verify(
        self,
        db: AsyncSession,
        expected_tables: dict[str, dict[str, Any]],
        fingerprints: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """执行恢复后数据完整性验证。"""
        ...


class ArchiveDecryptor(Protocol):
    """备份归档解密端口。"""

    async def decrypt_if_needed(
        self,
        zip_bytes: bytes,
        password: str | None,
        manifest_encrypted: bool,
    ) -> bytes:
        """如果需要则解密备份文件。"""
        ...
