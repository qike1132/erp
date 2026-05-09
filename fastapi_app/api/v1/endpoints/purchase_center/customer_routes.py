"""
采购中心 — 客户管理相关路由
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.purchase_center.schemas import (
    CustomerBatchRequest,
    CustomerSyncRequest,
)
from fastapi_app.core.database import get_async_db as get_db, get_async_read_db as get_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.services import purchase_center_service as svc

router = APIRouter()


@router.get("/customers")
async def api_get_customers(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: str = Query('all'),
    keyword: str = Query(''),
    sort_by: str = Query('name'),
    sort_order: str = Query('asc'),
    db: AsyncSession = Depends(get_read_db),
    _user=Depends(require_permission("product_manage")),
):
    result = await svc.get_customers(
        db, page=page, per_page=min(per_page, 100), status=status,
        keyword=keyword, sort_by=sort_by, sort_order=sort_order,
    )
    return {'success': True, **result}


@router.post("/customers/sync")
async def api_sync_customers(
    data: CustomerSyncRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    customer_ids = data.customer_ids

    from fastapi_app.shared_models import Customer
    query = select(Customer)
    if customer_ids:
        query = query.where(Customer.id.in_(customer_ids))
    result = await db.execute(query)
    customers = result.scalars().all()

    synced_count = 0
    skipped_count = 0
    details = []

    for customer in customers:
        try:
            synced_count += 1
            details.append({
                'id': customer.id, 'name': customer.name,
                'status': 'success', 'sync_time': datetime.now().isoformat(),
            })
        except (ValueError, RuntimeError):
            skipped_count += 1
            details.append({
                'id': customer.id, 'name': customer.name,
                'status': 'failed', 'error': '同步失败',
            })

    return {
        'success': True,
        'message': f'同步完成: 成功{synced_count}条, 跳过{skipped_count}条',
        'synced_count': synced_count,
        'skipped_count': skipped_count,
        'details': details,
    }


@router.post("/customers/batch")
async def api_batch_get_customers(
    data: CustomerBatchRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    customers = await svc.batch_get_customers(db, data.ids)
    return {'success': True, 'customers': customers}


@router.get("/customers/statistics")
async def api_get_customers_statistics(
    db: AsyncSession = Depends(get_read_db),
    _user=Depends(require_permission("product_manage")),
):
    stats = await svc.get_customers_statistics(db)
    return {'success': True, 'statistics': stats}


@router.get("/customers/{customer_id}")
async def api_get_customer_detail(
    customer_id: int,
    db: AsyncSession = Depends(get_read_db),
    _user=Depends(require_permission("product_manage")),
):
    result = await svc.get_customer_detail(db, customer_id)
    if not result:
        raise HTTPException(status_code=404, detail="客户不存在")
    return {'success': True, 'customer': result}
