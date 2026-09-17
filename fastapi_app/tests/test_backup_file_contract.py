"""备份文件列表契约测试 —— 生产者与消费者的字段名必须一致

背景（真实生产缺陷，2026-09-17）：备份健康检查页出现两条误报

    - "最近备份时间超过24小时（497115.8小时前）"
    - "备份文件异常: "（文件名为空）

根因不在健康检查逻辑本身，而在字段契约断裂：
``services/backup/records.list_backup_files()`` 只返回 ``{'filename', 'size'}``，
而校验侧（``api/v1/endpoints/backup/validation.py``）按 ``name`` / ``mtime`` 取值。
缺失字段被 ``.get(key, default)`` 静默降级：:

    mtime = 0   → 1970-01-01 → 凭空报"超过24小时"
    name  = ''  → BACKUP_DIR / '' → 判定"文件不存在" → "备份文件异常: "

既有单测为何没拦住？因为被测函数的替身伪造了 ``{'name', 'mtime'}`` 这一
**真实生产者从不返回**的形状（见 test_backup_validation_helpers.py），
替身与现实漂移，于是为一份不存在的契约盖了合格章 —— 与"AsyncMock 会合成
不存在的属性"同源的陷阱。

因此本文件**不 mock list_backup_files**：构造真实临时备份目录，让真实生产者
驱动真实消费者。下列测试修复前必失败，修复后必通过。
"""
import os
from pathlib import Path
from unittest.mock import patch

from fastapi_app.api.v1.endpoints.backup import validation
from fastapi_app.services.backup import records as records_mod

_BACKUP_NAME = 'erp_backup_20260917_114339.zip'
_HOUR = 3600


def _make_backup_dir(tmp_path: Path) -> Path:
    """造一个符合正式备份命名约定的真实文件（前缀/后缀需通过 _is_backup_file）"""
    (tmp_path / _BACKUP_NAME).write_bytes(b'PK\x03\x04 fake zip payload')
    return tmp_path


def _age_file(path: Path, hours: float) -> None:
    """把文件 mtime 回拨指定小时数"""
    ts = path.stat().st_mtime - hours * _HOUR
    os.utime(path, (ts, ts))


# ============================================================================
# 生产者输出契约
# ============================================================================
class TestListBackupFilesContract:
    def test_entry_exposes_filename_and_mtime(self, tmp_path):
        """条目必须同时给出 filename（序列化契约）与 mtime（时间判定依据）"""
        d = _make_backup_dir(tmp_path)
        with patch.object(records_mod, 'BACKUP_DIR', d):
            entries = records_mod.list_backup_files()
        assert len(entries) == 1
        entry = entries[0]
        assert entry['filename'] == _BACKUP_NAME
        assert entry['mtime'] > 0, 'mtime 缺失会让"最近备份时间"退化为 1970-01-01'
        assert abs(entry['mtime'] - (d / _BACKUP_NAME).stat().st_mtime) < 1

    def test_entry_keys_satisfy_all_consumers(self, tmp_path):
        """消费方读取的键必须都在生产者输出中，防止再次静默降级为 ''/0"""
        d = _make_backup_dir(tmp_path)
        with patch.object(records_mod, 'BACKUP_DIR', d):
            entries = records_mod.list_backup_files()
        required = {'filename', 'mtime', 'size'}
        assert required <= set(entries[0])

    def test_strict_filename_access_does_not_raise(self, tmp_path):
        """validate-integrity 的 cache_key 用 f['filename'] 硬取键，键名不符会 KeyError"""
        d = _make_backup_dir(tmp_path)
        with patch.object(records_mod, 'BACKUP_DIR', d):
            entries = records_mod.list_backup_files()
        assert '_'.join(sorted(f['filename'] for f in entries)) == _BACKUP_NAME


# ============================================================================
# 健康检查误报回归（真实生产者 → 真实消费者）
# ============================================================================
class TestBackupHealthFalseAlarms:
    def test_fresh_backup_does_not_trigger_24h_alarm(self, tmp_path):
        """刚生成的备份不得报"超过24小时"

        修复前：生产者无 mtime → .get('mtime', 0) → 1970 → 497115.8 小时 → 误报
        """
        d = _make_backup_dir(tmp_path)
        with patch.object(records_mod, 'BACKUP_DIR', d):
            result, issues = validation._check_last_backup()
        assert issues == [], f'新鲜备份不应产生任何告警，实际: {issues}'
        assert result['status'] == 'healthy'
        assert result['within_24h'] is True
        assert result['hours_since_last_backup'] < 1

    def test_stale_backup_still_triggers_24h_alarm(self, tmp_path):
        """"超24小时"检查必须仍然有效 —— 防止修复方式变成"把告警一律静音\""""
        d = _make_backup_dir(tmp_path)
        _age_file(d / _BACKUP_NAME, hours=48)
        with patch.object(records_mod, 'BACKUP_DIR', d):
            result, issues = validation._check_last_backup()
        assert result['status'] == 'warning'
        assert result['within_24h'] is False
        assert any('超过24小时' in i for i in issues)
        assert 47 < result['hours_since_last_backup'] < 49

    def test_integrity_check_uses_real_filename(self, tmp_path):
        """完整性抽样不得因取不到文件名而报"备份文件异常: "

        修复前：file_info.get('name', '') → '' → BACKUP_DIR / '' → 非普通文件 → 误报
        """
        d = _make_backup_dir(tmp_path)
        with patch.object(records_mod, 'BACKUP_DIR', d), \
             patch.object(validation.backup_service, 'BACKUP_DIR', d):
            result, issues = validation._check_backup_integrity()
        assert issues == [], f'真实存在的备份不应报异常，实际: {issues}'
        assert result['status'] == 'healthy'
        assert result['results'][0]['filename'] == _BACKUP_NAME
        assert result['results'][0]['readable'] is True

    def test_unreadable_entry_is_skipped_not_fatal(self, tmp_path):
        """扫描期间文件被保留策略删除（stat 抛 OSError）应跳过该条，而非整页报错"""
        d = _make_backup_dir(tmp_path)
        real_stat = Path.stat

        def flaky_stat(self, *args, **kwargs):
            if self.name == _BACKUP_NAME:
                raise FileNotFoundError(2, 'No such file or directory', str(self))
            return real_stat(self, *args, **kwargs)

        with patch.object(records_mod, 'BACKUP_DIR', d), \
             patch.object(records_mod, '_is_backup_file', lambda f: True), \
             patch.object(Path, 'stat', flaky_stat):
            entries = records_mod.list_backup_files()
        assert entries == []
