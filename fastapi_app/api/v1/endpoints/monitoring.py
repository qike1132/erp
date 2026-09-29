"""
Web Vitals 监控端点 - 接收并持久化前端真实用户体验指标

数据流
------
    前端 utils/webVitals.ts
      └─ navigator.sendBeacon ──> POST /api/v1/monitoring/vitals
                                      ├─> web_vital 表（持久化，形成可验收基线）
                                      └─> 进程内 deque（/summary 的快速回退路径）

**为什么要落库**（本模块 2026-09-14 改造的核心动因）
----------------------------------------------------
此前指标只存在**进程内存**（`dict[str, deque]`），有三个硬伤，导致
"前端体验提升 X%" 永远无法验收：

1. 重启即丢 —— 无法形成跨时间基线；
2. 多 worker 各自独立（本模块原 docstring 自认 per-worker）；
3. 仅 poor / needs-improvement 打日志，正常样本不落任何地方。

**未认证端点的防护**
--------------------
sendBeacon 无法携带 auth header，故本端点按设计不认证。写入侧因此自带三层
防护，**不依赖全局限流**（`core/limiter.py` 中 `enabled=False`，内网环境全站关闭）：

1. 单请求批次上限 `_MAX_BATCH`；
2. 保留期清理 `_RETENTION_DAYS`，进程内节流至 `_CLEANUP_INTERVAL_SECONDS` 一次；
3. 落库失败**熔断**（`_persist_disabled`）—— 表未迁移或持续失败时短路后续写入，
   只告警一次，绝不拖慢或影响上报链路。
"""
import logging
import time
from collections import deque
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.core.database import get_async_db_context
from fastapi_app.core.deps import get_current_user_id
from fastapi_app.core.limiter import limiter
from fastapi_app.shared_models import WebVital

logger = logging.getLogger(__name__)
# POST /vitals：由前端 sendBeacon 上报，无法携带 auth header，因此不作认证（router.py 也不注入全局 dependency）
# GET /vitals/summary：管理端查看汇总数据，需要登录认证，在端点函数参数中单独声明 Depends
router = APIRouter()

# 单请求批次上限（前端已按 5s 节流，此处为防御性上限）
_MAX_BATCH = 50
# 进程内统计窗口：仅供 /summary 在落库不可用时回退，不作为数据源
_MAX_ENTRIES = 500
_MAX_KEYS = 100
# 保留期：超期样本被清理，防止未认证端点导致表无限增长
_RETENTION_DAYS = 30
# 清理节流：避免每个上报请求都跑一次 DELETE
_CLEANUP_INTERVAL_SECONDS = 3600
# 落库失败后的重试冷却：熔断期间短路写入，冷却结束自动重试
# （自愈设计 —— 若因"迁移尚未执行"而失败，执行迁移后无需重启进程即可恢复）
_PERSIST_RETRY_SECONDS = 300

# 落库失败时的兜底异常集合（与 core/database.py 的宽容处理口径一致）
_PERSIST_ERRORS = (SQLAlchemyError, RuntimeError, OSError, ValueError)


class VitalEntry(BaseModel):
    name: str
    value: float
    rating: str
    delta: float
    navigationType: str
    timestamp: int


class VitalsPayload(BaseModel):
    vitals: list[VitalEntry]


class VitalsReceiveResponse(BaseModel):
    ok: bool = True
    error: str = ""
    # 落库是否成功。前端 sendBeacon 不读响应，此字段用于排查"表为空"的原因
    # （最常见：迁移 pg_standalone_041_web_vital 尚未执行）。
    persisted: bool = False


class VitalsSummaryResponse(BaseModel):
    note: str = ""
    metrics: dict = {}


_vital_stats: dict[str, deque[float]] = {}
_last_cleanup_at: float = 0.0
# 熔断截止时刻（monotonic）。在此之前短路写入，避免每请求都失败并刷日志。
_persist_disabled_until: float = 0.0


def _remember(entry: VitalEntry) -> None:
    """写入进程内统计（/summary 的降级数据源）。"""
    key = f"{entry.name}:{entry.rating}"
    if key not in _vital_stats:
        if len(_vital_stats) >= _MAX_KEYS:
            return
        _vital_stats[key] = deque(maxlen=_MAX_ENTRIES)
    _vital_stats[key].append(entry.value)


async def _maybe_cleanup() -> None:
    """按保留期删除过期样本。

    节流标志在 await 之前同步置位 —— asyncio 单线程下这可正确阻止
    并发请求同时触发清理（惊群）。
    """
    global _last_cleanup_at
    now = time.monotonic()
    if now - _last_cleanup_at < _CLEANUP_INTERVAL_SECONDS:
        return
    _last_cleanup_at = now

    cutoff = datetime.now(UTC) - timedelta(days=_RETENTION_DAYS)
    async with get_async_db_context() as db:
        await db.execute(delete(WebVital).where(WebVital.created_at < cutoff))
    logger.info('WebVitals 已清理 %s 天前的历史样本', _RETENTION_DAYS)


