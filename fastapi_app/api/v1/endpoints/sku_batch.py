"""SKU批次管理接口"""
from fastapi import APIRouter, Depends, Query
from fastapi_app.core.deps import require_permission
from fastapi_app.core.database import get_async_db
from fastapi_app.shared_models import User
from fastapi_app.schemas.sku_batch import SkuBatchListResponse
from fastapi_app.services import sku_batch_service as sb_service
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get("/stats")
async def get_stats(
    user: User = Depends(require_permission("sku_batch_view")),
    db: AsyncSession = Depends(get_async_db),
):
    """获取批次统计数据"""
    return await sb_service.get_sku_batch_stats(db)


@router.get("/batches", response_model=SkuBatchListResponse)
async def list_sku_batches(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    batch_no: str = Query('', description='批次号'),
    sku_code: str = Query('', description='SKU编号'),
    status: str = Query('', description='批次状态'),
    start_date: str = Query('', description='创建开始日期'),
    end_date: str = Query('', description='创建结束日期'),
    sort_by: str = Query('create_time', description='排序字段'),
    sort_order: str = Query('desc', description='排序方向: asc/desc'),
    user: User = Depends(require_permission("sku_batch_view")),
    db: AsyncSession = Depends(get_async_db),
):
    """查询SKU批次列表"""
    return await sb_service.get_sku_batches(
        db, page, per_page, batch_no, sku_code, status,
        start_date, end_date, sort_by, sort_order
    )
