"""
M3 还原强化测试(TECHNICAL_PLAN.md v2 §7 M3)

覆盖:
1. 还原锁 fail-closed:Redis 不可用/异常时 acquire=False、is_in_progress=True
2. 维护模式:enter/exit/is 读写 Redis 标志
3. restore_plan:manifest 差异预览(diff 计算/路径穿越/加密探测)
4. build_schema_snapshot:L4 DDL 比对的快照采集
"""
import json
import zipfile
from unittest.mock import AsyncMock, MagicMock

import pytest

import fastapi_app.core.backup_progress as bp
from fastapi_app.core import maintenance
from fastapi_app.services.backup import restore as restore_mod
from fastapi_app.services.backup import restore_plan as rp
from fastapi_app.services.backup.verify import core as verify_core

# ===========================================================================
# 1. 还原锁 fail-closed
# ===========================================================================

class TestRestoreLockFailClosed:
    @pytest.mark.asyncio
    async def test_acquire_fails_when_redis_unavailable(self, monkeypatch):
        monkeypatch.setattr(bp, '_get_redis', AsyncMock(return_value=None))
        assert await restore_mod.acquire_restore_lock('t') is False

    @pytest.mark.asyncio
    async def test_acquire_fails_on_exception(self, monkeypatch):
        async def boom():
            raise ConnectionError('redis down')
        monkeypatch.setattr(bp, '_get_redis', boom)
        assert await restore_mod.acquire_restore_lock('t') is False

    @pytest.mark.asyncio
    async def test_is_in_progress_true_when_redis_unavailable(self, monkeypatch):
        monkeypatch.setattr(bp, '_get_redis', AsyncMock(return_value=None))
        assert await restore_mod.is_restore_in_progress() is True

    @pytest.mark.asyncio
    async def test_acquire_succeeds_when_lock_free(self, monkeypatch):
        client = AsyncMock()
        client.set.return_value = True
        monkeypatch.setattr(bp, '_get_redis', AsyncMock(return_value=client))
        assert await restore_mod.acquire_restore_lock('t') is True


# ===========================================================================
# 1b. 还原互斥助手的锁探测/自愈链路（2026-09-24 生产事故回归）
# ===========================================================================

def _as_text(value):
    """归一化 Redis 返回值：客户端未启用 decode_responses，raw 值为 bytes。"""
    return value.decode() if isinstance(value, bytes) else value


class _FakeRedis:
    """最小 Redis 假实现（键值存储式）。

    键按传入的字符串文本比较——真实 Redis 会对 str 入参自动编码，而 bytes 入参
    经 f-string 拼接后变成 "b'xxx'" 文本；这层假实现正是用来暴露该差异。
    """

    def __init__(self, store):
        self.store = store

    async def get(self, key):
        return self.store.get(key)

    async def exists(self, key):
        return 1 if key in self.store else 0

    async def ttl(self, key):
        return 600 if key in self.store else -2

    async def eval(self, _script, _numkeys, key, arg):
        if _as_text(self.store.get(key)) == _as_text(arg):
            self.store.pop(key, None)
            return 1
        return 0


