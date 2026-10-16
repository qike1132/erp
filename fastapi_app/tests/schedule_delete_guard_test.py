"""备份调度删除守卫：校验类任务的最后一条启用行不许删。

背景（两次实测的生产漂移）
--------------------------
2026-10-12 与 2026-10-16 两次直连生产库 `SELECT ... FROM backup_schedule` 都只剩
**2 行**（full + cleanup）：备份完整性巡检 `integrity_check` 与月度灾备演练
`disaster_recovery_test` 均不在表中。AGENTS.md 记的备份调度缺口即此。

删除路径只有 UI 的 `DELETE /backup/schedule/{id}`（endpoints/backup/records.py），
`schedule_service.delete_schedule` 原先**无任何保护** —— 一次误点就静默失去
「备份到底能不能还原」的自动校验，且没有任何告警，只能靠人想起来手工跑
（`tasks/backup_tasks.py:_do_integrity_check` 的 docstring 原话）。

本文件锁住守卫行为：删这类任务必须被拒，且**不能留下半删状态**。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services.backup import schedule_service
from fastapi_app.services.backup.schedule_service import (
    BackupSettingsError,
    delete_schedule,
)
from fastapi_app.shared_models.backup_schedule import BackupSchedule

_GUARDED = schedule_service.GUARDED_TASK_TYPES


def _row(row_id: int, task_type: str, *, enabled: bool = True, name: str = '') -> BackupSchedule:
    r = BackupSchedule()
    r.id = row_id
    r.task_type = task_type
    r.enabled = enabled
    r.name = name or task_type
    return r


def _db(target: BackupSchedule | None):
    db = MagicMock()
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=target)
    return db


def _only(monkeypatch, *rows: BackupSchedule) -> None:
    """让 list_schedules 返回固定行集（守卫靠它数「同类型的其他启用行」）。"""
    monkeypatch.setattr(schedule_service, 'list_schedules', AsyncMock(return_value=list(rows)))


class TestGuardedTypesAreProtected:
    @pytest.mark.parametrize('task_type', _GUARDED)
    @pytest.mark.asyncio
    async def test_last_enabled_row_rejected(self, monkeypatch, task_type):
        """删掉该类型的最后一条启用行 → 必须拒绝。"""
        target = _row(7, task_type)
        db = _db(target)
        _only(monkeypatch, target)

        with pytest.raises(BackupSettingsError) as ei:
            await delete_schedule(db, 7)

        assert '不允许删除' in str(ei.value)
        # 关键：拒绝时必须**没有**执行删除，否则是半删状态
        db.delete.assert_not_awaited()

    @pytest.mark.parametrize('task_type', _GUARDED)
    @pytest.mark.asyncio
    async def test_rejected_even_when_other_rows_of_same_type_exist(
        self, monkeypatch, task_type
    ):
        """即使同类型还有别的行，校验类任务仍整类禁止删除。

        口径：这类任务的意义是「校验备份可用性」而非「某条备份计划」，一旦有人
        从界面清掉它们，备份损坏将完全静默。所以不采用「留一条就行」的宽松口径。
        """
        target = _row(7, task_type)
        other = _row(8, task_type)
        db = _db(target)
        _only(monkeypatch, target, other)

        with pytest.raises(BackupSettingsError):
            await delete_schedule(db, 7)
        db.delete.assert_not_awaited()

    @pytest.mark.parametrize('task_type', _GUARDED)
    @pytest.mark.asyncio
    async def test_rejected_even_when_disabled(self, monkeypatch, task_type):
        """已禁用的行也拒绝删除 —— 否则运维会「先禁用、再删除」绕过守卫。"""
        target = _row(7, task_type, enabled=False)
        db = _db(target)
        _only(monkeypatch, target)

        with pytest.raises(BackupSettingsError):
            await delete_schedule(db, 7)
        db.delete.assert_not_awaited()

    @pytest.mark.parametrize('task_type', _GUARDED)
    @pytest.mark.asyncio
    async def test_renaming_does_not_bypass_guard(self, monkeypatch, task_type):
        """改名绕不过守卫 —— 匹配键是 task_type，不是 name。

        迁移 057 的教训：056 按 name 匹配被运维改名绕过，未命中。
        """
        target = _row(7, task_type, name='随便改个名')
        db = _db(target)
        _only(monkeypatch, target)

        with pytest.raises(BackupSettingsError):
            await delete_schedule(db, 7)
        db.delete.assert_not_awaited()


class TestNonGuardedTypesStillDeletable:
    @pytest.mark.parametrize('task_type', ['full', 'cleanup', 'incremental'])
    @pytest.mark.asyncio
    async def test_normal_schedule_deletes(self, monkeypatch, task_type):
        """非守卫类照常可删 —— 守卫不能把正常运维堵死。"""
        target = _row(3, task_type)
        db = _db(target)
        _only(monkeypatch, target)

        assert await delete_schedule(db, 3) is True
        db.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_guarded_row_deletable_after_type_reassigned(self, monkeypatch):
        """把行改成非守卫类型后即可删除（运维的正规出路：先改类型再删）。"""
        target = _row(7, 'integrity_check')
        target.task_type = 'full'
        db = _db(target)
        _only(monkeypatch, target)

        assert await delete_schedule(db, 7) is True
        db.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_row_returns_false(self, monkeypatch):
        """不存在的 id 返回 False（端点据此 404），不抛守卫错。"""
        db = _db(None)
        _only(monkeypatch)

        assert await delete_schedule(db, 999) is False
        db.delete.assert_not_awaited()


class TestGuardConstantShape:
    def test_guarded_types_are_known_task_types(self):
        """守卫常量必须落在 TASK_TYPE_TO_FUNC 里，否则拼错永不生效。"""
        for t in _GUARDED:
            assert t in schedule_service.TASK_TYPE_TO_FUNC, t

    def test_full_is_not_guarded(self):
        """每日全量备份必须可删（守卫若堵住它，磁盘满时运维无法自救）。"""
        assert 'full' not in _GUARDED
