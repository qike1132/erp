# 备份定时任务改进文档

## 概述

本文档介绍了对备份定时任务文件 (`backup_tasks.py`) 的改进，包括新增的备份失败自动告警机制、健康检查监控、备份策略管理、性能监控、智能清理和灾难恢复测试功能。

## 新增功能

### 1. 备份失败自动告警机制

#### 功能描述
- 修改现有的定时任务，添加失败告警功能
- 支持多种告警方式：日志记录、邮件通知、数据库记录、Webhook触发
- 添加重试机制和指数退避
- 连续失败达到阈值时升级告警级别

#### 核心类
- `BackupAlertService`: 备份告警服务

#### 配置项
```bash
# 邮件告警配置
BACKUP_ALERT_EMAIL_ENABLED=false
BACKUP_ALERT_SMTP_HOST=smtp.gmail.com
BACKUP_ALERT_SMTP_PORT=587
BACKUP_ALERT_SMTP_USERNAME=
BACKUP_ALERT_SMTP_PASSWORD=
BACKUP_ALERT_EMAIL_FROM=
BACKUP_ALERT_EMAIL_TO=

# Webhook告警配置
BACKUP_ALERT_WEBHOOK_ENABLED=false
BACKUP_ALERT_WEBHOOK_URL=
BACKUP_ALERT_WEBHOOK_HEADERS={"Content-Type": "application/json"}

# 告警阈值配置
BACKUP_ALERT_FAILURE_THRESHOLD=3
BACKUP_ALERT_CRITICAL_THRESHOLD=5
BACKUP_ALERT_COOLDOWN_MINUTES=30
BACKUP_ALERT_MAX_RETRIES=3
BACKUP_ALERT_RETRY_DELAY_BASE=2
```

#### 使用方法
```python
from fastapi_app.services.backup_alert_service import alert_service

# 发送告警
await alert_service.send_alert(
    task_name='daily_backup',
    error='备份失败：磁盘空间不足',
    task_type='backup',
    severity='error',
    additional_info={'backup_size': '500MB', 'free_space': '1GB'}
)

# 指数退避重试
success, result = await alert_service.retry_with_backoff(
    task_func=backup_function,
    task_name='daily_backup',
    arg1=value1,
    arg2=value2
)

# 获取告警统计
stats = await alert_service.get_alert_statistics(days=7)
```

### 2. 健康检查监控

#### 功能描述
- 添加新的定时任务 `backup_health_check_task`
- 检查项目：备份目录可用空间、最近备份时间、备份文件完整性、恢复测试
- 生成健康报告并存储到数据库

#### 核心类
- `BackupHealthCheckService`: 健康检查服务

#### 配置项
```bash
# 健康检查配置
BACKUP_DISK_SPACE_THRESHOLD=10.0
BACKUP_AGE_THRESHOLD=24
BACKUP_INTEGRITY_SAMPLE_RATE=10.0
BACKUP_RECOVERY_TEST_FREQUENCY=7
BACKUP_HEALTH_CHECK_INTERVAL=60
BACKUP_REPORT_RETENTION_DAYS=30
```

#### 使用方法
```python
from fastapi_app.services.backup_health_check_service import health_check_service

# 执行健康检查
health_report = await health_check_service.perform_health_check()

# 执行恢复测试
recovery_test_result = await health_check_service.perform_recovery_test()

# 获取健康历史
health_history = await health_check_service.get_health_history(days=7)
```

### 3. 备份策略管理

#### 功能描述
- 添加备份策略配置：全量/增量备份频率、保留策略、加密设置
- 添加 `apply_backup_policy_task` 定时任务，根据策略执行备份

#### 核心类
- `BackupPolicyService`: 备份策略管理服务