class TestRestoreSlotMutex:
    """ensure_restore_slot_free：锁探测 → 陈旧判定 → 自愈清除。

    2026-09-24 生产事故两点回归：
    1. 锁工具必须由包根 services.backup 导出，否则抛 AttributeError（HTTP 500）；
    2. holder 是 bytes 时不解码，进度键会被拼成 "erp:restore_progress:b'xxx'"，
       陈旧锁永远判定不出来，409 一直卡到 TTL 到期。
    """

    @staticmethod
    def _store(holder, progress_status=None):
        from fastapi_app.services.backup.restore import _RESTORE_LOCK_KEY

        store = {_RESTORE_LOCK_KEY: holder}
        if progress_status is not None:
            store[bp.RESTORE_KEY_PREFIX + _as_text(holder)] = json.dumps({'status': progress_status})
        return store

    @pytest.mark.asyncio
    async def test_stale_lock_self_heals(self, monkeypatch):
        from fastapi_app.api.v1.endpoints.backup import _mutex
        from fastapi_app.services.backup.restore import _RESTORE_LOCK_KEY

        store = self._store(b'restore-task-1', 'failed')
        monkeypatch.setattr(bp, '_get_redis', AsyncMock(return_value=_FakeRedis(store)))
        monkeypatch.setattr(bp, 'is_redis_available', AsyncMock(return_value=True))

        assert await _mutex.ensure_restore_slot_free() is None
        assert _RESTORE_LOCK_KEY not in store  # 陈旧锁已被自愈清除

    @pytest.mark.asyncio
    async def test_live_lock_returns_409(self, monkeypatch):
        from fastapi import HTTPException

        from fastapi_app.api.v1.endpoints.backup import _mutex
        from fastapi_app.services.backup.restore import _RESTORE_LOCK_KEY

        store = self._store(b'restore-task-2', 'restore_db')
        monkeypatch.setattr(bp, '_get_redis', AsyncMock(return_value=_FakeRedis(store)))
        monkeypatch.setattr(bp, 'is_redis_available', AsyncMock(return_value=True))

        with pytest.raises(HTTPException) as exc:
            await _mutex.ensure_restore_slot_free()
        assert exc.value.status_code == 409
        assert exc.value.detail['code'] == 'TASK_RUNNING'
        assert exc.value.detail['holder'] == 'restore-task-2'  # 必须是 str，不能是 b'...'
        assert exc.value.detail['ttl_seconds'] == 600
        assert _RESTORE_LOCK_KEY in store  # 真实占用不得清锁


# ===========================================================================
# 2. 维护模式
# ===========================================================================

class TestMaintenance:
    # 客户端来源已改为 core/redis_wrapper.get_client()（自愈客户端，
    # 见 core/maintenance.py 模块 docstring），故 mock 目标从 bp._get_redis
    # 改为 maintenance._get_client；bf._get_redis 的 mock 仍用于还原锁那组测试。
    @pytest.mark.asyncio
    async def test_enter_sets_flag(self, monkeypatch):
        client = AsyncMock()
        monkeypatch.setattr(maintenance, '_get_client', AsyncMock(return_value=client))
        assert await maintenance.enter_maintenance() is True
        client.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_exit_deletes_flag(self, monkeypatch):
        client = AsyncMock()
        monkeypatch.setattr(maintenance, '_get_client', AsyncMock(return_value=client))
        await maintenance.exit_maintenance()
        client.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_is_on(self, monkeypatch):
        client = AsyncMock()
        client.get.return_value = b'1'
        monkeypatch.setattr(maintenance, '_get_client', AsyncMock(return_value=client))
        assert await maintenance.is_maintenance_mode() is True

    @pytest.mark.asyncio
    async def test_middleware_blocks_write_when_on(self, monkeypatch):
        from starlette.requests import Request
        client = AsyncMock()
        client.get.return_value = b'1'
        monkeypatch.setattr(maintenance, '_get_client', AsyncMock(return_value=client))

        async def call_next(req):
            return MagicMock(status_code=200)

        req = Request({'type': 'http', 'method': 'POST', 'path': '/api/v1/orders', 'headers': [], 'query_string': b'', 'client': ('127.0.0.1', 1), 'server': ('t', 80), 'scheme': 'http', 'root_path': ''})
        resp = await maintenance.maintenance_middleware(req, call_next)
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_middleware_allows_backup_path(self, monkeypatch):
        from starlette.requests import Request
        client = AsyncMock()
        client.get.return_value = b'1'
        monkeypatch.setattr(maintenance, '_get_client', AsyncMock(return_value=client))

        async def call_next(req):
            return MagicMock(status_code=200)

        req = Request({'type': 'http', 'method': 'POST', 'path': '/api/v1/backup/restore/execute', 'headers': [], 'query_string': b'', 'client': ('127.0.0.1', 1), 'server': ('t', 80), 'scheme': 'http', 'root_path': ''})
        resp = await maintenance.maintenance_middleware(req, call_next)
        assert resp.status_code == 200


# ===========================================================================
# 3. restore_plan
# ===========================================================================

