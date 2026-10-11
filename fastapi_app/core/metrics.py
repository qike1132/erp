"""
Prometheus 指标模块
提供应用级别的监控指标，供 Prometheus 采集
若 prometheus_client 未安装，提供空操作替代，不影响应用启动
"""
import logging

logger = logging.getLogger(__name__)

METRICS_AVAILABLE = False

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
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

    Counter = Histogram = Gauge = _NoOpMetric  # type: ignore[misc,assignment]
    CONTENT_TYPE_LATEST = "text/plain"

    def generate_latest() -> bytes:  # type: ignore[misc]
        return b""


# ==================== 请求指标 ====================
# 防止热重载时重复注册：先检查指标是否已存在于全局注册表

def _get_or_create_counter(name, doc, labelnames=None):
    """获取或创建 Counter，避免热重载时 ValueError: Duplicated timeseries"""
    if not METRICS_AVAILABLE:
        return _NoOpMetric()  # type: ignore[return-value]
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
        return _NoOpMetric()  # type: ignore[return-value]
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
        return _NoOpMetric()  # type: ignore[return-value]
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

DOMAIN_EVENT_PUBLISH_FAILURES = _get_or_create_counter(
    'domain_event_publish_failures_total',
    '领域事件发布失败次数（按事件类型）',
    ['event_type']
)


# ==================== 业务指标 ====================

DB_CONNECTIONS_ACTIVE = _get_or_create_gauge(
    'db_connections_active',
    '活跃数据库连接数'
)

DB_POOL_SIZE = _get_or_create_gauge(
    'db_pool_size',
    '连接池大小（总容量）',
    ['pool']
)

DB_POOL_CHECKED_OUT = _get_or_create_gauge(
    'db_pool_checked_out',
    '连接池已签出连接数',
    ['pool']
)

DB_POOL_OVERFLOW = _get_or_create_gauge(
    'db_pool_overflow',
    '连接池溢出连接数',
    ['pool']
)

DB_POOL_CHECKEDIN = _get_or_create_gauge(
    'db_pool_checked_in',
    '连接池空闲连接数',
    ['pool']
)

DB_POOL_WAITING = _get_or_create_gauge(
    'db_pool_waiting',
    '等待连接的请求数',
    ['pool']
)

CACHE_OPERATIONS = _get_or_create_counter(
    'cache_operations_total',
    '缓存操作计数',
    ['operation']
)

SLOW_QUERY_TOTAL = _get_or_create_counter(
    'slow_query_total',
    '慢查询总数（超过阈值的SQL查询）'
)

TASK_FAILURE_TOTAL = _get_or_create_counter(
    'arq_task_failure_total',
    'ARQ任务失败总数（重试耗尽后计入）',
    ['task']
)

TASK_RUNTIME_SECONDS = _get_or_create_histogram(
    'arq_task_runtime_seconds',
    'ARQ任务运行耗时（秒）',
    ['task'],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600]
)


# ==================== 缓存监控指标 ====================

PERM_CACHE_SIZE = _get_or_create_gauge(
    'erp_perm_cache_size',
    '权限缓存当前大小（L1 TTL Cache）'
)

PERM_CACHE_HITS = _get_or_create_counter(
    'erp_perm_cache_hits_total',
    '权限缓存命中次数'
)

PERM_CACHE_MISSES = _get_or_create_counter(
    'erp_perm_cache_misses_total',
    '权限缓存未命中次数'
)

USER_ACTIVE_CACHE_SIZE = _get_or_create_gauge(
    'erp_user_active_cache_size',
    '用户活跃状态缓存当前大小'
)


# ==================== 系统资源指标 ====================

SYSTEM_CPU_USAGE = _get_or_create_gauge(
    'system_cpu_usage_percent',
    'CPU使用率(百分比)'
)

SYSTEM_MEMORY_USAGE = _get_or_create_gauge(
    'system_memory_usage_percent',
    '内存使用率(百分比)'
)

SYSTEM_DISK_USAGE = _get_or_create_gauge(
    'system_disk_usage_percent',
    '磁盘使用率(百分比)'
)

CONNECTION_POOL_UTILIZATION = _get_or_create_gauge(
    'connection_pool_utilization_percent',
    '连接池使用率(百分比)'
)

# ==================== 业务关键指标 ====================

ERROR_RATE = _get_or_create_gauge(
    'error_rate',
    '错误率(请求错误数/总请求数)'
)

RESPONSE_TIME_P95 = _get_or_create_histogram(
    'response_time_p95_seconds',
    'P95响应时间(秒)',
    ['endpoint'],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

ORDER_COUNT = _get_or_create_counter(
    'order_count_total',
    '订单总数',
    ['status']
)

STOCK_LEVEL = _get_or_create_gauge(
    'stock_level_current',
    '当前库存水平',
    ['product_id']
)

BACKUP_STATUS = _get_or_create_gauge(
    'backup_status',
    '备份状态(0=失败 1=成功 2=进行中)'
)

ARQ_DEAD_LETTER_QUEUE_DEPTH = _get_or_create_gauge(
    'arq_dead_letter_queue_depth',
    'ARQ 死信队列当前深度（条）'
)


async def refresh_dead_letter_queue_depth() -> None:
    """刷新死信队列深度（Redis ``LLEN arq:dead_letter``）。

    死信队列由 ARQ worker 进程写入，API 进程经共享 Redis 跨进程读取。
    在 ``/metrics`` 抓取前调用，使 ``arq_dead_letter_queue_depth`` 反映实时值
    （此前该指标名从未导出，``ERP_DeadLetterQueueGrowing`` 规则永不触发）。
    读取走 ``redis_wrapper``（与写入方 ``safe_lpush`` 同一条客户端栈），
    避免 ``REDIS_CACHE_URL != REDIS_URL`` 时读到不同 keyspace。
    失败静默：指标刷新绝不能影响抓取本身。
    """
    try:
        from fastapi_app.core.arq_callbacks import DLQ_KEY
        from fastapi_app.core.redis_wrapper import get_client
        client = get_client()
        if client is None:
            return
        depth = await client.llen(DLQ_KEY)
        ARQ_DEAD_LETTER_QUEUE_DEPTH.set(int(depth))
    except Exception as e:  # defensive: 刷新失败不得影响抓取；debug 级留痕便于排障
        logger.debug("死信队列深度刷新失败: %s", e)


def get_metrics():
    """生成 Prometheus 格式的指标数据"""
    return generate_latest()


def get_content_type():
    """返回 Prometheus 指标的 Content-Type"""
    return CONTENT_TYPE_LATEST