async def _persist(entries: list[VitalEntry], path: str) -> bool:
    """把上报样本写入 web_vital 表。

    任何失败都不得影响上报链路 —— 前端 sendBeacon 是 fire-and-forget，
    但异常若冒泡会导致 500，污染错误率指标。故此处全量兜底并熔断。
    """
    global _persist_disabled_until
    if time.monotonic() < _persist_disabled_until:
        return False
    try:
        async with get_async_db_context() as db:
            db.add_all([
                WebVital(
                    name=e.name[:16],
                    value=e.value,
                    rating=e.rating[:24],
                    delta=e.delta,
                    navigation_type=(e.navigationType or '')[:24] or None,
                    path=path[:500] or None,
                )
                for e in entries
            ])
    except _PERSIST_ERRORS as exc:
        _persist_disabled_until = time.monotonic() + _PERSIST_RETRY_SECONDS
        logger.warning(
            'WebVitals 落库失败，%s 秒内不再重试。请确认已执行迁移 '
            'pg_standalone_041_web_vital：%s', _PERSIST_RETRY_SECONDS, exc,
        )
        return False

    # 清理失败不应影响落库结果，单独兜底
    try:
        await _maybe_cleanup()
    except _PERSIST_ERRORS:
        logger.warning('WebVitals 保留期清理失败（不影响上报）', exc_info=True)
    return True


async def _summarize_from_db(hours: int) -> dict:
    """按指标名 × 评级聚合，返回 count / avg / p95。"""
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    async with get_async_db_context() as db:
        rows = (await db.execute(
            select(
                WebVital.name,
                WebVital.rating,
                func.count().label('n'),
                func.avg(WebVital.value).label('avg_value'),
                func.percentile_cont(0.95).within_group(WebVital.value).label('p95'),
            )
            .where(WebVital.created_at >= cutoff)
            .group_by(WebVital.name, WebVital.rating)
        )).all()

    result: dict[str, dict] = {}
    for name, rating, n, avg_value, p95 in rows:
        result.setdefault(name, {})[rating] = {
            'count': int(n),
            'avg': round(float(avg_value), 1),
            'p95': round(float(p95), 1),
        }
    return result


def _summarize_from_memory() -> dict:
    """进程内统计（降级路径，多 worker 各自独立）。"""
    result: dict[str, dict] = {}
    for key, values in _vital_stats.items():
        name, rating = key.split(':')
        vals = list(values)
        result.setdefault(name, {})[rating] = {
            'count': len(vals),
            'avg': round(sum(vals) / len(vals), 1) if vals else 0,
            'p95': round(sorted(vals)[min(int(len(vals) * 0.95) - 1, len(vals) - 1)], 1) if len(vals) > 1 else round(vals[0], 1) if vals else 0,
        }
    return result


@router.post("/vitals", response_model=VitalsReceiveResponse)
@limiter.limit("30/minute")  # M-1：匿名端点（sendBeacon 带不了鉴权头），靠 IP/用户限流挡存储洪泛
async def receive_vitals(payload: VitalsPayload, request: Request):
    if len(payload.vitals) > _MAX_BATCH:
        return {"ok": False, "error": "batch too large", "persisted": False}

    referer = request.headers.get("referer", "")

    for v in payload.vitals:
        if v.rating in ("poor", "needs-improvement"):
            logger.warning(
                "WebVitals: name=%s value=%.1fms rating=%s nav=%s path=%s",
                v.name, v.value, v.rating, v.navigationType, referer,
            )
        _remember(v)

    persisted = await _persist(payload.vitals, referer)
    return {"ok": True, "persisted": persisted}


@router.get("/vitals/summary", response_model=VitalsSummaryResponse)
async def vitals_summary(
    hours: int = Query(24, ge=1, le=24 * 30, description='统计时间窗（小时）'),
    _current_user_id: int = Depends(get_current_user_id),
):
    """查看 Web Vitals 汇总数据（需登录）。

    优先读持久化表 —— 跨 worker 聚合、跨重启保留，可作为体验基线；
    表不可用时回退进程内统计（多 worker 各自独立）。
    """
    try:
        metrics = await _summarize_from_db(hours)
        return {
            "note": f"来自 web_vital 表，时间窗 {hours}h",
            "metrics": metrics,
        }
    except _PERSIST_ERRORS:
        logger.warning('WebVitals 汇总读库失败，回退进程内统计', exc_info=True)
        return {
            "note": "进程内统计（多 worker 各自独立、重启即丢；请确认已执行迁移）",
            "metrics": _summarize_from_memory(),
        }
