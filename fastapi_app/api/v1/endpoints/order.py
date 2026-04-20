"""
订单管理 API 端点

从 Flask order.py 迁移的 REST API。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import require_permission
from fastapi_app.shared_models import User
from fastapi_app.schemas.order import (
    OrderCreate, OrderUpdate, OrderActionResponse,
    OrderListResponse, ApprovalCancelResponse, ApprovalListResponse,
)
from fastapi_app.services import order_service
from fastapi_app.services.order_service import PermissionDeniedError

router = APIRouter()


@router.get("/list", response_model=OrderListResponse)
async def list_orders(
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(50, ge=1, le=5000, description="每页数量"),
    customer: Optional[str] = Query(None, description="客户名筛选"),
    product_id: Optional[int] = Query(None, description="产品ID筛选"),
    status: Optional[str] = Query(None, description="状态筛选"),
    order_type: Optional[str] = Query(None, description="订单类型筛选：regular/custom"),
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("order_manage")),
):
    """订单列表（支持分页和筛选）"""
    result = await order_service.get_orders(db, page=page, per_page=per_page,
                                            customer=customer, product_id=product_id,
                                            status=status, order_type=order_type)
    return OrderListResponse(data=result['items'], total=result['total'],
                             page=result['page'], per_page=result['per_page'])


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
        raise HTTPException(status_code=400, detail=str(e))


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
        from fastapi_app.shared_models import Order
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
        raise HTTPException(status_code=400, detail=str(e))


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
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/cancel-approval/{approval_id}", response_model=ApprovalCancelResponse)
async def cancel_approval(
    approval_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("order_manage")),
):
    """取消审批请求"""
    try:
        await order_service.cancel_approval(db, approval_id, user)
        return ApprovalCancelResponse(success=True, message="审批请求已取消")
    except PermissionDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/my-approvals", response_model=ApprovalListResponse)
async def my_approvals(
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("order_manage")),
):
    """查看我的审批请求"""
    approvals = await order_service.get_my_approvals(db, user)
    return ApprovalListResponse(data=approvals, total=len(approvals))
