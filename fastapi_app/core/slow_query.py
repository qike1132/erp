"""
SQLAlchemy 慢查询监听器

通过 SQLAlchemy 事件系统监控所有 SQL 查询，
超过阈值的查询自动记录到日志和 Prometheus 指标。
支持按查询类型设定不同阈值（OLTP vs 报表）。
"""

import logging
import os
import re
import threading
import time

from sqlalchemy import event

logger = logging.getLogger(__name__)

SLOW_QUERY_THRESHOLD = float(os.getenv("SLOW_QUERY_THRESHOLD", "0.2"))
SLOW_QUERY_REPORT_THRESHOLD = float(os.getenv("SLOW_QUERY_REPORT_THRESHOLD", "1.0"))

_REPORT_PATTERN = re.compile(
    r'(?:SELECT\s+COUNT|GROUP\s+BY|pg_stat|export|summary|dashboard|statistics)',
    re.IGNORECASE,
)


class _SlowQueryCounter:
    def __init__(self):
        self.value = 0
        self.lock = threading.Lock()

    def inc(self) -> int:
        with self.lock:
            self.value += 1
            return self.value

    def get(self) -> int:
        with self.lock:
            return self.value

    def reset(self) -> None:
        with self.lock:
            self.value = 0


_counter = _SlowQueryCounter()


def _get_threshold(statement: str) -> float:
    if _REPORT_PATTERN.search(statement):
        return SLOW_QUERY_REPORT_THRESHOLD
    return SLOW_QUERY_THRESHOLD


def setup_slow_query_listener(engine):
    """为 SQLAlchemy 引擎注册慢查询监听器"""

    @event.listens_for(engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._query_start_time = time.time()

    @event.listens_for(engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        start_time = getattr(context, '_query_start_time', None)
        if start_time is None:
            return
        total = time.time() - start_time

        threshold = _get_threshold(statement)
        if total > threshold:
            _counter.inc()

            truncated = statement[:200] + "..." if len(statement) > 200 else statement
            logger.warning(
                "慢查询: %.3fs (阈值: %.1fs) 类型: %s | SQL: %s | 参数: %s",
                total,
                threshold,
                "report" if threshold == SLOW_QUERY_REPORT_THRESHOLD else "oltp",
                truncated,
                str(parameters)[:100] if parameters else "",
            )

            try:
                from fastapi_app.core.metrics import SLOW_QUERY_TOTAL
                SLOW_QUERY_TOTAL.inc()
            except (ImportError, ValueError, Exception):
                pass


def get_slow_query_count() -> int:
    return _counter.get()


def reset_slow_query_count() -> None:
    """重置慢查询计数器（用于测试/监控指标重置）"""
    _counter.reset()
