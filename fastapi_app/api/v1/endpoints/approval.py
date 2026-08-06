"""审批管理接口

提供审批列表查询、审批详情、同意/拒绝审批、待处理计数等端点。
所有端点均要求 order_manage 权限。
"""
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache import CacheDomain
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_superuser
from fastapi_app.core.domain_events import DomainEvent, DomainEventType
from fastapi_app.core.domain_events import publish as publish_domain_event
from fastapi_app.core.exceptions import db_transaction
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

# 待处理计数缓存 TTL（秒）
_PENDING_COUNT_TTL = 30
_PENDING_COUNT_LOCAL_TTL = 10


@router.get("/list", response_model=ApprovalListResponse)
async def approval_list(
    status: str = Query('pending', description="状态筛选: pending/approved/rejected/all"),
    search: str = Query('', description="搜索关键词"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _current_user: User = Depends(require_superuser('order_manage')),
    db: AsyncSession = Depends(get_async_read_db),
) -> ApprovalListResponse:
    """获取审批列表（分页）。

    支持按状态筛选和关键词搜索，返回各状态计数。

    Args:
        status: 状态筛选，可选 pending/approved/rejected/all。
        search: 搜索关键词（订单号、用户名、操作类型）。
        page: 页码，从 1 开始。
        per_page: 每页条数，1-100。
        _current_user: 当前操作者（用于权限校验）。
        db: 只读数据库会话。

    Returns:
        ApprovalListResponse: 审批列表及各状态计数。
    """
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
    _current_user: User = Depends(require_superuser('order_manage')),
    db: AsyncSession = Depends(get_async_read_db),
) -> ApprovalDetailResponse:
    """获取审批详情（含操作日志和关联订单信息）。

    Args:
        approval_id: 审批请求 ID。
        _current_user: 当前操作者（用于权限校验）。
        db: 只读数据库会话。

    Returns:
        ApprovalDetailResponse: 审批详情数据。

    Raises:
        HTTPException 404: 审批请求不存在时抛出。
    """
    try:
        data = await approval_service.get_approval_detail(db, approval_id)
        return ApprovalDetailResponse(data=data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/approve/{approval_id}", response_model=ApprovalActionResponse)
async def approve(
    approval_id: int,
    user: User = Depends(require_superuser('order_manage')),
    db: AsyncSession = Depends(get_async_db),
) -> ApprovalActionResponse:
    """同意审批请求。

    根据审批类型执行订单编辑或删除操作，事务提交后发布缓存失效、
    库存事件及领域事件。事件发布失败不影响审批结果。

    Args:
        approval_id: 审批请求 ID。
        user: 当前操作者（审批人）。
        db: 读写数据库会话。

    Returns:
        ApprovalActionResponse: 操作结果消息。
    """
    async with db_transaction(db):
        result = await approval_service.approve_request(db, approval_id, user)
    # 事务提交后失效缓存，确保后续查询看到最新数据
    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER_AND_INVENTORY)
    await cache_mgr.invalidate(InvalidationStrategy.PURCHASE)
    # 发布库存变更事件（失败不影响审批结果）
    await _publish_stock_event(result)
    # 领域事件：ORDER_DELETED 在事务提交后发布（订阅者使用独立 session，需可见已提交变更）
    if result.get('operation_type') == 'delete' and result.get('order_id'):
        try:
            await publish_domain_event(DomainEvent(
                event_type=DomainEventType.ORDER_DELETED,
                domain='order',
                payload={'order_id': result['order_id']},
            ))
        except (RuntimeError, OSError, ValueError):  # defensive: 领域事件发布失败不影响审批操作结果
            logger.warning("ORDER_DELETED 领域事件发布失败", exc_info=True)
    return ApprovalActionResponse(message=result['message'])


async def _publish_stock_event(result: dict) -> None:
    """根据审批操作类型发布对应的库存事件，失败仅记录日志。

    Args:
        result: approve_request 返回的操作结果 dict。
    """
    try:
        from fastapi_app.services.notification_service import StockEvent, publish_stock_event
        event_payload = {
            'order_id': result.get('order_id'),
            'order_no': result.get('order_no', ''),
        }
        operation_type = result.get('operation_type')
        if operation_type == 'delete':
            await publish_stock_event(StockEvent.ORDER_DELETED, event_payload)
        elif operation_type == 'edit':
            await publish_stock_event(StockEvent.ORDER_UPDATED, event_payload)
    except (RuntimeError, OSError, ValueError):
        logger.warning("审批事件发布失败", exc_info=True)


@router.post("/reject/{approval_id}", response_model=ApprovalActionResponse)
async def reject(
    approval_id: int,
    data: ApprovalActionRequest = Body(default=ApprovalActionRequest()),
    user: User = Depends(require_superuser('order_manage')),
    db: AsyncSession = Depends(get_async_db),
) -> ApprovalActionResponse:
    """拒绝审批请求。

    解除订单锁定，记录拒绝原因。

    Args:
        approval_id: 审批请求 ID。
        data: 拒绝请求参数（含拒绝原因）。
        user: 当前操作者（审批人）。
        db: 读写数据库会话。

    Returns:
        ApprovalActionResponse: 操作结果消息。
    """
    async with db_transaction(db):
        message = await approval_service.reject_request(db, approval_id, user, data.reason)
    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER_AND_INVENTORY)
    return ApprovalActionResponse(message=message)


@router.get("/pending-count", response_model=ApprovalPendingCountResponse)
async def pending_count(
    _current_user: User = Depends(require_superuser('order_manage')),
    db: AsyncSession = Depends(get_async_read_db),
) -> ApprovalPendingCountResponse:
    """获取待处理审批数量（带缓存）。

    使用本地+远程双层缓存减轻数据库压力。

    Args:
        _current_user: 当前操作者（用于权限校验）。
        db: 只读数据库会话。

    Returns:
        ApprovalPendingCountResponse: 待处理审批数量。
    """
    from fastapi_app.core.cache import cache_result
    from fastapi_app.services.approval_service import get_pending_count as _get_pending_count

    @cache_result(key_prefix="approval:pending_count", ttl=_PENDING_COUNT_TTL, local_ttl=_PENDING_COUNT_LOCAL_TTL)
    async def _cached_count() -> int:
        return await _get_pending_count(db)

    count = await _cached_count()
    return ApprovalPendingCountResponse(count=count)
