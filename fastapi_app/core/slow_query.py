"""
SQLAlchemy 慢查询监听器

通过 SQLAlchemy 事件系统监控所有 SQL 查询，
超过阈值的查询自动记录到日志和 Prometheus 指标。
"""

import time
import logging
import os

from sqlalchemy import event

logger = logging.getLogger(__name__)

SLOW_QUERY_THRESHOLD = float(os.getenv("SLOW_QUERY_THRESHOLD", "0.5"))

_slow_query_count = 0


def setup_slow_query_listener(engine):
    """为 SQLAlchemy 引擎注册慢查询监听器"""

    @event.listens_for(engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._query_start_time = time.time()

    @event.listens_for(engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        total = time.time() - context._query_start_time
        del context._query_start_time

        if total > SLOW_QUERY_THRESHOLD:
            global _slow_query_count
            _slow_query_count += 1

            truncated = statement[:200] + "..." if len(statement) > 200 else statement
            logger.warning(
                "慢查询 [%.3fs]: %s | 参数: %s",
                total,
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
