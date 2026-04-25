"""
订单管理 API 端点

从 Flask order.py 迁移的 REST API。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import json
import hashlib
import logging

from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.cache import cache_result, invalidate_cache
from fastapi_app.shared_models import User
from fastapi_app.schemas.order import (
    OrderCreate, OrderUpdate, OrderActionResponse,
    OrderListResponse, OrderDetailResponse, ApprovalCancelResponse, ApprovalListResponse,
)
from fastapi_app.services import order_service
from fastapi_app.services.order_service import PermissionDeniedError

logger = logging.getLogger(__name__)
router = APIRouter()

async def _get_order_list_cache_key(page, per_page, customer, product_id, status, order_type) -> str:
    """生成订单列表缓存键"""
    params = {'page': page, 'per_page': per_page, 'customer': customer,
              'product_id': product_id, 'status': status, 'order_type': order_type}
    hash_val = hashlib.md5(json.dumps(params, sort_keys=True, default=str).encode(), usedforsecurity=False).hexdigest()[:12]
    return f"orders:list:{hash_val}"


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
    """订单列表（支持分页和筛选，带缓存）"""
    import json
    try:
        from utils.redis_cache import redis_cache
    except Exception:
        redis_cache = None
    
    cache_key = f"orders:list:{page}:{per_page}:{hash(str(customer) + str(product_id) + str(status) + str(order_type))}"
    try:
        if redis_cache:
            cached_data = await redis_cache.get(cache_key)
            if cached_data:
                cached = json.loads(cached_data)
                return OrderListResponse(data=cached['items'], total=cached['total'],
                                         page=cached['page'], per_page=cached['per_page'])
    except Exception:
        pass

    result = await order_service.get_orders(db, page=page, per_page=per_page,
                                            customer=customer, product_id=product_id,
                                            status=status, order_type=order_type)

    try:
        if redis_cache:
            await redis_cache.set(cache_key, json.dumps(result, ensure_ascii=False, default=str), ex=60)
    except Exception:
        pass

    return OrderListResponse(data=result['items'], total=result['total'],
                             page=result['page'], per_page=result['per_page'])


@router.get("/{order_id}", response_model=OrderDetailResponse)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_async_db),
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


@router.put("/batch-no/{order_id}")
async def update_batch_no(
    order_id: int,
    body: dict,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("order_manage")),
):
    """更新订单批次号"""
    from fastapi_app.shared_models import Order as OrderModel
    from sqlalchemy import select
    result = await db.execute(select(OrderModel).where(OrderModel.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    order.batch_no = body.get("batch_no", "")
    await db.commit()
    return {"success": True, "message": "批次号已更新"}
