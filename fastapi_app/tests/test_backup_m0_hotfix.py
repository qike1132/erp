"""
M0 热修回归测试（docs/ui-redesign/backup-center/TECHNICAL_PLAN.md v2 §4.1）

覆盖三块：
1. legacy 导入守卫：AST 扫描 services/backup 包，禁止再出现对已删除模块
   fastapi_app.services.backup_service 的导入（fa156a3 收敛时遗漏过 7 处，
   导致 psql 还原/安全备份/组件恢复/还原后校验运行时崩溃）。
2. 委托冒烟：strategies / adapters / orchestrator / format_strategy 中
   修复后的惰性导入路径可正常解析并委托到包内子模块。
3. 加密密码回退：_get_encryption_password 无密码时返回 None（禁止随机密码），
   _resolve_encryption 未配置密码时降级为不加密。
"""
import ast
import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from fastapi_app.api.v1.endpoints.backup import _deps
from fastapi_app.services.backup.adapters import (
    ExistingComponentRestoreAdapter,
    ExistingRestoreVerifierAdapter,
    ExistingSafetyBackupAdapter,
)
from fastapi_app.services.backup.format_strategy import DefaultBackupFormatStrategy
from fastapi_app.services.backup.format_types import PackOptions
from fastapi_app.services.backup.orchestrator import DatabaseRestoreOrchestrator
from fastapi_app.services.backup.strategies import (
    JsonRestoreStrategy,
    PsqlRestoreStrategy,
)

BACKUP_PKG_DIR = Path(__file__).resolve().parents[1] / 'services' / 'backup'
LEGACY_MODULE = 'fastapi_app.services.backup_service'


# ---------------------------------------------------------------------------
# 1. legacy 导入守卫
# ---------------------------------------------------------------------------

