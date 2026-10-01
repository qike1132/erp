"""P0-2：恢复演练脚本 scripts/restore_drill.py 的选包与口令逻辑（函数级测试）。

覆盖三件事：
1. 只 glob erp_backup_*.zip 的旧实现选不到生产加密产物（.zip.enc）→ 必然 SystemExit；
2. .zip.enc.meta 伴随文件比 .enc 更新，不能被当成备份产物选中；
3. 加密包在没有口令时必须显式报错，绝不静默按明文处理。
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PASSPHRASE_ENV = 'BACKUP_ENCRYPTION_PASSWORD'


@pytest.fixture(scope='module')
def drill():
    """导入 scripts.restore_drill，并撤销它导入期的进程级副作用。

    该脚本按设计在导入时就 (a) chdir 到项目根、(b) 注入 DB_NAME=erp_system_drill、
    (c) load_dotenv(.env)。这些副作用对「真跑演练」是安全护栏，但会污染整个 pytest
    会话，因此导入后立即还原环境快照与工作目录；模块内被测试的函数都在调用时读环境，
    不受还原影响。
    """
    pristine_env = dict(os.environ)
    pristine_cwd = os.getcwd()
    module = importlib.import_module('scripts.restore_drill')
    os.environ.clear()
    os.environ.update(pristine_env)
    os.chdir(pristine_cwd)
    return module


def _touch(path: Path, mtime: float, payload: bytes = b'x') -> Path:
    """写入文件并设定期望的 mtime（排序可复现）。"""
    path.write_bytes(payload)
    os.utime(path, (mtime, mtime))
    return path


def _make_zip(path: Path) -> bytes:
    """造一个含 database/dump.sql.gz 的最小备份包，返回其字节。"""
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('database/dump.sql.gz', b'\x1f\x8b\x08\x00')
    return path.read_bytes()


# --- ① 发现与匹配 ---------------------------------------------------------


def test_candidate_accepts_plain_and_encrypted_full_backups(drill):
    assert drill.is_backup_candidate('erp_backup_20261001_070001.zip')
    assert drill.is_backup_candidate('erp_backup_20261001_070001.zip.enc')
    assert drill.is_backup_candidate('erp_auto_daily_20261001_020013.zip.enc')


def test_candidate_rejects_sidecars_incrementals_and_junk(drill):
    assert not drill.is_backup_candidate('erp_backup_20261001_070001.zip.enc.meta')
    assert not drill.is_backup_candidate('erp_backup_20261001_070001.zip.record')
    assert not drill.is_backup_candidate('erp_backup_20261001_070001.zip.meta')
    assert not drill.is_backup_candidate('erp_incremental_20261001_070001.zip.enc')
    assert not drill.is_backup_candidate('erp_backup_20261001_070001.json')
    assert not drill.is_backup_candidate('random.zip')


def test_list_candidates_skips_sidecars_and_sorts_by_mtime(drill, tmp_path):
    old_plain = _touch(tmp_path / 'erp_backup_20260901_000000.zip', 1_700_000_000)
    new_enc = _touch(tmp_path / 'erp_backup_20260901_010000.zip.enc', 1_700_007_200)
    _touch(tmp_path / 'erp_backup_20260901_010000.zip.enc.meta', 1_700_999_999)
    _touch(tmp_path / 'erp_incremental_20260901_010000.zip.enc', 1_700_999_999)
    _touch(tmp_path / 'notes.txt', 1_700_999_999)

    assert drill.list_backup_candidates(tmp_path) == [old_plain, new_enc]
    assert drill.list_backup_candidates(tmp_path / 'does-not-exist') == []


def test_newest_backup_picks_latest_encrypted_artifact(drill, tmp_path):
    """旧实现只匹配 *.zip ⇒ 永远选不到 .enc；这里必须选中加密全量包。"""
    _touch(tmp_path / 'erp_backup_20260901_000000.zip', 1_700_000_000)
    enc = _touch(tmp_path / 'erp_backup_20260901_010000.zip.enc', 1_700_003_600)
    # .meta 的 mtime 比 .enc 更晚（写盘顺序就是如此），但绝不能被选中
    _touch(tmp_path / 'erp_backup_20260901_010000.zip.enc.meta', 1_700_007_200)

    newest = drill.newest_backup(tmp_path)

    assert newest == enc
    assert drill.is_encrypted_backup(newest)


def test_newest_backup_raises_system_exit_without_candidates(drill, tmp_path):
    _touch(tmp_path / 'erp_incremental_20260901_010000.zip.enc', 1_700_000_000)
    with pytest.raises(SystemExit) as excinfo:
        drill.newest_backup(tmp_path)
    assert '未找到' in str(excinfo.value)

    with pytest.raises(SystemExit) as excinfo_missing_dir:
        drill.newest_backup(tmp_path / 'missing')
    assert '未找到' in str(excinfo_missing_dir.value)


# --- ② 口令解析与显式报错 -------------------------------------------------


def test_resolve_passphrase_prefers_cli_then_env(drill, monkeypatch):
    monkeypatch.setenv(PASSPHRASE_ENV, 'env-pass')
    assert drill.resolve_passphrase() == 'env-pass'
    assert drill.resolve_passphrase('cli-pass') == 'cli-pass'

    monkeypatch.delenv(PASSPHRASE_ENV, raising=False)
    assert drill.resolve_passphrase() == ''


def test_encrypted_backup_without_passphrase_raises_explicitly(drill, monkeypatch, tmp_path):
    monkeypatch.delenv(PASSPHRASE_ENV, raising=False)
    enc = tmp_path / 'erp_backup_20260901_010000.zip.enc'

    with pytest.raises(drill.MissingPassphraseError) as excinfo:
        drill.require_passphrase(enc)

    message = str(excinfo.value)
    assert enc.name in message
    assert PASSPHRASE_ENV in message


def test_plain_zip_needs_no_passphrase(drill, monkeypatch, tmp_path):
    monkeypatch.delenv(PASSPHRASE_ENV, raising=False)
    assert drill.require_passphrase(tmp_path / 'erp_backup_20260901_000000.zip') == ''


# --- ③ 打开归档（明文直开 / 密文解密） --------------------------------------


def test_open_backup_archive_plain_zip(drill, tmp_path):
    plain = tmp_path / 'erp_backup_20260901_000000.zip'
    _make_zip(plain)

    zf, temp_path = drill.open_backup_archive(plain)
    try:
        assert temp_path is None
        assert 'database/dump.sql.gz' in zf.namelist()
    finally:
        zf.close()


def test_open_backup_archive_decrypts_encrypted_package(drill, tmp_path):
    from fastapi_app.core.backup_encryption import encrypt_backup_auto

    plain = tmp_path / 'plain.zip'
    payload = _make_zip(plain)
    encrypted_bytes, _meta = encrypt_backup_auto(payload, 'drill-pass')
    enc = tmp_path / 'erp_backup_20260901_010000.zip.enc'
    enc.write_bytes(encrypted_bytes)

    zf, temp_path = drill.open_backup_archive(enc, 'drill-pass')
    try:
        assert temp_path is not None and temp_path.exists()
        assert 'database/dump.sql.gz' in zf.namelist()
        assert zf.read('database/dump.sql.gz') == b'\x1f\x8b\x08\x00'
    finally:
        zf.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        assert temp_path is not None and not temp_path.exists()


def test_open_backup_archive_encrypted_without_passphrase_refuses(drill, monkeypatch, tmp_path):
    """密文 + 无口令 ⇒ 显式报错（绝不把密文当明文交给 psql）。"""
    monkeypatch.delenv(PASSPHRASE_ENV, raising=False)
    enc = tmp_path / 'erp_backup_20260901_010000.zip.enc'
    enc.write_bytes(b'not-really-encrypted')

    with pytest.raises(drill.MissingPassphraseError):
        drill.open_backup_archive(enc)


# --- ④ main(--dry-run)：不连库 -------------------------------------------------


def test_main_dry_run_returns_zero_for_plain_package(drill, monkeypatch, tmp_path):
    monkeypatch.delenv(PASSPHRASE_ENV, raising=False)
    plain = tmp_path / 'erp_backup_20260901_000000.zip'
    _make_zip(plain)

    assert asyncio.run(drill.main(['--dry-run', str(plain)])) == 0


def test_main_dry_run_returns_one_when_dump_missing(drill, monkeypatch, tmp_path):
    monkeypatch.delenv(PASSPHRASE_ENV, raising=False)
    package = tmp_path / 'erp_backup_20260901_000000.zip'
    with zipfile.ZipFile(package, 'w') as zf:
        zf.writestr('manifest.json', '{}')

    assert asyncio.run(drill.main(['--dry-run', str(package)])) == 1


def test_main_dry_run_encrypted_without_passphrase_raises(drill, monkeypatch, tmp_path):
    monkeypatch.delenv(PASSPHRASE_ENV, raising=False)
    enc = tmp_path / 'erp_backup_20260901_010000.zip.enc'
    enc.write_bytes(b'not-really-encrypted')

    with pytest.raises(drill.MissingPassphraseError):
        asyncio.run(drill.main(['--dry-run', str(enc)]))


def test_main_defaults_to_newest_candidate_in_directory(drill, monkeypatch, tmp_path):
    """不传路径时取目录内最新产物 —— 演练默认行为覆盖加密全量包。"""
    monkeypatch.delenv(PASSPHRASE_ENV, raising=False)
    monkeypatch.setattr(drill, 'BACKUP_DIR', tmp_path)
    plain = tmp_path / 'erp_backup_20260901_000000.zip'
    payload = _make_zip(plain)
    os.utime(plain, (1_700_000_000, 1_700_000_000))
    from fastapi_app.core.backup_encryption import encrypt_backup_auto

    encrypted_bytes, _meta = encrypt_backup_auto(payload, 'drill-pass')
    enc = tmp_path / 'erp_backup_20260901_010000.zip.enc'
    enc.write_bytes(encrypted_bytes)
    # 加密包是最新产物（写盘晚于明文包）
    os.utime(enc, (1_700_003_600, 1_700_003_600))
    _touch(tmp_path / 'erp_backup_20260901_010000.zip.enc.meta', 1_700_999_999, b'{}')
    # 无口令时必须点名加密产物并拒绝
    with pytest.raises(drill.MissingPassphraseError) as excinfo:
        asyncio.run(drill.main(['--dry-run']))
    assert enc.name in str(excinfo.value)

    assert asyncio.run(drill.main(['--dry-run', str(enc), 'drill-pass'])) == 0
