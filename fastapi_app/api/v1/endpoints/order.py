"""
订单管理 API 端点

从 Flask order.py 迁移的 REST API。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.schemas.order import (
    ApprovalCancelResponse,
    ApprovalListResponse,
    OrderActionResponse,
    OrderCreate,
    OrderDetailResponse,
    OrderListResponse,
    OrderUpdate,
)
from fastapi_app.services import order_batch_service, order_service
from fastapi_app.services.order_service import PermissionDeniedError
from fastapi_app.shared_models import Order, User

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/list", response_model=OrderListResponse)
async def list_orders(
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(50, ge=1, le=500, description="每页数量"),
    customer: str | None = Query(None, description="客户名筛选"),
    product_id: int | None = Query(None, description="产品ID筛选"),
    status: str | None = Query(None, description="状态筛选"),
    order_type: str | None = Query(None, description="订单类型筛选：regular/custom"),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("order_manage")),
):
    """订单列表（支持分页和筛选，缓存由 service 层 @cache_result 管理）"""
    result = await order_service.get_orders(db, page=page, per_page=per_page,
                                            customer=customer, product_id=product_id,
                                            status=status, order_type=order_type)

    return OrderListResponse(data=result['items'], total=result['total'],
                             page=result['page'], per_page=result['per_page'])


@router.get("/{order_id}", response_model=OrderDetailResponse)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("order_manage")),
):
    """获取单个订单详情"""
    result = await order_service.get_order_by_id(db, order_id)
    if not result:
        raise HTTPException(status_code=404, detail="订单不存在")
    return result


@router.post("/create", response_model=OrderActionResponse)
async def create_order(
    data: OrderCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("order_manage")),
):
    """创建订单"""
    try:
        await order_service.create_order(
            db, product_id=data.product_id, quantity=data.quantity,
            customer=data.customer, note=data.note or '', current_user=user,
            order_type=data.order_type, country=data.country
        )
        return OrderActionResponse(success=True, message="订单添加成功！")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.put("/edit/{order_id}", response_model=OrderActionResponse)
async def edit_order(
    order_id: int,
    data: OrderUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("order_manage")),
):
    """编辑订单（管理员直接编辑，非管理员提交审批）"""
    try:
        # 获取当前订单以填充未提供的字段
        order = await db.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="订单不存在")

        quantity = data.quantity if data.quantity is not None else order.quantity
        customer = data.customer if data.customer is not None else order.customer
        note = data.note if data.note is not None else (order.note or '')
        order_type = data.order_type if data.order_type is not None else order.order_type
        country = data.country if data.country is not None else order.country

        result = await order_service.update_order(
            db, order_id=order_id, quantity=quantity,
            customer=customer, note=note, current_user=user,
            order_type=order_type, country=country
        )
        return OrderActionResponse(success=result['success'], message=result['message'])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/delete/{order_id}", response_model=OrderActionResponse)
async def delete_order(
    order_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("order_manage")),
):
    """删除订单（管理员直接删除，非管理员提交审批）"""
    try:
        result = await order_service.delete_order(db, order_id, user)
        return OrderActionResponse(success=result['success'], message=result['message'])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except IntegrityError as e:
        await db.rollback()
        logger.warning("删除订单完整性约束冲突: %s", e)
        raise HTTPException(status_code=409, detail='订单存在关联数据，无法删除') from e
    except PermissionDeniedError as e:
        raise HTTPException(status_code=403, detail=settings.sanitize_business_error(e)) from e
    except (SQLAlchemyError, OSError) as e:
        await db.rollback()
        logger.error("删除订单失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail='删除订单失败，请稍后重试') from e


@router.post("/cancel-approval/{approval_id}", response_model=ApprovalCancelResponse)
async def cancel_approval(
    approval_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("order_manage")),
):
    """取消审批请求"""
    try:
        await order_service.cancel_approval(db, approval_id, user)
        await invalidate_related_caches(CacheDomain.ORDER_AND_INVENTORY)
        return ApprovalCancelResponse(success=True, message="审批请求已取消")
    except PermissionDeniedError as e:
        raise HTTPException(status_code=403, detail=settings.sanitize_business_error(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/my-approvals", response_model=ApprovalListResponse)
async def my_approvals(
    db: AsyncSession = Depends(get_async_read_db),
    user: User = Depends(require_permission("order_manage")),
):
    """查看我的审批请求"""
    approvals = await order_service.get_my_approvals(db, user)
    return ApprovalListResponse(data=approvals, total=len(approvals))


@router.put("/batch-no/{order_id}")
async def update_batch_no(
    order_id: int,
    batch_no: str = Query("", max_length=100, description="批次号"),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("order_manage")),
):
    """更新订单批次号"""
    try:
        await order_batch_service.update_batch_no(
            db, order_id=order_id, batch_no=batch_no,
            sync_same_batch=False, user=user,
        )
        await invalidate_related_caches(CacheDomain.ORDER)
        return {"success": True, "message": "批次号已更新"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
