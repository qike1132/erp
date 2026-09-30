"""API v2 仪表盘端点

P2-15: 仪表盘统计与最近活动已迁移到 /api/v2，
复用服务层逻辑以保证与 v1 行为一致，并通过响应头暴露版本与弃用政策。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from fastapi_app.core.database import get_async_read_db
from fastapi_app.core.deps import get_current_user_id, get_current_user_with_permissions
from fastapi_app.core.production_scope import production_scope_of
from fastapi_app.services.dashboard_service import (
    Activity,
    CustomerOutDetailResponse,
    DashboardResponse,
    DashboardStats,
    MobileDashboardResponse,
    NavSection,
    SystemStatusResponse,
    TodoListResponse,
    fetch_customer_order_details,
    fetch_customer_out_details,
    fetch_dashboard_activities,
    fetch_dashboard_stats,
    fetch_dashboard_todos,
    fetch_mobile_dashboard,
    fetch_nav_sections,
    fetch_system_status,
)
from fastapi_app.shared_models import User

from ..versioning import _version_headers

router = APIRouter()


def _set_version_headers(response: Response) -> None:
    for header_name, header_value in _version_headers().items():
        response.headers[header_name] = header_value


@router.get("/stats", response_model=DashboardResponse)
async def get_dashboard_stats_v2(
    response: Response,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """v2 仪表盘统计数据"""
    try:
        dashboard_stats = await fetch_dashboard_stats(db)
    except (OperationalError, DisconnectionError):
        # 数据库不可用不得吞成空统计返回 200（掩盖故障），显式 503 触发告警。
        raise HTTPException(status_code=503, detail="数据库暂不可用，请稍后重试") from None
    _set_version_headers(response)
    return DashboardResponse(success=True, data=DashboardStats(**dashboard_stats))


@router.get("/activities", response_model=list[Activity])
async def get_dashboard_activities_v2(
    response: Response,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """v2 仪表盘最近活动数据"""
    activities = await fetch_dashboard_activities(db)
    _set_version_headers(response)
    return activities


@router.get("/todos", response_model=TodoListResponse)
async def get_dashboard_todos_v2(
    response: Response,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """v2 仪表盘待办事项"""
    todos = await fetch_dashboard_todos(db)
    _set_version_headers(response)
    return todos


@router.get("/system-status", response_model=SystemStatusResponse)
async def get_system_status_v2(
    response: Response,
    user_id: int = Depends(get_current_user_id),
):
    """v2 系统运行状态"""
    status = fetch_system_status()
    _set_version_headers(response)
    return status


@router.get("/mobile", response_model=MobileDashboardResponse)
async def get_mobile_dashboard_v2(
    response: Response,
    query_date: str | None = None,
    user_id: int = Depends(get_current_user_id),
    current_user: User = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_async_read_db),
):
    """v2 移动端数据看板"""
    # 同 v1：生产卡片按当前用户的部门范围收窄，非抛错的 production_scope_of 保证
    # 无生产权限时返回空卡片而非 403。
    scope = production_scope_of(current_user, write=False)
    data = await fetch_mobile_dashboard(query_date, db, departments=scope)
    _set_version_headers(response)
    return MobileDashboardResponse(**data)


@router.get("/nav-sections", response_model=dict[str, NavSection])
async def get_nav_sections_v2(
    response: Response,
    user_id: int = Depends(get_current_user_id),
):
    """v2 导航菜单数据"""
    sections = await fetch_nav_sections()
    _set_version_headers(response)
    return sections


@router.get("/customer-out-details", response_model=CustomerOutDetailResponse)
async def get_customer_out_details_v2(
    response: Response,
    period: str = "today",
    query_date: str | None = None,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """v2 客户出库详情"""
    details = await fetch_customer_out_details(period, query_date, db)
    _set_version_headers(response)
    return details


@router.get("/customer-order-details", response_model=CustomerOutDetailResponse)
async def get_customer_order_details_v2(
    response: Response,
    period: str = "today",
    date_param: str | None = None,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """v2 客户订单详情"""
    details = await fetch_customer_order_details(period, date_param, db)
    _set_version_headers(response)
    return details
