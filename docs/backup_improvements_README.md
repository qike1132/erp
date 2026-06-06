# 备份系统改进说明

## 概述

本文档介绍了对 ERP 系统备份功能的改进，包括新增的告警机制、健康检查、策略管理、性能监控、智能清理和灾难恢复测试功能。

## 新增功能

### 1. 备份失败自动告警机制
- **功能**：备份失败时自动发送告警通知
- **告警方式**：日志记录、邮件通知、Webhook、数据库记录
- **重试机制**：指数退避重试，连续失败升级告警级别
- **配置文件**：`.env` 中的 `BACKUP_ALERT_*` 配置项

### 2. 健康检查监控
- **功能**：定期检查备份系统健康状况
- **检查项目**：磁盘空间、备份时间、文件完整性、恢复测试
- **报告**：生成健康报告并存储到数据库
- **配置文件**：`.env` 中的 `BACKUP_*_THRESHOLD` 配置项

### 3. 备份策略管理
- **功能**：灵活的备份策略配置和管理
- **策略项**：备份频率、保留策略、加密设置、通知设置
- **应用**：定时应用策略，自动清理过期备份
- **配置文件**：`.env` 中的 `BACKUP_*_CRON` 和 `BACKUP_RETENTION_*` 配置项

### 4. 性能监控指标收集
- **功能**：收集和分析备份性能指标
- **指标**：备份耗时、大小、压缩率、成功率、资源使用
- **分析**：趋势分析、性能告警、报告导出
- **配置文件**：`.env` 中的 `BACKUP_METRICS_*` 配置项

### 5. 智能清理优化
- **功能**：基于多种因素的智能备份清理
- **策略**：存储空间、备份重要性、恢复测试结果
- **报告**：清理报告和通知
- **配置文件**：`.env` 中的 `BACKUP_SMART_CLEANUP` 和 `BACKUP_*_SPACE` 配置项

### 6. 灾难恢复测试
- **功能**：定期测试备份恢复能力
- **测试**：恢复测试数据到临时环境，验证完整性
- **报告**：生成恢复测试报告
- **配置文件**：`.env` 中的 `BACKUP_RECOVERY_TEST_*` 配置项

## 快速开始

### 1. 环境配置

复制环境变量模板并配置：

```bash
cp .env.example .env
# 编辑 .env 文件，配置备份相关设置
```

主要配置项：
```bash
# 告警配置
BACKUP_ALERT_EMAIL_ENABLED=true
BACKUP_ALERT_SMTP_HOST=smtp.gmail.com
BACKUP_ALERT_SMTP_USERNAME=your-email@gmail.com
BACKUP_ALERT_SMTP_PASSWORD=your-app-password
BACKUP_ALERT_EMAIL_FROM=backup@your-domain.com
BACKUP_ALERT_EMAIL_TO=admin@your-domain.com,backup-admin@your-domain.com

# 健康检查配置
BACKUP_DISK_SPACE_THRESHOLD=10.0
BACKUP_AGE_THRESHOLD=24

# 备份策略
BACKUP_FULL_CRON=0 2 * * *
BACKUP_INCREMENTAL_CRON=0 */1 * * *
BACKUP_RETENTION_DAYS=30
BACKUP_RETENTION_COUNT=100

# 性能监控
BACKUP_METRICS_INTERVAL=60
BACKUP_SUCCESS_RATE_THRESHOLD=95.0

# 智能清理
BACKUP_SMART_CLEANUP=true
BACKUP_MIN_FREE_SPACE_GB=10.0

# 灾难恢复测试
BACKUP_RECOVERY_TEST_FREQUENCY=7
BACKUP_TEST_DB_HOST=localhost
BACKUP_TEST_DB_NAME=erp_backup_test
```

### 2. 安装依赖

确保已安装所需依赖：
```bash
pip install psutil httpx
```

### 3. 启动服务

启动 Celery worker 和 beat：

```bash
# 启动 worker（处理任务）
celery -A fastapi_app.celery_app worker --loglevel=info -Q batch

# 启动 beat（调度任务）
celery -A fastapi_app.celery_app beat --loglevel=info
```

### 4. 验证功能

手动测试新功能：

```python
# 测试健康检查
from fastapi_app.tasks.backup_tasks import backup_health_check_task
result = backup_health_check_task.delay().get(timeout=600)
print(f"健康检查结果: {result}")

# 测试策略应用
from fastapi_app.tasks.backup_tasks import apply_backup_policy_task
result = apply_backup_policy_task.delay().get(timeout=300)
print(f"策略应用结果: {result}")

# 测试恢复测试
from fastapi_app.tasks.backup_tasks import disaster_recovery_test_task
result = disaster_recovery_test_task.delay().get(timeout=1800)
print(f"恢复测试结果: {result}")
```

## 定时任务调度

### 默认调度配置

| 任务名称 | 调度时间 | 描述 |
|---------|----------|------|
| auto_daily_backup_task | 每天 02:00 | 每日全量备份 |
| auto_incremental_backup_task | 每小时 00 分 | 增量备份 |
| backup_integrity_check_task | 每天 03:00 | 备份完整性检查 |
| backup_health_check_task | 每30分钟 | 健康检查 |
| apply_backup_policy_task | 每天 04:00 | 应用备份策略 |
| disaster_recovery_test_task | 每周日 05:00 | 灾难恢复测试 |
| backup_cleanup_task | 每天 01:00 | 智能清理 |
| backup_metrics_report_task | 每天 06:00 | 性能指标报告 |

