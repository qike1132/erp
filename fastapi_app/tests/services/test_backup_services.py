"""
备份服务集成测试

运行所有备份相关服务的测试
"""

import pytest


def test_backup_alert_service_import():
    """测试备份告警服务导入"""
    from fastapi_app.services.backup.metrics.alert_service import BackupAlertService
    service = BackupAlertService()
    assert service is not None
    assert hasattr(service, 'send_alert')
    assert hasattr(service, 'retry_with_backoff')
    assert hasattr(service, 'get_alert_statistics')


def test_backup_health_check_service_import():
    """测试健康检查服务导入"""
    from fastapi_app.services.backup.verify.health_check_service import BackupHealthCheckService
    service = BackupHealthCheckService()
    assert service is not None
    assert hasattr(service, 'perform_health_check')
    assert hasattr(service, 'perform_recovery_test')
    assert hasattr(service, 'get_health_history')


def test_backup_policy_service_import():
    """测试备份策略服务导入"""
    from fastapi_app.services.backup.orchestration.policy_service import BackupPolicyService
    service = BackupPolicyService()
    assert service is not None
    assert hasattr(service, 'get_current_policy')
    assert hasattr(service, 'update_policy')
    assert hasattr(service, 'apply_backup_policy')
    assert hasattr(service, 'get_policy_compliance')


def test_backup_metrics_service_import():
    """测试性能监控服务导入"""
    from fastapi_app.services.backup.metrics.service import BackupMetricsService
    service = BackupMetricsService()
    assert service is not None
    assert hasattr(service, 'collect_backup_metrics')
    assert hasattr(service, 'get_performance_summary')
    assert hasattr(service, 'get_trend_analysis')
    assert hasattr(service, 'get_performance_alerts')
    assert hasattr(service, 'export_metrics_report')


def test_backup_cleanup_service_import():
    """测试备份清理服务导入"""
    from fastapi_app.services.backup.cleanup.service import BackupCleanupService
    service = BackupCleanupService()
    assert service is not None
    assert hasattr(service, 'smart_cleanup')
    assert hasattr(service, 'get_cleanup_history')


def test_backup_recovery_test_service_import():
    """测试灾难恢复测试服务导入"""
    from fastapi_app.services.backup.orchestration.recovery_test_service import DisasterRecoveryTestService
    service = DisasterRecoveryTestService()
    assert service is not None
    assert hasattr(service, 'perform_recovery_test')
    assert hasattr(service, 'get_test_history')
    assert hasattr(service, 'get_test_summary')


def test_service_interactions():
    """测试服务间交互"""
    # 测试服务可以相互导入而不冲突
    from fastapi_app.services.backup.cleanup.service import cleanup_service
    from fastapi_app.services.backup.metrics.alert_service import alert_service
    from fastapi_app.services.backup.metrics.service import metrics_service
    from fastapi_app.services.backup.orchestration.policy_service import policy_service
    from fastapi_app.services.backup.orchestration.recovery_test_service import recovery_test_service
    from fastapi_app.services.backup.verify.health_check_service import health_check_service

    assert alert_service is not None
    assert health_check_service is not None
    assert policy_service is not None
    assert metrics_service is not None
    assert cleanup_service is not None
    assert recovery_test_service is not None


def test_config_loading():
    """测试配置加载"""
    import os
    from unittest.mock import patch

    # 测试环境变量加载
    with patch.dict(os.environ, {
        'BACKUP_ALERT_FAILURE_THRESHOLD': '5',
        'BACKUP_DISK_SPACE_THRESHOLD': '15.0',
        'BACKUP_RETENTION_DAYS': '60',
        'BACKUP_METRICS_INTERVAL': '120',
        'BACKUP_SMART_CLEANUP': 'false',
        'BACKUP_RECOVERY_TEST_FREQUENCY': '14'
    }):
        from fastapi_app.services.backup.cleanup.service import BackupCleanupService
        from fastapi_app.services.backup.metrics.alert_service import BackupAlertService
        from fastapi_app.services.backup.metrics.service import BackupMetricsService
        from fastapi_app.services.backup.orchestration.policy_service import BackupPolicyService
        from fastapi_app.services.backup.orchestration.recovery_test_service import DisasterRecoveryTestService
        from fastapi_app.services.backup.verify.health_check_service import BackupHealthCheckService

        alert_service = BackupAlertService()
        health_service = BackupHealthCheckService()
        policy_service = BackupPolicyService()
        metrics_service = BackupMetricsService()
        cleanup_service = BackupCleanupService()
        recovery_service = DisasterRecoveryTestService()

        # 验证配置已加载
        assert alert_service.alert_config['failure_threshold'] == 5
        assert health_service.health_config['disk_space_threshold'] == 15.0
        assert policy_service.policy_config['retention_days'] == 60
        assert metrics_service.metrics_config['collection_interval'] == 120
        assert cleanup_service.cleanup_config['smart_cleanup_enabled'] is False
        assert recovery_service.test_config['test_frequency_days'] == 14


if __name__ == '__main__':
    """运行所有测试"""
    pytest.main([__file__, '-v'])