#### 配置项
```bash
# 备份策略配置
BACKUP_FULL_CRON=0 2 * * *
BACKUP_INCREMENTAL_CRON=0 */1 * * *
BACKUP_RETENTION_DAYS=30
BACKUP_RETENTION_COUNT=100
BACKUP_ENCRYPTION_ENABLED=false
BACKUP_ENCRYPTION_ALGORITHM=AES256
BACKUP_ENCRYPTION_KEY_PATH=
BACKUP_COMPRESSION_LEVEL=6
BACKUP_STORAGE_LOCATION=backups/server
BACKUP_PRE_CHECK=true
BACKUP_POST_VALIDATION=true
BACKUP_PARALLEL=false
BACKUP_MAX_PARALLEL_JOBS=2
BACKUP_NOTIFY_SUCCESS=false
BACKUP_NOTIFY_FAILURE=true
BACKUP_NOTIFY_WARNING=true
```

#### 使用方法
```python
from fastapi_app.services.backup_policy_service import policy_service

# 获取当前策略
current_policy = await policy_service.get_current_policy()

# 更新策略
success, message = await policy_service.update_policy({
    'policy_name': 'custom_policy',
    'full_backup': {
        'enabled': True,
        'schedule': '0 3 * * *',
        'timeout_minutes': 45
    },
    'retention': {
        'enabled': True,
        'strategy': 'hybrid',
        'retention_days': 60,
        'retention_count': 200
    }
})

# 应用策略
result = await policy_service.apply_backup_policy()

# 获取策略合规性报告
compliance = await policy_service.get_policy_compliance()
```

### 4. 性能监控指标收集

#### 功能描述
- 添加备份性能指标收集：备份耗时、备份大小、压缩率、成功率、资源使用
- 存储指标到数据库，用于趋势分析

#### 核心类
- `BackupMetricsService`: 性能监控服务

#### 配置项
```bash
# 性能监控配置
BACKUP_METRICS_INTERVAL=60
BACKUP_METRICS_RETENTION_DAYS=90
BACKUP_DURATION_THRESHOLD=1800
BACKUP_SIZE_THRESHOLD=1073741824
BACKUP_CPU_THRESHOLD=80.0
BACKUP_MEMORY_THRESHOLD=80.0
BACKUP_DISK_IO_THRESHOLD=100
BACKUP_TREND_WINDOW=24
BACKUP_SUCCESS_RATE_THRESHOLD=95.0
BACKUP_FAILURE_COUNT_THRESHOLD=3
```

#### 使用方法
```python
from fastapi_app.services.backup_metrics_service import metrics_service

# 收集备份指标
metrics = await metrics_service.collect_backup_metrics(
    backup_type='full',
    start_time=start_time,
    end_time=end_time,
    backup_size=backup_size,
    success=True,
    error_message=None,
    additional_metrics={'original_size': original_size}
)

# 获取性能摘要
summary = await metrics_service.get_performance_summary(hours=24)

# 获取趋势分析
trend = await metrics_service.get_trend_analysis(days=7)

# 获取性能告警
alerts = await metrics_service.get_performance_alerts()

# 导出指标报告
report = await metrics_service.export_metrics_report(days=7, format='json')
```

### 5. 自动清理优化

#### 功能描述
- 优化现有的 `backup_cleanup_task`
- 添加智能清理策略：基于存储空间使用率、备份重要性、恢复测试结果
- 添加清理报告和通知

#### 核心类
- `BackupCleanupService`: 备份清理服务

#### 配置项
```bash
# 智能清理配置
BACKUP_SMART_CLEANUP=true
BACKUP_KEEP_MANUAL=true
BACKUP_KEEP_FAILED=false
BACKUP_MIN_FREE_SPACE_GB=10.0
BACKUP_TEST_BEFORE_DELETE=false
BACKUP_TEST_SAMPLE_RATE=10.0
BACKUP_NOTIFY_CLEANUP=true
BACKUP_CLEANUP_REPORT_DAYS=7
```

#### 使用方法
```python
from fastapi_app.services.backup_cleanup_service import cleanup_service

# 执行智能清理
cleanup_result = await cleanup_service.smart_cleanup()

# 获取清理历史
cleanup_history = await cleanup_service.get_cleanup_history(days=7)
```

