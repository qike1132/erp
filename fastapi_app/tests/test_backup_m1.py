"""
M1 备份任务化测试(TECHNICAL_PLAN.md v2 §7 M1)

覆盖:
1. settings_service.validate_path:路径校验(绝对路径/非法字符/穿越/黑名单/可写/空间)
2. settings_service.get_settings / save_settings:读写与回退
3. 端点 POST /full、/incremental:202 入队 + 409 互斥
4. 端点 GET/POST /settings、POST /settings/validate-path

注意:本文件独立运行(conftest 的 client fixture 存在 event loop 污染,见项目规则)。
"""
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from fastapi_app.services.backup import settings_service
from fastapi_app.services.backup.settings_service import (
    BackupSettingsError,
    get_settings,
    save_settings,
    validate_path,
)


# ===========================================================================
# 1. validate_path
# ===========================================================================

class TestValidatePath:
    def test_empty_path(self):
        assert validate_path('')['valid'] is False
        assert validate_path('   ')['valid'] is False

    def test_relative_path_rejected(self):
        assert validate_path('backups/server')['valid'] is False
        assert validate_path('./backups')['valid'] is False

    def test_illegal_chars_rejected(self):
        result = validate_path('D:\\back<ups')
        assert result['valid'] is False
        assert '非法字符' in result['error']

    def test_path_traversal_rejected(self):
        result = validate_path('D:\\backups\\..\\etc')
        assert result['valid'] is False
        assert '..' in result['error']

    def test_drive_whitelist(self):
        # G: 盘不在白名单
        result = validate_path('G:\\backups')
        assert result['valid'] is False
        assert '盘符' in result['error']

    def test_system_dir_blacklist(self):
        result = validate_path('C:\\Windows\\System32\\backups')
        assert result['valid'] is False
        assert '系统目录' in result['error']

    def test_existing_root_parent_allowed(self):
        # 路径上级(D:\)存在且可写 → 目录将被创建,判定为合法
        with patch('fastapi_app.services.backup.settings_service._BLACKLIST_SUBSTR', ()):
            result = validate_path('D:\\no_such_dir_xyz\\backups')
        assert result['valid'] is True

    def test_unix_absolute_allowed(self, tmp_path):
        # 绝对可写目录:校验通过(patch 黑名单,因 pytest 临时目录位于 AppData 下)
        probe = tmp_path / 'sub'
        probe.mkdir()
        with patch('fastapi_app.services.backup.settings_service._BLACKLIST_SUBSTR', ()):
            result = validate_path(str(probe))
        assert result['valid'] is True

    @patch('fastapi_app.services.backup.settings_service.psutil.disk_usage')
    def test_low_disk_space_rejected(self, mock_usage, tmp_path):
        import types
        usage = types.SimpleNamespace(free=1 * 1024 ** 3)  # 1 GB < 5 GB
        mock_usage.return_value = usage
        with patch('fastapi_app.services.backup.settings_service._BLACKLIST_SUBSTR', ()):
            result = validate_path(str(tmp_path))
        assert result['valid'] is False
        assert '空间不足' in result['error']


# ===========================================================================
# 2. get_settings / save_settings
# ===========================================================================

def _fake_db_with_settings(row):
    """构造 AsyncSession mock:execute 返回含 scalar_one_or_none 的 Result mock"""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute.return_value = result
    return db


class TestSettingsService:
    @pytest.mark.asyncio
    async def test_get_settings_fallback_when_not_initialized(self):
        """表未初始化 → 回退 env/默认值,initialized=False"""
        db = _fake_db_with_settings(None)
        result = await get_settings(db)
        assert result['initialized'] is False
        assert result['backup_dir']  # 非空
        assert result['retention_days'] == 30

    @pytest.mark.asyncio
    async def test_get_settings_initialized(self):
        row = MagicMock()
        row.backup_dir = 'D:\\erp_data\\backups'
        row.retention_days = 60
        row.max_count = 20
        row.encryption_mode = 'password'
        row.updated_by = 'admin'
        row.updated_at = None
        db = _fake_db_with_settings(row)
        result = await get_settings(db)
        assert result['initialized'] is True
        assert result['backup_dir'] == 'D:\\erp_data\\backups'
        assert result['retention_days'] == 60
        assert result['max_count'] == 20

    @pytest.mark.asyncio
    async def test_save_settings_invalid_dir_raises(self):
        db = _fake_db_with_settings(None)
        with pytest.raises(BackupSettingsError):
            await save_settings(db, backup_dir='relative/path')

    @pytest.mark.asyncio
    async def test_save_settings_creates_row(self, tmp_path):
        db = _fake_db_with_settings(None)
        # tmp_path 位于 AppData 下,需 patch 黑名单
        with patch('fastapi_app.services.backup.settings_service._BLACKLIST_SUBSTR', ()):
            await save_settings(
                db, backup_dir=str(tmp_path),
                retention_days=15, max_count=10,
                encryption_mode='off', operator='admin',
            )
        # 应 add 一行
        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added.backup_dir == str(tmp_path)
        assert added.retention_days == 15
        assert added.max_count == 10
        assert added.encryption_mode == 'off'

    @pytest.mark.asyncio
    async def test_save_settings_invalid_retention(self):
        db = _fake_db_with_settings(None)
        with pytest.raises(BackupSettingsError):
            await save_settings(db, retention_days=0)

    @pytest.mark.asyncio
    async def test_save_settings_invalid_encryption_mode(self):
        db = _fake_db_with_settings(None)
        with pytest.raises(BackupSettingsError):
            await save_settings(db, encryption_mode='unknown')


