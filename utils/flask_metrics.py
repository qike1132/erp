"""
Flask Prometheus 指标模块
提供 Flask 应用的监控指标，供 Prometheus 采集
"""
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST


# ==================== Flask 应用快照指标 ====================
# 使用 Gauge 而非 Counter，因为这些值来自 PerformanceMonitor 的快照

flask_requests_total = Gauge(
    'flask_requests_total',
    'Flask 请求总数(快照)'
)

flask_request_errors_total = Gauge(
    'flask_request_errors_total',
    'Flask 请求错误总数(快照)'
)

flask_slow_requests_total = Gauge(
    'flask_slow_requests_total',
    'Flask 慢请求总数(快照)'
)

flask_avg_response_time_seconds = Gauge(
    'flask_avg_response_time_seconds',
    'Flask 平均响应时间(快照)'
)


def update_flask_metrics():
    """从 PerformanceMonitor 更新指标快照"""
    try:
        from utils.performance_monitor import performance_monitor
        stats = performance_monitor.get_stats()
        flask_requests_total.set(stats.get('total_requests', 0))
        flask_request_errors_total.set(stats.get('errors', 0))
        flask_slow_requests_total.set(stats.get('slow_requests', 0))
        flask_avg_response_time_seconds.set(stats.get('avg_response_time', 0))
    except ImportError:
        pass


def get_metrics():
    """生成 Prometheus 格式的指标数据"""
    update_flask_metrics()
    return generate_latest()


def get_content_type():
    """返回 Prometheus 指标的 Content-Type"""
    return CONTENT_TYPE_LATEST
