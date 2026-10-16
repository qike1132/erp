"""成品库存（批次级）API 端点

只读：按 客户/产品/批次 聚合成品库存 + 某产品的批次可用量列表。
真相源与 /stock 同源（daily_production_record 包装部 + stock_out 批次扣减）。
"""
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

router = APIRouter()


@router.get('/summary', response_model=FinishedStockSummaryResponse)
async def finished_stock_summary(
    customer: str = Query('', description='客户名称筛选（精确）'),
    product: str = Query('', description='产品名称/69码搜索'),
    batch_no: str = Query('', description='批次号筛选（精确）'),
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(20, ge=1, le=200, description='每页数量'),
    db: AsyncSession = Depends(get_async_read_db),
    # 与 /stock/inventory 同权限用户（stock_view / stockin_manage），外加本页导航权限码
    # finished_stock_view（见 seed_nav.py）——否则管理员按导航勾选「成品库存」的用户
    # 能看到入口却拿 403（导航码↔接口码错配）。
    _user: User = Depends(require_any_permission('stockin_manage', 'stock_view', 'finished_stock_view')),
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
    # 唯一消费方是出库管理页（StockOutTab → finishedStockApi.batches），其权限码是
    # stockout_manage；只授该码的用户也须能取批次，否则出货页批次下拉静默 403。
    _user: User = Depends(require_any_permission('stockin_manage', 'stock_view', 'finished_stock_view', 'stockout_manage')),
) -> BatchListResponse:
    """某产品的批次可用量列表（供 /stock-out 录入 SKU 后带出批次选择）。"""
    rows = await finished_stock_service.get_batches_by_product(db, product_id, customer_name=customer)
    return BatchListResponse(data=rows)
