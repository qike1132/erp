"""
备份健康检查服务单元测试
"""

import json
import os
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fastapi_app.services.backup.verify.health_check_service import BackupHealthCheckService


class TestBackupHealthCheckService:
    """备份健康检查服务测试类"""

    @pytest.fixture
    def health_check_service(self):
        """创建健康检查服务实例（环境变量在整个用例期间生效）"""
        with patch.dict(os.environ, {
            'BACKUP_DISK_SPACE_THRESHOLD': '10.0',
            'BACKUP_AGE_THRESHOLD': '24',
            'BACKUP_INTEGRITY_SAMPLE_RATE': '10.0',
            'BACKUP_RECOVERY_TEST_FREQUENCY': '7',
            'BACKUP_HEALTH_CHECK_INTERVAL': '61',
            'BACKUP_REPORT_RETENTION_DAYS': '30',
        }):
            service = BackupHealthCheckService()
            service.__init__()
            yield service

    @pytest.fixture
    def mock_backup_dir(self):
        """创建模拟备份目录"""
        with tempfile.TemporaryDirectory() as temp_dir:
            backup_dir = Path(temp_dir) / 'backups'
            backup_dir.mkdir(parents=True)

            # 创建一些模拟备份文件
            for i in range(3):
                backup_file = backup_dir / f'erp_backup_2024010{i+1}_120000.zip'
                with zipfile.ZipFile(backup_file, 'w') as zf:
                    # 添加manifest.json
                    manifest = {
                        'version': '2.0',
                        'type': 'full',
                        'exported_at': '2024-01-01 12:00:00',
                        'exported_by': 'test_user',
                        'table_count': 10,
                        'total_rows': 1000,
                        'checksums': {
                            'database/dump.json': 'test_hash'
                        }
                    }
                    zf.writestr('manifest.json', json.dumps(manifest))

                    # 添加metadata.json
                    metadata = {
                        'backup_time': '2024-01-01 12:00:00',
                        'backup_type': 'full'
                    }
                    zf.writestr('metadata.json', json.dumps(metadata))

                    # 添加数据文件
                    zf.writestr('database/dump.json', json.dumps({'test': 'data'}))

            yield backup_dir

    def test_load_health_config(self, health_check_service):
        """测试加载健康检查配置"""
        config = health_check_service._load_health_config()

        assert 'disk_space_threshold' in config
        assert 'backup_age_threshold' in config
        assert 'integrity_sample_rate' in config
        assert 'recovery_test_frequency' in config
        assert 'health_check_interval' in config
        assert 'report_retention_days' in config

        assert config['disk_space_threshold'] == 10.0
        assert config['backup_age_threshold'] == 24
        assert config['integrity_sample_rate'] == 10.0
        assert config['recovery_test_frequency'] == 7
        assert config['health_check_interval'] == 61
        assert config['report_retention_days'] == 30

    @pytest.mark.asyncio
    async def test_check_disk_space(self, health_check_service):
        """测试检查磁盘空间"""
        with patch('psutil.disk_usage') as mock_disk_usage:
            # 模拟磁盘使用情况（空间充足）
            mock_disk_usage.return_value = MagicMock(
                total=100 * 1024 ** 3,  # 100GB
                used=80 * 1024 ** 3,     # 80GB
                free=20 * 1024 ** 3,      # 20GB
                percent=80.0
            )

            result = await health_check_service._check_disk_space()

            assert 'healthy' in result
            assert 'path' in result
            assert 'total_gb' in result
            assert 'used_gb' in result
            assert 'free_gb' in result
            assert 'used_percent' in result
            assert 'free_percent' in result
            assert 'threshold_percent' in result

            assert result['healthy'] is True
            assert result['free_percent'] == 20.0
            assert result['threshold_percent'] == 10.0

        with patch('psutil.disk_usage') as mock_disk_usage:
            # 模拟磁盘使用情况（空间不足）
            mock_disk_usage.return_value = MagicMock(
                total=100 * 1024 ** 3,  # 100GB
                used=95 * 1024 ** 3,     # 95GB
                free=5 * 1024 ** 3,      # 5GB
                percent=95.0
            )

            result = await health_check_service._check_disk_space()

            assert result['healthy'] is False
            assert result['free_percent'] == 5.0
            assert 'issue' in result
            assert '磁盘空间不足' in result['issue']

    @pytest.mark.asyncio
    async def test_check_backup_age(self, health_check_service, mock_backup_dir):
        """测试检查备份时间"""
        with patch('fastapi_app.services.backup.verify.health_check_service.BACKUP_DIR', mock_backup_dir), \
             patch('fastapi_app.services.backup.verify.health_check_service.ensure_backup_dir'):

            # 创建一些备份文件
            for i in range(3):
                backup_file = mock_backup_dir / f'test_backup_{i}.zip'
                backup_file.touch()
                # 设置不同的修改时间
                mtime = (datetime.now() - timedelta(hours=i*12)).timestamp()
                os.utime(backup_file, (mtime, mtime))

            result = await health_check_service._check_backup_age()

            assert 'healthy' in result
            assert 'latest_backup' in result
            assert 'latest_backup_time' in result
            assert 'age_hours' in result
            assert 'threshold_hours' in result

            # 最新备份应该小于24小时
            assert result['age_hours'] <= 24
            assert result['healthy'] is True

    @pytest.mark.asyncio
    async def test_check_backup_age_no_backups(self, health_check_service):
        """测试检查备份时间（无备份文件）"""
        with tempfile.TemporaryDirectory() as temp_dir:
            empty_dir = Path(temp_dir)

            with patch('fastapi_app.services.backup.verify.health_check_service.BACKUP_DIR', empty_dir), \
                 patch('fastapi_app.services.backup.verify.health_check_service.ensure_backup_dir'):

                result = await health_check_service._check_backup_age()

                assert result['healthy'] is False
                assert result['latest_backup'] is None
                assert result['age_hours'] is None
                assert '未找到备份文件' in result['issue']

    @pytest.mark.asyncio
    async def test_check_backup_age_old_backup(self, health_check_service, mock_backup_dir):
        """测试检查备份时间（旧备份）"""
        with patch('fastapi_app.services.backup.verify.health_check_service.BACKUP_DIR', mock_backup_dir), \
             patch('fastapi_app.services.backup.verify.health_check_service.ensure_backup_dir'):

            # 清理 fixture 创建的近期备份，确保目录中仅有旧备份场景
            for f in mock_backup_dir.glob('erp_backup_*.zip'):
                f.unlink()

            # 创建一个很旧的备份文件
            old_backup = mock_backup_dir / 'old_backup.zip'
            old_backup.touch()
            mtime = (datetime.now() - timedelta(days=2)).timestamp()
            os.utime(old_backup, (mtime, mtime))

            result = await health_check_service._check_backup_age()

            assert result['healthy'] is False
            assert result['age_hours'] > 24
            assert '备份文件过旧' in result['issue']

    @pytest.mark.asyncio
    async def test_check_single_backup_integrity_valid(self, health_check_service, mock_backup_dir):
        """测试检查单个备份文件完整性（有效文件）"""
        # 创建有效的备份文件
        backup_file = mock_backup_dir / 'valid_backup.zip'
        with zipfile.ZipFile(backup_file, 'w') as zf:
            manifest = {
                'version': '2.0',
                'type': 'full',
                'table_count': 10,
                'total_rows': 1000
            }
            zf.writestr('manifest.json', json.dumps(manifest))
            zf.writestr('metadata.json', json.dumps({'backup_time': '2024-01-01 12:00:00'}))
            zf.writestr('database/dump.json', json.dumps({'test': 'data'}))

        result = await health_check_service._check_single_backup_integrity(backup_file)

        assert result['filename'] == 'valid_backup.zip'
        assert result['healthy'] is True
        assert 'file_size_mb' in result
        assert 'last_modified' in result

    @pytest.mark.asyncio
    async def test_check_single_backup_integrity_missing_manifest(self, health_check_service, mock_backup_dir):
        """测试检查单个备份文件完整性（缺少manifest）"""
        # 创建缺少manifest的备份文件
        backup_file = mock_backup_dir / 'invalid_backup.zip'
        with zipfile.ZipFile(backup_file, 'w') as zf:
            zf.writestr('database/dump.json', json.dumps({'test': 'data'}))

        result = await health_check_service._check_single_backup_integrity(backup_file)

        assert result['filename'] == 'invalid_backup.zip'
        assert result['healthy'] is False
        assert '缺少必要文件' in result['issue']

    @pytest.mark.asyncio
    async def test_check_single_backup_integrity_corrupted(self, health_check_service, mock_backup_dir):
        """测试检查单个备份文件完整性（损坏文件）"""
        # 创建损坏的备份文件
        backup_file = mock_backup_dir / 'corrupted_backup.zip'
        backup_file.write_bytes(b'invalid zip data')

        result = await health_check_service._check_single_backup_integrity(backup_file)

        assert result['filename'] == 'corrupted_backup.zip'
        assert result['healthy'] is False
        assert 'ZIP文件损坏' in result['issue'] or '完整性检查异常' in result['issue']

    @pytest.mark.asyncio
    async def test_check_single_backup_integrity_empty_file(self, health_check_service, mock_backup_dir):
        """测试检查单个备份文件完整性（空文件）"""
        # 创建空文件
        backup_file = mock_backup_dir / 'empty_backup.zip'
        backup_file.touch()

        result = await health_check_service._check_single_backup_integrity(backup_file)

        assert result['filename'] == 'empty_backup.zip'
        assert result['healthy'] is False
        assert '文件大小为0' in result['issue']

    @pytest.mark.asyncio
    async def test_check_single_backup_integrity_nonexistent(self, health_check_service, mock_backup_dir):
        """测试检查单个备份文件完整性（不存在文件）"""
        backup_file = mock_backup_dir / 'nonexistent_backup.zip'

        result = await health_check_service._check_single_backup_integrity(backup_file)

        assert result['filename'] == 'nonexistent_backup.zip'
        assert result['healthy'] is False
        assert '文件不存在' in result['issue']

    @pytest.mark.asyncio
    async def test_check_backup_integrity(self, health_check_service, mock_backup_dir):
        """测试检查备份文件完整性"""
        with patch('fastapi_app.services.backup.verify.health_check_service.BACKUP_DIR', mock_backup_dir), \
             patch('fastapi_app.services.backup.verify.health_check_service.ensure_backup_dir'):

            # 创建一些备份文件
            for i in range(5):
                backup_file = mock_backup_dir / f'backup_{i}.zip'
                with zipfile.ZipFile(backup_file, 'w') as zf:
                    manifest = {
                        'version': '2.0',
                        'type': 'full',
                        'table_count': 10,
                        'total_rows': 1000,
                        'checksums': {
                            'database/dump.json': 'test_hash'
                        }
                    }
                    zf.writestr('manifest.json', json.dumps(manifest))
                    zf.writestr('metadata.json', json.dumps({'backup_time': '2024-01-01 12:00:00'}))
                    zf.writestr('database/dump.json', json.dumps({'test': 'data'}))

            result = await health_check_service._check_backup_integrity()

            assert 'healthy' in result
            assert 'checked_files' in result
            assert 'passed_files' in result
            assert 'failed_files' in result
            assert 'issues' in result
            assert 'details' in result

            # 应该检查所有文件
            assert result['checked_files'] > 0
            # 所有文件应该通过检查
            assert result['passed_files'] == result['checked_files']
            assert result['failed_files'] == 0
            assert result['healthy'] is True

    @pytest.mark.asyncio
    async def test_check_backup_integrity_with_corrupted(self, health_check_service, mock_backup_dir):
        """测试检查备份文件完整性（有损坏文件）"""
        with patch('fastapi_app.services.backup.verify.health_check_service.BACKUP_DIR', mock_backup_dir), \
             patch('fastapi_app.services.backup.verify.health_check_service.ensure_backup_dir'):

            # 创建有效备份文件
            valid_backup = mock_backup_dir / 'valid_backup.zip'
            with zipfile.ZipFile(valid_backup, 'w') as zf:
                manifest = {
                    'version': '2.0',
                    'type': 'full',
                    'table_count': 10,
                    'total_rows': 1000,
                    'checksums': {
                        'database/dump.json': 'test_hash'
                    }
                }
                zf.writestr('manifest.json', json.dumps(manifest))
                zf.writestr('metadata.json', json.dumps({'backup_time': '2024-01-01 12:00:00'}))
                zf.writestr('database/dump.json', json.dumps({'test': 'data'}))

            # 创建损坏备份文件
            corrupted_backup = mock_backup_dir / 'corrupted_backup.zip'
            corrupted_backup.write_bytes(b'invalid zip data')

            result = await health_check_service._check_backup_integrity()

            assert result['healthy'] is False
            assert result['failed_files'] > 0
            assert len(result['issues']) > 0

    @pytest.mark.asyncio
    async def test_check_system_resources(self, health_check_service):
        """测试检查系统资源"""
        with patch('psutil.cpu_percent') as mock_cpu_percent, \
             patch('psutil.virtual_memory') as mock_virtual_memory, \
             patch('psutil.disk_io_counters') as mock_disk_io:

            # 模拟正常系统资源
            mock_cpu_percent.return_value = 50.0
            mock_virtual_memory.return_value = MagicMock(
                percent=60.0,
                available=8 * 1024 ** 3,  # 8GB
                used=12 * 1024 ** 3,       # 12GB
                total=20 * 1024 ** 3        # 20GB
            )
            mock_disk_io.return_value = MagicMock(
                busy_time=1000
            )

            result = await health_check_service._check_system_resources()

            assert 'healthy' in result
            assert 'cpu_percent' in result
            assert 'memory_percent' in result
            assert 'memory_available_gb' in result
            assert 'memory_used_gb' in result
            assert 'memory_total_gb' in result
            assert 'disk_busy_time' in result
            assert 'issues' in result

            assert result['healthy'] is True
            assert result['cpu_percent'] == 50.0
            assert result['memory_percent'] == 60.0
            assert result['memory_available_gb'] == 8.0
            assert result['memory_used_gb'] == 12.0
            assert result['memory_total_gb'] == 20.0
            assert result['disk_busy_time'] == 1000
            assert len(result['issues']) == 0

        with patch('psutil.cpu_percent') as mock_cpu_percent, \
             patch('psutil.virtual_memory') as mock_virtual_memory:

            # 模拟高CPU使用率
            mock_cpu_percent.return_value = 95.0
            mock_virtual_memory.return_value = MagicMock(
                percent=60.0,
                available=8 * 1024 ** 3,
                used=12 * 1024 ** 3,
                total=20 * 1024 ** 3
            )

            result = await health_check_service._check_system_resources()

            assert result['healthy'] is False
            assert 'CPU使用率过高' in '; '.join(result['issues'])

    def test_generate_recommendations(self, health_check_service):
        """测试生成建议"""
        # 测试正常情况
        results = {
            'overall_status': 'healthy',
            'checks': {
                'disk_space': {'healthy': True, 'free_percent': 30.0, 'threshold_percent': 10.0},
                'backup_age': {'healthy': True, 'age_hours': 12.0, 'threshold_hours': 24},
                'backup_integrity': {'healthy': True, 'failed_files': 0},
                'backup_records': {'healthy': True, 'failed_count': 0, 'success_rate': 100.0},
                'system_resources': {'healthy': True, 'cpu_percent': 50.0, 'memory_percent': 60.0}
            }
        }

        recommendations = health_check_service._generate_recommendations(results)

        # 所有检查都正常，应该有正面反馈
        assert len(recommendations) == 1
        assert '运行良好' in recommendations[0]

        # 测试磁盘空间不足
        results['checks']['disk_space'] = {
            'healthy': False,
            'free_percent': 5.0,
            'threshold_percent': 10.0
        }
        results['overall_status'] = 'warning'

        recommendations = health_check_service._generate_recommendations(results)

        assert len(recommendations) >= 1
        assert any('磁盘空间不足' in rec for rec in recommendations)

        # 测试备份文件过旧
        results['checks']['backup_age'] = {
            'healthy': False,
            'age_hours': 48.0,
            'threshold_hours': 24
        }

        recommendations = health_check_service._generate_recommendations(results)

        assert len(recommendations) >= 2
        assert any('备份文件过旧' in rec for rec in recommendations)

        # 测试备份完整性检查失败
        results['checks']['backup_integrity'] = {
            'healthy': False,
            'failed_files': 2
        }
        results['overall_status'] = 'error'

        recommendations = health_check_service._generate_recommendations(results)

        assert len(recommendations) >= 3
        assert any('完整性检查失败' in rec for rec in recommendations)

        # 测试备份记录问题
        results['checks']['backup_records'] = {
            'healthy': False,
            'failed_count': 3,
            'success_rate': 70.0
        }

        recommendations = health_check_service._generate_recommendations(results)

        assert len(recommendations) >= 4
        assert any('备份成功率较低' in rec for rec in recommendations)

        # 测试系统资源紧张
        results['checks']['system_resources'] = {
            'healthy': False,
            'cpu_percent': 95.0,
            'memory_percent': 90.0
        }

        recommendations = health_check_service._generate_recommendations(results)

        assert len(recommendations) >= 5
        assert any('系统资源紧张' in rec for rec in recommendations)

    @pytest.mark.asyncio
    async def test_perform_health_check(self, health_check_service):
        """测试执行健康检查"""
        with patch.object(health_check_service, '_check_disk_space') as mock_disk, \
             patch.object(health_check_service, '_check_backup_age') as mock_age, \
             patch.object(health_check_service, '_check_backup_integrity') as mock_integrity, \
             patch.object(health_check_service, '_check_backup_records') as mock_records, \
             patch.object(health_check_service, '_check_system_resources') as mock_system, \
             patch.object(health_check_service, '_store_health_report') as mock_store, \
             patch.object(health_check_service, '_alert_on_issues') as mock_alert:

            # 模拟所有检查都通过
            mock_disk.return_value = {'healthy': True, 'free_percent': 30.0}
            mock_age.return_value = {'healthy': True, 'age_hours': 12.0}
            mock_integrity.return_value = {'healthy': True, 'failed_files': 0}
            mock_records.return_value = {'healthy': True, 'failed_count': 0, 'success_rate': 100.0}
            mock_system.return_value = {'healthy': True, 'cpu_percent': 50.0, 'memory_percent': 60.0}

            result = await health_check_service.perform_health_check()

            assert 'check_time' in result
            assert 'overall_status' in result
            assert 'checks' in result
            assert 'issues' in result
            assert 'recommendations' in result

            assert result['overall_status'] == 'healthy'
            assert len(result['issues']) == 0
            assert len(result['recommendations']) == 1  # 正面反馈

            # 验证方法被调用
            mock_disk.assert_called_once()
            mock_age.assert_called_once()
            mock_integrity.assert_called_once()
            mock_records.assert_called_once()
            mock_system.assert_called_once()
            mock_store.assert_called_once()
            mock_alert.assert_not_called()  # 没有问题，不发送告警

        with patch.object(health_check_service, '_check_disk_space') as mock_disk, \
             patch.object(health_check_service, '_check_backup_age') as mock_age, \
             patch.object(health_check_service, '_check_backup_integrity') as mock_integrity, \
             patch.object(health_check_service, '_check_backup_records') as mock_records, \
             patch.object(health_check_service, '_check_system_resources') as mock_system, \
             patch.object(health_check_service, '_store_health_report') as mock_store, \
             patch.object(health_check_service, '_alert_on_issues') as mock_alert:

            # 模拟有问题的检查
            mock_disk.return_value = {'healthy': False, 'free_percent': 5.0, 'issue': '磁盘空间不足'}
            mock_age.return_value = {'healthy': True, 'age_hours': 12.0}
            mock_integrity.return_value = {'healthy': True, 'failed_files': 0}
            mock_records.return_value = {'healthy': True, 'failed_count': 0, 'success_rate': 100.0}
            mock_system.return_value = {'healthy': True, 'cpu_percent': 50.0, 'memory_percent': 60.0}

            result = await health_check_service.perform_health_check()

            assert result['overall_status'] == 'warning'
            assert len(result['issues']) > 0
            assert '磁盘空间不足' in result['issues'][0]
            mock_alert.assert_called_once()  # 有问题，发送告警

    @pytest.mark.asyncio
    async def test_perform_health_check_exception(self, health_check_service):
        """测试执行健康检查（异常情况）"""
        with patch.object(health_check_service, '_check_disk_space') as mock_disk:
            mock_disk.side_effect = Exception("测试异常")

            result = await health_check_service.perform_health_check()

            assert result['overall_status'] == 'error'
            assert 'error' in result
            assert '测试异常' in result['error']

    @pytest.mark.asyncio
    async def test_check_backup_age_counts_encrypted_backups(self, health_check_service):
        """回归（2026-10-02 P2 审计 H-1）：加密备份（.zip.enc）必须计入备份年龄。

        生产 BACKUP_ENCRYPTION_ENABLED=true，落盘全是 `.zip.enc` 且**没有** `.zip`
        兄弟文件。原先 glob 只认 `*.zip`，导致健康检查恒报"备份过旧"（实测生产恒报
        最新备份 132 小时前，而当天刚出过加密包）——既持续假告警，又永远测不出
        真正的"备份停了"。
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            backup_dir = Path(temp_dir)
            # 一个陈旧的明文包 + 一个刚刚产出的加密包（生产常态）
            old = backup_dir / 'erp_auto_daily_20260927_020504.zip'
            old.touch()
            old_mtime = (datetime.now() - timedelta(hours=132)).timestamp()
            os.utime(old, (old_mtime, old_mtime))

            fresh = backup_dir / 'erp_auto_daily_20261002_060002.zip.enc'
            fresh.touch()

            with patch('fastapi_app.services.backup.verify.health_check_service.BACKUP_DIR', backup_dir), \
                 patch('fastapi_app.services.backup.verify.health_check_service.ensure_backup_dir'):

                result = await health_check_service._check_backup_age()

            assert result['healthy'] is True, result
            assert result['latest_backup'] == fresh.name
            assert result['age_hours'] < 1
