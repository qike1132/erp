"""皮套管理接口

SKU 主档（主件/配件）CRUD、统一出入库流水（增删改/批量）、库存分组汇总与导出。
所有端点均需 case_manage 权限；写操作经 db_transaction 保证事务一致性，并在提交后
发布 case_stock_changed 事件供前端实时刷新。
"""
import io
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.response import success_response
from fastapi_app.schemas.case import (
    BatchCaseMovementRequest,
    CaseActionResponse,
    CaseBatchMovementResponse,
    CaseForProductRequest,
    CaseInventoryResponse,
    CaseItemCreate,
    CaseItemCreateResponse,
    CaseItemListResponse,
    CaseItemUpdate,
    CaseMovementCreate,
    CaseMovementCreateResponse,
    CaseMovementListResponse,
    CaseMovementOut,
    CaseMovementUpdate,
    CaseSearchItem,
    CaseTreeResponse,
)
from fastapi_app.services import case_service
from fastapi_app.services.case._export import inventory_to_xlsx, movements_to_xlsx
from fastapi_app.services.case.queries import fetch_inventory_for_export, fetch_movements_for_export
from fastapi_app.services.notification_service import StockEvent, publish_stock_event
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)

router = APIRouter()


async def _publish_case_event(payload: dict) -> None:
    """发布皮套库存变更事件（失败仅记日志，不影响主业务）。"""
    try:
        await publish_stock_event(StockEvent.CASE_STOCK_CHANGED, payload)
    except (OSError, ValueError) as e:
        logger.warning('皮套%s事件发布失败（不影响数据）: %s', payload.get('change_type', ''), e)


# ==================== SKU 主档 ====================

@router.get('/search', response_model=list[CaseSearchItem])
async def case_search(q: str = Query('', description='搜索关键词'),
                      user: User = Depends(require_permission('case_manage')),
                      db: AsyncSession = Depends(get_async_read_db)) -> list[dict]:
    """皮套 SKU 搜索（录入联想，附当前库存）。"""
    return await case_service.search_cases(db, q)


@router.get('/items', response_model=CaseItemListResponse)
async def case_items(page: int = Query(1, ge=1),
                     per_page: int = Query(50, ge=1, le=200),
                     search: str = Query(''),
                     parent_id: int | None = Query(None),
                     roots_only: bool = Query(False),
                     user: User = Depends(require_permission('case_manage')),
                     db: AsyncSession = Depends(get_async_read_db)) -> dict:
    """皮套 SKU 列表（分页）。roots_only=true 只看主件；parent_id 只看某主件的配件。"""
    return await case_service.get_case_items(db, page, per_page, search, parent_id, roots_only)


@router.post('/items', response_model=CaseItemCreateResponse)
async def create_case_item(data: CaseItemCreate,
                           user: User = Depends(require_permission('case_manage')),
                           db: AsyncSession = Depends(get_async_db)) -> dict:
    """创建皮套 SKU（主件或配件）。需 name 或 product_id 至少一项。"""
    async with db_transaction(db):
        result = await case_service.create_case_item(
            db, name=data.name, barcode=data.barcode, image=data.image, unit=data.unit,
            product_id=data.product_id, parent_id=data.parent_id,
            qty_per_set=data.qty_per_set, initial_stock=data.initial_stock,
        )
    return result


@router.post('/for-product', response_model=CaseTreeResponse)
async def case_for_product(data: CaseForProductRequest,
                           user: User = Depends(require_permission('case_manage')),
                           db: AsyncSession = Depends(get_async_db)) -> dict:
    """取某产品的皮套主件（不存在则以产品信息自动创建），返回主件 + 其配件清单。"""
    async with db_transaction(db):
        result = await case_service.get_or_create_case_tree_for_product(db, data.product_id)
    return result


@router.put('/items/{item_id}', response_model=CaseActionResponse)
async def update_case_item(item_id: int, data: CaseItemUpdate,
                           user: User = Depends(require_permission('case_manage')),
                           db: AsyncSession = Depends(get_async_db)) -> dict:
    """更新皮套 SKU 静态字段。"""
    async with db_transaction(db):
        result = await case_service.update_case_item(db, item_id, data.model_dump(exclude_unset=True))
    return result


@router.delete('/items/{item_id}', response_model=CaseActionResponse)
async def delete_case_item(item_id: int,
                           user: User = Depends(require_permission('case_manage')),
                           db: AsyncSession = Depends(get_async_db)) -> dict:
    """删除皮套 SKU（存在流水或配件时拒绝）。"""
    async with db_transaction(db):
        await case_service.delete_case_item(db, item_id)
    return success_response(message='删除成功')


