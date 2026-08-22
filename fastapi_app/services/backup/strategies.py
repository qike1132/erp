"""数据库恢复策略实现。

直接复用包内 `dump.restore_database_via_psql` 和
`json_backup.restore_database_from_json`（均由原 backup_service.py 拆分而来），
后续可逐步替换为独立实现。
"""

from __future__ import annotations

import contextlib
import io
import logging
import zipfile

from fastapi_app.services.backup.ports import (
    BackupArchive,
    DatabaseRestoreStrategy,
    EngineLifecycle,
    ProgressReporter,
)
from fastapi_app.services.backup.types import (
    DatabaseRestoreResult,
    RestoreManifest,
    RestorePhase,
)

logger = logging.getLogger(__name__)


class _PhaseReporter:
    """把策略内部进度映射到 orchestrator 阶段的辅助类。"""

    def __init__(self, reporter: ProgressReporter | None, phase: RestorePhase) -> None:
        self._reporter = reporter
        self._phase = phase

    async def report(self, sub: float, detail: str = "") -> None:
        if self._reporter is not None:
            await self._reporter.report(self._phase, sub, detail)


class PsqlRestoreStrategy(DatabaseRestoreStrategy):
    """通过 psql 恢复数据库的策略。"""

    @property
    def needs_pool_rebuild(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "psql"

    async def restore(
        self,
        archive: BackupArchive,
        manifest: RestoreManifest,
        engine_lifecycle: EngineLifecycle,
        reporter: ProgressReporter | None = None,
        task_id: str | None = None,
    ) -> DatabaseRestoreResult:
        from fastapi_app.services.backup.dump import restore_database_via_psql

        phase_reporter = _PhaseReporter(reporter, RestorePhase.RESTORE_DATABASE)

        # 旧函数需要 AsyncSession 和 zipfile.ZipFile；策略层通过端口获取会话，
        # 通过 raw_bytes 自行构造 ZipFile。TODO: 后续重写 psql 恢复时移除对旧函数的依赖。
        db = await engine_lifecycle.new_session()
        try:
            with zipfile.ZipFile(io.BytesIO(archive.raw_bytes)) as zf:
                raw_result = await restore_database_via_psql(
                    zf,
                    db,
                    task_id=task_id,
                )
        finally:
            try:
                await db.close()
            except Exception as exc:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
                logger.warning("psql 策略关闭临时会话失败: %s", exc)

        # 把旧函数的返回值转换为新结果对象
        result = DatabaseRestoreResult(
            status=raw_result.get("status", "error"),
            message=raw_result.get("message", raw_result.get("error", "")),
            errors=[raw_result["error"]] if "error" in raw_result else [],
            strategy=self.name,
            details={
                "needs_pool_rebuild": self.needs_pool_rebuild,
                "raw": raw_result,
            },
        )

        # 阶段进度报告
        await phase_reporter.report(
            1.0,
            f"psql 数据库恢复{'完成' if result.status != 'error' else '失败'}",  # sql-safe: escape_like/绑定参数/常量片段
        )
        return result


class JsonRestoreStrategy(DatabaseRestoreStrategy):
    """通过 JSON 恢复数据库的策略（Legacy JSON 备份）。"""

    @property
    def needs_pool_rebuild(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return "json"

    async def restore(
        self,
        archive: BackupArchive,
        manifest: RestoreManifest,
        engine_lifecycle: EngineLifecycle,
        reporter: ProgressReporter | None = None,
        task_id: str | None = None,
    ) -> DatabaseRestoreResult:
        from fastapi_app.services.backup.json_backup import restore_database_from_json

        phase_reporter = _PhaseReporter(reporter, RestorePhase.RESTORE_DATABASE)

        db = await engine_lifecycle.new_session()
        try:
            with zipfile.ZipFile(io.BytesIO(archive.raw_bytes)) as zf:
                raw_result = await restore_database_from_json(
                    zf,
                    db,
                    task_id=task_id,
                )
            # JSON 恢复后需要提交
            await db.commit()  # manual-tx: try/except 内显式事务控制
        except Exception as exc:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
            with contextlib.suppress(Exception):
                await db.rollback()  # manual-tx: try/except 内显式事务控制
            logger.exception("JSON 数据库恢复异常")
            return DatabaseRestoreResult(
                status="error",
                message=f"JSON 数据库恢复异常: {exc}",
                strategy=self.name,
                details={"needs_pool_rebuild": self.needs_pool_rebuild},
            )
        finally:
            try:
                await db.close()
            except Exception as exc:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
                logger.warning("JSON 策略关闭临时会话失败: %s", exc)

        result = DatabaseRestoreResult(
            status=raw_result.get("status", "error"),
            message=raw_result.get("message", ""),
            errors=raw_result.get("errors", []),
            strategy=self.name,
            details={
                "needs_pool_rebuild": self.needs_pool_rebuild,
                "total_inserted": raw_result.get("total_inserted"),
                "raw": raw_result,
            },
        )

        await phase_reporter.report(
            1.0,
            f"JSON 数据库恢复{'完成' if result.status != 'error' else '失败'}",
        )
        return result