### 6. 灾难恢复测试

#### 功能描述
- 添加 `disaster_recovery_test_task` 定时任务
- 定期从备份中恢复测试数据到临时环境
- 验证恢复数据的完整性和可用性
- 生成恢复测试报告

#### 核心类
- `DisasterRecoveryTestService`: 灾难恢复测试服务

#### 配置项
```bash
# 灾难恢复测试配置
BACKUP_RECOVERY_TEST_FREQUENCY=7
BACKUP_TEST_DB_HOST=localhost
BACKUP_TEST_DB_PORT=5432
BACKUP_TEST_DB_NAME=erp_backup_test
BACKUP_TEST_DB_USER=postgres
BACKUP_TEST_DB_PASSWORD=
BACKUP_TEST_SAMPLE_SIZE=100
BACKUP_TEST_TIMEOUT_MINUTES=30
BACKUP_CLEANUP_TEST_DB=true
BACKUP_VALIDATE_INTEGRITY=true
BACKUP_VALIDATE_SCHEMA=true
BACKUP_VALIDATE_CONSTRAINTS=true
BACKUP_NOTIFY_TEST_SUCCESS=true
BACKUP_NOTIFY_TEST_FAILURE=true
BACKUP_TEST_REPORT_RETENTION_DAYS=30
```

#### 使用方法
```python
from fastapi_app.services.backup_recovery_test_service import recovery_test_service

# 执行恢复测试
test_result = await recovery_test_service.perform_recovery_test()

# 指定备份文件进行测试
test_result = await recovery_test_service.perform_recovery_test(
    backup_file='erp_backup_20240101_120000.zip'
)

# 获取测试历史
test_history = await recovery_test_service.get_test_history(days=30)

# 获取测试摘要
test_summary = await recovery_test_service.get_test_summary(days=30)
```

## 定时任务集成

### 新增定时任务

在 `backup_tasks.py` 中添加以下定时任务：

```python
@shared_task(bind=True, name='backup_health_check_task', queue='batch', time_limit=600, max_retries=1, default_retry_delay=60)
def backup_health_check_task(self):
    """备份健康检查任务"""
    logger.info('开始执行备份健康检查...')
    try:
        from fastapi_app.services.backup_health_check_service import health_check_service
        result = _run_async(health_check_service.perform_health_check())
        
        if result.get('overall_status') != 'healthy':
            logger.warning(f'备份健康检查发现问题: {result.get("issues", [])}')
        
        logger.info(f'备份健康检查完成: {result.get("overall_status")}')
        return result
    except Exception as e:
        logger.error(f'备份健康检查失败: {e}')
        # 发送告警
        _run_async(alert_service.send_alert(
            task_name='backup_health_check',
            error=f'备份健康检查失败: {str(e)}',
            task_type='health_check',
            severity='error'
        ))
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e) from e
        return {'status': 'error', 'error': str(e)}


@shared_task(bind=True, name='apply_backup_policy_task', queue='batch', time_limit=300, max_retries=1, default_retry_delay=30)
def apply_backup_policy_task(self):
    """应用备份策略任务"""
    logger.info('开始应用备份策略...')
    try:
        from fastapi_app.services.backup_policy_service import policy_service
        result = _run_async(policy_service.apply_backup_policy())
        
        if result.get('success'):
            logger.info(f'备份策略应用成功: {result.get("message")}')
        else:
            logger.error(f'备份策略应用失败: {result.get("error")}')
            
        return result
    except Exception as e:
        logger.error(f'应用备份策略失败: {e}')
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e) from e
        return {'status': 'error', 'error': str(e)}


@shared_task(bind=True, name='disaster_recovery_test_task', queue='batch', time_limit=1800, max_retries=1, default_retry_delay=300)
def disaster_recovery_test_task(self):
    """灾难恢复测试任务"""
    logger.info('开始执行灾难恢复测试...')
    try:
        from fastapi_app.services.backup_recovery_test_service import recovery_test_service
        result = _run_async(recovery_recovery_test_service.perform_recovery_test())
        
        if result.get('overall_success'):
            logger.info(f'灾难恢复测试成功: {result.get("summary", {})}')
        else:
            logger.error(f'灾难恢复测试失败: {result.get("error")}')
            
        return result
    except Exception as e:
        logger.error(f'灾难恢复测试失败: {e}')
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e) from e
        return {'status': 'error', 'error': str(e)}
```

