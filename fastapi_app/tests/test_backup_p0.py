"""P0 备份中心热修测试（2026-08-23 对标审核后整改）

覆盖:
1. P0-1 加密决策单点化:随机密钥回退移除、默认开关关闭、双信封格式自适应解密
2. P0-2 confirm_sensitive 透传到组件恢复
3. P0-3 分片 bundle 登记/读取/清扫（FakeRedis）
4. P0-4 .meta sidecar 写入/读取/级联删除/列表展示
5. P0-5 psql 单事务还原 + 还原锁统一(Redis) 的源码守卫

与 test_backup_m1 同款纪律:本文件独立运行,不依赖 client fixture。
"""
import asyncio
import io
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from fastapi_app.core import backup_encryption as enc
from fastapi_app.services.backup import records as records_mod
from fastapi_app.services.backup import restore as restore_mod


# ===========================================================================
# 1. P0-1 加密决策单点化
# ===========================================================================

class TestEncryptionNoRandomFallback:
    def test_fallback_flag_default_false_in_source(self):
        """源码级守卫:默认值必须为 'false'（防回归到随机密钥时代）。"""
        src = Path('fastapi_app/services/backup/_constants.py').read_text(encoding='utf-8')
        assert "'BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED', 'false'" in src

    def test_get_password_never_generates_random_even_if_flag_true(self, monkeypatch):
        monkeypatch.setattr(records_mod, 'BACKUP_ENCRYPTION_ENABLED', True, raising=False)
        import fastapi_app.services.backup.crypto as crypto
        monkeypatch.setattr(crypto, 'BACKUP_ENCRYPTION_ENABLED', True)
        monkeypatch.setattr(crypto, 'BACKUP_ENCRYPTION_PASSWORD', '')
        monkeypatch.setattr(crypto, 'BACKUP_ENCRYPTION_KEY', '')
        # 显式开启旧开关也不再生效（弃用告警 + None）
        assert crypto.get_backup_encryption_password() is None

    def test_get_password_env_password_wins(self, monkeypatch):
        import fastapi_app.services.backup.crypto as crypto
        monkeypatch.setattr(crypto, 'BACKUP_ENCRYPTION_ENABLED', True)
        monkeypatch.setattr(crypto, 'BACKUP_ENCRYPTION_PASSWORD', 'env-pw')
        assert crypto.get_backup_encryption_password() == 'env-pw'

    def test_misleading_random_key_log_removed_from_core(self):
        """core.py 不再输出"密钥已记录在日志中"的误导日志。"""
        src = Path('fastapi_app/services/backup/orchestration/core.py').read_text(encoding='utf-8')
        assert '密钥已记录在日志中' not in src


