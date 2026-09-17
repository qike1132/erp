"""backup/validation.py 中提取的健康检查 helper 函数 - 单元测试

覆盖 P1-1 重构提取的 helper：
- _check_backup_dir / _check_database / _check_redis
- _check_last_backup / _check_backup_integrity / _check_disk_space
- _aggregate_health_status
"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.api.v1.endpoints.backup import validation


# ============================================================================
# _check_backup_dir
# ============================================================================
class TestCheckBackupDir:
    @pytest.mark.asyncio
    async def test_check_backup_dir_writable_returns_healthy(self, tmp_path):
        """备份目录存在且可写时应返回 healthy 状态"""
        with patch.object(validation.backup_service, 'BACKUP_DIR', tmp_path):
            result, issues = await validation._check_backup_dir()
        assert result['status'] == 'healthy'
        assert result['writable'] is True
        assert issues == []

    @pytest.mark.asyncio
    async def test_check_backup_dir_missing_creates_and_warns(self, tmp_path):
        """备份目录不存在时应自动创建并返回 warning"""
        target = tmp_path / "nonexistent_subdir"
        with patch.object(validation.backup_service, 'BACKUP_DIR', target):
            result, _issues = await validation._check_backup_dir()
        assert result['status'] == 'warning'
        assert '已自动创建' in result['message']
        assert target.exists()

    @pytest.mark.asyncio
    async def test_check_backup_dir_not_writable_returns_unhealthy(self, tmp_path):
        """备份目录不可写时应返回 unhealthy 并记录 issue"""
        with patch.object(validation.backup_service, 'BACKUP_DIR', tmp_path), \
             patch('pathlib.Path.touch', side_effect=PermissionError("denied")):
            result, issues = await validation._check_backup_dir()
        assert result['status'] == 'unhealthy'
        assert result['writable'] is False
        assert any('不可写' in i for i in issues)


# ============================================================================
# _check_database
# ============================================================================
class TestCheckDatabase:
    @pytest.mark.asyncio
    async def test_check_database_alive_returns_healthy(self):
        """数据库连通正常时应返回 healthy"""
        with patch('fastapi_app.services.backup.verify.query_service.check_database_alive',
                    new=AsyncMock(return_value=True)):
            result, issues = await validation._check_database()
        assert result['status'] == 'healthy'
        assert result['connected'] is True
        assert issues == []

    @pytest.mark.asyncio
    async def test_check_database_down_returns_unhealthy(self):
        """数据库连接失败时应返回 unhealthy 并记录 issue"""
        with patch('fastapi_app.services.backup.verify.query_service.check_database_alive',
                    new=AsyncMock(return_value=False)):
            result, issues = await validation._check_database()
        assert result['status'] == 'unhealthy'
        assert result['connected'] is False
        assert any('数据库连接失败' in i for i in issues)

    @pytest.mark.asyncio
    async def test_check_database_exception_returns_unhealthy(self):
        """check_database_alive 抛异常时应捕获并返回 unhealthy"""
        with patch('fastapi_app.services.backup.verify.query_service.check_database_alive',
                    new=AsyncMock(side_effect=RuntimeError("conn refused"))):
            result, issues = await validation._check_database()
        assert result['status'] == 'unhealthy'
        assert 'error' in result
        assert any('检查失败' in i for i in issues)


# ============================================================================
# _check_redis
# ============================================================================
class TestCheckRedis:
    @pytest.mark.asyncio
    async def test_check_redis_connected_returns_healthy(self):
        """Redis ping 成功时应返回 healthy"""
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)
        mock_cache = MagicMock()
        mock_cache.redis_client = mock_client
        with patch('utils.redis_cache.redis_cache', mock_cache):
            result, issues = await validation._check_redis()
        assert result['status'] == 'healthy'
        assert result['connected'] is True
        assert issues == []

    @pytest.mark.asyncio
    async def test_check_redis_client_none_returns_warning(self):
        """Redis 客户端未初始化时应返回 warning"""
        mock_cache = MagicMock()
        mock_cache.redis_client = None
        with patch('utils.redis_cache.redis_cache', mock_cache):
            result, issues = await validation._check_redis()
        assert result['status'] == 'warning'
        assert result['connected'] is False
        assert any('未初始化' in i for i in issues)

    @pytest.mark.asyncio
    async def test_check_redis_ping_fails_returns_warning(self):
        """Redis ping 抛异常时应降级为 warning（不影响核心功能）"""
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(side_effect=ConnectionError("timeout"))
        mock_cache = MagicMock()
        mock_cache.redis_client = mock_client
        with patch('utils.redis_cache.redis_cache', mock_cache):
            result, _issues = await validation._check_redis()
        assert result['status'] == 'warning'
        assert result['connected'] is False


# ============================================================================
# _check_last_backup
# ============================================================================
class TestCheckLastBackup:
    @staticmethod
    def _use_real_dir(tmp_path, monkeypatch):
        """真实临时目录方案：替身形状必须镜像真实生产者（{'filename','size'}，无 mtime）。

        历史教训：旧版用 {'filename','mtime'} 伪造 list_backup_files 返回，
        与真实生产者（records.py:166 仅含 filename/size）不一致，导致
        「1970-01-01」缺陷长期全绿漏检。改为真实文件系统 + 真实生产者。"""
        import zipfile as _zipfile
        from fastapi_app.services.backup import records as _records
        monkeypatch.setattr(_records, 'BACKUP_DIR', tmp_path)
        monkeypatch.setattr(validation.backup_service, 'BACKUP_DIR', tmp_path)
        return _zipfile

    def test_check_last_backup_recent_returns_healthy(self, tmp_path, monkeypatch):
        """最近备份在 24h 内应返回 healthy"""
        import os, time
        zipfile = self._use_real_dir(tmp_path, monkeypatch)
        p = tmp_path / 'erp_backup_recent.zip'
        with zipfile.ZipFile(p, 'w') as zf:
            zf.writestr('manifest.json', '{}')
        recent = time.time() - 2 * 3600
        os.utime(p, (recent, recent))
        result, issues = validation._check_last_backup()
        assert result['status'] == 'healthy'
        assert result['within_24h'] is True
        assert result['hours_since_last_backup'] is not None
        assert issues == []

    def test_check_last_backup_stale_returns_warning(self, tmp_path, monkeypatch):
        """最近备份超过 24h 应返回 warning 并记录 issue"""
        import os, time
        zipfile = self._use_real_dir(tmp_path, monkeypatch)
        p = tmp_path / 'erp_backup_old.zip'
        with zipfile.ZipFile(p, 'w') as zf:
            zf.writestr('manifest.json', '{}')
        stale = time.time() - 48 * 3600
        os.utime(p, (stale, stale))
        result, issues = validation._check_last_backup()
        assert result['status'] == 'warning'
        assert result['within_24h'] is False
        assert any('超过24小时' in i for i in issues)

    def test_check_last_backup_no_files_returns_warning(self):
        """无备份文件时应返回 warning"""
        with patch.object(validation.backup_service, 'list_backup_files', return_value=[]):
            result, issues = validation._check_last_backup()
        assert result['status'] == 'warning'
        assert result['latest_backup_time'] is None
        assert any('未找到' in i for i in issues)

    def test_check_last_backup_exception_returns_unhealthy(self):
        """list_backup_files 抛异常时应返回 unhealthy"""
        with patch.object(validation.backup_service, 'list_backup_files',
                          side_effect=OSError("disk error")):
            result, _issues = validation._check_last_backup()
        assert result['status'] == 'unhealthy'
        assert 'error' in result


# ============================================================================
# _check_backup_integrity
# ============================================================================
class TestCheckBackupIntegrity:
    def test_check_backup_integrity_no_files_returns_warning(self):
        """无备份文件时应返回 warning 且 sample_size=0"""
        with patch.object(validation.backup_service, 'list_backup_files', return_value=[]):
            result, _issues = validation._check_backup_integrity()
        assert result['status'] == 'warning'
        assert result['sample_size'] == 0
        assert result['results'] == []

    def test_check_backup_integrity_all_healthy(self, tmp_path):
        """所有抽样文件完整可读时应返回 healthy"""
        f = tmp_path / "ok.zip"
        f.write_bytes(b"data")
        files = [{'filename': 'ok.zip', 'mtime': 0}]
        with patch.object(validation.backup_service, 'list_backup_files', return_value=files), \
             patch.object(validation.backup_service, 'BACKUP_DIR', tmp_path):
            result, _issues = validation._check_backup_integrity()
        assert result['status'] == 'healthy'
        assert result['sample_size'] == 1
        assert result['results'][0]['readable'] is True

    def test_check_backup_integrity_missing_file_returns_degraded(self, tmp_path):
        """抽样文件不存在时应返回 degraded 并记录 issue"""
        files = [{'filename': 'ghost.zip', 'mtime': 0}]
        with patch.object(validation.backup_service, 'list_backup_files', return_value=files), \
             patch.object(validation.backup_service, 'BACKUP_DIR', tmp_path):
            result, issues = validation._check_backup_integrity()
        assert result['status'] == 'degraded'
        assert result['results'][0]['readable'] is False
        assert any('ghost.zip' in i for i in issues)


# ============================================================================
# _check_disk_space
# ============================================================================
class TestCheckDiskSpace:
    def test_check_disk_space_sufficient_returns_healthy(self, tmp_path):
        """磁盘可用空间充足时应返回 healthy"""
        with patch.object(validation.backup_service, 'BACKUP_DIR', tmp_path), \
             patch('shutil.disk_usage', return_value=MagicMock(total=100 * 1024**3, used=50 * 1024**3, free=50 * 1024**3)):
            result, _issues = validation._check_disk_space()
        assert result['status'] == 'healthy'
        assert result['sufficient'] is True
        assert result['free_percent'] > 10

    def test_check_disk_space_low_returns_warning(self, tmp_path):
        """磁盘可用空间低于 10% 时应返回 warning 并记录 issue"""
        with patch.object(validation.backup_service, 'BACKUP_DIR', tmp_path), \
             patch('shutil.disk_usage', return_value=MagicMock(total=100 * 1024**3, used=92 * 1024**3, free=8 * 1024**3)):
            result, issues = validation._check_disk_space()
        assert result['status'] == 'warning'
        assert result['sufficient'] is False
        assert any('磁盘空间不足' in i for i in issues)

    def test_check_disk_space_critical_returns_warning_with_issue(self, tmp_path):
        """磁盘可用空间低于 5% 时应记录严重不足 issue"""
        with patch.object(validation.backup_service, 'BACKUP_DIR', tmp_path), \
             patch('shutil.disk_usage', return_value=MagicMock(total=100 * 1024**3, used=97 * 1024**3, free=3 * 1024**3)):
            result, issues = validation._check_disk_space()
        assert result['status'] == 'warning'
        assert any('严重不足' in i for i in issues)

    def test_check_disk_space_dir_missing_returns_warning(self, tmp_path):
        """备份目录不存在时应返回 warning 且 sufficient=None"""
        missing = tmp_path / "no_such_dir"
        with patch.object(validation.backup_service, 'BACKUP_DIR', missing):
            result, _issues = validation._check_disk_space()
        assert result['status'] == 'warning'
        assert result['sufficient'] is None


# ============================================================================
# _aggregate_health_status
# ============================================================================
class TestAggregateHealthStatus:
    def test_aggregate_all_healthy_returns_healthy(self):
        """所有检查项 healthy 时应聚合为 healthy"""
        checks = {'a': {'status': 'healthy'}, 'b': {'status': 'healthy'}}
        assert validation._aggregate_health_status(checks) == 'healthy'

    def test_aggregate_returns_worst_status_unhealthy(self):
        """含 unhealthy 时应聚合为 unhealthy（最高优先级）"""
        checks = {'a': {'status': 'healthy'}, 'b': {'status': 'warning'}, 'c': {'status': 'unhealthy'}}
        assert validation._aggregate_health_status(checks) == 'unhealthy'

    def test_aggregate_returns_degraded_when_present(self):
        """含 degraded 时应聚合为 degraded"""
        checks = {'a': {'status': 'healthy'}, 'b': {'status': 'degraded'}}
        assert validation._aggregate_health_status(checks) == 'degraded'

    def test_aggregate_returns_warning_when_only_warning(self):
        """仅含 warning 时应聚合为 warning"""
        checks = {'a': {'status': 'warning'}, 'b': {'status': 'healthy'}}
        assert validation._aggregate_health_status(checks) == 'warning'

    def test_aggregate_empty_checks_returns_healthy(self):
        """空检查字典应返回 healthy"""
        assert validation._aggregate_health_status({}) == 'healthy'

    def test_aggregate_unknown_status_treated_as_low_priority(self):
        """未知状态应按低优先级处理（不覆盖已有 healthy）"""
        checks = {'a': {'status': 'healthy'}, 'b': {'status': 'unknown_status'}}
        assert validation._aggregate_health_status(checks) == 'healthy'

    def test_aggregate_missing_status_key_defaults_healthy(self):
        """缺少 status 键时应默认为 healthy"""
        checks = {'a': {'other_key': 'value'}}
        assert validation._aggregate_health_status(checks) == 'healthy'
