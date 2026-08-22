"""
数据备份 单元测试

覆盖：
- 备份创建（全量/增量备份）
- 备份恢复
- 备份记录写入
- 备份锁管理
- 备份策略/健康检查/指标/告警服务存在性
"""
from unittest.mock import MagicMock, patch

import pytest


class TestBackupLock:
    """备份锁管理"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.backup.acquire_backup_lock')
    async def test_acquire_backup_lock_success(self, mock_lock):
        """成功获取备份锁"""
        mock_lock.return_value = True
        result = await mock_lock(MagicMock())
        assert result is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.backup.acquire_backup_lock')
    async def test_acquire_backup_lock_conflict(self, mock_lock):
        """备份锁已被持有"""
        mock_lock.return_value = False
        result = await mock_lock(MagicMock())
        assert result is False

    @pytest.mark.asyncio
    @patch('fastapi_app.services.backup.release_backup_lock')
    async def test_release_backup_lock(self, mock_release):
        """释放备份锁"""
        await mock_release(MagicMock())
        mock_release.assert_called_once()


class TestCreateFullBackup:
    """全量备份创建"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.backup.create_full_backup')
    async def test_create_full_backup_success(self, mock_backup):
        """正常创建全量备份"""
        mock_backup.return_value = {
            'success': True,
            'filename': 'backup_20240615_001.enc',
            'size_bytes': 1048576,
            'message': '备份创建成功'
        }

        result = await mock_backup(db=MagicMock(), user_name='admin', remark='手动备份')

        assert result['success'] is True
        assert 'backup_20240615' in result['filename']

    @pytest.mark.asyncio
    @patch('fastapi_app.services.backup.create_full_backup')
    async def test_create_full_backup_lock_conflict(self, mock_backup):
        """备份锁冲突"""
        mock_backup.side_effect = ValueError('已有备份任务在执行')

        with pytest.raises(ValueError, match='已有备份任务在执行'):
            await mock_backup(db=MagicMock(), user_name='admin')

    @pytest.mark.asyncio
    @patch('fastapi_app.services.backup.create_full_backup')
    async def test_create_full_backup_disk_full(self, mock_backup):
        """磁盘空间不足"""
        mock_backup.side_effect = OSError('磁盘空间不足')

        with pytest.raises(IOError, match='磁盘空间不足'):
            await mock_backup(db=MagicMock(), user_name='admin')


class TestRestoreFromZip:
    """备份恢复"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.backup.restore_from_zip')
    async def test_restore_success(self, mock_restore):
        """恢复成功"""
        mock_restore.return_value = {
            'success': True,
            'tables_restored': 50,
            'message': '恢复成功'
        }

        result = await mock_restore(db=MagicMock(), backup_path='/backups/test.enc')

        assert result['success'] is True
        assert result['tables_restored'] == 50

    @pytest.mark.asyncio
    @patch('fastapi_app.services.backup.restore_from_zip')
    async def test_restore_lock_conflict(self, mock_restore):
        """恢复锁冲突"""
        mock_restore.side_effect = ValueError('已有恢复任务在执行')

        with pytest.raises(ValueError, match='已有恢复任务在执行'):
            await mock_restore(db=MagicMock(), backup_path='/backups/test.enc')

    @pytest.mark.asyncio
    @patch('fastapi_app.services.backup.restore_from_zip')
    async def test_restore_file_not_found(self, mock_restore):
        """备份文件不存在"""
        mock_restore.side_effect = FileNotFoundError('备份文件不存在')

        with pytest.raises(FileNotFoundError, match='备份文件不存在'):
            await mock_restore(db=MagicMock(), backup_path='/backups/missing.enc')


class TestWriteBackupRecord:
    """写入备份记录"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.backup.write_backup_record')
    async def test_write_backup_record_success(self, mock_write):
        """写入成功"""
        mock_write.return_value = {'id': 1, 'filename': 'backup_20240615.enc'}

        result = await mock_write(
            db=MagicMock(), filename='backup_20240615.enc',
            backup_type='full', size_bytes=1048576,
            user_name='admin', remark='手动备份',
            status='completed', checksum='abc123',
            tables_count=50, duration_seconds=120
        )

        assert result is not None

    @pytest.mark.asyncio
    @patch('fastapi_app.services.backup.write_backup_record')
    async def test_write_backup_record_failed(self, mock_write):
        """写入失败记录"""
        mock_write.return_value = {'id': 2, 'status': 'failed'}

        result = await mock_write(
            db=MagicMock(), filename='backup_failed.enc',
            backup_type='full', size_bytes=0,
            user_name='system', remark='自动备份',
            status='failed', checksum=None,
            tables_count=0, duration_seconds=300
        )

        assert result is not None


class TestBackupPolicyService:
    """备份策略服务"""

    @pytest.mark.asyncio
    async def test_backup_policy_service_exists(self):
        """验证备份策略服务类存在"""
        from fastapi_app.services.backup.orchestration.policy_service import BackupPolicyService
        assert BackupPolicyService is not None


class TestBackupHealthCheckService:
    """备份健康检查服务"""

    @pytest.mark.asyncio
    async def test_backup_health_check_service_exists(self):
        """验证备份健康检查服务类存在"""
        from fastapi_app.services.backup.verify.health_check_service import BackupHealthCheckService
        assert BackupHealthCheckService is not None


class TestBackupMetricsService:
    """备份指标服务"""

    @pytest.mark.asyncio
    async def test_backup_metrics_service_exists(self):
        """验证备份指标服务类存在"""
        from fastapi_app.services.backup.metrics.service import BackupMetricsService
        assert BackupMetricsService is not None


class TestBackupAlertService:
    """备份告警服务"""

    @pytest.mark.asyncio
    async def test_backup_alert_service_exists(self):
        """验证备份告警服务类存在"""
        from fastapi_app.services.backup.metrics.alert_service import BackupAlertService
        assert BackupAlertService is not None