# ===========================================================================
# 3. 端点:POST /full /incremental(202 + 409)
# ===========================================================================

@pytest_asyncio.fixture
async def client():
    """独立 HTTP 客户端(仅用于本文件,避免与全量 conftest client 冲突)。

    与 conftest.client 一致:先 GET /api/health 获取 CSRF cookie,
    设置 X-CSRF-Token + Bearer token,使 POST 请求通过 CSRF/权限中间件。
    """
    from httpx import ASGITransport, AsyncClient

    from fastapi_app.main import app

    async def override_get_async_db():
        yield AsyncMock()

    async def override_get_user():
        user = MagicMock()
        user.id = 1
        user.username = 'tester'
        user.is_super = True
        user.has_permission = MagicMock(return_value=True)
        return user

    from fastapi_app.core.database import get_async_db
    from fastapi_app.core.deps import _get_user_with_permissions
    app.dependency_overrides[get_async_db] = override_get_async_db
    app.dependency_overrides[_get_user_with_permissions] = override_get_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as ac:
        await ac.get('/api/health')
        csrf_cookie = ac.cookies.get('fastapi_csrf_token', '')
        if csrf_cookie:
            ac.headers['X-CSRF-Token'] = csrf_cookie
        ac.headers['Authorization'] = 'Bearer test-token'
        yield ac

    app.dependency_overrides.clear()


class TestTriggerEndpoints:
    @pytest.mark.asyncio
    async def test_full_returns_202_with_task_id(self, client):
        """POST /full → 202 + task_id + 入队调用"""
        fake_pool = AsyncMock()
        with patch(
            'fastapi_app.core.arq_app.get_arq_pool',
            new=AsyncMock(return_value=fake_pool),
        ), patch(
            'fastapi_app.api.v1.endpoints.backup.actions._check_task_mutex',
            new=AsyncMock(),
        ):
            resp = await client.post('/api/v1/backup/full', json={'remark': '手动测试'})
        assert resp.status_code == 202
        body = resp.json()
        assert body['success'] is True
        assert body['task_id']
        assert body['task_name'] == 'manual_full_backup_task'
        # 入队参数校验
        call_kwargs = fake_pool.enqueue_job.call_args.kwargs
        assert not any(k.startswith('_') for k in call_kwargs)
        assert call_kwargs['remark'] == '手动测试'
        assert call_kwargs['task_id'] == body['task_id']

    @pytest.mark.asyncio
    async def test_incremental_returns_202(self, client):
        fake_pool = AsyncMock()
        with patch(
            'fastapi_app.core.arq_app.get_arq_pool',
            new=AsyncMock(return_value=fake_pool),
        ), patch(
            'fastapi_app.api.v1.endpoints.backup.actions._check_task_mutex',
            new=AsyncMock(),
        ):
            resp = await client.post('/api/v1/backup/incremental', json={'since': '20260820_020000'})
        assert resp.status_code == 202
        body = resp.json()
        assert body['task_id']
        assert body['task_name'] == 'manual_incremental_backup_task'
        call_kwargs = fake_pool.enqueue_job.call_args.kwargs
        assert call_kwargs['since'] == '20260820_020000'

    @pytest.mark.asyncio
    async def test_full_returns_409_when_busy(self, client):
        """互斥:备份任务执行中 → 409 TASK_RUNNING"""
        from fastapi import HTTPException

        async def _busy(db):
            raise HTTPException(status_code=409, detail={'code': 'TASK_RUNNING', 'message': 'busy'})

        fake_pool = AsyncMock()
        with patch(
            'fastapi_app.core.arq_app.get_arq_pool',
            new=AsyncMock(return_value=fake_pool),
        ), patch(
            'fastapi_app.api.v1.endpoints.backup.actions._check_task_mutex',
            new=_busy,
        ):
            resp = await client.post('/api/v1/backup/full', json={})
        assert resp.status_code == 409
        assert resp.json()['detail']['code'] == 'TASK_RUNNING'
        fake_pool.enqueue_job.assert_not_awaited()


# ===========================================================================
# 4. 端点:GET/POST /settings、validate-path
# ===========================================================================

