"""
告警规则定义
覆盖关键指标阈值告警,供 Prometheus AlertManager 使用
"""

ALERT_RULES = {
    "error_rate_high": {
        "metric": "error_rate",
        "threshold": 0.05,
        "description": "错误率超过5%",
    },
    "response_time_p95_high": {
        "metric": "response_time",
        "threshold": 2.0,
        "description": "P95响应时间超过2秒",
    },
    "cpu_usage_high": {
        "metric": "cpu",
        "threshold": 80.0,
        "description": "CPU使用率超过80%",
    },
    "memory_usage_high": {
        "metric": "memory",
        "threshold": 85.0,
        "description": "内存使用率超过85%",
    },
    "disk_usage_high": {
        "metric": "disk",
        "threshold": 90.0,
        "description": "磁盘使用率超过90%",
    },
    "connection_pool_high": {
        "metric": "connection_pool",
        "threshold": 80.0,
        "description": "连接池使用率超过80%",
    },
}
