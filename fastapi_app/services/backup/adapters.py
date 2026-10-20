"""数据库恢复生命周期的默认适配器实现。

这些实现复用包内各子模块函数（由原 backup_service.py 拆分而来），
便于逐步迁移。后续可将具体适配器替换为独立的实现。
"""

from __future__ import annotations

import io
import logging
import zipfile
from types import TracebackType
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.backup.ports import (
    ArchiveDecryptor,
    BackupArchive,
    CacheInvalidator,
    ComponentRestorePort,
    EngineLifecycle,
    ProgressReporter,
    RestoreVerifier,
    SafetyBackupProvider,
)
from fastapi_app.services.backup.types import ComponentsRestoreResult

logger = logging.getLogger(__name__)


class ExistingComponentRestoreAdapter(ComponentRestorePort):
    """复用现有 `restore_non_dependent_components` 的组件恢复适配器。"""

    async def restore(
        self,
        archive: BackupArchive,
        confirm_sensitive: bool,
        reporter: ProgressReporter | None,
    ) -> ComponentsRestoreResult:
        from fastapi_app.services.backup.restore import restore_non_dependent_components
        from fastapi_app.services.backup.types import RestorePhase

        if reporter is not None:
            await reporter.report(RestorePhase.RESTORE_COMPONENTS, 0.0, "开始恢复非依赖组件...")

        # 现有函数接受 zipfile.ZipFile，通过 raw_bytes 桥接
        with zipfile.ZipFile(io.BytesIO(archive.raw_bytes)) as zf:
            raw_result = await restore_non_dependent_components(
                zf,
                confirm_sensitive=confirm_sensitive,
            )

        if reporter is not None:
            await reporter.report(RestorePhase.RESTORE_COMPONENTS, 1.0, "非依赖组件恢复完成")

        return ComponentsRestoreResult(
            filestore=raw_result.get("filestore", {}),
            config=raw_result.get("config", {}),
            redis=raw_result.get("redis", {}),
            meilisearch=raw_result.get("meilisearch", {}),
            errors=raw_result.get("errors", []),
        )


class ExistingEngineLifecycleAdapter(EngineLifecycle):
    """复用现有数据库生命周期函数的适配器。"""

    async def dispose_engine(self) -> None:
        """关闭当前请求的数据库会话和全局引擎。"""
        from fastapi_app.core.database import _async_engine

        # 这里仅做 dispose；实际 psql 策略内部已处理 dispose。
        # 该端口主要为测试和后续重构预留。
        if _async_engine is not None:
            try:
                await _async_engine.dispose()
            except Exception as exc:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
                logger.warning("释放数据库引擎失败: %s", exc)

    async def rebuild_pool(self) -> None:
        from fastapi_app.core.database import rebuild_pool

        await rebuild_pool()

    async def new_session(self) -> AsyncSession:
        from fastapi_app.core.database import _AsyncSessionLocal

        if _AsyncSessionLocal is None:
            raise RuntimeError("数据库会话工厂未初始化")
        return _AsyncSessionLocal()


class ExistingCacheInvalidatorAdapter(CacheInvalidator):
    """复用现有缓存失效逻辑的适配器。"""

    async def invalidate_all(self) -> None:
        try:
            from fastapi_app.core.cache import CacheDomain, invalidate_related_caches

            await invalidate_related_caches(CacheDomain.ALL)
        except Exception as exc:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
            logger.warning("恢复后通用缓存清除失败: %s", exc)

        try:
            from fastapi_app.core.purchase_cache import invalidate_purchase_caches

            # 2026-08-24 审计修正: 该函数为协程，此前未 await 导致采购缓存从未真正失效
            await invalidate_purchase_caches()
        except Exception as exc:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
            logger.warning("恢复后采购缓存清除失败: %s", exc)


class ExistingRestoreVerifierAdapter(RestoreVerifier):
    """复用现有 `verify_restore` 的验证适配器。"""

    async def verify(
        self,
        db: AsyncSession,
        expected_tables: dict[str, dict[str, Any]],
        fingerprints: dict[str, Any] | None,
        schema_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from fastapi_app.services.backup.verify.core import verify_restore

        return await verify_restore(db, expected_tables, fingerprints, schema_snapshot)


class NoOpAdvisoryLockAdapter:
    """no-op 锁适配器（P1-3 接线用）。

    调用方（端点层）已持有 Redis 还原锁时注入本适配器，
    避免内核二次加锁导致死锁。
    """

    async def __aenter__(self) -> NoOpAdvisoryLockAdapter:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        return None


class NoOpSafetyBackupAdapter(SafetyBackupProvider):
    """no-op 安全备份适配器（P1-3 接线用）。

    调用方（端点层）已创建 pre-restore 安全备份时注入本适配器，
    避免内核重复执行一次全量备份。
    """

    async def create(self) -> dict[str, Any]:
        return {"success": True, "skipped": True, "reason": "endpoint-owned"}


class DefaultArchiveDecryptorAdapter(ArchiveDecryptor):
    """复用 `backup_encryption.decrypt_backup_auto` 的解密适配器。

    2026-10-17 审计 AUD-06：此前用 `decrypt_backup`——它只认 chunked-v1 magic
    与裸信封，**不剥离 4B meta 前缀**，旧 `/save` 产出的格式 B 密文会被当成
    裸信封解（salt/nonce 错位），正确密码被误报「密码错误」。auto 版本四格式
    全认（内部 `_strip_meta_prefix`）。
    """

    async def decrypt_if_needed(
        self,
        zip_bytes: bytes,
        password: str | None,
        manifest_encrypted: bool,
    ) -> bytes:
        from fastapi_app.core.backup_encryption import decrypt_backup_auto

        if not password:
            raise ValueError("备份文件已加密，需要提供解密密码")
        plaintext, _meta = decrypt_backup_auto(zip_bytes, password)
        return plaintext
