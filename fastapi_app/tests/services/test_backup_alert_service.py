"""
备份告警服务单元测试
"""

import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.backup.metrics.alert_service import BackupAlertService


class TestBackupAlertService:
    """备份告警服务测试类"""

    @pytest.fixture
    def alert_service(self):
        """创建告警服务实例"""
        service = BackupAlertService()
        # 模拟环境变量
        with patch.dict(os.environ, {
            'BACKUP_ALERT_EMAIL_ENABLED': 'false',
            'BACKUP_ALERT_WEBHOOK_ENABLED': 'false',
            'BACKUP_ALERT_FAILURE_THRESHOLD': '3',
            'BACKUP_ALERT_CRITICAL_THRESHOLD': '5',
            'BACKUP_ALERT_COOLDOWN_MINUTES': '30',
            'BACKUP_ALERT_MAX_RETRIES': '3',
            'BACKUP_ALERT_RETRY_DELAY_BASE': '2',
        }):
            service.__init__()
            return service

    @pytest.fixture
    def mock_db_session(self):
        """模拟数据库会话"""
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.close = AsyncMock()
        return session

    def test_load_alert_config(self, alert_service):
        """测试加载告警配置"""
        config = alert_service._load_alert_config()

        assert 'email_enabled' in config
        assert 'webhook_enabled' in config
        assert 'failure_threshold' in config
        assert 'critical_threshold' in config
        assert 'alert_cooldown_minutes' in config
        assert 'max_retries' in config
        assert 'retry_delay_base' in config

        assert config['email_enabled'] is False
        assert config['webhook_enabled'] is False
        assert config['failure_threshold'] == 3
        assert config['critical_threshold'] == 5
        assert config['alert_cooldown_minutes'] == 30
        assert config['max_retries'] == 3
        assert config['retry_delay_base'] == 2

    def test_update_failure_count(self, alert_service):
        """测试更新失败计数"""
        task_name = "test_task"

        # 初始状态
        assert task_name not in alert_service.failure_counts

        # 更新错误计数
        alert_service._update_failure_count(task_name, 'error')
        assert task_name in alert_service.failure_counts
        assert alert_service.failure_counts[task_name]['error'] == 1
        assert alert_service.failure_counts[task_name]['critical'] == 0
        assert alert_service.failure_counts[task_name]['last_failure_time'] is not None

        # 更新严重错误计数
        alert_service._update_failure_count(task_name, 'critical')
        assert alert_service.failure_counts[task_name]['critical'] == 1

        # 再次更新错误计数
        alert_service._update_failure_count(task_name, 'error')
        assert alert_service.failure_counts[task_name]['error'] == 2

    def test_should_send_alert(self, alert_service):
        """测试是否应该发送告警"""
        task_name = "test_task"

        # 无失败记录时首次告警应发送（无冷却时间、无阈值限制）
        assert alert_service._should_send_alert(task_name, 'error') is True

        # 设置失败计数达到阈值
        alert_service.failure_counts[task_name] = {
            'error': 3,
            'critical': 0,
            'last_failure_time': datetime.now()
        }

        # 应该发送（达到阈值）
        assert alert_service._should_send_alert(task_name, 'error') is True

        # 设置最近告警时间在冷却期内
        alert_service.last_alert_times[task_name] = datetime.now()

        # 不应该发送（在冷却期内）
        assert alert_service._should_send_alert(task_name, 'error') is False

        # critical级别应该总是发送
        assert alert_service._should_send_alert(task_name, 'critical') is True

    def test_prepare_alert_data(self, alert_service):
        """测试准备告警数据"""
        task_name = "test_task"
        error = "测试错误信息"
        task_type = "backup"
        severity = "error"
        additional_info = {"key": "value"}

        alert_data = alert_service._prepare_alert_data(
            task_name, error, task_type, severity, additional_info
        )

        assert alert_data['task_name'] == task_name
        assert alert_data['error'] == error
        assert alert_data['task_type'] == task_type
        assert alert_data['severity'] == severity
        assert 'timestamp' in alert_data
        assert 'hostname' in alert_data
        assert 'failure_counts' in alert_data
        assert alert_data['key'] == 'value'  # 附加信息

    def test_generate_email_text(self, alert_service):
        """测试生成邮件纯文本内容"""
        alert_data = {
            'task_name': 'test_task',
            'task_type': 'backup',
            'severity': 'error',
            'timestamp': '2024-01-01T12:00:00',
            'hostname': 'test-server',
            'error': '测试错误信息',
            'failure_counts': {
                'error': 3,
                'critical': 1,
                'last_failure_time': '2024-01-01T11:00:00'
            }
        }

        text_content = alert_service._generate_email_text(alert_data)

        assert '备份告警通知' in text_content
        assert 'test_task' in text_content
        assert 'backup' in text_content
        assert 'ERROR' in text_content
        assert '测试错误信息' in text_content
        assert '错误次数: 3' in text_content
        assert '严重错误次数: 1' in text_content

    def test_generate_email_html(self, alert_service):
        """测试生成邮件HTML内容"""
        alert_data = {
            'task_name': 'test_task',
            'task_type': 'backup',
            'severity': 'error',
            'timestamp': '2024-01-01T12:00:00',
            'hostname': 'test-server',
            'error': '测试错误信息',
            'failure_counts': {
                'error': 3,
                'critical': 1,
                'last_failure_time': '2024-01-01T11:00:00'
            }
        }

        html_content = alert_service._generate_email_html(alert_data)

        assert '<!DOCTYPE html>' in html_content
        assert 'test_task' in html_content
        assert 'backup' in html_content
        assert 'ERROR' in html_content
        assert '测试错误信息' in html_content
        assert '错误次数:</span> 3' in html_content
        assert '严重错误次数:</span> 1' in html_content

        # 检查严重级别颜色
        assert '#fd7e14' in html_content  # error级别的颜色

    @pytest.mark.asyncio
    async def test_send_alert_without_config(self, alert_service):
        """测试发送告警（无配置）"""
        # 模拟数据库上下文管理器
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with patch('fastapi_app.services.backup.metrics.alert_service.get_async_db_context') as mock_context:
            mock_context.return_value.__aenter__.return_value = mock_session

            # 发送告警
            result = await alert_service.send_alert(
                task_name='test_task',
                error='测试错误',
                task_type='backup',
                severity='error'
            )

            # 应该成功（即使没有邮件和webhook配置）
            assert result is True

            # 验证失败计数已更新
            assert 'test_task' in alert_service.failure_counts
            assert alert_service.failure_counts['test_task']['error'] == 1

    @pytest.mark.asyncio
    async def test_send_alert_with_email_config(self, alert_service):
        """测试发送告警（有邮件配置）"""
        # 设置邮件配置
        alert_service.alert_config['email_enabled'] = True
        alert_service.alert_config['email_from'] = 'test@example.com'
        alert_service.alert_config['email_to'] = ['admin@example.com']
        alert_service.alert_config['smtp_username'] = 'user'
        alert_service.alert_config['smtp_password'] = 'pass'
        # 预置失败计数达到阈值，使通知渠道被触发
        alert_service.failure_counts['test_task'] = {
            'error': alert_service.alert_config['failure_threshold'],
            'critical': 0,
            'last_failure_time': datetime.now()
        }

        # 模拟数据库上下文管理器
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with patch('fastapi_app.services.backup.metrics.alert_service.get_async_db_context') as mock_context, \
             patch('smtplib.SMTP') as mock_smtp:

            mock_context.return_value.__aenter__.return_value = mock_session
            mock_smtp_instance = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_smtp_instance

            # 发送告警
            result = await alert_service.send_alert(
                task_name='test_task',
                error='测试错误',
                task_type='backup',
                severity='error'
            )

            # 应该尝试发送邮件
            assert mock_smtp.called
            assert result is True

    @pytest.mark.asyncio
    async def test_send_alert_with_webhook_config(self, alert_service):
        """测试发送告警（有webhook配置）"""
        # 设置webhook配置
        alert_service.alert_config['webhook_enabled'] = True
        alert_service.alert_config['webhook_url'] = 'http://example.com/webhook'
        # 预置失败计数达到阈值，使通知渠道被触发
        alert_service.failure_counts['test_task'] = {
            'error': alert_service.alert_config['failure_threshold'],
            'critical': 0,
            'last_failure_time': datetime.now()
        }

        # 模拟数据库上下文管理器
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with patch('fastapi_app.services.backup.metrics.alert_service.get_async_db_context') as mock_context, \
             patch('httpx.AsyncClient') as mock_client:

            mock_context.return_value.__aenter__.return_value = mock_session
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.post.return_value = MagicMock(status_code=200)

            # 发送告警
            result = await alert_service.send_alert(
                task_name='test_task',
                error='测试错误',
                task_type='backup',
                severity='error'
            )

            # 应该尝试发送webhook
            assert mock_client.called
            assert result is True

    @pytest.mark.asyncio
    async def test_retry_with_backoff_success(self, alert_service):
        """测试指数退避重试（成功）"""
        mock_func = AsyncMock(return_value="success")

        success, result = await alert_service.retry_with_backoff(
            mock_func,
            task_name='test_task'
        )

        assert success is True
        assert result == "success"
        assert mock_func.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_with_backoff_failure(self, alert_service):
        """测试指数退避重试（失败）"""
        mock_func = AsyncMock(side_effect=Exception("test error"))

        success, result = await alert_service.retry_with_backoff(
            mock_func,
            task_name='test_task'
        )

        assert success is False
        assert isinstance(result, Exception)
        assert str(result) == "test error"
        # 应该重试3次（max_retries=3）
        assert mock_func.call_count == 4  # 初始尝试 + 3次重试

    @pytest.mark.asyncio
    async def test_retry_with_backoff_success_on_retry(self, alert_service):
        """测试指数退避重试（重试后成功）"""
        call_count = 0

        async def mock_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception(f"attempt {call_count} failed")
            return "success"

        success, result = await alert_service.retry_with_backoff(
            mock_func,
            task_name='test_task'
        )

        assert success is True
        assert result == "success"
        assert call_count == 3  # 第3次尝试成功

    @pytest.mark.asyncio
    async def test_get_alert_statistics(self, alert_service, mock_db_session):
        """测试获取告警统计信息"""
        # 模拟数据库查询结果
        mock_records = [
            MagicMock(
                id=1,
                type='full',
                filename='backup1.zip',
                error_message='ERROR: 磁盘空间不足',
                created_at=datetime.now()
            ),
            MagicMock(
                id=2,
                type='incremental',
                filename='backup2.zip',
                error_message='WARNING: 备份超时',
                created_at=datetime.now()
            ),
            MagicMock(
                id=3,
                type='full',
                filename='backup3.zip',
                error_message='CRITICAL: 数据库连接失败',
                created_at=datetime.now()
            ),
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_records
        mock_db_session.execute.return_value = mock_result

        with patch('fastapi_app.services.backup.metrics.alert_service.get_async_db_context') as mock_context:
            mock_context.return_value.__aenter__.return_value = mock_db_session

            stats = await alert_service.get_alert_statistics(days=7)

            assert 'total_failures' in stats
            assert 'by_task_type' in stats
            assert 'by_severity' in stats
            assert 'recent_failures' in stats

            assert stats['total_failures'] == 3
            assert stats['by_task_type']['full'] == 2
            assert stats['by_task_type']['incremental'] == 1
            assert stats['by_severity']['error'] == 1
            assert stats['by_severity']['warning'] == 1
            assert stats['by_severity']['critical'] == 1
            assert len(stats['recent_failures']) == 3

    def test_get_hostname(self, alert_service):
        """测试获取主机名"""
        hostname = alert_service._get_hostname()

        # 主机名应该是字符串
        assert isinstance(hostname, str)
        # 不应该为空
        assert hostname != ''
        # 如果是未知的，应该是'unknown'
        if hostname == 'unknown':
            # 这可能在测试环境中发生
            pass
        else:
            # 否则应该是一个有效的主机名
            assert len(hostname) > 0
