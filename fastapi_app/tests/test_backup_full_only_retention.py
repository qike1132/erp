"""全量-only 保留策略回归（2026-10-12）。

覆盖：超天数删、天数内留、至少留 1 个、正在写入跳过、增量文件不扫、伴生文件同删。
"""
import json
import os
from datetime import datetime

import pytest

from fastapi_app.services.backup._constants import RETENTION_DAYS_ENV
from fastapi_app.services.backup.cleanup import service as cleanup_service


def _make(directory, name, *, age_days=0.0, size=8):
    """造一个最小全量文件；age_days 控制 mtime（保留期内用 1 天，避开 120 秒宽限）。"""
    p = directory / name
    p.write_bytes(b'x' * size)
    stamp = datetime.now().timestamp() - age_days * 86400
    os.utime(p, (stamp, stamp))
    return p


def _sidecars(p):
    for s in ('.meta', '.record'):
        (p.parent / (p.name + s)).write_text(
            json.dumps({'created_at': None}), encoding='utf-8')


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    """把清理目标重定向到 tmp_path，并短路 DB 记录删除。"""
    monkeypatch.setattr(cleanup_service, 'BACKUP_DIR', tmp_path)

    async def _no_db(self, deleted_files):
        return len(deleted_files), False

    monkeypatch.setattr(cleanup_service.BackupCleanupService, '_delete_backup_records', _no_db)
    return cleanup_service.BackupCleanupService()


async def test_deletes_full_older_than_retention_days(svc, tmp_path, monkeypatch):
    """20 天前的自动全量 + 保留 7 天 ⇒ 删（另放一份保留期内的，避免触发 keep_floor）。"""
    old = _make(tmp_path, 'erp_auto_daily_20260901_000000.zip', age_days=20)
    _make(tmp_path, 'erp_auto_daily_20261011_000000.zip', age_days=1)
    monkeypatch.setenv(RETENTION_DAYS_ENV, '7')
    result = await svc.smart_cleanup()
    assert result['success'] is True, result
    assert result['summary']['deleted_files'] == 1, result
    assert not old.exists()


async def test_manual_and_auto_are_treated_alike(svc, tmp_path, monkeypatch):
    """手动 erp_backup_ 与自动 erp_auto_daily_ 一视同仁：超期都删。"""
    m = _make(tmp_path, 'erp_backup_20260901_000000.zip', age_days=20)
    a = _make(tmp_path, 'erp_auto_daily_20260901_000000.zip', age_days=20)
    _make(tmp_path, 'erp_auto_daily_20261011_000000.zip', age_days=1)  # 防 keep_floor
    monkeypatch.setenv(RETENTION_DAYS_ENV, '7')
    result = await svc.smart_cleanup()
    assert result['summary']['deleted_files'] == 2, result
    assert not m.exists() and not a.exists()


async def test_keeps_full_within_retention_days(svc, tmp_path, monkeypatch):
    """3 天前的全量 + 保留 7 天 ⇒ 留。"""
    _make(tmp_path, 'erp_auto_daily_20261009_000000.zip', age_days=3)
    monkeypatch.setenv(RETENTION_DAYS_ENV, '7')
    result = await svc.smart_cleanup()
    assert result['summary']['deleted_files'] == 0, result
    assert result['summary']['kept_files'] == 1, result


async def test_never_deletes_all_backups(svc, tmp_path, monkeypatch):
    """全部超期时至少留最新 1 个（Review Focus 1）。"""
    _make(tmp_path, 'erp_auto_daily_20260901_000000.zip', age_days=40)
    newest = _make(tmp_path, 'erp_auto_daily_20260902_000000.zip', age_days=39)
    monkeypatch.setenv(RETENTION_DAYS_ENV, '7')
    result = await svc.smart_cleanup()
    assert result['summary']['kept_files'] >= 1, result
    assert newest.exists(), '最新的一份必须被强制保留'


async def test_skips_file_being_written(svc, tmp_path, monkeypatch):
    """120 秒内仍在写入的全量不处理（Review Focus 2）。"""
    old = _make(tmp_path, 'erp_auto_daily_20260901_000000.zip', age_days=20)  # 超期
    _make(tmp_path, 'erp_auto_daily_20261011_000000.zip', age_days=1)        # 保留期内
    fresh = _make(tmp_path, 'erp_auto_daily_20261012_000000.zip', age_days=0)  # 刚写
    monkeypatch.setenv(RETENTION_DAYS_ENV, '7')
    result = await svc.smart_cleanup()
    assert fresh.exists(), '刚写的备份不得被删'
    assert 'erp_auto_daily_20261012_000000.zip' not in result['cleanup_result']['deleted_files']
    assert not old.exists(), '扫描仍应正常执行（超期的照删）'


async def test_incremental_files_are_not_scanned(svc, tmp_path, monkeypatch):
    """残留的 erp_incremental_* 不扫、不动（Review Focus 3）。

    同时放一份保留期内的全量：total_files == 1 证明增量文件**没进扫描结果**，
    而非"进了扫描但碰巧没删"（旧实现下仅断言没删是恒绿的）。
    """
    inc = _make(tmp_path, 'erp_incremental_20260901_000000.zip', age_days=40)
    _make(tmp_path, 'erp_auto_daily_20261011_000000.zip', age_days=1)
    monkeypatch.setenv(RETENTION_DAYS_ENV, '7')
    result = await svc.smart_cleanup()
    assert result['summary']['total_files'] == 1, result
    assert inc.exists(), '增量文件不在扫描范围内，不应被删'


async def test_sidecars_removed_with_main_file(svc, tmp_path, monkeypatch):
    """删主文件同步删 .meta/.record（Review Focus 4）。"""
    p = _make(tmp_path, 'erp_auto_daily_20260901_000000.zip.enc', age_days=20)
    _sidecars(p)
    _make(tmp_path, 'erp_auto_daily_20261011_000000.zip', age_days=1)  # 防 keep_floor
    monkeypatch.setenv(RETENTION_DAYS_ENV, '7')
    await svc.smart_cleanup()
    assert not p.exists()
    assert not (tmp_path / 'erp_auto_daily_20260901_000000.zip.enc.meta').exists()
    assert not (tmp_path / 'erp_auto_daily_20260901_000000.zip.enc.record').exists()