class TestRestorePlan:
    @pytest.mark.asyncio
    async def test_diff_computation(self):
        db = AsyncMock()
        counts = {'users': 100, 'orders': 200}

        async def execute(q):
            sql = str(q)
            res = MagicMock()
            res.scalar.return_value = next((v for k, v in counts.items() if f'"{k}"' in sql), None)
            return res

        db.execute = execute
        manifest = {'tables': {'users': {'rows': 90}, 'orders': {'rows': 250}}}
        plan = await rp.build_restore_plan(db, manifest)
        assert plan['table_count'] == 2
        diffs = {d['table']: d['diff'] for d in plan['tables']}
        assert diffs['users'] == 10    # 100-90
        assert diffs['orders'] == -50  # 200-250
        assert {a['table'] for a in plan['affected_tables']} == {'users', 'orders'}
        assert plan['total_backup_rows'] == 340
        assert plan['affected_count'] == 2

    def test_read_manifest_from_backup_traversal_guard(self, tmp_path):
        # basename 化后文件不存在 → FileNotFoundError
        with pytest.raises(FileNotFoundError):
            rp.read_manifest_from_backup('../evil.zip', base_dir=tmp_path)

    def test_read_manifest_encrypted_detection(self, tmp_path):
        import pytest as _pytest
        p = tmp_path / 'enc.zip.enc'
        p.write_bytes(b'')
        with _pytest.raises(ValueError):
            rp.read_manifest_from_backup('enc.zip.enc', base_dir=tmp_path)

    def test_read_manifest_success(self, tmp_path):
        p = tmp_path / 'ok.zip'
        with zipfile.ZipFile(p, 'w') as zf:
            zf.writestr('manifest.json', json.dumps({'tables': {'users': {'rows': 5}}}))
        manifest = rp.read_manifest_from_backup('ok.zip', base_dir=tmp_path)
        assert manifest['tables']['users']['rows'] == 5


# ===========================================================================
# 4. build_schema_snapshot
# ===========================================================================

class TestSchemaSnapshot:
    @pytest.mark.asyncio
    async def test_build(self):
        db = AsyncMock()
        rows = [
            ('users', 'id', 'integer', 'NO'),
            ('users', 'name', 'text', 'YES'),
            ('orders', 'id', 'bigint', 'NO'),
        ]
        res = MagicMock()
        res.fetchall.return_value = rows
        db.execute = AsyncMock(return_value=res)
        snap = await verify_core.build_schema_snapshot(db)
        assert set(snap.keys()) == {'users', 'orders'}
        assert snap['users'][0]['column'] == 'id'
        assert snap['users'][1]['nullable'] is True


# ===========================================================================
# 5. DR 服务加密包处理（M3 演练：历史加密备份可被识别/尝试）
# ===========================================================================

class TestDRServiceEncryption:
    @pytest.fixture
    def svc(self):
        from fastapi_app.services.backup.orchestration.recovery_test_service import (
            DisasterRecoveryTestService,
        )
        s = DisasterRecoveryTestService()
        s.test_config['test_password'] = ''
        return s

    def test_plain_returns_same(self, svc, tmp_path):
        p = tmp_path / 'plain.zip'
        p.write_bytes(b'')
        out = svc._open_backup_content(p)
        assert out == p

    def test_enc_without_password_raises(self, svc, tmp_path):
        p = tmp_path / 'db.zip.enc'
        p.write_bytes(b'\x00\x01')
        with pytest.raises(ValueError, match='BACKUP_TEST_PASSWORD'):
            svc._open_backup_content(p)

    def test_enc_with_password_decrypts(self, svc, tmp_path, monkeypatch):
        from fastapi_app.core import backup_encryption as be
        p = tmp_path / 'db.zip.enc'
        p.write_bytes(b'\x00\x01')
        svc.test_config['test_password'] = 'secret'
        monkeypatch.setattr(be, 'decrypt_backup', lambda data, pw: b'PK\x03\x04-decrypted')
        out = svc._open_backup_content(p)
        try:
            assert out != p
            assert out.suffix == '.zip'
            assert out.read_bytes() == b'PK\x03\x04-decrypted'
        finally:
            out.unlink(missing_ok=True)

    def test_select_ignores_orphan_meta(self, tmp_path, monkeypatch):
        # 仅孤儿 .enc.meta 存在时不应被选中
        import importlib
        rts = importlib.import_module(
            'fastapi_app.services.backup.orchestration.recovery_test_service'
        )
        meta = tmp_path / 'x.zip.enc.meta'
        meta.write_bytes(b'{}')
        monkeypatch.setattr(rts, 'BACKUP_DIR', tmp_path)
        svc = rts.DisasterRecoveryTestService()
        svc.test_config['test_password'] = ''
        import asyncio
        info = asyncio.run(svc._select_backup_for_test(None))
        assert info is None
