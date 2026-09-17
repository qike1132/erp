# -*- coding: utf-8 -*-
"""备份健康检查的跨层契约测试（不 mock 生产者）。

历史根因（两次线上假告警）：
- list_backup_files() 返回的 dict 仅含 {'filename', 'size'}（records.py:166），
  消费方却按 {'name', 'mtime'} 取值 → mtime 恒 0 → 「1970-01-01 / 49 万小时前」假告警；
  name 恒 '' → 「备份文件异常: 」空文件名单。
- 既有测试用 {'name','mtime'} 伪造生产者返回，形状与真实生产者不一致 → 缺陷全绿漏检。

本文件用**真实临时目录 + 真实 list_backup_files()** 端到端串起生产者与消费方，
防止同类错配再次入库。
"""
import os
import time
import zipfile
from pathlib import Path

import pytest

from fastapi_app.api.v1.endpoints.backup import validation as validation_mod
from fastapi_app.services import backup as backup_pkg
from fastapi_app.services.backup import records as records_mod


def _make_backup(dirpath: Path, name: str, mtime: float) -> Path:
    """造一个符合命名约定、带合法 zip 结构与指定 mtime 的备份文件。"""
    p = dirpath / name
    with zipfile.ZipFile(p, 'w') as zf:
        zf.writestr('manifest.json', '{"type": "full", "exported_at": "2026-09-17T02:00:00"}')
    os.utime(p, (mtime, mtime))
    return p


@pytest.fixture()
def real_backup_dir(tmp_path, monkeypatch):
    """把生产者与消费方两侧引用的 BACKUP_DIR 同时指向同一临时目录。"""
    monkeypatch.setattr(records_mod, 'BACKUP_DIR', tmp_path)
    monkeypatch.setattr(backup_pkg, 'BACKUP_DIR', tmp_path)
    return tmp_path


class TestLastBackupContract:
    def test_latest_time_comes_from_real_fs_mtime(self, real_backup_dir):
        now = time.time()
        _make_backup(real_backup_dir, 'erp_backup_old.zip', now - 48 * 3600)
        newer = _make_backup(real_backup_dir, 'erp_backup_new.zip', now - 3600)

        result, issues = validation_mod._check_last_backup()

        # 修复前：mtime 恒 0 → 1970-01-01；修复后：必须接近较新文件的真实 mtime
        assert result['status'] == 'healthy', f"应判定 24h 内有备份: {result}"
        assert result['within_24h'] is True
        assert not any('超过24小时' in i for i in issues), f"不应出现超时假告警: {issues}"
        expected = int(newer.stat().st_mtime)
        got = int(__import__('datetime').datetime.fromisoformat(result['latest_backup_time']).timestamp())
        assert abs(got - expected) <= 2, f"latest_backup_time 应来自文件系统 mtime: got={got} want≈{expected}"

    def test_stale_backup_triggers_real_warning(self, real_backup_dir):
        now = time.time()
        _make_backup(real_backup_dir, 'erp_backup_old.zip', now - 72 * 3600)

        result, issues = validation_mod._check_last_backup()

        assert result['status'] == 'warning'
        assert any('超过24小时' in i for i in issues), f"真实超时应有告警: {issues}"
        # 告警小时数必须基于真实 mtime（≈72h），而非 49 万小时
        assert result['hours_since_last_backup'] < 100

    def test_empty_dir_reports_no_backup(self, real_backup_dir):
        result, issues = validation_mod._check_last_backup()
        assert result['status'] == 'warning'
        assert result['latest_backup_time'] is None


class TestIntegrityContract:
    def test_sampled_filenames_are_nonempty(self, real_backup_dir):
        now = time.time()
        for i in range(3):
            _make_backup(real_backup_dir, f'erp_backup_t{i}.zip', now - i * 60)

        result, issues = validation_mod._check_backup_integrity()

        filenames = [r['filename'] for r in result['results']]
        assert all(filenames), f"抽样文件名不得为空（错键根因）: {filenames}"
        assert all(f.startswith('erp_backup_') for f in filenames)
        assert not any(i.startswith('备份文件异常') for i in issues), f"不应出现空文件名假告警: {issues}"
        assert all(r['status'] == 'healthy' for r in result['results'])
