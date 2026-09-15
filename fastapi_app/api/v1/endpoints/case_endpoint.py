"""皮套管理接口

提供皮套产品的 CRUD、入库/出库管理、库存汇总与流水查询等 HTTP 端点。
所有端点均需要 case_manage 权限，写操作通过 db_transaction 保证事务一致性，
并通过 publish_stock_event 发布库存变更事件供前端实时刷新。
"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.response import success_response
from fastapi_app.schemas.case import (
    BatchCaseStockInRequest,
    BatchCaseStockOutRequest,
    CaseActionResponse,
    CaseBatchStockInResponse,
    CaseBatchStockOutResponse,
    CaseInventoryLogsResponse,
    CaseInventorySummaryResponse,
    CaseProductCreate,
    CaseProductCreateResponse,
    CaseProductsResponse,
    CaseSearchItem,
    CaseStockInCreate,
    CaseStockInCreateResponse,
    CaseStockInDetailResponse,
    CaseStockInListResponse,
    CaseStockInUpdate,
    CaseStockOutCreate,
    CaseStockOutCreateResponse,
    CaseStockOutDetailResponse,
    CaseStockOutListResponse,
    CaseStockOutUpdate,
)
from fastapi_app.services import case_service
from fastapi_app.services.notification_service import StockEvent, publish_stock_event
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)

router = APIRouter()


async def _publish_case_event(payload: dict) -> None:
    """发布皮套库存变更事件，失败时仅记录日志不影响主业务。

    所有皮套写操作（入库/出库/删除/批量）在事务提交后调用此函数，
    通知前端通过 WebSocket 实时刷新库存数据。

    Args:
        payload: 事件数据，必须包含 change_type 字段用于日志标识。
    """
    try:
        await publish_stock_event(StockEvent.CASE_STOCK_CHANGED, payload)
    except (OSError, ValueError) as e:
        logger.warning('皮套%s事件发布失败（不影响数据）: %s', payload.get('change_type', ''), e)


@router.get('/search', response_model=list[CaseSearchItem])
async def case_search(q: str = Query('', description='搜索关键词'),
                      user: User = Depends(require_permission('case_manage')),
                      db: AsyncSession = Depends(get_async_read_db)) -> list[dict]:
    """皮套搜索

    按产品名称或条码模糊匹配，返回附库存信息的皮套列表。

    Args:
        q: 搜索关键词，空字符串返回前 20 条。
        user: 当前登录用户（需 case_manage 权限）。
        db: 异步只读数据库会话。

    Returns:
        皮套字典列表，每项包含 id、name、barcode、current_stock。
    """
    return await case_service.search_cases(db, q)


@router.get('/in/list', response_model=CaseStockInListResponse)
async def case_stockins(page: int = Query(1, ge=1),
                        per_page: int = Query(20, ge=1, le=100),
                        customer: str = Query(''),
                        start_date: str = Query(''),
                        end_date: str = Query(''),
                        quantity_min: int | None = Query(None),
                        quantity_max: int | None = Query(None),
                        user: User = Depends(require_permission('case_manage')),
                        db: AsyncSession = Depends(get_async_read_db)) -> dict:
    """皮套入库列表

    分页查询入库记录，支持按客户、日期范围、数量范围过滤。

    Args:
        page: 页码，从 1 开始。
        per_page: 每页数量，1-100。
        customer: 客户名称模糊匹配。
        start_date: 开始日期（YYYY-MM-DD）。
        end_date: 结束日期（YYYY-MM-DD，含当天）。
        quantity_min: 最小数量（含）。
        quantity_max: 最大数量（含）。
        user: 当前登录用户（需 case_manage 权限）。
        db: 异步只读数据库会话。

    Returns:
        dict，包含 stockins、total、pages、current_page。
    """
    return await case_service.get_case_stockins(
        db, page, per_page, customer, start_date, end_date, quantity_min, quantity_max
    )


@router.get('/in/{stockin_id}', response_model=CaseStockInDetailResponse)
async def get_case_stockin(stockin_id: int,
                           user: User = Depends(require_permission('case_manage')),
                           db: AsyncSession = Depends(get_async_read_db)) -> dict:
    """获取单个皮套入库记录

    Args:
        stockin_id: 入库记录 ID。
        user: 当前登录用户（需 case_manage 权限）。
        db: 异步只读数据库会话。

    Returns:
        dict，包含入库记录字段。

    Raises:
        HTTPException: 入库记录不存在时抛出 404。
    """
    return await case_service.get_case_stockin_detail(db, stockin_id)


@router.post('/in/create', response_model=CaseStockInCreateResponse)
async def create_case_stockin(data: CaseStockInCreate,
                              user: User = Depends(require_permission('case_manage')),
                              db: AsyncSession = Depends(get_async_db)) -> dict:
    """皮套入库（单条）

    创建入库记录并同步更新库存，事务提交后发布库存变更事件。

    Args:
        data: 入库数据，包含 product_id、quantity、stockin_date、customer、note。
        user: 当前登录用户（需 case_manage 权限）。
        db: 异步数据库会话。

    Returns:
        dict，包含 success、stockin_no、id。
    """
    async with db_transaction(db):
        result = await case_service.create_case_stockin(
            db, data.product_id, data.quantity, data.stockin_date, data.customer, data.note
        )
    await _publish_case_event({
        'change_type': '皮套入库', 'quantity': data.quantity, 'product_id': data.product_id,
    })
    return result


@router.put('/in/{stockin_id}', response_model=CaseActionResponse)
async def update_case_stockin(stockin_id: int, data: CaseStockInUpdate,
                              user: User = Depends(require_permission('case_manage')),
                              db: AsyncSession = Depends(get_async_db)) -> dict:
    """更新皮套入库记录

    支持更新数量、客户、日期、备注；数量变更时同步调整库存。

    Args:
        stockin_id: 入库记录 ID。
        data: 待更新字段。
        user: 当前登录用户（需 case_manage 权限）。
        db: 异步数据库会话。

    Returns:
        dict，包含 success、message。
    """
    async with db_transaction(db):
        result = await case_service.update_case_stockin(db, stockin_id, data.model_dump(exclude_none=True))
    await _publish_case_event({'change_type': '皮套入库编辑', 'stockin_id': stockin_id})
    return result


@router.delete('/in/{stockin_id}', response_model=CaseActionResponse)
async def delete_case_stockin(stockin_id: int,
                              user: User = Depends(require_permission('case_manage')),
                              db: AsyncSession = Depends(get_async_db)) -> dict:
    """删除皮套入库记录

    删除时同步扣减库存，存在出库关联时禁止删除。

    Args:
        stockin_id: 入库记录 ID。
        user: 当前登录用户（需 case_manage 权限）。
        db: 异步数据库会话。

    Returns:
        dict，包含 success、message。
    """
    async with db_transaction(db):
        result = await case_service.delete_case_stockin(db, stockin_id)
    await _publish_case_event({'change_type': '皮套入库删除', 'stockin_id': stockin_id})
    return result


@router.post('/in/batch', response_model=CaseBatchStockInResponse)
async def batch_submit_case_stockins(data: BatchCaseStockInRequest,
                                     user: User = Depends(require_permission('case_manage')),
                                     db: AsyncSession = Depends(get_async_db)) -> dict:
    """批量提交皮套入库

    逐条处理，单条失败不影响其他记录。

    Args:
        data: 批量入库数据，包含 stockins 列表。
        user: 当前登录用户（需 case_manage 权限）。
        db: 异步数据库会话。

    Returns:
        dict，包含 success、message、failed。
    """
    async with db_transaction(db):
        result = await case_service.batch_create_case_stockins(db, data.stockins)
    await _publish_case_event({
        'change_type': '皮套批量入库', 'count': len(data.stockins),
    })
    return result


@router.get('/out/list', response_model=CaseStockOutListResponse)
async def case_stockouts(page: int = Query(1, ge=1),
                         per_page: int = Query(20, ge=1, le=100),
                         customer: str = Query(''),
                         start_date: str = Query(''),
                         end_date: str = Query(''),
                         quantity_min: int | None = Query(None),
                         quantity_max: int | None = Query(None),
                         user: User = Depends(require_permission('case_manage')),
                         db: AsyncSession = Depends(get_async_read_db)) -> dict:
    """皮套出库列表

    分页查询出库记录，支持按客户、日期范围、数量范围过滤。

    Args:
        page: 页码，从 1 开始。
        per_page: 每页数量，1-100。
        customer: 客户名称模糊匹配。
        start_date: 开始日期（YYYY-MM-DD）。
        end_date: 结束日期（YYYY-MM-DD，含当天）。
        quantity_min: 最小数量（含）。
        quantity_max: 最大数量（含）。
        user: 当前登录用户（需 case_manage 权限）。
        db: 异步只读数据库会话。

    Returns:
        dict，包含 stockouts、total、pages、current_page。
    """
    return await case_service.get_case_stockout_list(
        db, page, per_page, customer, start_date, end_date, quantity_min, quantity_max
    )


@router.get('/out/{stockout_id}', response_model=CaseStockOutDetailResponse)
async def get_case_stockout(stockout_id: int,
                            user: User = Depends(require_permission('case_manage')),
                            db: AsyncSession = Depends(get_async_read_db)) -> dict:
    """获取单个皮套出库记录

    Args:
        stockout_id: 出库记录 ID。
        user: 当前登录用户（需 case_manage 权限）。
        db: 异步只读数据库会话。

    Returns:
        dict，包含出库记录字段。

    Raises:
        HTTPException: 出库记录不存在时抛出 404。
    """
    return await case_service.get_case_stockout_detail(db, stockout_id)


@router.post('/out/create', response_model=CaseStockOutCreateResponse)
async def create_case_stockout(data: CaseStockOutCreate,
                               user: User = Depends(require_permission('case_manage')),
                               db: AsyncSession = Depends(get_async_db)) -> dict:
    """皮套出库（单条）

    创建出库记录并同步扣减库存，库存不足时拒绝。

    Args:
        data: 出库数据，包含 product_id、quantity、stockout_date、customer、note。
        user: 当前登录用户（需 case_manage 权限）。
        db: 异步数据库会话。

    Returns:
        dict，包含 success、stockout_no、id。
    """
    async with db_transaction(db):
        result = await case_service.create_case_stockout(
            db, data.product_id, data.quantity, data.stockout_date, data.customer, data.note
        )
    await _publish_case_event({
        'change_type': '皮套出库', 'quantity': data.quantity, 'product_id': data.product_id,
    })
    return result


@router.put('/out/{stockout_id}', response_model=CaseActionResponse)
async def update_case_stockout(stockout_id: int, data: CaseStockOutUpdate,
                               user: User = Depends(require_permission('case_manage')),
                               db: AsyncSession = Depends(get_async_db)) -> dict:
    """更新皮套出库记录

    支持更新数量、客户、日期、备注；数量变更时同步调整库存。

    Args:
        stockout_id: 出库记录 ID。
        data: 待更新字段。
        user: 当前登录用户（需 case_manage 权限）。
        db: 异步数据库会话。

    Returns:
        dict，包含 success、message。
    """
    async with db_transaction(db):
        result = await case_service.update_case_stockout(db, stockout_id, data.model_dump(exclude_none=True))
    await _publish_case_event({'change_type': '皮套出库编辑', 'stockout_id': stockout_id})
    return result


@router.delete('/out/{stockout_id}', response_model=CaseActionResponse)
async def delete_case_stockout(stockout_id: int,
                               user: User = Depends(require_permission('case_manage')),
                               db: AsyncSession = Depends(get_async_db)) -> dict:
    """删除皮套出库记录

    删除时同步回补库存。

    Args:
        stockout_id: 出库记录 ID。
        user: 当前登录用户（需 case_manage 权限）。
        db: 异步数据库会话。

    Returns:
        dict，包含 success、message。
    """
    async with db_transaction(db):
        result = await case_service.delete_case_stockout(db, stockout_id)
    await _publish_case_event({'change_type': '皮套出库删除', 'stockout_id': stockout_id})
    return result


@router.post('/out/batch', response_model=CaseBatchStockOutResponse)
async def batch_submit_case_stockouts(data: BatchCaseStockOutRequest,
                                      user: User = Depends(require_permission('case_manage')),
                                      db: AsyncSession = Depends(get_async_db)) -> dict:
    """批量提交皮套出库

    逐条处理，单条失败不影响其他记录。

    Args:
        data: 批量出库数据，包含 stockouts 列表。
        user: 当前登录用户（需 case_manage 权限）。
        db: 异步数据库会话。

    Returns:
        dict，包含 success、results。
    """
    async with db_transaction(db):
        result = await case_service.batch_create_case_stockouts(db, data.stockouts)
    await _publish_case_event({
        'change_type': '皮套批量出库', 'count': len(data.stockouts),
    })
    return result


@router.get('/inventory-summary', response_model=CaseInventorySummaryResponse)
async def inventory_summary(page: int = Query(1, ge=1),
                            per_page: int = Query(50, ge=1, le=200),
                            search: str = Query('', description='搜索产品名称或69码'),
                            user: User = Depends(require_permission('case_manage')),
                            db: AsyncSession = Depends(get_async_read_db)) -> dict:
    """皮套库存汇总

    通过聚合入库/出库记录计算每个皮套的当前库存，并返回整体统计。

    Args:
        page: 页码，从 1 开始。
        per_page: 每页数量，1-200。
        search: 搜索关键词，匹配 Case.name、Case.barcode、Product.name、Product.barcode。
        user: 当前登录用户（需 case_manage 权限）。
        db: 异步只读数据库会话。

    Returns:
        dict，包含 inventory、total、page、per_page、pages、stats。
    """
    return await case_service.get_case_inventory_summary(db, page=page, per_page=per_page, search=search)


@router.get('/inventory-logs/{case_id}', response_model=CaseInventoryLogsResponse)
async def inventory_logs(case_id: int,
                         page: int = Query(1, ge=1),
                         per_page: int = Query(20, ge=1, le=100),
                         type: str = Query(''),
                         start_date: str = Query(''),
                         end_date: str = Query(''),
                         user: User = Depends(require_permission('case_manage')),
                         db: AsyncSession = Depends(get_async_read_db)) -> dict:
    """皮套库存流水

    分页查询指定皮套的库存变动流水。

    Args:
        case_id: 皮套 ID。
        page: 页码，从 1 开始。
        per_page: 每页数量，1-100。
        type: 流水类型过滤（如"入库"、"出库"），空字符串表示不限制。
        start_date: 开始日期（YYYY-MM-DD）。
        end_date: 结束日期（YYYY-MM-DD，含当天）。
        user: 当前登录用户（需 case_manage 权限）。
        db: 异步只读数据库会话。

    Returns:
        dict，包含 success、logs、pagination。
    """
    return await case_service.get_case_inventory_logs(
        db, case_id, page, per_page, type, start_date, end_date
    )


@router.get('/products', response_model=CaseProductsResponse)
async def case_products(page: int = Query(1, ge=1, description='页码'),
                        per_page: int = Query(50, ge=1, le=200, description='每页数量'),
                        search: str = Query('', description='搜索产品名称或69码'),
                        user: User = Depends(require_permission('case_manage')),
                        db: AsyncSession = Depends(get_async_read_db)) -> dict:
    """皮套产品列表（分页）

    Args:
        page: 页码，从 1 开始。
        per_page: 每页数量，1-200。
        search: 搜索关键词，匹配 Case.name、Case.barcode、Product.name、Product.barcode。
        user: 当前登录用户（需 case_manage 权限）。
        db: 异步只读数据库会话。

    Returns:
        dict，包含 cases、total、page、per_page。
    """
    return await case_service.get_case_products(db, page=page, per_page=per_page, search=search)


@router.post('/products', response_model=CaseProductCreateResponse)
async def create_case_product(data: CaseProductCreate,
                              user: User = Depends(require_permission('case_manage')),
                              db: AsyncSession = Depends(get_async_db)) -> dict:
    """创建皮套产品

    需提供 name 或 product_id 至少一项。

    Args:
        data: 皮套产品数据，包含 name、barcode、image、product_id。
        user: 当前登录用户（需 case_manage 权限）。
        db: 异步数据库会话。

    Returns:
        dict，包含 success、message、id。
    """
    async with db_transaction(db):
        result = await case_service.create_case_product(
            db, name=data.name, barcode=data.barcode, image=data.image, product_id=data.product_id
        )
    return result


@router.delete('/product/{case_id}', response_model=CaseActionResponse)
async def delete_case_product(case_id: int,
                              user: User = Depends(require_permission('case_manage')),
                              db: AsyncSession = Depends(get_async_db)) -> dict:
    """删除皮套产品

    仅允许删除库存为 0 且无关联记录的皮套。

    Args:
        case_id: 皮套 ID。
        user: 当前登录用户（需 case_manage 权限）。
        db: 异步数据库会话。

    Returns:
        dict，包含 success、message。
    """
    async with db_transaction(db):
        await case_service.delete_case_product(db, case_id)
    return success_response(message='删除成功')
