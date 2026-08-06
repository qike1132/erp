"""
API v2 路由

P2-15：/api/v2 版本策略示例。所有 v2 端点通过该 router 注册，
并在响应头中暴露 Sunset / Deprecation 信息以支持弃用政策。
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fastapi_app.api.v2.endpoints.dashboard import router as dashboard_router
from fastapi_app.api.v2.versioning import _version_headers

router = APIRouter(prefix="/v2")

router.include_router(
    dashboard_router,
    prefix="/dashboard",
    tags=["v2-仪表盘"],
)


@router.get("/health", tags=["v2"])
async def health_v2(request: Request):
    """v2 健康检查示例端点"""
    return JSONResponse(
        content={"status": "ok", "version": "2.0.0"},
        headers=_version_headers(),
    )
