"""
备份策略服务单元测试
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fastapi_app.services.backup.orchestration.policy_service import BackupPolicyService


class TestBackupPolicyService:
    """备份策略服务测试类"""

    @pytest.fixture
    def policy_service(self):
        """创建策略服务实例。

        ⚠️ patch.dict 必须**覆盖测试体**：此前写成 `with patch.dict(...): return service`，
        上下文在 fixture 返回时即退出，测试体里 `_load_policy_config()` 读到的是本机
        `.env` 的真值（`BACKUP_ENCRYPTION_ENABLED=true`），于是
        `test_load_policy_config` 在本机必红、CI（无 .env）为绿 —— 假回归信号。
        改为 yield，让钉住的环境变量活到测试结束。
        """
        with patch.dict(os.environ, {
            'BACKUP_FULL_CRON': '0 2 * * *',
            'BACKUP_RETENTION_DAYS': '30',
            'BACKUP_RETENTION_COUNT': '100',
            'BACKUP_ENCRYPTION_ENABLED': 'false',
            'BACKUP_ENCRYPTION_ALGORITHM': 'AES256',
            'BACKUP_COMPRESSION_LEVEL': '6',
            'BACKUP_STORAGE_LOCATION': 'backups/server',
            'BACKUP_PRE_CHECK': 'true',
            'BACKUP_POST_VALIDATION': 'true',
            'BACKUP_PARALLEL': 'false',
            'BACKUP_MAX_PARALLEL_JOBS': '2',
            'BACKUP_NOTIFY_SUCCESS': 'false',
            'BACKUP_NOTIFY_FAILURE': 'true',
            'BACKUP_NOTIFY_WARNING': 'true',
        }):
            service = BackupPolicyService()
            service.__init__()
            yield service

    @pytest.fixture
    def temp_policy_file(self):
        """创建临时策略文件"""
        with tempfile.TemporaryDirectory() as temp_dir:
            policy_file = Path(temp_dir) / 'backup_policy.json'
            yield policy_file

    def test_load_policy_config(self, policy_service):
        """测试加载策略配置"""
        config = policy_service._load_policy_config()

        assert 'full_backup_cron' in config
        assert 'retention_days' in config
        assert 'retention_count' in config
        assert 'encryption_enabled' in config
        assert 'encryption_algorithm' in config
        assert 'compression_level' in config
        assert 'storage_location' in config
        assert 'pre_backup_check' in config
        assert 'post_backup_validation' in config
        assert 'parallel_backup' in config
        assert 'max_parallel_jobs' in config
        assert 'notify_on_success' in config
        assert 'notify_on_failure' in config
        assert 'notify_on_warning' in config

        assert config['full_backup_cron'] == '0 2 * * *'
        assert config['retention_days'] == 30
        assert config['retention_count'] == 100
        assert config['encryption_enabled'] is False
        assert config['encryption_algorithm'] == 'AES256'
        assert config['compression_level'] == 6
        assert config['storage_location'] == 'backups/server'
        assert config['pre_backup_check'] is True
        assert config['post_backup_validation'] is True
        assert config['parallel_backup'] is False
        assert config['max_parallel_jobs'] == 2
        assert config['notify_on_success'] is False
        assert config['notify_on_failure'] is True
        assert config['notify_on_warning'] is True

    def test_get_default_policy(self, policy_service):
        """测试获取默认策略"""
        policy = policy_service._get_default_policy()

        assert 'policy_name' in policy
        assert 'description' in policy
        assert 'version' in policy
        assert 'created_at' in policy
        assert 'updated_at' in policy
        assert 'full_backup' in policy
        assert 'retention' in policy
        assert 'encryption' in policy
        assert 'compression' in policy
        assert 'validation' in policy
        assert 'notification' in policy
        assert 'performance' in policy
        assert 'storage' in policy
        assert 'incremental_backup' not in policy

        assert policy['policy_name'] == 'default'
        assert policy['description'] == '默认备份策略'
        assert policy['version'] == '1.0'
        assert policy['full_backup']['enabled'] is True
        assert policy['full_backup']['schedule'] == '0 2 * * *'
        assert policy['retention']['enabled'] is True
        assert policy['retention']['strategy'] == 'hybrid'
        assert policy['retention']['retention_days'] == 30
        assert 'retention_count' not in policy['retention']
        assert 'keep_manual_backups' not in policy['retention']
        assert 'keep_failed_backups' not in policy['retention']
        assert policy['encryption']['enabled'] is False
        assert policy['encryption']['algorithm'] == 'AES256'
        assert policy['compression']['enabled'] is True
        assert policy['compression']['level'] == 6
        assert policy['notification']['enabled'] is True

    def test_is_valid_cron(self, policy_service):
        """测试验证cron表达式"""
        # 有效的cron表达式
        assert policy_service._is_valid_cron('0 2 * * *') is True  # 每天凌晨2点
        assert policy_service._is_valid_cron('0 */1 * * *') is True  # 每小时
        assert policy_service._is_valid_cron('30 3 * * 1-5') is True  # 工作日凌晨3:30
        assert policy_service._is_valid_cron('0 0 1 * *') is True  # 每月1号

        # 无效的cron表达式
        assert policy_service._is_valid_cron('') is False  # 空字符串
        assert policy_service._is_valid_cron('0 2 * *') is False  # 缺少字段
        assert policy_service._is_valid_cron('0 2 * * * *') is False  # 多余字段
        assert policy_service._is_valid_cron('60 2 * * *') is False  # 分钟超出范围
        assert policy_service._is_valid_cron('0 24 * * *') is False  # 小时超出范围

    def test_is_valid_cron_part(self, policy_service):
        """测试验证cron表达式部分"""
        # 有效的cron部分
        assert policy_service._is_valid_cron_part('*') is True
        assert policy_service._is_valid_cron_part('5') is True
        assert policy_service._is_valid_cron_part('0-59') is True
        assert policy_service._is_valid_cron_part('0,15,30,45') is True
        assert policy_service._is_valid_cron_part('*/5') is True
        assert policy_service._is_valid_cron_part('0-23/2') is True

        # 无效的cron部分
        assert policy_service._is_valid_cron_part('') is False
        assert policy_service._is_valid_cron_part('60') is False  # 超出范围
        assert policy_service._is_valid_cron_part('0-60') is False  # 结束值超出范围
        assert policy_service._is_valid_cron_part('0,61,30') is False  # 包含超出范围的值
        assert policy_service._is_valid_cron_part('*/0') is False  # 步长为0
        assert policy_service._is_valid_cron_part('*/a') is False  # 非数字步长

    @pytest.mark.asyncio
    async def test_get_current_policy_no_file(self, policy_service, temp_policy_file):
        """测试获取当前策略（无文件）"""
        with patch.object(policy_service, 'policy_file', temp_policy_file):
            policy = await policy_service.get_current_policy()

            # 应该返回默认策略
            assert policy['policy_name'] == 'default'
            assert policy['description'] == '默认备份策略'
            assert policy['version'] == '1.0'

    @pytest.mark.asyncio
    async def test_get_current_policy_with_file(self, policy_service, temp_policy_file):
        """测试获取当前策略（有文件）"""
        # 创建策略文件
        custom_policy = {
            'policy_name': 'custom_policy',
            'version': '2.0',
            'full_backup': {
                'enabled': False,
                'schedule': '0 4 * * *'
            }
        }

        with open(temp_policy_file, 'w', encoding='utf-8') as f:
            json.dump(custom_policy, f)

        with patch.object(policy_service, 'policy_file', temp_policy_file):
            policy = await policy_service.get_current_policy()

            # 应该返回文件中的策略
            assert policy['policy_name'] == 'custom_policy'
            assert policy['version'] == '2.0'
            assert policy['full_backup']['enabled'] is False
            assert policy['full_backup']['schedule'] == '0 4 * * *'

    @pytest.mark.asyncio
    async def test_apply_backup_policy_disabled(self, policy_service):
        """测试应用备份策略（已禁用）"""
        # 模拟禁用所有备份的策略
        with patch.object(policy_service, 'get_current_policy') as mock_get_policy:
            mock_get_policy.return_value = {
                'policy_name': 'disabled_policy',
                'full_backup': {'enabled': False}
            }

            result = await policy_service.apply_backup_policy()

            assert result['success'] is True
            assert result['policy_applied'] is False
            assert '备份策略已禁用' in result['message']

    @pytest.mark.asyncio
    async def test_apply_backup_policy_success(self, policy_service):
        """测试应用备份策略（成功）"""
        with patch.object(policy_service, 'get_current_policy') as mock_get_policy, \
             patch.object(policy_service, '_perform_policy_checks') as mock_checks, \
             patch.object(policy_service, '_apply_retention_policy') as mock_retention, \
             patch.object(policy_service, '_apply_storage_policy') as mock_storage:

            # 模拟策略检查和应用结果
            mock_get_policy.return_value = {
                'policy_name': 'test_policy',
                'full_backup': {'enabled': True},
                'storage': {'sync_to_secondary': False}
            }

            mock_checks.return_value = {
                'disk_space': {'passed': True, 'message': '磁盘空间充足'},
                'backup_location': {'passed': True, 'message': '备份目录正常'},
                'encryption_key': {'passed': True, 'message': '加密配置正常'},
                'schedule_validity': {'passed': True, 'message': '计划任务配置有效'}
            }

            mock_retention.return_value = {
                'applied': True,
                'strategy': 'hybrid',
                'total_records': 50,
                'kept_records': 30,
                'deleted_records': 20,
                'deleted_files': ['backup1.zip', 'backup2.zip'],
                'message': '保留策略应用成功'
            }

            mock_storage.return_value = {
                'applied': False,
                'message': '存储同步未启用或未配置二级存储位置'
            }

            result = await policy_service.apply_backup_policy()

            assert result['success'] is True
            assert result['policy_applied'] is True
            assert result['policy_name'] == 'test_policy'
            assert 'checks' in result
            assert 'cleanup_result' in result
            assert 'storage_result' in result
            assert 'applied_at' in result

    @pytest.mark.asyncio
    async def test_apply_backup_policy_failure(self, policy_service):
        """测试应用备份策略（失败）"""
        with patch.object(policy_service, 'get_current_policy') as mock_get_policy, \
             patch.object(policy_service, '_perform_policy_checks') as mock_checks:

            mock_get_policy.return_value = {
                'policy_name': 'test_policy',
                'full_backup': {'enabled': True}
            }

            mock_checks.side_effect = Exception('策略检查失败')

            result = await policy_service.apply_backup_policy()

            assert result['success'] is False
            assert result['policy_applied'] is False
            assert '应用备份策略失败' in result['message']
            assert '策略检查失败' in result['error']

    def test_should_keep_backup(self, policy_service):
        """测试判断是否应该保留备份"""
        from fastapi_app.shared_models.backup_record import BackupRecord

        # 创建模拟备份记录
        record = MagicMock(spec=BackupRecord)
        record.trigger_type = 'manual'
        record.status = 'success'
        record.created_at = datetime.now()

        retention = {
            'enabled': True,
            'strategy': 'hybrid',
            'retention_days': 30,
            'retention_count': 100
        }

        # 测试手动备份保留
        keep = policy_service._should_keep_backup(
            record, 'hybrid', retention, keep_manual=True, keep_failed=False
        )
        assert keep is True  # 手动备份应该保留

        # 测试失败备份保留
        record.status = 'failed'
        record.trigger_type = 'auto'

        keep = policy_service._should_keep_backup(
            record, 'hybrid', retention, keep_manual=False, keep_failed=True
        )
        assert keep is True  # 失败备份应该保留

        # 测试时间策略
        record.status = 'success'
        record.trigger_type = 'auto'
        record.created_at = datetime.now()  # 当前时间

        keep = policy_service._should_keep_backup(
            record, 'time', retention, keep_manual=False, keep_failed=False
        )
        assert keep is True  # 在保留时间内

        # 测试没有创建时间的情况
        record.created_at = None

        keep = policy_service._should_keep_backup(
            record, 'time', retention, keep_manual=False, keep_failed=False
        )
        assert keep is True  # 没有创建时间，默认保留