def test_no_legacy_backup_service_imports_in_backup_pkg():
    offenders: list[str] = []
    for py in BACKUP_PKG_DIR.rglob('*.py'):
        if '__pycache__' in py.parts:
            continue
        tree = ast.parse(py.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and (
                node.module == LEGACY_MODULE or node.module.startswith(LEGACY_MODULE + '.')
            ):
                offenders.append(f'{py.relative_to(BACKUP_PKG_DIR)}:{node.lineno}')
    assert not offenders, f'发现对已删除模块 {LEGACY_MODULE} 的导入: {offenders}'


# ---------------------------------------------------------------------------
# 2. 委托冒烟（修复前这些路径 ModuleNotFoundError）
# ---------------------------------------------------------------------------

def _empty_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w'):
        pass
    return buf.getvalue()


class _FakeEngineLifecycle:
    def __init__(self):
        self.session = SimpleNamespace(
            close=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock(),
        )

    async def new_session(self):
        return self.session


@pytest.mark.asyncio
async def test_psql_strategy_delegates_to_dump(monkeypatch):
    from fastapi_app.services.backup import dump

    fake = AsyncMock(return_value={'status': 'ok', 'message': 'done'})
    monkeypatch.setattr(dump, 'restore_database_via_psql', fake)

    archive = SimpleNamespace(raw_bytes=_empty_zip_bytes())
    lifecycle = _FakeEngineLifecycle()
    result = await PsqlRestoreStrategy().restore(archive, SimpleNamespace(), lifecycle)

    assert result.status == 'ok'
    assert result.strategy == 'psql'
    fake.assert_awaited_once()
    passed_zf, passed_db = fake.await_args.args
    assert isinstance(passed_zf, zipfile.ZipFile)
    assert passed_db is lifecycle.session


@pytest.mark.asyncio
async def test_json_strategy_delegates_to_json_backup(monkeypatch):
    from fastapi_app.services.backup import json_backup

    fake = AsyncMock(return_value={'status': 'ok', 'message': 'done', 'total_inserted': 3})
    monkeypatch.setattr(json_backup, 'restore_database_from_json', fake)

    archive = SimpleNamespace(raw_bytes=_empty_zip_bytes())
    lifecycle = _FakeEngineLifecycle()
    result = await JsonRestoreStrategy().restore(archive, SimpleNamespace(), lifecycle)

    assert result.status == 'ok'
    assert result.strategy == 'json'
    lifecycle.session.commit.assert_awaited_once()
    passed_zf, passed_db = fake.await_args.args
    assert isinstance(passed_zf, zipfile.ZipFile)
    assert passed_db is lifecycle.session


@pytest.mark.asyncio
async def test_safety_backup_adapter_delegates(monkeypatch):
    from fastapi_app.services.backup.orchestration import core as orchestration_core

    fake = AsyncMock(return_value={'filename': 'pre_restore.zip'})
    monkeypatch.setattr(orchestration_core, 'create_pre_restore_backup', fake)

    db = SimpleNamespace()
    result = await ExistingSafetyBackupAdapter(db).create()

    assert result == {'filename': 'pre_restore.zip'}
    fake.assert_awaited_once_with(db)


@pytest.mark.asyncio
async def test_component_restore_adapter_delegates(monkeypatch):
    from fastapi_app.services.backup import restore as restore_mod

    fake = AsyncMock(return_value={
        'filestore': {'ok': True}, 'config': {}, 'redis': {}, 'meilisearch': {}, 'errors': [],
    })
    monkeypatch.setattr(restore_mod, 'restore_non_dependent_components', fake)

    archive = SimpleNamespace(raw_bytes=_empty_zip_bytes())
    result = await ExistingComponentRestoreAdapter().restore(archive, False, None)

    assert result.filestore == {'ok': True}
    passed_zf = fake.await_args.args[0]
    assert isinstance(passed_zf, zipfile.ZipFile)
    assert fake.await_args.kwargs == {'confirm_sensitive': False}


@pytest.mark.asyncio
async def test_verifier_adapter_delegates(monkeypatch):
    from fastapi_app.services.backup.verify import core as verify_core

    fake = AsyncMock(return_value={'overall': 'ok'})
    monkeypatch.setattr(verify_core, 'verify_restore', fake)

    db = SimpleNamespace()
    result = await ExistingRestoreVerifierAdapter().verify(db, {'users': {}}, None)

    assert result == {'overall': 'ok'}
    fake.assert_awaited_once_with(db, {'users': {}}, None)


@pytest.mark.asyncio
async def test_orchestrator_checksum_uses_crypto_sha256():
    """校验和路径（orchestrator 内惰性导入 sha256_bytes）正常工作。"""
    from fastapi_app.services.backup import crypto
    from fastapi_app.services.backup import orchestrator as orchestrator_module

    data = b'payload'
    archive = SimpleNamespace(
        has=lambda name: name == 'database/dump.sql.gz',
        read=lambda name: data,
    )
    ctx = SimpleNamespace(log=lambda *a, **k: None)

    good = SimpleNamespace(checksums={'database/dump.sql.gz': crypto.sha256_bytes(data)})
    # 方法体不使用 self，unbound 调用即可验证惰性导入路径
    await DatabaseRestoreOrchestrator._validate_database_checksums(None, archive, good, ctx)

    # 注意：orchestrator.py 自定义了与 exceptions.RestoreError 同名但独立的异常类，
    # 此处按抛出方模块取类（同名双类为既有瑕疵，清理项记入 M3）
    bad = SimpleNamespace(checksums={'database/dump.sql.gz': 'deadbeef'})
    with pytest.raises(orchestrator_module.RestoreError):
        await DatabaseRestoreOrchestrator._validate_database_checksums(None, archive, bad, ctx)


def test_format_strategy_generated_key_resolves_from_crypto(monkeypatch):
    from fastapi_app.services.backup import crypto
    from fastapi_app.services.backup import format_strategy as fs

    monkeypatch.setattr(fs, 'BACKUP_ENCRYPTION_PASSWORD', '')
    monkeypatch.setattr(fs, 'BACKUP_ENCRYPTION_KEY', '')
    monkeypatch.setattr(fs, 'BACKUP_ENCRYPTION_ENABLED', True)
    monkeypatch.setattr(fs, 'BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED', True)
    monkeypatch.setattr(crypto, 'generate_encryption_key', lambda: 'GEN-KEY')

    resolved = DefaultBackupFormatStrategy._resolve_password(None, PackOptions(encrypt=True))

    assert resolved == 'GEN-KEY'


# ---------------------------------------------------------------------------
# 3. 加密密码回退（禁止随机密码）
# ---------------------------------------------------------------------------

class TestGetEncryptionPassword:
    def test_password_param_wins(self, monkeypatch):
        monkeypatch.setenv('BACKUP_ENCRYPTION_PASSWORD', 'env-secret')
        assert _deps._get_encryption_password('p1', 'h1') == 'p1'

    def test_header_over_env(self, monkeypatch):
        monkeypatch.setenv('BACKUP_ENCRYPTION_PASSWORD', 'env-secret')
        assert _deps._get_encryption_password(None, 'h1') == 'h1'

    def test_env_used(self, monkeypatch):
        monkeypatch.setenv('BACKUP_ENCRYPTION_PASSWORD', 'env-secret')
        assert _deps._get_encryption_password() == 'env-secret'

    def test_returns_none_when_unconfigured(self, monkeypatch):
        monkeypatch.delenv('BACKUP_ENCRYPTION_PASSWORD', raising=False)
        assert _deps._get_encryption_password() is None


class TestResolveEncryption:
    def test_encrypt_false_short_circuits(self):
        assert _deps._resolve_encryption(False, password='x') == (False, None)

    def test_with_password(self):
        assert _deps._resolve_encryption(True, password='x') == (True, 'x')

    def test_with_header(self):
        assert _deps._resolve_encryption(True, x_backup_password='h') == (True, 'h')

    def test_degrades_to_plain_when_unconfigured(self, monkeypatch):
        monkeypatch.delenv('BACKUP_ENCRYPTION_PASSWORD', raising=False)
        assert _deps._resolve_encryption(True) == (False, None)
