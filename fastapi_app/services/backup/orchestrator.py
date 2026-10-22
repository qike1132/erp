"""数据库恢复生命周期编排器。

提供 `DatabaseRestoreOrchestrator` 作为恢复流程的唯一入口，
隐藏 advisory lock、安全备份、策略选择、连接池重建、缓存失效、
恢复后验证等复杂细节。
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import zipfile
from typing import Any

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

logger = logging.getLogger(__name__)


class _NoOpReporter:
    """空进度报告器，用于未提供 reporter 时。"""

    async def report(self, phase: RestorePhase | str, sub: float, detail: str = "") -> None:
        pass


class ZipBackupArchive:
    """基于 zipfile 的 BackupArchive 实现。"""

    def __init__(self, zip_bytes: bytes) -> None:
        self._zip_bytes = zip_bytes
        self._zf = zipfile.ZipFile(io.BytesIO(zip_bytes))

    @property
    def raw_bytes(self) -> bytes:
        return self._zip_bytes

    def has(self, name: str) -> bool:
        return name in self._zf.namelist()

    def read(self, name: str) -> bytes:
        return self._zf.read(name)

    def namelist(self) -> list[str]:
        return self._zf.namelist()


class DatabaseRestoreOrchestrator:
    """数据库恢复生命周期编排器。

    对外只暴露 `restore()` 一个方法，内部按阶段推进并记录 journal。
    所有基础设施依赖通过构造函数注入，便于测试和替换。
    """

    def __init__(
        self,
        *,
        lock: AdvisoryLock,
        safety_backup_provider: SafetyBackupProvider,
        strategy_selector: StrategySelector,
        engine_lifecycle: EngineLifecycle,
        component_restore: ComponentRestorePort,
        cache_invalidator: CacheInvalidator,
        verifier: RestoreVerifier,
        decryptor: ArchiveDecryptor | None = None,
    ) -> None:
        self._lock = lock
        self._safety_backup_provider = safety_backup_provider
        self._strategy_selector = strategy_selector
        self._engine_lifecycle = engine_lifecycle
        self._component_restore = component_restore
        self._cache_invalidator = cache_invalidator
        self._verifier = verifier
        self._decryptor = decryptor

    async def restore(
        self,
        zip_bytes: bytes,
        *,
        decrypt_password: str | None = None,
        confirm_sensitive: bool = False,
        reporter: ProgressReporter | None = None,
    ) -> RestoreOutcome:
        """执行完整的数据库恢复生命周期。

        Args:
            zip_bytes: 备份文件字节内容。
            decrypt_password: 解密密码，加密备份时必填。
            confirm_sensitive: 是否确认恢复敏感配置文件。
            reporter: 进度报告器。

        Returns:
            RestoreOutcome: 恢复结果，包含数据库、组件、验证、日志等信息。
        """
        ctx = RestoreContext(
            zip_bytes=zip_bytes,
            decrypt_password=decrypt_password,
            task_id=None,
            confirm_sensitive=confirm_sensitive,
            reporter=reporter,
        )
        outcome = RestoreOutcome(
            status=RestoreStatus.OK,
            phase=RestorePhase.COMPLETED,
            message="恢复完成",
        )
        reporter = reporter or _NoOpReporter()

        try:
            async with self._lock:
                # 阶段 1：恢复前安全备份
                outcome.pre_restore_backup = await self._create_safety_backup(ctx, reporter)

                # 阶段 2：打开并验证归档
                archive, manifest = await self._open_and_validate_archive(ctx, reporter)
                outcome.manifest = ctx.runtime.get("manifest_dict", {})

                # 阶段 3：数据库恢复（psql 或 JSON 策略）
                outcome.database = await self._restore_database(ctx, archive, manifest, reporter)
                if outcome.database.status == "error":
                    raise RestoreError(f"数据库恢复失败: {outcome.database.message}")

                # 阶段 4：非依赖组件恢复
                outcome.components = await self._restore_components(ctx, archive, reporter)

                # 阶段 5：重建连接池（仅 psql 策略需要）
                await self._rebuild_pool_if_needed(ctx, outcome.database, reporter)

                # 自愈只读角色授权：psql/JSON 恢复会重建表或重放备份，导致 erp_readonly 的
                # SELECT 授权被清空（只读接口 500）。置于连接池重建之后，确保拿到全新连接
                # 而非指向被恢复库的陈旧连接。此处幂等补授，失败仅记录、不中断恢复主流程。
                try:
                    from fastapi_app.services.backup.ro_grants import ensure_readonly_grants
                    if await ensure_readonly_grants():
                        logger.warning("恢复完成后已自愈只读角色 %s 权限", "erp_readonly")
                except Exception as exc:  # broad-except: 自愈为尽力而为，不影响恢复结果
                    logger.warning("恢复后只读授权自愈失败（可忽略）: %s", exc)

                # 阶段 6：缓存失效
                await self._invalidate_caches(ctx, reporter)

                # 阶段 7：恢复后验证
                outcome.verification = await self._verify(ctx, manifest, reporter)

                outcome.status = self._derive_status(outcome)
                outcome.phase = RestorePhase.COMPLETED
                outcome.message = self._build_completion_message(outcome)
                outcome.journal = ctx.journal

        except RestoreError as exc:
            outcome.status = RestoreStatus.ERROR
            outcome.phase = RestorePhase.FAILED
            outcome.message = str(exc)
            outcome.errors.append(str(exc))
            outcome.journal = ctx.journal
            logger.error("恢复失败: %s", exc)
        except Exception as exc:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
            outcome.status = RestoreStatus.ERROR
            outcome.phase = RestorePhase.FAILED
            outcome.message = f"恢复过程中发生意外错误: {exc}"
            outcome.errors.append(str(exc))
            outcome.journal = ctx.journal
            logger.exception("恢复过程中发生意外错误")

        return outcome

    async def _create_safety_backup(
        self,
        ctx: RestoreContext,
        reporter: ProgressReporter,
    ) -> dict[str, Any]:
        """阶段 1：创建恢复前安全备份。"""
        await reporter.report(RestorePhase.PRE_RESTORE_BACKUP, 0.0, "创建恢复前安全备份...")
        try:
            result = await self._safety_backup_provider.create()
            ctx.log(RestorePhase.PRE_RESTORE_BACKUP, "create", True, str(result.get("filename", "")))
            await reporter.report(RestorePhase.PRE_RESTORE_BACKUP, 1.0, "安全备份创建完成")
            return result
        except Exception as exc:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
            ctx.log(RestorePhase.PRE_RESTORE_BACKUP, "create", False, str(exc))
            await reporter.report(RestorePhase.PRE_RESTORE_BACKUP, 1.0, f"安全备份创建失败: {exc}")
            logger.warning("恢复前安全备份创建失败（不阻塞恢复）: %s", exc)
            return {"success": False, "error": str(exc)}

    async def _open_and_validate_archive(
        self,
        ctx: RestoreContext,
        reporter: ProgressReporter,
    ) -> tuple[BackupArchive, RestoreManifest]:
        """阶段 2：解密、打开归档并解析 manifest。"""
        await reporter.report(RestorePhase.DECRYPT_ARCHIVE, 0.0, "读取备份文件...")

        raw_bytes, manifest_dict = await self._decrypt_and_read_manifest(ctx)
        archive: BackupArchive = ZipBackupArchive(raw_bytes)
        manifest = RestoreManifest(
            version=manifest_dict.get("version"),
            exported_at=manifest_dict.get("exported_at"),
            exported_by=manifest_dict.get("exported_by"),
            remark=manifest_dict.get("remark", ""),
            tables=manifest_dict.get("tables", {}),
            fingerprints=manifest_dict.get("fingerprints"),
            checksums=manifest_dict.get("checksums", {}),
            encrypted=manifest_dict.get("encrypted", False),
            schema_snapshot=manifest_dict.get("schema_snapshot"),
        )

        # 校验数据库文件 checksum
        await self._validate_database_checksums(archive, manifest, ctx)

        ctx.runtime["archive_bytes"] = raw_bytes
        ctx.runtime["manifest_dict"] = manifest_dict
        ctx.log(RestorePhase.DECRYPT_ARCHIVE, "open_and_validate", True, f"manifest version={manifest.version}")
        await reporter.report(RestorePhase.DECRYPT_ARCHIVE, 1.0, "备份文件读取完成")
        return archive, manifest

    async def _decrypt_and_read_manifest(
        self,
        ctx: RestoreContext,
    ) -> tuple[bytes, dict[str, Any]]:
        """尝试读取 manifest，必要时解密。返回 (原始字节, manifest 字典)。"""
        raw_bytes = ctx.zip_bytes
        manifest_dict = self._try_read_manifest(raw_bytes)

        needs_decrypt = manifest_dict is None or manifest_dict.get("encrypted")
        if needs_decrypt:
            if not ctx.decrypt_password:
                raise RestoreError("备份文件已加密或无效，需要提供解密密码")
            raw_bytes = await self._decrypt(raw_bytes, ctx.decrypt_password)
            manifest_dict = self._try_read_manifest(raw_bytes)
            if manifest_dict is None:
                raise RestoreError("解密后仍无法读取备份文件")

        # needs_decrypt 为假时 manifest_dict 必然非 None；为真时上面已判空并抛错。
        assert manifest_dict is not None  # noqa: S101
        return raw_bytes, manifest_dict

    def _try_read_manifest(self, data: bytes) -> dict[str, Any] | None:
        """尝试从字节中读取 manifest.json，失败返回 None。"""
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if "manifest.json" not in zf.namelist():
                    return None
                return json.loads(zf.read("manifest.json"))
        except (zipfile.BadZipFile, ValueError, KeyError):
            return None

    async def _decrypt(self, data: bytes, password: str) -> bytes:
        """如果需要则使用注入的 decryptor 解密。"""
        if self._decryptor is not None:
            return await self._decryptor.decrypt_if_needed(data, password, True)
        # 默认回退：整包解密是 CPU 密集操作，下沉线程池
        from fastapi_app.core.backup_encryption import decrypt_backup

        return await asyncio.to_thread(decrypt_backup, data, password)

    async def _validate_database_checksums(
        self,
        archive: BackupArchive,
        manifest: RestoreManifest,
        ctx: RestoreContext,
    ) -> None:
        """校验备份中数据库文件的 checksum。不匹配时抛出 RestoreError。"""
        from fastapi_app.services.backup.crypto import sha256_bytes

        for db_file in ("database/dump.sql.gz", "database/dump.json"):
            expected = manifest.checksums.get(db_file)
            if expected and archive.has(db_file):
                actual = sha256_bytes(archive.read(db_file))
                if actual != expected:
                    msg = f"{db_file} 校验和不匹配"
                    ctx.log(RestorePhase.DECRYPT_ARCHIVE, "checksum_validate", False, msg)
                    logger.error(msg)
                    raise RestoreError(msg)

    async def _restore_database(
        self,
        ctx: RestoreContext,
        archive: BackupArchive,
        manifest: RestoreManifest,
        reporter: ProgressReporter,
    ) -> DatabaseRestoreResult:
        """阶段 3：选择并执行数据库恢复策略。"""
        await reporter.report(RestorePhase.RESTORE_DATABASE, 0.0, "准备恢复数据库...")
        strategy = self._strategy_selector.select(archive)
        ctx.runtime["strategy"] = strategy.name
        ctx.runtime["needs_pool_rebuild"] = strategy.needs_pool_rebuild

        try:
            result = await strategy.restore(
                archive,
                manifest,
                self._engine_lifecycle,
                reporter=reporter,
                task_id=ctx.task_id,
            )
            ctx.log(
                RestorePhase.RESTORE_DATABASE,
                "restore",
                result.status != "error",
                f"strategy={strategy.name}, status={result.status}",
            )
            await reporter.report(
                RestorePhase.RESTORE_DATABASE,
                1.0,
                f"数据库恢复完成（{strategy.name}, {result.status}）",
            )
            return result
        except Exception as exc:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
            ctx.log(RestorePhase.RESTORE_DATABASE, "restore", False, str(exc))
            await reporter.report(RestorePhase.RESTORE_DATABASE, 1.0, f"数据库恢复异常: {exc}")
            logger.exception("数据库恢复异常")
            return DatabaseRestoreResult(
                status="error",
                message=f"数据库恢复异常: {exc}",
                strategy=strategy.name,
            )

    async def _restore_components(
        self,
        ctx: RestoreContext,
        archive: BackupArchive,
        reporter: ProgressReporter,
    ) -> ComponentsRestoreResult:
        """阶段 4：恢复非依赖组件。"""
        await reporter.report(RestorePhase.RESTORE_COMPONENTS, 0.0, "准备恢复非依赖组件...")
        try:
            result = await self._component_restore.restore(
                archive,
                ctx.confirm_sensitive,
                reporter,
            )
            ctx.log(
                RestorePhase.RESTORE_COMPONENTS,
                "restore",
                not result.errors,
                f"errors={len(result.errors)}",
            )
            await reporter.report(RestorePhase.RESTORE_COMPONENTS, 1.0, "非依赖组件恢复完成")
            return result
        except Exception as exc:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
            ctx.log(RestorePhase.RESTORE_COMPONENTS, "restore", False, str(exc))
            await reporter.report(RestorePhase.RESTORE_COMPONENTS, 1.0, f"非依赖组件恢复异常: {exc}")
            logger.exception("非依赖组件恢复异常")
            return ComponentsRestoreResult(errors=[str(exc)])

    async def _rebuild_pool_if_needed(
        self,
        ctx: RestoreContext,
        db_result: DatabaseRestoreResult,
        reporter: ProgressReporter,
    ) -> None:
        """阶段 5：psql 策略后重建连接池。"""
        if not db_result.details.get("needs_pool_rebuild", False):
            ctx.log(RestorePhase.REBUILD_POOL, "skip", True, "JSON 策略无需重建连接池")
            return

        await reporter.report(RestorePhase.REBUILD_POOL, 0.0, "重建数据库连接池...")
        try:
            await self._engine_lifecycle.rebuild_pool()
            ctx.log(RestorePhase.REBUILD_POOL, "rebuild", True, "连接池重建成功")
            await reporter.report(RestorePhase.REBUILD_POOL, 1.0, "连接池重建完成")
        except Exception as exc:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
            ctx.log(RestorePhase.REBUILD_POOL, "rebuild", False, str(exc))
            await reporter.report(RestorePhase.REBUILD_POOL, 1.0, f"连接池重建失败: {exc}")
            raise RestoreError(f"数据库连接池重建失败: {exc}") from exc

    async def _invalidate_caches(
        self,
        ctx: RestoreContext,
        reporter: ProgressReporter,
    ) -> None:
        """阶段 6：失效应用缓存。"""
        await reporter.report(RestorePhase.INVALIDATE_CACHES, 0.0, "清理应用缓存...")
        try:
            await self._cache_invalidator.invalidate_all()
            ctx.log(RestorePhase.INVALIDATE_CACHES, "invalidate", True, "缓存清理完成")
            await reporter.report(RestorePhase.INVALIDATE_CACHES, 1.0, "缓存清理完成")
        except Exception as exc:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
            ctx.log(RestorePhase.INVALIDATE_CACHES, "invalidate", False, str(exc))
            await reporter.report(RestorePhase.INVALIDATE_CACHES, 1.0, f"缓存清理失败: {exc}")
            logger.warning("恢复后缓存失效失败: %s", exc)

    async def _verify(
        self,
        ctx: RestoreContext,
        manifest: RestoreManifest,
        reporter: ProgressReporter,
    ) -> VerificationResult:
        """阶段 7：恢复后数据完整性验证。"""
        await reporter.report(RestorePhase.VERIFY, 0.0, "数据完整性验证中...")
        try:
            db = await self._engine_lifecycle.new_session()
            try:
                # JSON 策略：值经 JSON 序列化往返，COALESCE(col::text) 精确定文本
                # 表示（float/JSON 格式化/timestamptz/字节等）已改变，L2 指纹必然
                # 假阴性；退化为跳过 L2（match=None 不计 mismatch），overall_pass
                # 依赖真实可验证的 L1 行数 + L4 表结构。psql 策略（二进制精确）仍完整校验 L2。
                strategy = ctx.runtime.get("strategy")
                fingerprints = None if strategy == "json" else manifest.fingerprints
                verify_dict = await self._verifier.verify(
                    db,
                    manifest.tables,
                    fingerprints,
                    manifest.schema_snapshot,
                )
                _known_keys = {
                    "overall_pass", "l0_global_checksum", "l1_row_count",
                    "l2_fingerprint", "l3_id_sampling",
                }
                verification = VerificationResult(
                    overall_pass=verify_dict.get("overall_pass", False),
                    l0_global_checksum=verify_dict.get("l0_global_checksum", {}),
                    l1_row_count=verify_dict.get("l1_row_count", {}),
                    l2_fingerprint=verify_dict.get("l2_fingerprint", {}),
                    l3_id_sampling=verify_dict.get("l3_id_sampling", {}),
                    extras={k: v for k, v in verify_dict.items() if k not in _known_keys},
                )
                ctx.log(
                    RestorePhase.VERIFY,
                    "verify",
                    verification.overall_pass,
                    f"overall_pass={verification.overall_pass}",
                )
                await reporter.report(
                    RestorePhase.VERIFY,
                    1.0,
                    "验证完成" if verification.overall_pass else "验证未通过",
                )
                return verification
            finally:
                await db.close()
        except Exception as exc:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
            ctx.log(RestorePhase.VERIFY, "verify", False, str(exc))
            await reporter.report(RestorePhase.VERIFY, 1.0, f"验证异常: {exc}")
            logger.warning("恢复后验证失败: %s", exc)
            return VerificationResult(error=str(exc))

    def _derive_status(self, outcome: RestoreOutcome) -> RestoreStatus:
        """根据各阶段结果推导最终状态。"""
        if outcome.database.status == "error":
            return RestoreStatus.ERROR
        if outcome.verification.error or not outcome.verification.overall_pass:
            return RestoreStatus.PARTIAL
        if outcome.components.errors:
            return RestoreStatus.PARTIAL
        if outcome.database.status == "partial":
            return RestoreStatus.PARTIAL
        return RestoreStatus.OK

    def _build_completion_message(self, outcome: RestoreOutcome) -> str:
        """生成完成消息。"""
        if outcome.status == RestoreStatus.OK:
            return "恢复完成"
        if outcome.status == RestoreStatus.PARTIAL:
            parts = []
            if outcome.components.errors:
                parts.append("组件恢复存在错误")
            if outcome.verification.error:
                parts.append("验证异常")
            elif not outcome.verification.overall_pass:
                parts.append("验证未通过")
            return "恢复完成（有警告）: " + "; ".join(parts)
        return outcome.message


class StrategySelector:
    """根据备份归档内容选择数据库恢复策略。"""

    def __init__(
        self,
        psql_strategy: DatabaseRestoreStrategy,
        json_strategy: DatabaseRestoreStrategy,
    ) -> None:
        self._psql_strategy = psql_strategy
        self._json_strategy = json_strategy

    def select(self, archive: BackupArchive) -> DatabaseRestoreStrategy:
        """优先选择 psql 策略，否则选择 JSON 策略。"""
        if archive.has("database/dump.sql.gz"):
            return self._psql_strategy
        if archive.has("database/dump.json"):
            return self._json_strategy
        raise RestoreError("备份文件中未找到数据库导出（dump.sql.gz 或 dump.json）")


class RestoreError(Exception):
    """恢复过程中的业务错误。"""
