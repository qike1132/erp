"""
仪表盘 API

为 Vue/Vite 前端提供仪表盘统计数据和最近活动数据。
从 pages.py:index_page 的服务端渲染逻辑提取而来。

权限分级（AUD-04，2026-10-24 审计）：
- stats / activities / todos / nav-sections / system-status / mobile：
  登录即可读——它们是「全员首页」的运营聚合数字（今日备货/出货/待办数等），
  前端首屏依赖，收紧会让无业务权限码的账号首屏 403。若 owner 决定进一步
  收紧，在对应端点补 require_any_permission 即可。
- customer-out-details / customer-order-details：逐客户营收金额明细（敏感），
  前端零调用（服务端渲染时代遗留），已收紧为 report_view + 工厂隔离，
  与 /reports/* 同口径。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_read_db
from fastapi_app.core.deps import (
    get_current_user_id,
    get_current_user_with_permissions,
    require_permission,
)
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

logger = logging.getLogger(__name__)

router = APIRouter()


def _dashboard_factory_scope(user: User) -> str:
    """工厂隔离口径：非超管且绑定工厂时只看本厂（product.factory）。

    与 report.py 的 _factory_scope 同口径逐字一致（AUD-04，2026-10-24 审计：
    客户金额明细从「登录即可读两厂」收敛到报表权限 + 工厂隔离）。放在本文件
    而非 import report 的私有函数——端点间不互引私有实现。
    """
    return user.factory if (user.factory and not user.is_super) else ''


@router.get("/stats", response_model=DashboardResponse)
async def get_dashboard_stats(
    user: User = Depends(get_current_user_with_permissions),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """仪表盘统计数据（30s L1+L2 缓存，按工厂隔离，兼顾实时性与并发性能）"""
    # 短 TTL 缓存（30s）：用户要求"今日备货/今日出货/待审批/待备料"等模块近实时显示。
    # 30s 窗口足够小，用户无感知；同时避免高并发下 10+ 聚合查询打满 DB。
    # 工厂隔离（A-M22）：厂绑定用户只能看到本厂口径，缓存键随工厂分桶。
    try:
        dashboard_stats = await fetch_dashboard_stats(db, _dashboard_factory_scope(user))
    except (OperationalError, DisconnectionError):
        # 数据库不可用时不得吞成空统计返回 200（会掩盖故障、前端展示全 0 无告警），
        # 应显式 503 触发监控告警与前端降级提示。
        logger.warning("仪表盘统计查询失败", exc_info=True)
        raise HTTPException(status_code=503, detail="数据库暂不可用，请稍后重试") from None

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
    user: User = Depends(get_current_user_with_permissions),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """仪表盘待办事项（按工厂隔离：厂绑定用户只看到本厂订单待办）"""
    return await fetch_dashboard_todos(db, _dashboard_factory_scope(user))


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
    current_user: User = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_async_read_db),
):
    """移动端数据看板（一次聚合所有板块数据）"""
    # 生产卡片按当前用户的部门范围收窄。用非抛错的 production_scope_of：
    # 无生产权限的用户得到空集（生产卡片为空），而不是 403 拖垮整个看板。
    scope = production_scope_of(current_user, write=False)
    data = await fetch_mobile_dashboard(query_date, db, departments=scope)
    return MobileDashboardResponse(**data)


@router.get("/customer-out-details", response_model=CustomerOutDetailResponse)
async def get_customer_out_details(
    period: str = "today",
    query_date: str | None = None,
    user: User = Depends(require_permission('report_view')),
    db: AsyncSession = Depends(get_async_read_db),
):
    """获取客户出库详情（逐客户营收金额，AUD-04 收口：report_view + 工厂隔离）。"""
    return await fetch_customer_out_details(
        period, query_date, db, factory=_dashboard_factory_scope(user))


@router.get("/customer-order-details", response_model=CustomerOutDetailResponse)
async def get_customer_order_details(
    period: str = "today",
    date_param: str | None = None,
    user: User = Depends(require_permission('report_view')),
    db: AsyncSession = Depends(get_async_read_db),
):
    """获取客户订单详情（逐客户营收金额，AUD-04 收口：report_view + 工厂隔离）。"""
    return await fetch_customer_order_details(
        period, date_param, db, factory=_dashboard_factory_scope(user))

