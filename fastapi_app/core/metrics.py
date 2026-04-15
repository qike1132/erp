"""
Prometheus 指标模块
提供应用级别的监控指标，供 Prometheus 采集
若 prometheus_client 未安装，提供空操作替代，不影响应用启动
"""
import logging

logger = logging.getLogger(__name__)

METRICS_AVAILABLE = False

try:
    from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
    METRICS_AVAILABLE = True
except ImportError:
    logger.warning("prometheus_client 未安装，监控指标功能已禁用")

    class _NoOpMetric:
        """空操作指标替代，确保 labels().inc()/dec()/observe() 等调用不会报错"""
        def labels(self, **kwargs):
            return self
        def inc(self, amount=1):
            pass
        def dec(self, amount=1):
            pass
        def observe(self, value):
            pass

    Counter = Histogram = Gauge = _NoOpMetric
    CONTENT_TYPE_LATEST = "text/plain"

    def generate_latest():
        return b""


# ==================== 请求指标 ====================
# 防止热重载时重复注册：先检查指标是否已存在于全局注册表

def _get_or_create_counter(name, doc, labelnames=None):
    """获取或创建 Counter，避免热重载时 ValueError: Duplicated timeseries"""
    if not METRICS_AVAILABLE:
        return Counter()
    from prometheus_client import REGISTRY
    try:
        return Counter(name, doc, labelnames or [])
    except ValueError:
        # 热重载场景：指标已存在于全局注册表，直接获取
        for collector in REGISTRY._names_to_collectors.values():
            if hasattr(collector, '_name') and collector._name == name:
                return collector
        raise

def _get_or_create_histogram(name, doc, labelnames=None, buckets=None):
    """获取或创建 Histogram，避免热重载时 ValueError: Duplicated timeseries"""
    if not METRICS_AVAILABLE:
        return Histogram()
    from prometheus_client import REGISTRY
    kwargs = {}
    if buckets:
        kwargs['buckets'] = buckets
    try:
        return Histogram(name, doc, labelnames or [], **kwargs)
    except ValueError:
        for collector in REGISTRY._names_to_collectors.values():
            if hasattr(collector, '_name') and collector._name == name:
                return collector
        raise

def _get_or_create_gauge(name, doc, labelnames=None):
    """获取或创建 Gauge，避免热重载时 ValueError: Duplicated timeseries"""
    if not METRICS_AVAILABLE:
        return Gauge()
    from prometheus_client import REGISTRY
    try:
        return Gauge(name, doc, labelnames or [])
    except ValueError:
        for collector in REGISTRY._names_to_collectors.values():
            if hasattr(collector, '_name') and collector._name == name:
                return collector
        raise


REQUEST_COUNT = _get_or_create_counter(
    'http_requests_total',
    'HTTP请求总数',
    ['method', 'endpoint', 'status']
)

REQUEST_LATENCY = _get_or_create_histogram(
    'http_request_duration_seconds',
    'HTTP请求耗时（秒）',
    ['method', 'endpoint'],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

REQUESTS_IN_PROGRESS = _get_or_create_gauge(
    'http_requests_in_progress',
    '当前处理中的请求数',
    ['method', 'endpoint']
)


# ==================== 业务指标 ====================

DB_CONNECTIONS_ACTIVE = _get_or_create_gauge(
    'db_connections_active',
    '活跃数据库连接数'
)

CACHE_OPERATIONS = _get_or_create_counter(
    'cache_operations_total',
    '缓存操作计数',
    ['operation']  # hit, miss, set, delete
)


def get_metrics():
    """生成 Prometheus 格式的指标数据"""
    return generate_latest()


def get_content_type():
    """返回 Prometheus 指标的 Content-Type"""
    return CONTENT_TYPE_LATEST
