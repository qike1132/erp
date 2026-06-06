"""订单批次号管理路由"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.deps import require_permission
from fastapi_app.schemas.order_batch import (
    BatchAssignRequest,
    BatchAssignResponse,
    BatchCompleteRequest,
    BatchCompleteResponse,
    BatchNoUpdate,
    BatchNoUpdateResponse,
    BatchQueryItem,
    BatchQueryListResponse,
    OrderBatchListResponse,
    WhitelistResponse,
)
from fastapi_app.services import order_batch_service
from fastapi_app.shared_models import User

router = APIRouter()


@router.get("/batch-query", response_model=BatchQueryListResponse)
async def batch_query_list(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    batch_no: str | None = Query(None),
    status: str | None = Query(None),
    customer: str | None = Query(None),
    keyword: str | None = Query(None),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("batch_manage")),
):
    result = await order_batch_service.get_batch_query_list(
        db, page=page, per_page=per_page, batch_no=batch_no, status=status, customer=customer, keyword=keyword,
    )
    return BatchQueryListResponse(data=result['items'], total=result['total'], page=page, per_page=per_page)


@router.get("/orders", response_model=OrderBatchListResponse)
async def list_batch_orders(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    batch_no: str | None = Query(None),
    status: str | None = Query(None),
    customer: str | None = Query(None),
    keyword: str | None = Query(None),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("order_manage")),
):
    result = await order_batch_service.get_batch_orders(
        db, page=page, per_page=per_page, batch_no=batch_no, status=status, customer=customer, keyword=keyword,
    )
    return OrderBatchListResponse(data=result['items'], total=result['total'], page=page, per_page=per_page)


@router.put("/orders/{order_id}/batch-no", response_model=BatchNoUpdateResponse)
async def update_order_batch_no(
    order_id: int,
    data: BatchNoUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("order_manage")),
):
    async with db_transaction(db):
        result = await order_batch_service.update_batch_no(
            db, order_id=order_id, batch_no=data.batch_no, sync_same_batch=data.sync_same_batch, user=user,
        )
    return BatchNoUpdateResponse(success=True, message="批次号更新成功", updated_count=result['updated_count'])


@router.post("/orders/batch-assign", response_model=BatchAssignResponse)
async def batch_assign_orders(
    data: BatchAssignRequest,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("order_manage")),
):
    async with db_transaction(db):
        result = await order_batch_service.batch_assign(
            db, order_ids=data.order_ids, batch_no=data.batch_no, user=user,
        )
    return BatchAssignResponse(success=True, message="批次号设置成功", updated_count=result['updated_count'])


@router.post("/batch/complete", response_model=BatchCompleteResponse)
async def complete_batch(
    data: BatchCompleteRequest,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("order_manage")),
):
    async with db_transaction(db):
        result = await order_batch_service.complete_batch(db, batch_no=data.batch_no, user=user)
    return BatchCompleteResponse(
        success=True,
        message=f"批次完成，{result['completed_count']}个订单已归档",
        completed_count=result['completed_count'],
        failed_orders=result['failed_orders'],
    )


@router.get("/history", response_model=OrderBatchListResponse)
async def list_batch_history(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    batch_no: str | None = Query(None),
    customer: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("order_manage")),
):
    result = await order_batch_service.get_batch_history(
        db, page=page, per_page=per_page, batch_no=batch_no, customer=customer, date_from=date_from, date_to=date_to,
    )
    return OrderBatchListResponse(data=result['items'], total=result['total'], page=page, per_page=per_page)


@router.get("/whitelist", response_model=WhitelistResponse)
async def get_whitelist(
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission("order_manage")),
):
    customers = await order_batch_service.get_whitelist(db)
    return WhitelistResponse(customers=customers)


@router.put("/whitelist", response_model=WhitelistResponse)
async def update_whitelist(
    data: WhitelistResponse,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission("order_manage")),
):
    await order_batch_service.set_whitelist(db, data.customers, user.id)
    return WhitelistResponse(customers=data.customers)