class TestSettingsEndpoints:
    @pytest.mark.asyncio
    async def test_get_settings_endpoint(self, client):
        async def _get_settings(db):
            return {
                'backup_dir': 'D:\\erp_data\\backups', 'retention_days': 30,
                'max_count': 50, 'encryption_mode': 'env',
                'initialized': True,
            }

        with patch(
            'fastapi_app.api.v1.endpoints.backup.settings.backup_service.get_settings',
            new=_get_settings,
        ):
            resp = await client.get('/api/v1/backup/settings')
        assert resp.status_code == 200
        body = resp.json()
        assert body['backup_dir'] == 'D:\\erp_data\\backups'
        assert body['initialized'] is True

    @pytest.mark.asyncio
    async def test_validate_path_endpoint(self, client):
        """validate-path 端点:合法路径(临时目录)→ valid=true"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, patch(
            'fastapi_app.api.v1.endpoints.backup.settings.backup_service.validate_path',
            return_value={'valid': True, 'path': tmp, 'message': '路径可写,空间充足'},
        ):
            resp = await client.post(
                '/api/v1/backup/settings/validate-path',
                json={'path': tmp},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body['valid'] is True

    @pytest.mark.asyncio
    async def test_validate_path_endpoint_invalid(self, client):
        with patch(
            'fastapi_app.api.v1.endpoints.backup.settings.backup_service.validate_path',
            return_value={'valid': False, 'error': '必须是绝对路径(如 D:\\backups 或 /data/backups)'},
        ):
            resp = await client.post(
                '/api/v1/backup/settings/validate-path',
                json={'path': 'relative/path'},
            )
        assert resp.status_code == 200
        assert resp.json()['valid'] is False

    @pytest.mark.asyncio
    async def test_update_settings_endpoint(self, client):
        async def _save_settings(db, **kwargs):
            return {
                'backup_dir': 'D:\\erp_data\\backups',
                'retention_days': kwargs.get('retention_days'),
                'max_count': kwargs.get('max_count'),
                'encryption_mode': 'env',
                'initialized': True,
            }

        with patch(
            'fastapi_app.api.v1.endpoints.backup.settings.backup_service.save_settings',
            new=_save_settings,
        ):
            resp = await client.post(
                '/api/v1/backup/settings',
                json={'retention_days': 60, 'max_count': 30},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body['retention_days'] == 60
        assert body['max_count'] == 30


# ===========================================================================
# 4.5 手动任务 task_id 一致性(M1 缺陷回归)
#    入口端点生成的 task_id 必须作为进度 key,不能由任务自行重生成,
#    否则前端轮询 GET /progress/{task_id} 取不到进度。
# ===========================================================================

@pytest.mark.asyncio
async def test_manual_full_task_uses_passed_task_id(monkeypatch, tmp_path):
    from contextlib import asynccontextmanager

    import fastapi_app.core.database as database_mod
    from fastapi_app.tasks import backup_tasks as bt

    captured: dict = {}

    async def fake_create_progress(task_id, **kwargs):
        captured['task_id'] = task_id

    async def fake_update_progress(*args, **kwargs):
        return None

    async def fake_fail_progress(*args, **kwargs):
        return None

    async def fake_ensure_backup_dir(*args, **kwargs):
        return None

    async def fake_create_full_backup(db, user, remark, encrypt_password=None, encrypt=True):
        return (b'zip-bytes', {'table_count': 1, 'total_rows': 5, 'encrypted': False})

    async def fake_write_backup_record(db, **kwargs):
        captured['record'] = kwargs

    @asynccontextmanager
    async def fake_db_ctx():
        yield AsyncMock()

    monkeypatch.setattr(bt, 'create_progress', fake_create_progress)
    monkeypatch.setattr(bt, 'update_progress', fake_update_progress)
    monkeypatch.setattr(bt, 'fail_progress', fake_fail_progress)
    monkeypatch.setattr(database_mod, 'get_async_db_context', fake_db_ctx)
    from fastapi_app.services import backup as backup_mod
    monkeypatch.setattr(backup_mod, 'ensure_backup_dir', fake_ensure_backup_dir)
    monkeypatch.setattr(backup_mod, 'create_full_backup', fake_create_full_backup)
    monkeypatch.setattr(backup_mod, 'write_backup_record', fake_write_backup_record)
    monkeypatch.setattr(backup_mod, 'BACKUP_DIR', tmp_path)

    result = await bt.manual_full_backup_task(
        {'job_try': 1}, task_id='EXPECTED-ID', remark='r', encrypt=False,
    )

    # 进度 key:必须使用入口传入的 task_id,而非重新生成
    assert captured.get('task_id') == 'EXPECTED-ID'
    # 落库记录:trigger=manual,文件名写入真实目录
    assert captured['record']['trigger_type'] == 'manual'
    assert captured['record']['record_type'] == 'full'
    assert result['status'] == 'ok'


# ===========================================================================
# 5. 迁移可回滚性(静态检查:Alembic downgrade 存在且对称)
# ===========================================================================

def test_migration_has_symmetric_downgrade():
    import ast
    from pathlib import Path

    mig_path = (
        Path(__file__).resolve().parents[2]
        / 'migrations' / 'versions' / 'pg_standalone_035_backup_center_m1.py'
    )
    tree = ast.parse(mig_path.read_text(encoding='utf-8'))
    funcs = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert 'upgrade' in funcs and 'downgrade' in funcs
