"""皮套管理接口"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.schemas.case import (
    CaseStockInCreate, CaseStockInUpdate, CaseStockOutCreate, CaseStockOutUpdate,
    CaseProductCreate, BatchCaseStockInRequest, BatchCaseStockOutRequest,
    CaseSearchItem, CaseStockInItem, CaseStockInListResponse, CaseStockInDetailResponse,
    CaseStockInCreateResponse, CaseActionResponse, CaseBatchFailedItem,
    CaseBatchStockInResponse, CaseStockOutItem, CaseStockOutListResponse,
    CaseStockOutDetailResponse, CaseStockOutCreateResponse, CaseBatchStockOutResultItem,
    CaseBatchStockOutResponse, CaseInventoryItem, CaseInventoryStats,
    CaseInventorySummaryResponse, CaseInventoryLogItem, CasePaginationInfo,
    CaseInventoryLogsResponse, CaseProductItem, CaseProductsResponse,
    CaseProductCreateResponse,
)
from fastapi_app.services import case_service, escape_like
from fastapi_app.services.notification_service import StockEvent, publish_stock_event
from fastapi_app.shared_models import Product, User

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get('/search', response_model=list[CaseSearchItem])
async def case_search(q: str=Query('', description='搜索关键词'), user: User=Depends(require_permission('case_manage')), db: AsyncSession=Depends(get_async_read_db)):
    """皮套搜索"""
    return await case_service.search_cases(db, q)

@router.get('/in/list', response_model=CaseStockInListResponse)
async def case_stockins(page: int=Query(1, ge=1), per_page: int=Query(20, ge=1, le=100), customer: str=Query(''), start_date: str=Query(''), end_date: str=Query(''), quantity_min: int | None=Query(None), quantity_max: int | None=Query(None), user: User=Depends(require_permission('case_manage')), db: AsyncSession=Depends(get_async_read_db)):
    """皮套入库列表"""
    return await case_service.get_case_stockins(db, page, per_page, customer, start_date, end_date, quantity_min, quantity_max)

@router.get('/in/{stockin_id}', response_model=CaseStockInDetailResponse)
async def get_case_stockin(stockin_id: int, user: User=Depends(require_permission('case_manage')), db: AsyncSession=Depends(get_async_read_db)):
    """获取单个皮套入库记录"""
    from fastapi_app.shared_models import CaseStockIn
    result = await db.execute(select(CaseStockIn).options(joinedload(CaseStockIn.case)).where(CaseStockIn.id == stockin_id))
    stockin = result.unique().scalar_one_or_none()
    if not stockin:
        raise HTTPException(status_code=404, detail='入库记录不存在')
    return {'id': stockin.id, 'stockin_no': stockin.stockin_no, 'stockin_date': stockin.stockin_date.strftime('%Y-%m-%d') if stockin.stockin_date else '', 'customer': stockin.customer, 'case_id': stockin.case_id, 'case_name': stockin.case.sync_name if stockin.case else '', 'quantity': stockin.quantity, 'note': stockin.note or ''}

@router.post('/in/create', response_model=CaseStockInCreateResponse)
async def create_case_stockin(data: CaseStockInCreate, user: User=Depends(require_permission('case_manage')), db: AsyncSession=Depends(get_async_db)):
    """皮套入库（单条）"""
    async with db_transaction(db):
        result = await case_service.create_case_stockin(db, data.product_id, data.quantity, data.stockin_date, data.customer, data.note)
    try:
        await publish_stock_event(StockEvent.CASE_STOCK_CHANGED, {'change_type': '皮套入库', 'quantity': data.quantity, 'product_id': data.product_id})
    except (OSError, ValueError) as e:
        logger.warning('皮套入库事件发布失败（不影响数据）: %s', e)
    return result

@router.put('/in/{stockin_id}', response_model=CaseActionResponse)
async def update_case_stockin(stockin_id: int, data: CaseStockInUpdate, user: User=Depends(require_permission('case_manage')), db: AsyncSession=Depends(get_async_db)):
    """更新皮套入库记录"""
    async with db_transaction(db):
        result = await case_service.update_case_stockin(db, stockin_id, data.model_dump(exclude_none=True))
    try:
        await publish_stock_event(StockEvent.CASE_STOCK_CHANGED, {'change_type': '皮套入库编辑', 'stockin_id': stockin_id})
    except (OSError, ValueError) as e:
        logger.warning('皮套入库编辑事件发布失败（不影响数据）: %s', e)
    return result

@router.delete('/in/{stockin_id}', response_model=CaseActionResponse)
async def delete_case_stockin(stockin_id: int, user: User=Depends(require_permission('case_manage')), db: AsyncSession=Depends(get_async_db)):
    """删除皮套入库记录"""
    async with db_transaction(db):
        result = await case_service.delete_case_stockin(db, stockin_id)
    try:
        await publish_stock_event(StockEvent.CASE_STOCK_CHANGED, {'change_type': '皮套入库删除', 'stockin_id': stockin_id})
    except (OSError, ValueError) as e:
        logger.warning('皮套入库删除事件发布失败（不影响数据）: %s', e)
    return result

@router.post('/in/batch', response_model=CaseBatchStockInResponse)
async def batch_submit_case_stockins(data: BatchCaseStockInRequest, user: User=Depends(require_permission('case_manage')), db: AsyncSession=Depends(get_async_db)):
    """批量提交皮套入库"""
    async with db_transaction(db):
        result = await case_service.batch_create_case_stockins(db, data.stockins)
    try:
        cnt = len(data.stockins)
        await publish_stock_event(StockEvent.CASE_STOCK_CHANGED, {'change_type': '皮套批量入库', 'count': cnt})
    except (OSError, ValueError) as e:
        logger.warning('皮套批量入库事件发布失败（不影响数据）: %s', e)
    return result

@router.get('/out/list', response_model=CaseStockOutListResponse)
async def case_stockouts(page: int=Query(1, ge=1), per_page: int=Query(20, ge=1, le=100), customer: str=Query(''), start_date: str=Query(''), end_date: str=Query(''), quantity_min: int | None=Query(None), quantity_max: int | None=Query(None), user: User=Depends(require_permission('case_manage')), db: AsyncSession=Depends(get_async_read_db)):
    """皮套出库列表"""
    return await case_service.get_case_stockout_list(db, page, per_page, customer, start_date, end_date, quantity_min, quantity_max)

@router.get('/out/{stockout_id}', response_model=CaseStockOutDetailResponse)
async def get_case_stockout(stockout_id: int, user: User=Depends(require_permission('case_manage')), db: AsyncSession=Depends(get_async_read_db)):
    """获取单个皮套出库记录"""
    from fastapi_app.shared_models import CaseStockOut
    result = await db.execute(select(CaseStockOut).options(joinedload(CaseStockOut.case)).where(CaseStockOut.id == stockout_id))
    stockout = result.unique().scalar_one_or_none()
    if not stockout:
        raise HTTPException(status_code=404, detail='出库记录不存在')
    return {'id': stockout.id, 'stockout_no': stockout.stockout_no, 'stockout_date': stockout.stockout_date.strftime('%Y-%m-%d') if stockout.stockout_date else '', 'customer': stockout.customer or '', 'case_id': stockout.case_id, 'case_name': stockout.case.sync_name if stockout.case else '', 'quantity': stockout.quantity, 'note': stockout.note or ''}

@router.post('/out/create', response_model=CaseStockOutCreateResponse)
async def create_case_stockout(data: CaseStockOutCreate, user: User=Depends(require_permission('case_manage')), db: AsyncSession=Depends(get_async_db)):
    """皮套出库（单条）"""
    async with db_transaction(db):
        result = await case_service.create_case_stockout(db, data.product_id, data.quantity, data.stockout_date, data.customer, data.note)
    try:
        await publish_stock_event(StockEvent.CASE_STOCK_CHANGED, {'change_type': '皮套出库', 'quantity': data.quantity, 'product_id': data.product_id})
    except (OSError, ValueError) as e:
        logger.warning('皮套出库事件发布失败（不影响数据）: %s', e)
    return result

@router.put('/out/{stockout_id}', response_model=CaseActionResponse)
async def update_case_stockout(stockout_id: int, data: CaseStockOutUpdate, user: User=Depends(require_permission('case_manage')), db: AsyncSession=Depends(get_async_db)):
    """更新皮套出库记录"""
    async with db_transaction(db):
        result = await case_service.update_case_stockout(db, stockout_id, data.model_dump(exclude_none=True))
    try:
        await publish_stock_event(StockEvent.CASE_STOCK_CHANGED, {'change_type': '皮套出库编辑', 'stockout_id': stockout_id})
    except (OSError, ValueError) as e:
        logger.warning('皮套出库编辑事件发布失败（不影响数据）: %s', e)
    return result

@router.delete('/out/{stockout_id}', response_model=CaseActionResponse)
async def delete_case_stockout(stockout_id: int, user: User=Depends(require_permission('case_manage')), db: AsyncSession=Depends(get_async_db)):
    """删除皮套出库记录"""
    async with db_transaction(db):
        result = await case_service.delete_case_stockout(db, stockout_id)
    try:
        await publish_stock_event(StockEvent.CASE_STOCK_CHANGED, {'change_type': '皮套出库删除', 'stockout_id': stockout_id})
    except (OSError, ValueError) as e:
        logger.warning('皮套出库删除事件发布失败（不影响数据）: %s', e)
    return result

@router.post('/out/batch', response_model=CaseBatchStockOutResponse)
async def batch_submit_case_stockouts(data: BatchCaseStockOutRequest, user: User=Depends(require_permission('case_manage')), db: AsyncSession=Depends(get_async_db)):
    """批量提交皮套出库"""
    async with db_transaction(db):
        result = await case_service.batch_create_case_stockouts(db, data.stockouts)
    try:
        cnt = len(data.stockouts)
        await publish_stock_event(StockEvent.CASE_STOCK_CHANGED, {'change_type': '皮套批量出库', 'count': cnt})
    except (OSError, ValueError) as e:
        logger.warning('皮套批量出库事件发布失败（不影响数据）: %s', e)
    return result

@router.get('/inventory-summary', response_model=CaseInventorySummaryResponse)
async def inventory_summary(page: int=Query(1, ge=1), per_page: int=Query(50, ge=1, le=200), search: str=Query('', description='搜索产品名称或69码'), user: User=Depends(require_permission('case_manage')), db: AsyncSession=Depends(get_async_read_db)):
    """皮套库存汇总"""
    return await case_service.get_case_inventory_summary(db, page=page, per_page=per_page, search=search)

@router.get('/inventory-logs/{case_id}', response_model=CaseInventoryLogsResponse)
async def inventory_logs(case_id: int, page: int=Query(1, ge=1), per_page: int=Query(20, ge=1, le=100), type: str=Query(''), start_date: str=Query(''), end_date: str=Query(''), user: User=Depends(require_permission('case_manage')), db: AsyncSession=Depends(get_async_read_db)):
    """皮套库存流水"""
    return await case_service.get_case_inventory_logs(db, case_id, page, per_page, type, start_date, end_date)

@router.get('/products', response_model=CaseProductsResponse)
async def case_products(page: int=Query(1, ge=1, description='页码'), per_page: int=Query(50, ge=1, le=200, description='每页数量'), search: str=Query('', description='搜索产品名称或69码'), user: User=Depends(require_permission('case_manage')), db: AsyncSession=Depends(get_async_read_db)):
    """皮套产品列表（分页）"""
    query = select(Case).options(joinedload(Case.product))
    count_base = select(func.count()).select_from(Case)
    if search:
        pattern = f'%{escape_like(search)}%'
        query = query.outerjoin(Product, Case.product_id == Product.id).where(
            Case.name.like(pattern) | Case.barcode.like(pattern)
            | Product.name.like(pattern) | Product.barcode.like(pattern)
        )
        count_base = count_base.outerjoin(Product, Case.product_id == Product.id).where(
            Case.name.like(pattern) | Case.barcode.like(pattern)
            | Product.name.like(pattern) | Product.barcode.like(pattern)
        )
    total = (await db.execute(count_base)).scalar() or 0
    offset = (page - 1) * per_page
    result = await db.execute(query.order_by(Case.create_time.desc()).offset(offset).limit(per_page))
    cases = list(result.unique().scalars().all())
    return {
        'cases': [{'id': c.id, 'name': c.sync_name, 'barcode': c.sync_barcode or '', 'image': c.image or '', 'current_stock': c.current_stock, 'create_time': c.create_time.strftime('%Y-%m-%d') if c.create_time else ''} for c in cases],
        'total': total,
        'page': page,
        'per_page': per_page,
    }

@router.post('/products', response_model=CaseProductCreateResponse)
async def create_case_product(data: CaseProductCreate, user: User=Depends(require_permission('case_manage')), db: AsyncSession=Depends(get_async_db)):
    """创建皮套产品"""
    async with db_transaction(db):
        result = await case_service.create_case_product(db, name=data.name, barcode=data.barcode, image=data.image, product_id=data.product_id)
    return result

@router.delete('/product/{case_id}', response_model=CaseActionResponse)
async def delete_case_product(case_id: int, user: User=Depends(require_permission('case_manage')), db: AsyncSession=Depends(get_async_db)):
    """删除皮套产品"""
    async with db_transaction(db):
        await case_service.delete_case_product(db, case_id)
    return {'success': True, 'message': '删除成功'}
