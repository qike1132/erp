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

_slow_query_count = 0
_slow_query_lock = threading.Lock()


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
        total = time.time() - context._query_start_time
        del context._query_start_time

        threshold = _get_threshold(statement)
        if total > threshold:
            with _slow_query_lock:
                _slow_query_count += 1

            truncated = statement[:200] + "..." if len(statement) > 200 else statement
            logger.warning(
                "慢查询 [%.3fs > %.2fs]: %s | 参数: %s",
                total,
                threshold,
                truncated,
                str(parameters)[:100] if parameters else "",
            )

            try:
                from fastapi_app.core.metrics import SLOW_QUERY_TOTAL
                SLOW_QUERY_TOTAL.inc()
            except (ImportError, ValueError):
                pass


def get_slow_query_count() -> int:
    return _slow_query_count
