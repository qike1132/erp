"""
Celery Beat 调度配置示例

此文件展示了如何配置新的备份定时任务调度
"""

from celery.schedules import crontab

# Celery Beat 调度配置
CELERY_BEAT_SCHEDULE = {
    # ==================== 现有任务 ====================
    
    # 每日自动全量备份 - 每天凌晨2点
    'auto_daily_backup': {
        'task': 'auto_daily_backup_task',
        'schedule': crontab(hour=2, minute=0),
        'options': {
            'queue': 'batch',
            'priority': 5
        }
    },
    
    # 自动增量备份 - 每小时
    'auto_incremental_backup': {
        'task': 'auto_incremental_backup_task',
        'schedule': crontab(minute=0),
        'options': {
            'queue': 'batch',
            'priority': 6
        }
    },
    
    # 备份完整性巡检 - 每天凌晨3点
    'backup_integrity_check': {
        'task': 'backup_integrity_check_task',
        'schedule': crontab(hour=3, minute=0),
        'options': {
            'queue': 'batch',
            'priority': 7
        }
    },
    
    # 备份清理任务 - 每天凌晨1点
    'backup_cleanup': {
        'task': 'backup_cleanup_task',
        'schedule': crontab(hour=1, minute=0),
        'options': {
            'queue': 'batch',
            'priority': 8
        }
    },
    
    # ==================== 新增任务 ====================
    
    # 备份健康检查 - 每30分钟
    'backup_health_check': {
        'task': 'backup_health_check_task',
        'schedule': crontab(minute='*/30'),
        'options': {
            'queue': 'batch',
            'priority': 4
        }
    },
    
    # 应用备份策略 - 每天凌晨4点
    'apply_backup_policy': {
        'task': 'apply_backup_policy_task',
        'schedule': crontab(hour=4, minute=0),
        'options': {
            'queue': 'batch',
            'priority': 3
        }
    },
    
    # 灾难恢复测试 - 每周日凌晨5点
    'disaster_recovery_test': {
        'task': 'disaster_recovery_test_task',
        'schedule': crontab(day_of_week=0, hour=5, minute=0),  # 0=周日
        'options': {
            'queue': 'batch',
            'priority': 2
        }
    },
    
    # 备份性能指标报告 - 每天凌晨6点
    'backup_metrics_report': {
        'task': 'backup_metrics_report_task',
        'schedule': crontab(hour=6, minute=0),
        'options': {
            'queue': 'batch',
            'priority': 1
        }
    },
    
    # ==================== 其他系统任务 ====================
    
    # 系统监控任务 - 每15分钟
    'system_monitoring': {
        'task': 'system_monitoring_task',
        'schedule': crontab(minute='*/15'),
        'options': {
            'queue': 'monitor',
            'priority': 9
        }
    },
    
    # 日志清理任务 - 每天凌晨0点
    'log_cleanup': {
        'task': 'log_cleanup_task',
        'schedule': crontab(hour=0, minute=0),
        'options': {
            'queue': 'maintenance',
            'priority': 10
        }
    },
}

# 任务优先级说明（数字越小优先级越高）：
# 1: 备份性能指标报告（重要但非紧急）
# 2: 灾难恢复测试（重要，但可以在非高峰时间运行）
# 3: 应用备份策略（重要配置更新）
# 4: 备份健康检查（监控任务，需要频繁运行）
# 5: 每日全量备份（核心业务任务）
# 6: 增量备份（核心业务任务）
# 7: 完整性检查（质量保证）
# 8: 备份清理（维护任务）
# 9: 系统监控（基础监控）
# 10: 日志清理（维护任务）

# 队列配置说明：
# - batch: 批处理任务，可以长时间运行
# - monitor: 监控任务，需要快速响应
# - maintenance: 维护任务，可以在后台运行

# 如何应用此配置：
# 1. 将 CELERY_BEAT_SCHEDULE 配置添加到你的 Celery 配置中
# 2. 确保所有任务函数在相应的模块中定义
# 3. 启动 Celery Beat 调度器：
#    celery -A your_app.celery_app beat --loglevel=info
# 4. 启动 Celery Worker 处理任务：
#    celery -A your_app.celery_app worker --loglevel=info -Q batch,monitor,maintenance

# 注意事项：
# 1. 根据实际业务需求调整调度时间
# 2. 考虑系统负载和资源限制
# 3. 监控任务执行情况，及时调整配置
# 4. 确保有足够的 worker 处理并发任务
# 5. 定期检查任务日志，发现问题及时处理