class TestDecryptBackupAuto:
    """双信封格式（裸信封 A / meta 前缀 B）自适应解密。"""

    DATA = b'PK\x03\x04 fake zip payload for tests'

    def _build_zip_bytes(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('manifest.json', json.dumps({
                'version': '2.0', 'type': 'full', 'encrypted': True,
                'tables': {}, 'checksums': {}, 'remark': 'p0-test',
            }))
        return buf.getvalue()

    def test_raw_envelope_roundtrip(self):
        envelope, _ = enc.encrypt_backup(self._build_zip_bytes(), 'pw1')
        plain, meta = enc.decrypt_backup_auto(envelope, 'pw1')
        assert plain[:4] == b'PK\x03\x04'
        assert meta is None  # 格式 A 无前缀 meta

    def test_prefixed_envelope_roundtrip(self):
        inner, enc_meta = enc.encrypt_backup(self._build_zip_bytes(), 'pw1')
        meta_json = json.dumps({'encrypted': True, **enc_meta}).encode('utf-8')
        prefixed = len(meta_json).to_bytes(4, 'big') + meta_json + inner
        plain, meta = enc.decrypt_backup_auto(prefixed, 'pw1')
        assert plain[:4] == b'PK\x03\x04'
        assert meta is not None and meta.get('encrypted') is True

    def test_wrong_password_raises(self):
        envelope, _ = enc.encrypt_backup(self._build_zip_bytes(), 'pw1')
        with pytest.raises(enc.BackupFileError):
            enc.decrypt_backup_auto(envelope, 'wrong')


# ===========================================================================
# 2. P0-2 confirm_sensitive 透传
# ===========================================================================

@pytest.mark.asyncio
async def test_restore_from_zip_passes_confirm_sensitive(monkeypatch):
    """restore_from_zip 将 confirm_sensitive 透传给组件恢复（默认 False）。"""
    captured = {}

    async def _fake_components(zf, confirm_sensitive=False):
        captured['confirm_sensitive'] = confirm_sensitive
        return {}

    async def _fake_verify(*args, **kwargs):
        return {'overall_pass': True}

    monkeypatch.setattr(restore_mod, 'restore_non_dependent_components', _fake_components)
    monkeypatch.setattr(restore_mod, 'verify_restore', _fake_verify)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('manifest.json', json.dumps({
            'version': '2.0', 'type': 'full', 'tables': {}, 'checksums': {},
        }))
        zf.writestr('filestore/demo.txt', 'x')
    zip_bytes = buf.getvalue()

    from unittest.mock import MagicMock
    db = MagicMock()
    db.commit = AsyncMock()

    # 默认 False
    await restore_mod.restore_from_zip(zip_bytes, db)
    assert captured['confirm_sensitive'] is False
    # 显式 True
    await restore_mod.restore_from_zip(zip_bytes, db, confirm_sensitive=True)
    assert captured['confirm_sensitive'] is True


@pytest.mark.asyncio
async def test_restore_from_zip_decrypts_envelope(monkeypatch):
    """加密 ZIP（裸信封）经内核解密后还原（P1-3 起走 DatabaseRestoreOrchestrator）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('manifest.json', json.dumps({
            'version': '2.0', 'type': 'full', 'tables': {}, 'checksums': {},
            'remark': 'encrypted-p0', 'encrypted': True,
        }))
        zf.writestr('database/dump.json', json.dumps({'version': '1.0', 'tables': {}}))
    envelope, _ = enc.encrypt_backup(buf.getvalue(), 'pw1')

    # 策略/验证器打桩，避免真实数据库会话（解密路径在内核阶段 2 已覆盖）
    from fastapi_app.services.backup.strategies import JsonRestoreStrategy
    from fastapi_app.services.backup.types import DatabaseRestoreResult

    async def _fake_strategy_restore(self, archive, manifest, engine_lifecycle, reporter=None, task_id=None):
        return DatabaseRestoreResult(status='ok', message='ok', strategy='json')

    monkeypatch.setattr(JsonRestoreStrategy, 'restore', _fake_strategy_restore)

    from fastapi_app.services.backup.adapters import (
        ExistingEngineLifecycleAdapter,
        ExistingRestoreVerifierAdapter,
    )

    async def _fake_verify(self, db, tables, fingerprints, schema_snapshot=None):
        return {'overall_pass': True}

    monkeypatch.setattr(ExistingRestoreVerifierAdapter, 'verify', _fake_verify)
    # 测试环境无全局会话工厂，验证阶段会话打桩
    monkeypatch.setattr(ExistingEngineLifecycleAdapter, 'new_session', AsyncMock(return_value=AsyncMock()))

    from unittest.mock import MagicMock
    db = MagicMock()
    db.commit = AsyncMock()

    result = await restore_mod.restore_from_zip(envelope, db, decrypt_password='pw1')
    assert result['remark'] == 'encrypted-p0'
    assert result['verification']['overall_pass'] is True
    assert result['database']['status'] == 'ok'

    # 无密码 → 明确报错
    with pytest.raises(restore_mod.RestoreError):
        await restore_mod.restore_from_zip(envelope, db)


# ===========================================================================
# 3. P0-3 分片 bundle 缓存
# ===========================================================================

class _FakeRedis:
    def __init__(self):
        self._data: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        self._data[key] = value

    async def get(self, key):
        return self._data.get(key)


@pytest.mark.asyncio
async def test_chunk_bundle_register_and_load(monkeypatch, tmp_path):
    from fastapi_app.api.v1.endpoints.backup import export as export_mod
    fake = _FakeRedis()

    async def _fake_get_redis():
        return fake

    monkeypatch.setattr('fastapi_app.core.backup_progress._get_redis', _fake_get_redis)

    payload_file = tmp_path / 'bundle.bin'
    payload_file.write_bytes(b'x' * 32)
    bundle_id = await export_mod._register_chunk_bundle(
        payload_file, filename='erp_backup_x.zip', total_size=32,
        chunk_size=10, total_chunks=4, checksum='deadbeef',
    )
    assert bundle_id
    loaded = await export_mod._load_chunk_bundle(bundle_id)
    assert loaded is not None
    assert loaded['total_chunks'] == 4 and loaded['checksum'] == 'deadbeef'
    # 未知/过期 bundle → None（调用方回退逐片生成）
    assert await export_mod._load_chunk_bundle('no-such-id') is None


@pytest.mark.asyncio
async def test_chunk_bundle_sweep_removes_expired(monkeypatch, tmp_path):
    import os
    from fastapi_app.api.v1.endpoints.backup import export as export_mod
    monkeypatch.setattr(export_mod, '_CHUNK_BUNDLE_DIR', tmp_path)
    fresh = tmp_path / 'fresh.bundle'
    stale = tmp_path / 'stale.bundle'
    fresh.write_bytes(b'f')
    stale.write_bytes(b's')
    old_ts = (datetime.now() - timedelta(seconds=export_mod._CHUNK_BUNDLE_TTL_SECONDS + 60)).timestamp()
    os.utime(stale, (old_ts, old_ts))

    await export_mod._sweep_chunk_bundle_files()
    assert fresh.exists()
    assert not stale.exists()


# ===========================================================================
# 4. P0-4 .meta sidecar
# ===========================================================================

class TestMetaSidecar:
    def _make_backup_dir(self, monkeypatch, tmp_path) -> Path:
        monkeypatch.setattr(records_mod, 'BACKUP_DIR', tmp_path)
        return tmp_path

    def test_write_and_read_meta(self, monkeypatch, tmp_path):
        d = self._make_backup_dir(monkeypatch, tmp_path)
        f = d / 'erp_backup_20260823_120000.zip.enc'
        f.write_bytes(b'encrypted-bytes')
        manifest = {
            'version': '2.0', 'type': 'full', 'encrypted': True,
            'exported_at': '2026-08-23 12:00:00', 'exported_by': 'admin',
            'remark': 'r1', 'table_count': 10, 'total_rows': 100,
        }
        meta_path = records_mod.write_backup_meta_file(f, manifest)
        assert meta_path is not None and meta_path.exists()

        # _backup_created_time 优先读 meta（不再依赖 mtime）
        got = records_mod._backup_created_time(f)
        assert got == datetime.strptime('2026-08-23 12:00:00', '%Y-%m-%d %H:%M:%S')

    def test_delete_removes_sidecar(self, monkeypatch, tmp_path):
        d = self._make_backup_dir(monkeypatch, tmp_path)
        f = d / 'erp_backup_20260823_120001.zip'
        f.write_bytes(b'x')
        manifest = {'version': '2.0', 'type': 'full', 'exported_at': '2026-08-23 12:00:01'}
        records_mod.write_backup_meta_file(f, manifest)
        assert (d / (f.name + '.meta')).exists()

        records_mod.delete_backup_file(f.name)
        assert not f.exists()
        assert not (d / (f.name + '.meta')).exists()

    def test_list_backup_files_includes_enc_with_meta_info(self, monkeypatch, tmp_path):
        d = self._make_backup_dir(monkeypatch, tmp_path)
        # 明文 zip（带 manifest）
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('manifest.json', json.dumps({
                'type': 'full', 'table_count': 5, 'total_rows': 50,
                'exported_at': '2026-08-23 11:00:00', 'exported_by': 'u',
                'remark': 'plain', 'includes': {},
            }))
        (d / 'erp_backup_20260823_110000.zip').write_bytes(buf.getvalue())
        # 加密 zip.enc（信息在 meta）
        enc_f = d / 'erp_backup_20260823_120000.zip.enc'
        enc_f.write_bytes(b'ciphertext')
        records_mod.write_backup_meta_file(enc_f, {
            'version': '2.0', 'type': 'full', 'encrypted': True,
            'exported_at': '2026-08-23 12:00:00', 'exported_by': 'u',
            'remark': 'enc', 'table_count': 7, 'total_rows': 70,
        })

        entries = {e['filename']: e for e in records_mod.list_backup_files()}
        assert 'erp_backup_20260823_110000.zip' in entries
        enc_entry = entries.get('erp_backup_20260823_120000.zip.enc')
        assert enc_entry is not None, '加密备份(.zip.enc)必须出现在列表中'
        assert enc_entry['encrypted'] is True
        assert enc_entry['table_count'] == 7 and enc_entry['remark'] == 'enc'


# ===========================================================================
# 5. P0-5 源码守卫（与项目 AST/源码守卫测试惯例一致）
# ===========================================================================

class TestSourceGuards:
    def test_psql_single_transaction_and_error_stop(self):
        src = Path('fastapi_app/services/backup/dump.py').read_text(encoding='utf-8')
        assert '--single-transaction' in src, 'psql 还原必须单事务'
        assert 'ON_ERROR_STOP=1' in src, 'psql 还原必须遇错即停'

    def test_restore_endpoints_use_redis_lock_only(self):
        """还原端点不再使用 PG advisory 锁（统一 Redis，消除双锁并发窗口）。"""
        src = Path('fastapi_app/api/v1/endpoints/backup/restore.py').read_text(encoding='utf-8')
        assert 'try_acquire_restore_lock' not in src

    def test_save_endpoint_no_double_encryption(self):
        """旧 /save 的端点二次加密包装（_encrypt_backup_data）不得回流到该端点。"""
        src = Path('fastapi_app/api/v1/endpoints/backup/export.py').read_text(encoding='utf-8')
        save_section = src[src.index("@router.post('/save'"):]
        save_section = save_section[:save_section.index('# ', 1) if '# ' in save_section[1:] else len(save_section)]
        assert '_encrypt_backup_data' not in save_section

    def test_task_writes_meta_sidecar(self):
        src = Path('fastapi_app/tasks/backup_tasks.py').read_text(encoding='utf-8')
        assert src.count('write_backup_meta_file') >= 2, '手动与自动全量任务都须写 .meta'
