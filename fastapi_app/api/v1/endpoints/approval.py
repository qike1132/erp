"""审批管理接口"""
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import require_permission
from fastapi_app.schemas.approval import (
    ApprovalActionRequest,
    ApprovalActionResponse,
    ApprovalDetailResponse,
    ApprovalListResponse,
    ApprovalPendingCountResponse,
)
from fastapi_app.services import approval_service
from fastapi_app.shared_models import User

router = APIRouter()
logger = logging.getLogger(__name__)


def _require_admin(permission: str = "order_manage"):
    async def checker(user: User = Depends(require_permission(permission))) -> User:
        if not user.is_super:
            raise HTTPException(status_code=403, detail="仅管理员可执行审批操作")
        return user
    return checker


@router.get("/list", response_model=ApprovalListResponse)
async def approval_list(
    status: str = Query('pending', description="状态筛选: pending/approved/rejected/all"),
    search: str = Query('', description="搜索关键词"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(_require_admin()),
    db: AsyncSession = Depends(get_async_db),
):
    result = await approval_service.get_approval_list(db, status, search, page, per_page)
    return ApprovalListResponse(
        data=result['approvals'],
        pending_count=result['pending_count'],
        approved_count=result['approved_count'],
        rejected_count=result['rejected_count'],
    )


@router.get("/detail/{approval_id}", response_model=ApprovalDetailResponse)
async def approval_detail(
    approval_id: int,
    user: User = Depends(_require_admin()),
    db: AsyncSession = Depends(get_async_db),
):
    try:
        data = await approval_service.get_approval_detail(db, approval_id)
        return ApprovalDetailResponse(data=data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/approve/{approval_id}", response_model=ApprovalActionResponse)
async def approve(
    approval_id: int,
    user: User = Depends(_require_admin()),
    db: AsyncSession = Depends(get_async_db),
):
    try:
        result = await approval_service.approve_request(db, approval_id, user)
        await db.commit()
        await invalidate_related_caches(CacheDomain.ORDER_AND_INVENTORY)
        # 清除采购中心缓存（审批可能同步删除/更新了采购订单）
        try:
            from fastapi_app.core.purchase_cache import invalidate_purchase_caches
            await invalidate_purchase_caches()
        except (RuntimeError, OSError, ValueError):
            logger.warning("采购中心缓存失效失败(approval)", exc_info=True)
        # 在 commit 后发布事件，避免 commit 失败时前端收到错误通知
        try:
            from fastapi_app.services.notification_service import StockEvent, publish_stock_event
            if result.get('operation_type') == 'delete':
                await publish_stock_event(StockEvent.ORDER_DELETED, {
                    'order_id': result.get('order_id'),
                    'order_no': result.get('order_no', ''),
                })
            elif result.get('operation_type') == 'edit':
                await publish_stock_event(StockEvent.ORDER_UPDATED, {
                    'order_id': result.get('order_id'),
                    'order_no': result.get('order_no', ''),
                })
        except (RuntimeError, OSError, ValueError):
            logger.warning("审批事件发布失败", exc_info=True)
        return ApprovalActionResponse(message=result['message'])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/reject/{approval_id}", response_model=ApprovalActionResponse)
async def reject(
    approval_id: int,
    data: ApprovalActionRequest = Body(default=ApprovalActionRequest()),
    user: User = Depends(_require_admin()),
    db: AsyncSession = Depends(get_async_db),
):
    try:
        message = await approval_service.reject_request(db, approval_id, user, data.reason)
        await db.commit()
        # 保守策略：reject 虽不直接修改库存，但订单列表页可能包含库存关联字段，
        # 统一失效 ORDER+INVENTORY 与 approve 保持一致
        await invalidate_related_caches(CacheDomain.ORDER_AND_INVENTORY)
        return ApprovalActionResponse(message=message)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/pending-count", response_model=ApprovalPendingCountResponse)
async def pending_count(
    user: User = Depends(_require_admin()),
    db: AsyncSession = Depends(get_async_db),
):
    from fastapi_app.core.cache import cache_result
    from fastapi_app.services.approval_service import get_pending_count as _get_pending_count

    @cache_result(key_prefix="approval:pending_count", ttl=30, local_ttl=10)
    async def _cached_count():
        return await _get_pending_count(db)

    count = await _cached_count()
    return ApprovalPendingCountResponse(count=count)
