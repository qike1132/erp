"""
备份性能监控服务单元测试
"""

import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.backup.metrics.service import BackupMetricsService


class TestBackupMetricsService:
    """备份性能监控服务测试类"""

    @pytest.fixture
    def metrics_service(self):
        """创建性能监控服务实例"""
        service = BackupMetricsService()
        # 模拟环境变量
        with patch.dict(os.environ, {
            'BACKUP_METRICS_INTERVAL': '60',
            'BACKUP_METRICS_RETENTION_DAYS': '90',
            'BACKUP_DURATION_THRESHOLD': '1800',
            'BACKUP_SIZE_THRESHOLD': '1073741824',
            'BACKUP_CPU_THRESHOLD': '80.0',
            'BACKUP_MEMORY_THRESHOLD': '80.0',
            'BACKUP_DISK_IO_THRESHOLD': '100',
            'BACKUP_TREND_WINDOW': '24',
            'BACKUP_SUCCESS_RATE_THRESHOLD': '95.0',
            'BACKUP_FAILURE_COUNT_THRESHOLD': '3',
        }):
            service.__init__()
            return service

    @pytest.fixture
    def mock_backup_record(self):
        """创建模拟备份记录"""
        from fastapi_app.shared_models.backup_record import BackupRecord

        record = MagicMock(spec=BackupRecord)
        record.id = 1
        record.type = 'full'
        record.filename = 'backup_20240101_120000.zip'
        record.size = 1024 * 1024 * 100  # 100MB
        record.status = 'success'
        record.error_message = None
        record.duration_seconds = 300.5  # 5分钟
        record.created_at = datetime.now() - timedelta(hours=1)
        return record

    def test_load_metrics_config(self, metrics_service):
        """测试加载指标配置"""
        config = metrics_service._load_metrics_config()

        assert 'collection_interval' in config
        assert 'retention_days' in config
        assert 'backup_duration_threshold' in config
        assert 'backup_size_threshold' in config
        assert 'cpu_usage_threshold' in config
        assert 'memory_usage_threshold' in config
        assert 'disk_io_threshold' in config
        assert 'trend_window_hours' in config
        assert 'success_rate_threshold' in config
        assert 'failure_count_threshold' in config

        assert config['collection_interval'] == 60
        assert config['retention_days'] == 90
        assert config['backup_duration_threshold'] == 1800
        assert config['backup_size_threshold'] == 1073741824
        assert config['cpu_usage_threshold'] == 80.0
        assert config['memory_usage_threshold'] == 80.0
        assert config['disk_io_threshold'] == 100
        assert config['trend_window_hours'] == 24
        assert config['success_rate_threshold'] == 95.0
        assert config['failure_count_threshold'] == 3

    @pytest.mark.asyncio
    async def test_collect_backup_metrics_success(self, metrics_service):
        """测试收集备份指标（成功）"""
        start_time = datetime.now() - timedelta(minutes=5)
        end_time = datetime.now()
        backup_size = 1024 * 1024 * 50  # 50MB

        with patch.object(metrics_service, '_collect_system_metrics') as mock_system_metrics, \
             patch.object(metrics_service, '_store_metrics') as mock_store, \
             patch.object(metrics_service, '_check_performance_thresholds') as mock_check:

            # 模拟系统指标
            mock_system_metrics.return_value = {
                'cpu_percent': 25.5,
                'memory_percent': 45.2,
                'memory_available_gb': 8.5,
                'memory_used_gb': 7.5,
                'memory_total_gb': 16.0,
                'timestamp': datetime.now().isoformat()
            }

            metrics = await metrics_service.collect_backup_metrics(
                backup_type='full',
                start_time=start_time,
                end_time=end_time,
                backup_size=backup_size,
                success=True,
                error_message=None,
                additional_metrics={'original_size': 1024 * 1024 * 100}  # 100MB原始大小
            )

            assert 'backup_type' in metrics
            assert 'start_time' in metrics
            assert 'end_time' in metrics
            assert 'duration_seconds' in metrics
            assert 'backup_size_bytes' in metrics
            assert 'backup_size_mb' in metrics
            assert 'success' in metrics
            assert 'error_message' in metrics
            assert 'compression_ratio' in metrics
            assert 'system_metrics' in metrics
            assert 'additional_metrics' in metrics
            assert 'collected_at' in metrics

            assert metrics['backup_type'] == 'full'
            assert metrics['success'] is True
            assert metrics['error_message'] is None
            assert metrics['backup_size_bytes'] == backup_size
            assert metrics['backup_size_mb'] == 50.0
            assert metrics['compression_ratio'] == 0.5  # 50MB / 100MB
            assert 'cpu_percent' in metrics['system_metrics']
            assert 'memory_percent' in metrics['system_metrics']

            # 验证方法被调用
            mock_system_metrics.assert_called_once()
            mock_store.assert_called_once()
            mock_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_collect_backup_metrics_failure(self, metrics_service):
        """测试收集备份指标（失败）"""
        start_time = datetime.now() - timedelta(minutes=5)
        end_time = datetime.now()
        backup_size = 1024 * 1024 * 50  # 50MB

        with patch.object(metrics_service, '_collect_system_metrics') as mock_system_metrics, \
             patch.object(metrics_service, '_store_metrics') as mock_store, \
             patch.object(metrics_service, '_check_performance_thresholds') as mock_check:

            # 模拟系统指标
            mock_system_metrics.return_value = {
                'cpu_percent': 25.5,
                'memory_percent': 45.2,
                'timestamp': datetime.now().isoformat()
            }

            metrics = await metrics_service.collect_backup_metrics(
                backup_type='auto',
                start_time=start_time,
                end_time=end_time,
                backup_size=backup_size,
                success=False,
                error_message='备份失败：磁盘空间不足',
                additional_metrics=None
            )

            assert metrics['backup_type'] == 'auto'
            assert metrics['success'] is False
            assert metrics['error_message'] == '备份失败：磁盘空间不足'
            assert metrics['compression_ratio'] is None  # 没有原始大小

            # 验证方法被调用
            mock_system_metrics.assert_called_once()
            mock_store.assert_called_once()
            mock_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_collect_backup_metrics_exception(self, metrics_service):
        """测试收集备份指标（异常）"""
        start_time = datetime.now() - timedelta(minutes=5)
        end_time = datetime.now()

        with patch.object(metrics_service, '_collect_system_metrics') as mock_system_metrics:
            mock_system_metrics.side_effect = Exception('系统指标收集失败')

            metrics = await metrics_service.collect_backup_metrics(
                backup_type='full',
                start_time=start_time,
                end_time=end_time,
                backup_size=1024 * 1024 * 100,
                success=True,
                error_message=None
            )

            assert 'error' in metrics
            assert metrics['success'] is False
            assert '系统指标收集失败' in metrics['error']

    @pytest.mark.asyncio
    async def test_collect_system_metrics(self, metrics_service):
        """测试收集系统指标"""
        with patch('psutil.cpu_percent') as mock_cpu, \
             patch('psutil.virtual_memory') as mock_memory, \
             patch('psutil.disk_io_counters') as mock_disk_io, \
             patch('psutil.net_io_counters') as mock_net_io:

            # 模拟系统指标
            mock_cpu.return_value = 35.7
            mock_memory.return_value = MagicMock(
                percent=65.3,
                available=6.2 * 1024 ** 3,  # 6.2GB
                used=9.8 * 1024 ** 3,        # 9.8GB
                total=16.0 * 1024 ** 3        # 16GB
            )
            mock_disk_io.return_value = MagicMock(
                read_bytes=1024 * 1024 * 500,  # 500MB
                write_bytes=1024 * 1024 * 300,  # 300MB
                read_count=1000,
                write_count=500
            )
            mock_net_io.return_value = MagicMock(
                bytes_sent=1024 * 1024 * 100,  # 100MB
                bytes_recv=1024 * 1024 * 200    # 200MB
            )

            metrics = await metrics_service._collect_system_metrics()

            assert 'cpu_percent' in metrics
            assert 'memory_percent' in metrics
            assert 'memory_available_gb' in metrics
            assert 'memory_used_gb' in metrics
            assert 'memory_total_gb' in metrics
            assert 'disk_read_mb' in metrics
            assert 'disk_write_mb' in metrics
            assert 'disk_read_count' in metrics
            assert 'disk_write_count' in metrics
            assert 'net_sent_mb' in metrics
            assert 'net_recv_mb' in metrics
            assert 'timestamp' in metrics

            assert metrics['cpu_percent'] == 35.7
            assert metrics['memory_percent'] == 65.3
            assert metrics['memory_available_gb'] == 6.2
            assert metrics['memory_used_gb'] == 9.8
            assert metrics['memory_total_gb'] == 16.0
            assert metrics['disk_read_mb'] == 500.0
            assert metrics['disk_write_mb'] == 300.0
            assert metrics['disk_read_count'] == 1000
            assert metrics['disk_write_count'] == 500
            assert metrics['net_sent_mb'] == 100.0
            assert metrics['net_recv_mb'] == 200.0

    @pytest.mark.asyncio
    async def test_collect_system_metrics_exception(self, metrics_service):
        """测试收集系统指标（异常）"""
        with patch('psutil.cpu_percent') as mock_cpu:
            mock_cpu.side_effect = Exception('CPU指标获取失败')

            metrics = await metrics_service._collect_system_metrics()

            assert 'error' in metrics
            assert 'timestamp' in metrics
            assert 'CPU指标获取失败' in metrics['error']

    @pytest.mark.asyncio
    async def test_check_performance_thresholds_normal(self, metrics_service):
        """测试检查性能阈值（正常）"""
        metrics = {
            'duration_seconds': 600.0,  # 10分钟
            'backup_size_bytes': 1024 * 1024 * 500,  # 500MB
            'system_metrics': {
                'cpu_percent': 50.0,
                'memory_percent': 60.0
            }
        }

        with patch('fastapi_app.services.backup.metrics.service.logger') as mock_logger:
            await metrics_service._check_performance_thresholds(metrics)

            # 所有指标都在阈值内，不应该记录警告
            assert not mock_logger.warning.called

    @pytest.mark.asyncio
    async def test_check_performance_thresholds_exceeded(self, metrics_service):
        """测试检查性能阈值（超出阈值）"""
        metrics = {
            'duration_seconds': 2000.0,  # 33分钟 > 30分钟阈值
            'backup_size_bytes': 2 * 1024 * 1024 * 1024,  # 2GB > 1GB阈值
            'system_metrics': {
                'cpu_percent': 90.0,  # > 80%阈值
                'memory_percent': 85.0  # > 80%阈值
            }
        }

        with patch('fastapi_app.services.backup.metrics.service.logger') as mock_logger:
            await metrics_service._check_performance_thresholds(metrics)

            # 应该记录警告
            assert mock_logger.warning.called
            warning_msg = mock_logger.warning.call_args[0][0]
            assert '备份耗时过长' in warning_msg
            assert '备份文件过大' in warning_msg
            assert 'CPU使用率过高' in warning_msg
            assert '内存使用率过高' in warning_msg

    @pytest.mark.asyncio
    async def test_get_performance_summary(self, metrics_service, mock_backup_record):
        """测试获取性能摘要"""
        with patch('fastapi_app.services.backup.metrics.service.get_async_db_context') as mock_context:
            mock_session = AsyncMock()
            mock_result = MagicMock()

            # 模拟成功和失败的备份记录
            success_record = mock_backup_record
            success_record.status = 'success'
            success_record.duration_seconds = 300.5
            success_record.size = 1024 * 1024 * 100  # 100MB

            failed_record = MagicMock()
            failed_record.type = 'auto'
            failed_record.status = 'failed'
            failed_record.duration_seconds = 150.2
            failed_record.size = 1024 * 1024 * 50  # 50MB
            failed_record.created_at = datetime.now() - timedelta(hours=2)

            # 模拟查询结果
            all_records = [success_record, success_record, failed_record]
            mock_result.scalars.return_value.all.return_value = all_records
            mock_session.execute.return_value = mock_result
            mock_context.return_value.__aenter__.return_value = mock_session

            summary = await metrics_service.get_performance_summary(hours=24)

            assert 'time_period_hours' in summary
            assert 'backup_type' in summary
            assert 'total_backups' in summary
            assert 'success_count' in summary
            assert 'failed_count' in summary
            assert 'success_rate' in summary
            assert 'average_duration_seconds' in summary
            assert 'total_size_bytes' in summary
            assert 'total_size_mb' in summary
            assert 'type_stats' in summary

            assert summary['time_period_hours'] == 24
            assert summary['backup_type'] == 'all'
            assert summary['total_backups'] == 3
            assert summary['success_count'] == 2
            assert summary['failed_count'] == 1
            assert summary['success_rate'] == pytest.approx(66.67, 0.01)
            assert summary['average_duration_seconds'] == pytest.approx(250.4, 0.1)  # (300.5*2 + 150.2)/3
            assert summary['total_size_bytes'] == 1024 * 1024 * 250  # 250MB
            assert summary['total_size_mb'] == 250.0

            # 检查类型统计
            assert 'full' in summary['type_stats']
            assert 'auto' in summary['type_stats']
            assert summary['type_stats']['full']['count'] == 2
            assert summary['type_stats']['full']['success'] == 2
            assert summary['type_stats']['full']['failed'] == 0
            assert summary['type_stats']['auto']['count'] == 1
            assert summary['type_stats']['auto']['success'] == 0
            assert summary['type_stats']['auto']['failed'] == 1

    @pytest.mark.asyncio
    async def test_get_performance_summary_by_type(self, metrics_service, mock_backup_record):
        """测试按类型获取性能摘要"""
        with patch('fastapi_app.services.backup.metrics.service.get_async_db_context') as mock_context:
            mock_session = AsyncMock()
            mock_result = MagicMock()

            # 模拟全量备份记录
            full_record = mock_backup_record
            full_record.type = 'full'
            full_record.status = 'success'

            # 模拟查询结果
            mock_result.scalars.return_value.all.return_value = [full_record, full_record]
            mock_session.execute.return_value = mock_result
            mock_context.return_value.__aenter__.return_value = mock_session

            summary = await metrics_service.get_performance_summary(hours=24, backup_type='full')

            assert summary['backup_type'] == 'full'
            assert summary['total_backups'] == 2
            assert summary['success_count'] == 2
            assert summary['failed_count'] == 0
            assert summary['success_rate'] == 100.0

    @pytest.mark.asyncio
    async def test_get_performance_summary_no_data(self, metrics_service):
        """测试获取性能摘要（无数据）"""
        with patch('fastapi_app.services.backup.metrics.service.get_async_db_context') as mock_context:
            mock_session = AsyncMock()
            mock_result = MagicMock()

            # 模拟无数据
            mock_result.scalars.return_value.all.return_value = []
            mock_session.execute.return_value = mock_result
            mock_context.return_value.__aenter__.return_value = mock_session

            summary = await metrics_service.get_performance_summary(hours=24)

            assert summary['total_backups'] == 0
            assert summary['success_rate'] == 0
            assert summary['average_duration'] == 0
            assert summary['total_size_mb'] == 0

    @pytest.mark.asyncio
    async def test_get_trend_analysis(self, metrics_service, mock_backup_record):
        """测试获取趋势分析"""
        with patch('fastapi_app.services.backup.metrics.service.get_async_db_context') as mock_context:
            mock_session = AsyncMock()
            mock_result = MagicMock()

            # 模拟不同日期的备份记录
            records = []
            for i in range(7):  # 最近7天
                record = MagicMock()
                record.type = 'full'
                record.status = 'success' if i < 6 else 'failed'  # 第7天失败
                record.created_at = datetime.now() - timedelta(days=6-i)
                record.size = 1024 * 1024 * 100  # 100MB
                record.duration_seconds = 300.0
                records.append(record)

            mock_result.scalars.return_value.all.return_value = records
            mock_session.execute.return_value = mock_result
            mock_context.return_value.__aenter__.return_value = mock_session

            analysis = await metrics_service.get_trend_analysis(days=7)

            assert 'time_period_days' in analysis
            assert 'backup_type' in analysis
            assert 'start_date' in analysis
            assert 'end_date' in analysis
            assert 'total_backups' in analysis
            assert 'total_success' in analysis
            assert 'total_failed' in analysis
            assert 'overall_success_rate' in analysis
            assert 'average_success_rate' in analysis
            assert 'trend_direction' in analysis
            assert 'daily_stats' in analysis
            assert 'success_rates' in analysis
            assert 'recommendations' in analysis

            assert analysis['time_period_days'] == 7
            assert analysis['backup_type'] == 'all'
            assert analysis['total_backups'] == 7
            assert analysis['total_success'] == 6
            assert analysis['total_failed'] == 1
            assert analysis['overall_success_rate'] == pytest.approx(85.71, 0.01)
            assert len(analysis['daily_stats']) == 7
            assert len(analysis['success_rates']) == 7
            assert analysis['trend_direction'] in ['stable', 'improving', 'declining']

            # 检查每日统计
            for day_stat in analysis['daily_stats']:
                assert 'date' in day_stat
                assert 'total' in day_stat
                assert 'success' in day_stat
                assert 'failed' in day_stat
                assert 'total_size' in day_stat
                assert 'total_duration' in day_stat
                assert 'avg_duration' in day_stat

    def test_generate_trend_recommendations(self, metrics_service):
        """测试生成趋势建议"""
        # 测试正常情况
        daily_stats = [
            {'date': '2024-01-01', 'total': 10, 'success': 10, 'failed': 0, 'total_size': 1000},
            {'date': '2024-01-02', 'total': 12, 'success': 12, 'failed': 0, 'total_size': 1200},
            {'date': '2024-01-03', 'total': 15, 'success': 15, 'failed': 0, 'total_size': 1500},
        ]
        success_rates = [100.0, 100.0, 100.0]

        recommendations = metrics_service._generate_trend_recommendations(daily_stats, success_rates)

        # 所有指标正常，应该有正面反馈
        assert len(recommendations) == 0  # 或者可能是其他建议

        # 测试成功率低
        success_rates = [80.0, 85.0, 82.0]
        recommendations = metrics_service._generate_trend_recommendations(daily_stats, success_rates)

        assert len(recommendations) > 0
        assert any('成功率' in rec for rec in recommendations)

        # 测试备份频率低
        daily_stats = [
            {'date': '2024-01-01', 'total': 0, 'success': 0, 'failed': 0, 'total_size': 0},
            {'date': '2024-01-02', 'total': 1, 'success': 1, 'failed': 0, 'total_size': 100},
            {'date': '2024-01-03', 'total': 0, 'success': 0, 'failed': 0, 'total_size': 0},
        ]
        success_rates = [0.0, 100.0, 0.0]

        recommendations = metrics_service._generate_trend_recommendations(daily_stats, success_rates)

        assert len(recommendations) > 0
        assert any('备份频率过低' in rec for rec in recommendations)

        # 测试备份大小变化大
        daily_stats = [
            {'date': '2024-01-01', 'total': 10, 'success': 10, 'failed': 0, 'total_size': 1000},
            {'date': '2024-01-02', 'total': 10, 'success': 10, 'failed': 0, 'total_size': 2000},
            {'date': '2024-01-03', 'total': 10, 'success': 10, 'failed': 0, 'total_size': 3000},
        ]
        success_rates = [100.0, 100.0, 100.0]

        recommendations = metrics_service._generate_trend_recommendations(daily_stats, success_rates)

        assert len(recommendations) > 0
        assert any('备份大小变化显著' in rec for rec in recommendations)

    @pytest.mark.asyncio
    async def test_get_performance_alerts_normal(self, metrics_service):
        """测试获取性能告警（正常）"""
        with patch.object(metrics_service, 'get_performance_summary') as mock_summary:
            # 模拟正常性能摘要
            mock_summary.return_value = {
                'success_rate': 98.5,
                'failed_count': 1,
                'average_duration_seconds': 600.0,
                'total_size_mb': 500.0
            }

            alerts = await metrics_service.get_performance_alerts()

            # 所有指标都在阈值内，应该没有告警
            assert len(alerts) == 0

    @pytest.mark.asyncio
    async def test_get_performance_alerts_warning(self, metrics_service):
        """测试获取性能告警（警告）"""
        with patch.object(metrics_service, 'get_performance_summary') as mock_summary:
            # 模拟有问题的性能摘要
            mock_summary.return_value = {
                'success_rate': 90.0,  # 低于95%阈值
                'failed_count': 5,      # 高于3次阈值
                'average_duration_seconds': 2000.0,  # 高于1800秒阈值
                'total_size_mb': 1500.0  # 高于1024MB阈值
            }

            alerts = await metrics_service.get_performance_alerts()

            # 应该有多个告警
            assert len(alerts) >= 3  # 至少成功率、失败次数、耗时、大小

            # 检查告警类型
            alert_types = [alert['type'] for alert in alerts]
            assert 'success_rate_low' in alert_types
            assert 'failure_count_high' in alert_types
            assert 'duration_too_long' in alert_types
            assert 'size_too_large' in alert_types

            # 检查告警内容
            for alert in alerts:
                assert 'type' in alert
                assert 'severity' in alert
                assert 'message' in alert
                assert 'current_value' in alert
                assert 'threshold' in alert
                assert 'time_period' in alert

    @pytest.mark.asyncio
    async def test_get_performance_alerts_exception(self, metrics_service):
        """测试获取性能告警（异常）"""
        with patch.object(metrics_service, 'get_performance_summary') as mock_summary:
            mock_summary.side_effect = Exception('获取性能摘要失败')

            alerts = await metrics_service.get_performance_alerts()

            # 应该有错误告警
            assert len(alerts) == 1
            assert alerts[0]['type'] == 'metrics_error'
            assert alerts[0]['severity'] == 'error'
            assert '获取性能摘要失败' in alerts[0]['message']

    @pytest.mark.asyncio
    async def test_export_metrics_report(self, metrics_service):
        """测试导出指标报告"""
        with patch.object(metrics_service, 'get_performance_summary') as mock_summary, \
             patch.object(metrics_service, 'get_trend_analysis') as mock_trend, \
             patch.object(metrics_service, 'get_performance_alerts') as mock_alerts:

            # 模拟数据
            mock_summary.return_value = {
                'time_period_hours': 24,
                'total_backups': 100,
                'success_rate': 98.5,
                'average_duration_seconds': 600.0
            }

            mock_trend.return_value = {
                'time_period_days': 7,
                'overall_success_rate': 97.8,
                'trend_direction': 'stable',
                'recommendations': ['建议1', '建议2']
            }

            mock_alerts.return_value = [
                {
                    'type': 'success_rate_low',
                    'severity': 'warning',
                    'message': '备份成功率低于阈值',
                    'current_value': 90.0,
                    'threshold': 95.0,
                    'time_period': '24h'
                }
            ]

            report = await metrics_service.export_metrics_report(days=7, format='json')

            assert 'generated_at' in report
            assert 'time_period_days' in report
            assert 'summary' in report
            assert 'trend_analysis' in report
            assert 'alerts' in report
            assert 'recommendations' in report

            assert report['time_period_days'] == 7
            assert report['summary']['total_backups'] == 100
            assert report['summary']['success_rate'] == 98.5
            assert report['trend_analysis']['overall_success_rate'] == 97.8
            assert report['trend_analysis']['trend_direction'] == 'stable'
            assert len(report['alerts']) == 1
            assert len(report['recommendations']) == 2

    @pytest.mark.asyncio
    async def test_export_metrics_report_exception(self, metrics_service):
        """测试导出指标报告（异常）"""
        with patch.object(metrics_service, 'get_performance_summary') as mock_summary:
            mock_summary.side_effect = Exception('测试异常')

            report = await metrics_service.export_metrics_report(days=7)

            assert 'error' in report
            assert 'message' in report
            assert '导出指标报告失败' in report['message']
