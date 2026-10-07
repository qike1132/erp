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
from collections.abc import Mapping

from sqlalchemy import event

logger = logging.getLogger(__name__)

SLOW_QUERY_THRESHOLD = float(os.getenv("SLOW_QUERY_THRESHOLD", "0.2"))
SLOW_QUERY_REPORT_THRESHOLD = float(os.getenv("SLOW_QUERY_REPORT_THRESHOLD", "1.0"))
SLOW_QUERY_PROBE_THRESHOLD = float(os.getenv("SLOW_QUERY_PROBE_THRESHOLD", "1.0"))

_REPORT_PATTERN = re.compile(
    r'(?:SELECT\s+COUNT|GROUP\s+BY|pg_stat|export|summary|dashboard|statistics)',
    re.IGNORECASE,
)

# 基础设施健康探针：catalog / 权限存在性检查，非用户可见 OLTP 查询。
# 其耗时只反映瞬时 DB/主机负载 —— 用 OLTP 阈值(0.2s)判它会在共享主机上持续假阳性
# （2026-10-07：to_regclass / has_table_privilege 在 cron tick 上 0.24~0.36s，
#  但同刻业务查询并不慢；MV 刷新本身也未超 0.2s）。用更高的 probe 阈值判定：
# 探针真的慢（>1s）才记，0.2~1s 的抖动不再刷屏。
_PROBE_PATTERN = re.compile(
    r'(?:to_regclass|to_regtype|to_regnamespace|has_table_privilege|has_schema_privilege)',
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
    if _PROBE_PATTERN.search(statement):
        return SLOW_QUERY_PROBE_THRESHOLD
    if _REPORT_PATTERN.search(statement):
        return SLOW_QUERY_REPORT_THRESHOLD
    return SLOW_QUERY_THRESHOLD


def _kind(threshold: float) -> str:
    if threshold == SLOW_QUERY_PROBE_THRESHOLD:
        return "probe"
    if threshold == SLOW_QUERY_REPORT_THRESHOLD:
        return "report"
    return "oltp"


def _summarize_params(parameters) -> str:
    """生成参数摘要（个数+类型），不记录参数值，防止密码哈希/token/PII 写入日志"""
    if not parameters:
        return ""
    try:
        if isinstance(parameters, Mapping):
            values = list(parameters.values())
        elif isinstance(parameters, (list, tuple)) and parameters and isinstance(parameters[0], (list, tuple, Mapping)):
            # executemany 场景：参数为多组集合，摘要为批次数+首组参数摘要
            first = parameters[0]
            return f"batch={len(parameters)},first={_summarize_params(first) or '0()'}"
        elif isinstance(parameters, (list, tuple)):
            values = list(parameters)
        else:
            values = [parameters]
        types = ",".join(type(v).__name__ for v in values[:5])
        return f"{len(values)}({types}{',...' if len(values) > 5 else ''})"
    except Exception:  # defensive: 摘要生成失败时兜底，不影响慢查询记录
        return "?"


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
                _kind(threshold),
                truncated,
                f"params={_summarize_params(parameters)}" if parameters else "",
            )

            try:
                from fastapi_app.core.metrics import SLOW_QUERY_TOTAL
                SLOW_QUERY_TOTAL.inc()
            except (ImportError, ValueError, Exception):  # broad-except: 慢查询监控容错，不影响业务逻辑
                logger.debug('慢查询计数器指标更新失败', exc_info=True)


def get_slow_query_count() -> int:
    return _counter.get()


def reset_slow_query_count() -> None:
    """重置慢查询计数器（用于测试/监控指标重置）"""
    _counter.reset()