### 优化现有任务

更新现有的 `backup_cleanup_task` 以使用新的清理服务：

```python
@shared_task(bind=True, name='backup_cleanup_task', queue='batch', time_limit=300, max_retries=1, default_retry_delay=30)
def backup_cleanup_task(self):
    """备份清理任务（智能清理）"""
    logger.info('开始执行备份智能清理...')
    try:
        from fastapi_app.services.backup_cleanup_service import cleanup_service
        result = _run_async(cleanup_service.smart_cleanup())
        
        if result.get('success'):
            logger.info(f'备份智能清理完成: 删除 {result.get("cleanup_result", {}).get("deleted_count", 0)} 个文件')
        else:
            logger.error(f'备份智能清理失败: {result.get("error")}')
            
        return result
    except Exception as e:
        logger.error(f'备份智能清理失败: {e}')
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e) from e
        return {'status': 'error', 'error': str(e)}
```

## 配置示例

### Celery Beat 调度配置

在 Celery Beat 调度配置中添加新任务：

```python
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    # 现有任务
    'auto_daily_backup': {
        'task': 'auto_daily_backup_task',
        'schedule': crontab(hour=2, minute=0),  # 每天凌晨2点
    },
    'auto_incremental_backup': {
        'task': 'auto_incremental_backup_task',
        'schedule': crontab(minute=0),  # 每小时
    },
    'backup_integrity_check': {
        'task': 'backup_integrity_check_task',
        'schedule': crontab(hour=3, minute=0),  # 每天凌晨3点
    },
    
    # 新增任务
    'backup_health_check': {
        'task': 'backup_health_check_task',
        'schedule': crontab(minute='*/30'),  # 每30分钟
    },
    'apply_backup_policy': {
        'task': 'apply_backup_policy_task',
        'schedule': crontab(hour=4, minute=0),  # 每天凌晨4点
    },
    'disaster_recovery_test': {
        'task': 'disaster_recovery_test_task',
        'schedule': crontab(day_of_week=0, hour=5, minute=0),  # 每周日凌晨5点
    },
    'backup_cleanup': {
        'task': 'backup_cleanup_task',
        'schedule': crontab(hour=1, minute=0),  # 每天凌晨1点
    },
}
```

## 测试

### 单元测试

运行备份服务的单元测试：

```bash
# 运行所有备份服务测试
pytest fastapi_app/tests/services/test_backup_services.py -v

# 运行特定服务测试
pytest fastapi_app/tests/services/test_backup_alert_service.py -v
pytest fastapi_app/tests/services/test_backup_health_check_service.py -v
pytest fastapi_app/tests/services/test_backup_policy_service.py -v
pytest fastapi_app/tests/services/test_backup_metrics_service.py -v
pytest fastapi_app/tests/services/test_backup_cleanup_service.py -v
pytest fastapi_app/tests/services/test_backup_recovery_test_service.py -v
```

### 集成测试

1. 启动 Celery worker 和 beat：
```bash
celery -A fastapi_app.celery_app worker --loglevel=info -Q batch
celery -A fastapi_app.celery_app beat --loglevel=info
```

