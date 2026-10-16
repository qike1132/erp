"""成品库存（批次级）API 端点

只读：按 客户/产品/批次 聚合成品库存 + 某产品的批次可用量列表。
真相源与 /stock 同源（daily_production_record 包装部 + stock_out 批次扣减）。
"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_read_db
from fastapi_app.core.deps import require_any_permission
from fastapi_app.schemas.finished_stock import (
    BatchListResponse,
    FinishedStockSummaryResponse,
)
from fastapi_app.services import finished_stock_service
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get('/summary', response_model=FinishedStockSummaryResponse)
async def finished_stock_summary(
    customer: str = Query('', description='客户名称筛选（精确）'),
    product: str = Query('', description='产品名称/69码搜索'),
    batch_no: str = Query('', description='批次号筛选（精确）'),
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(20, ge=1, le=200, description='每页数量'),
    db: AsyncSession = Depends(get_async_read_db),
    # 与 /stock/inventory 同权限：成品库存同服务 stock_view 与 stockin_manage 两类用户。
    _user: User = Depends(require_any_permission('stockin_manage', 'stock_view')),
) -> FinishedStockSummaryResponse:
    """按 客户/产品/批次 聚合成品库存（只读副本）。"""
    result = await finished_stock_service.get_finished_stock_summary(
        db,
        customer_name=customer,
        product_search=product,
        batch_no=batch_no,
        page=page,
        per_page=per_page,
    )
    return FinishedStockSummaryResponse(**result)


@router.get('/batches', response_model=BatchListResponse)
async def product_batches(
    product_id: int = Query(..., gt=0, description='产品ID'),
    customer: str = Query('', description='客户名称（可选，精确）'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_any_permission('stockin_manage', 'stock_view')),
) -> BatchListResponse:
    """某产品的批次可用量列表（供 /stock-out 录入 SKU 后带出批次选择）。"""
    rows = await finished_stock_service.get_batches_by_product(db, product_id, customer_name=customer)
    return BatchListResponse(data=rows)
