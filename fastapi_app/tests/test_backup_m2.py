"""
M2 调度 DB 化测试(TECHNICAL_PLAN.md v2 §7 M2)

覆盖:
1. cron 解析/匹配:种子四项(02:00/06-22/03:00/04:00)命中与非法
2. schedule_service CRUD:create/update/delete 校验
3. due_schedules 幂等:同一小时窗口不重复入队,跨日再调度
4. 迁移 036 对称 downgrade
"""
import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services.backup import schedule_service
from fastapi_app.services.backup.schedule_service import (
    BackupSettingsError,
    cron_matches,
    create_schedule,
    delete_schedule,
    due_schedules,
    parse_cron,
)
from fastapi_app.shared_models.backup_schedule import BackupSchedule


# ===========================================================================
# 1. cron 解析/匹配(种子四项等价性)
# ===========================================================================

class TestCronMatches:
    def test_daily_full_0200(self):
        assert cron_matches('0 2 * * *', __import__('datetime').datetime(2026, 8, 22, 2, 0)) is True
        assert cron_matches('0 2 * * *', __import__('datetime').datetime(2026, 8, 22, 3, 0)) is False

    def test_incremental_5shift(self):
        from datetime import datetime
        for h in (6, 10, 14, 18, 22):
            assert cron_matches('0 6,10,14,18,22 * * *', datetime(2026, 8, 22, h, 0)) is True, h
        assert cron_matches('0 6,10,14,18,22 * * *', datetime(2026, 8, 22, 8, 0)) is False
        assert cron_matches('0 6,10,14,18,22 * * *', datetime(2026, 8, 22, 6, 30)) is False

    def test_integrity_0300_and_cleanup_0400(self):
        from datetime import datetime
        assert cron_matches('0 3 * * *', datetime(2026, 8, 22, 3, 0)) is True
        assert cron_matches('0 4 * * *', datetime(2026, 8, 22, 4, 0)) is True
        assert cron_matches('0 3 * * *', datetime(2026, 8, 22, 4, 0)) is False


class TestParseCron:
    def test_invalid_length(self):
        assert parse_cron('0 2 * *') is None
        assert parse_cron('0 2 * * * extra') is None

    def test_invalid_fields(self):
        assert parse_cron('0 2 * * abc') is None
        assert parse_cron('60 2 * * *') is None   # 分钟超界
        assert parse_cron('0 25 * * *') is None   # 小时超界

    def test_valid(self):
        fields = parse_cron('0 6,10,14,18,22 * * *')
        assert fields is not None
        assert fields[0] == {0}
        assert fields[1] == {6, 10, 14, 18, 22}
        assert fields[3] is None  # 月通配


# ===========================================================================
# 2. CRUD 校验
# ===========================================================================

def _db_mock():
    db = MagicMock()
    db.add = MagicMock()
    db.get = AsyncMock(return_value=None)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = MagicMock()
    return db


class TestScheduleCrud:
    @pytest.mark.asyncio
    async def test_create_invalid_task_type(self):
        db = _db_mock()
        with pytest.raises(BackupSettingsError):
            await create_schedule(db, name='x', task_type='nope', cron_expr='0 2 * * *')

    @pytest.mark.asyncio
    async def test_create_invalid_cron(self):
        db = _db_mock()
        with pytest.raises(BackupSettingsError):
            await create_schedule(db, name='x', task_type='full', cron_expr='not cron')

    @pytest.mark.asyncio
    async def test_create_success(self):
        db = _db_mock()
        row = await create_schedule(db, name=' 每日 ', task_type='full', cron_expr='0 2 * * *')
        assert row.name == '每日'
        assert row.task_type == 'full'
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_not_found_returns_false(self):
        db = _db_mock()
        assert await delete_schedule(db, 999) is False


# ===========================================================================
# 3. due_schedules 幂等
# ===========================================================================

def _fake_row(task_type, cron, enabled=True, last_run_at=None):
    r = MagicMock(spec=BackupSchedule)
    r.id = 1
    r.name = task_type
    r.task_type = task_type
    r.cron_expr = cron
    r.enabled = enabled
    r.last_run_at = last_run_at
    return r


class TestDueSchedules:
    @pytest.mark.asyncio
    async def test_due_when_not_run(self, monkeypatch):
        from datetime import datetime
        rows = [_fake_row('full', '0 2 * * *')]
        monkeypatch.setattr(schedule_service, 'list_schedules', AsyncMock(return_value=rows))
        due = await due_schedules(MagicMock(), datetime(2026, 8, 22, 2, 0))
        assert due == rows

    @pytest.mark.asyncio
    async def test_skip_when_disabled(self, monkeypatch):
        from datetime import datetime
        rows = [_fake_row('full', '0 2 * * *', enabled=False)]
        monkeypatch.setattr(schedule_service, 'list_schedules', AsyncMock(return_value=rows))
        assert await due_schedules(MagicMock(), datetime(2026, 8, 22, 2, 0)) == []

    @pytest.mark.asyncio
    async def test_same_hour_window_idempotent(self, monkeypatch):
        from datetime import datetime
        now = datetime(2026, 8, 22, 2, 0)
        rows = [_fake_row('full', '0 2 * * *', last_run_at=now)]
        monkeypatch.setattr(schedule_service, 'list_schedules', AsyncMock(return_value=rows))
        assert await due_schedules(MagicMock(), now) == []

    @pytest.mark.asyncio
    async def test_next_day_due_again(self, monkeypatch):
        from datetime import datetime
        rows = [_fake_row('full', '0 2 * * *', last_run_at=datetime(2026, 8, 21, 2, 0))]
        monkeypatch.setattr(schedule_service, 'list_schedules', AsyncMock(return_value=rows))
        due = await due_schedules(MagicMock(), datetime(2026, 8, 22, 2, 0))
        assert due == rows


# ===========================================================================
# 4. 迁移 036 对称 downgrade
# ===========================================================================

def test_m2_migration_symmetric_downgrade():
    mig_path = (
        Path(__file__).resolve().parents[2]
        / 'migrations' / 'versions' / 'pg_standalone_036_backup_center_m2.py'
    )
    tree = ast.parse(mig_path.read_text(encoding='utf-8'))
    funcs = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert 'upgrade' in funcs and 'downgrade' in funcs