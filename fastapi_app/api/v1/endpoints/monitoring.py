"""
Web Vitals 监控端点 - 接收前端性能指标数据
"""
import logging
from collections import deque

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from fastapi_app.core.deps import get_current_user_id

logger = logging.getLogger(__name__)
# POST /vitals：由前端 sendBeacon 上报，无法携带 auth header，因此不作认证（router.py 也不注入全局 dependency）
# GET /vitals/summary：管理端查看汇总数据，需要登录认证，在端点函数参数中单独声明 Depends
router = APIRouter()


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


class VitalsSummaryResponse(BaseModel):
    note: str = ""
    metrics: dict = {}


_MAX_ENTRIES = 500
_MAX_KEYS = 100
_vital_stats: dict[str, deque[float]] = {}


@router.post("/vitals", response_model=VitalsReceiveResponse)
async def receive_vitals(payload: VitalsPayload, request: Request):
    if len(payload.vitals) > 50:
        return {"ok": False, "error": "batch too large"}
    for v in payload.vitals:
        if v.rating in ("poor", "needs-improvement"):
            logger.warning(
                "WebVitals: name=%s value=%.1fms rating=%s nav=%s path=%s",
                v.name, v.value, v.rating, v.navigationType,
                request.headers.get("referer", ""),
            )
        key = f"{v.name}:{v.rating}"
        if key not in _vital_stats:
            if len(_vital_stats) >= _MAX_KEYS:
                continue
            _vital_stats[key] = deque(maxlen=_MAX_ENTRIES)
        _vital_stats[key].append(v.value)
    return {"ok": True}


@router.get("/vitals/summary", response_model=VitalsSummaryResponse)
async def vitals_summary(
    _current_user_id: int = Depends(get_current_user_id),
):
    """查看 Web Vitals 汇总数据（需登录）"""
    result = {}
    for key, values in _vital_stats.items():
        name, rating = key.split(":")
        vals = list(values)
        result.setdefault(name, {})[rating] = {
            "count": len(vals),
            "avg": round(sum(vals) / len(vals), 1) if vals else 0,
            "p95": round(sorted(vals)[min(int(len(vals) * 0.95) - 1, len(vals) - 1)], 1) if len(vals) > 1 else round(vals[0], 1) if vals else 0,
        }
    return {"note": "per-worker stats (multi-worker deployments aggregate separately)", "metrics": result}
