"""
仪表盘 API

为 Vue/Vite 前端提供仪表盘统计数据和最近活动数据。
从 pages.py:index_page 的服务端渲染逻辑提取而来。
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_read_db
from fastapi_app.core.deps import get_current_user_id
from fastapi_app.services.dashboard_service import (
    Activity,
    CustomerOutDetailResponse,
    DashboardResponse,
    DashboardStats,
    MobileDashboardResponse,
    NavItem,
    NavSection,
    SystemStatusResponse,
    TodoItem,
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

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/stats", response_model=DashboardResponse)
async def get_dashboard_stats(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """仪表盘统计数据（10秒 L1+L2 缓存，兼顾实时性与并发性能）"""
    # 短 TTL 缓存（10s）：用户要求"今日备货/今日出货/待审批/待备料"等模块近实时显示。
    # 10s 窗口足够小，用户无感知；同时避免高并发下 10+ 聚合查询打满 DB。
    try:
        dashboard_stats = await fetch_dashboard_stats(db)
    except (OperationalError, DisconnectionError):
        logger.warning("仪表盘统计查询失败", exc_info=True)
        dashboard_stats = {}

    return DashboardResponse(
        success=True,
        data=DashboardStats(**dashboard_stats)
    )


@router.get("/activities", response_model=list[Activity])
async def get_dashboard_activities(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """仪表盘最近活动数据（Redis缓存60秒）"""
    return await fetch_dashboard_activities(db)


@router.get("/nav-sections", response_model=dict[str, NavSection])
async def get_nav_sections(user_id: int = Depends(get_current_user_id)):
    """导航菜单数据（供前端使用）"""
    return await fetch_nav_sections()


@router.get("/todos", response_model=TodoListResponse)
async def get_dashboard_todos(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """仪表盘待办事项"""
    return await fetch_dashboard_todos(db)


@router.get("/system-status", response_model=SystemStatusResponse)
async def get_system_status(
    user_id: int = Depends(get_current_user_id),
):
    """系统运行状态"""
    return fetch_system_status()


@router.get("/mobile", response_model=MobileDashboardResponse)
async def get_mobile_dashboard(
    query_date: str | None = None,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """移动端数据看板（一次聚合所有板块数据）"""
    data = await fetch_mobile_dashboard(query_date, db)
    return MobileDashboardResponse(**data)


@router.get("/customer-out-details", response_model=CustomerOutDetailResponse)
async def get_customer_out_details(
    period: str = "today",
    query_date: str | None = None,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """获取客户出库详情"""
    return await fetch_customer_out_details(period, query_date, db)


@router.get("/customer-order-details", response_model=CustomerOutDetailResponse)
async def get_customer_order_details(
    period: str = "today",
    date_param: str | None = None,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """获取客户订单详情"""
    return await fetch_customer_order_details(period, date_param, db)