2. 手动触发任务测试：
```python
from fastapi_app.tasks.backup_tasks import (
    backup_health_check_task,
    apply_backup_policy_task,
    disaster_recovery_test_task,
    backup_cleanup_task
)

# 执行健康检查
result = backup_health_check_task.delay().get(timeout=600)

# 应用备份策略
result = apply_backup_policy_task.delay().get(timeout=300)

# 执行灾难恢复测试
result = disaster_recovery_test_task.delay().get(timeout=1800)

# 执行智能清理
result = backup_cleanup_task.delay().get(timeout=300)
```

## 监控和告警

### 告警渠道配置

1. **邮件告警**：
   - 配置 SMTP 服务器信息
   - 设置发件人和收件人列表
   - 启用邮件告警：`BACKUP_ALERT_EMAIL_ENABLED=true`

2. **Webhook 告警**：
   - 配置 Webhook URL
   - 设置请求头信息
   - 启用 Webhook 告警：`BACKUP_ALERT_WEBHOOK_ENABLED=true`

3. **日志告警**：
   - 自动记录到应用日志
   - 支持不同日志级别（INFO/WARNING/ERROR/CRITICAL）

### 健康检查报告

健康检查报告存储在 `backups/server/health_reports/` 目录下，按时间戳命名：
- `health_report_YYYYMMDD_HHMMSS.json`

报告内容包括：
- 整体状态（healthy/warning/error）
- 各项检查结果
- 发现的问题
- 改进建议

### 性能监控指标

性能指标存储在 `backups/server/metrics/` 目录下，按日期分组：
- `backup_metrics_YYYYMMDD.json`

指标包括：
- 备份耗时、大小、压缩率
- 系统资源使用情况
- 成功率统计
- 趋势分析数据

## 故障排除

### 常见问题

1. **告警未发送**：
   - 检查告警配置是否正确
   - 验证 SMTP 或 Webhook 连接
   - 检查告警阈值设置

2. **健康检查失败**：
   - 检查备份目录权限
   - 验证磁盘空间是否充足
   - 检查备份文件完整性

3. **策略应用失败**：
   - 验证策略配置格式
   - 检查 Cron 表达式是否正确
   - 查看日志了解具体错误

4. **性能监控数据缺失**：
   - 检查指标收集间隔设置
   - 验证数据库连接
   - 检查指标存储目录权限

### 日志查看

查看备份相关日志：
```bash
# 查看 Celery worker 日志
tail -f logs/celery_worker.log

# 查看备份任务日志
grep "备份" logs/app.log

# 查看错误日志
grep "ERROR" logs/app.log | grep -i backup
```

## 性能优化建议

1. **调整检查频率**：
   - 根据系统负载调整健康检查间隔
   - 合理设置性能监控数据保留时间
   - 优化备份策略以减少对生产系统的影响

2. **资源限制**：
   - 设置合理的磁盘空间阈值
   - 控制并发备份任务数量
   - 优化恢复测试的资源使用

3. **存储优化**：
   - 定期清理旧的监控数据和报告
   - 使用压缩存储历史数据
   - 考虑使用外部存储备份监控数据

## 安全注意事项

1. **敏感信息保护**：
   - 加密存储备份文件
   - 保护告警配置中的凭据
   - 限制监控数据的访问权限

2. **访问控制**：
   - 限制备份目录的访问权限
   - 使用最小权限原则配置数据库用户
   - 定期审计备份和恢复操作

3. **数据保留**：
   - 遵守数据保留政策
   - 定期清理过期备份
   - 确保备份数据的完整性和可用性

## 后续改进计划

1. **多存储后端支持**：
   - 添加云存储支持（AWS S3, Azure Blob, Google Cloud Storage）
   - 支持分布式存储系统
   - 实现跨区域备份复制

2. **高级监控功能**：
   - 实时监控仪表板
   - 自定义告警规则
   - 预测性维护建议

3. **自动化恢复**：
   - 一键恢复功能
   - 时间点恢复支持
   - 跨环境恢复测试

4. **合规性报告**：
   - 生成合规性报告
   - 审计日志记录
   - 数据保护法规遵从性检查