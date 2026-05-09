"""
Web Vitals 监控端点 - 接收前端性能指标数据
"""
import logging
from collections import deque

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from fastapi_app.core.deps import require_permission
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
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


_MAX_ENTRIES = 500
_vital_stats: dict[str, deque[float]] = {}


@router.post("/vitals")
async def receive_vitals(payload: VitalsPayload, request: Request, _user: User = Depends(require_permission('product_manage'))):
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
            _vital_stats[key] = deque(maxlen=_MAX_ENTRIES)
        _vital_stats[key].append(v.value)
    return {"ok": True}


@router.get("/vitals/summary")
async def vitals_summary(_user: User = Depends(require_permission('product_manage'))):
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