@router.get('/inventory', response_model=CaseInventoryResponse)
async def case_inventory(page: int = Query(1, ge=1),
                         per_page: int = Query(50, ge=1, le=200),
                         search: str = Query(''),
                         user: User = Depends(require_permission('case_manage')),
                         db: AsyncSession = Depends(get_async_read_db)) -> dict:
    """皮套库存汇总（按主件分组，含配件）+ 整体统计。"""
    return await case_service.get_case_inventory(db, page, per_page, search)


# ==================== 出入库流水 ====================

@router.get('/movements', response_model=CaseMovementListResponse)
async def case_movements(page: int = Query(1, ge=1),
                         per_page: int = Query(20, ge=1, le=100),
                         case_id: int | None = Query(None),
                         direction: str = Query('', description='in/out，空为全部'),
                         customer: str = Query(''),
                         start_date: str = Query(''),
                         end_date: str = Query(''),
                         quantity_min: int | None = Query(None),
                         quantity_max: int | None = Query(None),
                         user: User = Depends(require_permission('case_manage')),
                         db: AsyncSession = Depends(get_async_read_db)) -> dict:
    """出入库流水列表（分页，可按 SKU/方向/客户/日期/数量过滤）。"""
    return await case_service.get_case_movements(
        db, page, per_page, case_id, direction, customer, start_date, end_date, quantity_min, quantity_max
    )


@router.post('/movements/batch', response_model=CaseBatchMovementResponse)
async def batch_case_movements(data: BatchCaseMovementRequest,
                               user: User = Depends(require_permission('case_manage')),
                               db: AsyncSession = Depends(get_async_db)) -> dict:
    """批量提交出入库（暂存单）。逐条隔离，单条失败不影响其它。"""
    async with db_transaction(db):
        result = await case_service.batch_create_movements(db, data.movements)
    await _publish_case_event({'change_type': '皮套批量出入库', 'count': len(data.movements)})
    return result


@router.get('/movements/{movement_id}', response_model=CaseMovementOut)
async def case_movement_detail(movement_id: int,
                               user: User = Depends(require_permission('case_manage')),
                               db: AsyncSession = Depends(get_async_read_db)) -> dict:
    """获取单条出入库流水。"""
    return await case_service.get_case_movement_detail(db, movement_id)


@router.post('/movements', response_model=CaseMovementCreateResponse)
async def create_case_movement(data: CaseMovementCreate,
                               user: User = Depends(require_permission('case_manage')),
                               db: AsyncSession = Depends(get_async_db)) -> dict:
    """新增一条出入库（入库增库存 / 出库扣库存，不足拒绝）。"""
    async with db_transaction(db):
        result = await case_service.create_movement(
            db, data.case_id, data.direction, data.quantity, data.movement_date, data.customer, data.note
        )
    await _publish_case_event({
        'change_type': '皮套' + ('入库' if data.direction == 'in' else '出库'),
        'quantity': data.quantity, 'case_id': data.case_id,
    })
    return result


@router.put('/movements/{movement_id}', response_model=CaseActionResponse)
async def update_case_movement(movement_id: int, data: CaseMovementUpdate,
                               user: User = Depends(require_permission('case_manage')),
                               db: AsyncSession = Depends(get_async_db)) -> dict:
    """更新流水（数量变化时同步库存）。"""
    async with db_transaction(db):
        result = await case_service.update_movement(db, movement_id, data.model_dump(exclude_unset=True))
    await _publish_case_event({'change_type': '皮套流水编辑', 'movement_id': movement_id})
    return result


@router.delete('/movements/{movement_id}', response_model=CaseActionResponse)
async def delete_case_movement(movement_id: int,
                               user: User = Depends(require_permission('case_manage')),
                               db: AsyncSession = Depends(get_async_db)) -> dict:
    """删除流水（回退库存影响）。"""
    async with db_transaction(db):
        result = await case_service.delete_movement(db, movement_id)
    await _publish_case_event({'change_type': '皮套流水删除', 'movement_id': movement_id})
    return result


# ==================== 导出 ====================

@router.get('/export')
async def export_cases(scope: str = Query('movements', description='movements/inventory'),
                       case_id: int | None = Query(None),
                       direction: str = Query(''),
                       customer: str = Query(''),
                       start_date: str = Query(''),
                       end_date: str = Query(''),
                       search: str = Query(''),
                       user: User = Depends(require_permission('case_manage')),
                       db: AsyncSession = Depends(get_async_read_db)) -> StreamingResponse:
    """导出皮套出入库流水或库存汇总为 .xlsx。"""
    if scope == 'inventory':
        rows = await fetch_inventory_for_export(db, search)
        content = inventory_to_xlsx(rows)
        filename = '皮套库存汇总.xlsx'
    else:
        rows = await fetch_movements_for_export(db, case_id, direction, customer, start_date, end_date)
        content = movements_to_xlsx(rows)
        filename = '皮套出入库流水.xlsx'
    headers = {'Content-Disposition': f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(
        io.BytesIO(content),
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers=headers,
    )