### 调整调度

在 Celery Beat 配置中调整调度时间：

```python
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'auto_daily_backup': {
        'task': 'auto_daily_backup_task',
        'schedule': crontab(hour=3, minute=0),  # 改为凌晨3点
        'options': {'queue': 'batch'}
    },
    # ... 其他任务配置
}
```

## 监控和告警

### 查看日志

```bash
# 查看备份任务日志
tail -f logs/celery_worker.log | grep -i backup

# 查看错误日志
grep "ERROR" logs/app.log | grep -i backup

# 查看告警日志
grep "ALERT" logs/app.log
```

### 检查健康状态

```python
from fastapi_app.services.backup_health_check_service import health_check_service

# 执行健康检查
health_report = await health_check_service.perform_health_check()
print(f"健康状态: {health_report.get('overall_status')}")
print(f"问题列表: {health_report.get('issues', [])}")
```

### 查看性能指标

```python
from fastapi_app.services.backup_metrics_service import metrics_service

# 获取性能摘要
summary = await metrics_service.get_performance_summary(hours=24)
print(f"24小时备份成功率: {summary.get('success_rate')}%")

# 获取趋势分析
trend = await metrics_service.get_trend_analysis(days=7)
print(f"7天趋势: {trend.get('trend_direction')}")

# 获取告警
alerts = await metrics_service.get_performance_alerts()
for alert in alerts:
    print(f"告警: {alert.get('message')}")
```

## 故障排除

### 常见问题

1. **告警未发送**
   - 检查邮件/SMTP配置
   - 验证 Webhook URL
   - 查看日志中的错误信息

2. **健康检查失败**
   - 检查备份目录权限
   - 验证磁盘空间
   - 检查备份文件完整性

3. **策略应用失败**
   - 检查策略配置文件格式
   - 验证 Cron 表达式
   - 查看数据库连接

4. **恢复测试失败**
   - 检查测试数据库配置
   - 验证备份文件完整性
   - 检查临时目录权限

### 调试命令

```bash
# 检查环境变量
python -c "import os; print([k for k in os.environ if 'BACKUP' in k])"

# 测试邮件发送
python -c "
import smtplib
from email.mime.text import MIMEText
msg = MIMEText('测试邮件')
msg['Subject'] = '测试'
msg['From'] = 'test@example.com'
msg['To'] = 'admin@example.com'
s = smtplib.SMTP('smtp.gmail.com', 587)
s.starttls()
s.login('user', 'pass')
s.send_message(msg)
s.quit()
"

# 检查备份目录
ls -la backups/server/
du -sh backups/server/
```

## 最佳实践

### 1. 容量规划
- 监控磁盘使用情况，确保有足够空间
- 根据数据增长调整保留策略
- 定期清理旧的监控数据

### 2. 性能优化
- 在系统负载低时执行备份
- 调整并发任务数量
- 监控备份耗时，优化大表备份

### 3. 安全考虑
- 加密敏感备份数据
- 限制备份文件访问权限
- 定期轮换加密密钥

### 4. 监控告警
- 设置合理的告警阈值
- 定期检查告警配置
- 建立告警响应流程

### 5. 测试验证
- 定期执行恢复测试
- 验证备份文件完整性
- 测试告警通知功能

## 扩展开发

### 添加新的告警渠道

```python
from fastapi_app.services.backup_alert_service import BackupAlertService

class CustomAlertService(BackupAlertService):
    async def _send_custom_alert(self, alert_data):
        # 实现自定义告警逻辑
        pass
    
    async def send_alert(self, task_name, error, task_type='backup', severity='error', additional_info=None):
        # 调用父类方法
        await super().send_alert(task_name, error, task_type, severity, additional_info)
        # 发送自定义告警
        await self._send_custom_alert(alert_data)
```

### 自定义健康检查

```python
from fastapi_app.services.backup_health_check_service import BackupHealthCheckService

class CustomHealthCheckService(BackupHealthCheckService):
    async def _custom_health_check(self):
        # 添加自定义健康检查
        return {'custom_check': {'healthy': True, 'message': '自定义检查通过'}}
    
    async def perform_health_check(self):
        result = await super().perform_health_check()
        custom_result = await self._custom_health_check()
        result['checks']['custom'] = custom_result['custom_check']
        return result
```

### 集成外部监控系统

```python
# 集成 Prometheus 监控
from prometheus_client import Counter, Gauge, Histogram

backup_success_counter = Counter('backup_success_total', 'Total successful backups')
backup_failure_counter = Counter('backup_failure_total', 'Total failed backups')
backup_duration_histogram = Histogram('backup_duration_seconds', 'Backup duration in seconds')

# 在备份任务中记录指标
def backup_task_with_metrics():
    start_time = time.time()
    try:
        result = perform_backup()
        backup_success_counter.inc()
        backup_duration_histogram.observe(time.time() - start_time)
        return result
    except Exception as e:
        backup_failure_counter.inc()
        raise e
```

## 支持

如有问题，请：

1. 查看日志文件：`logs/` 目录
2. 检查环境变量配置
3. 参考本文档的故障排除部分
4. 联系系统管理员

## 版本历史

- v1.0.0 (2024-01-01): 初始版本，基础备份功能
- v2.0.0 (2024-06-05): 增强版本，添加告警、监控、策略管理等功能

## 许可证

本项目遵循 MIT 许可证。