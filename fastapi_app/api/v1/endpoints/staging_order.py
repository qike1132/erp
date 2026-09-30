"""
暂存订单 FastAPI 端点
"""
import logging

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_any_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.schemas.staging import (
    StagingClearResponse,
    StagingListResponse,
    StagingOrderConfirmResult,
    StagingOrderImportResult,
    StagingOrderUpdate,
    StagingResponse,
)
from fastapi_app.services import staging_service as svc
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get('', response_model=StagingListResponse, summary='获取暂存订单列表')
async def get_staging_orders(session_id: str=Query('default', description='会话ID'), page: int=Query(1, ge=1, description='页码'), per_page: int=Query(100, ge=1, le=500, description='每页数量'), db: AsyncSession=Depends(get_async_read_db), current_user: User=Depends(require_any_permission('batch_import', 'order_manage'))):
    """获取指定会话的暂存订单列表"""
    scoped_session = f'u{current_user.id}:{session_id}'
    data = await svc.get_staging_orders(db, scoped_session, page=page, per_page=per_page)
    return StagingListResponse(success=True, data=data.get('items', []), total=data.get('total', 0))

@router.delete('/clear-session/{session_id}', response_model=StagingClearResponse, summary='清空指定会话的暂存订单')
async def clear_staging_orders_by_session(session_id: str, db: AsyncSession=Depends(get_async_db), current_user: User=Depends(require_any_permission('batch_import', 'order_manage'))):
    """清空指定批次的暂存订单"""
    scoped_session = f'u{current_user.id}:{session_id}'
    async with db_transaction(db):
        deleted = await svc.clear_staging_orders_by_session(db, scoped_session)
    return StagingClearResponse(success=True, message=f'已清空 {deleted} 个暂存订单', deleted=deleted)

@router.post('/import', response_model=StagingOrderImportResult, summary='导入订单到暂存区')
async def import_staging_orders(file: UploadFile=File(...), session_id: str=Query('default', description='会话ID'), db: AsyncSession=Depends(get_async_db), current_user: User=Depends(require_any_permission('batch_import', 'order_manage'))):
    """批量导入订单到暂存区"""
    if not file.filename or not file.filename.endswith('.xlsx'):
        return StagingOrderImportResult(success=False, message='只支持 .xlsx 格式，.xls 已不再支持')
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        return StagingOrderImportResult(success=False, message='文件大小超过10MB限制')
    if content[:4] != b'PK\x03\x04':
        return StagingOrderImportResult(success=False, message='文件内容不是有效的Excel格式')
    scoped_session = f'u{current_user.id}:{session_id}'
    async with db_transaction(db):
        imported, message, errors = await svc.import_staging_orders_from_excel(db, content, scoped_session)
    return StagingOrderImportResult(success=imported > 0 or len(errors) == 0, message=message, imported=imported, session_id=session_id, errors=errors)

@router.put('/{order_id}', response_model=StagingResponse, summary='更新暂存订单')
async def update_staging_order(order_id: int, data: StagingOrderUpdate, db: AsyncSession=Depends(get_async_db), current_user: User=Depends(require_any_permission('batch_import', 'order_manage'))):
    """更新暂存订单"""
    async with db_transaction(db):
        await svc.update_staging_order(db, order_id, data.model_dump(exclude_unset=True))
    return StagingResponse(success=True, message='更新成功')

@router.delete('/clear', response_model=StagingResponse, summary='清空当前会话的暂存订单')
async def clear_staging_orders(session_id: str=Query('default', description='会话ID'), db: AsyncSession=Depends(get_async_db), current_user: User=Depends(require_any_permission('batch_import', 'order_manage'))):
    """清空当前会话的暂存订单"""
    scoped_session = f'u{current_user.id}:{session_id}'
    async with db_transaction(db):
        await svc.clear_staging_orders(db, scoped_session)
    return StagingResponse(success=True, message='清空成功')

@router.delete('/{order_id}', response_model=StagingResponse, summary='删除暂存订单')
async def delete_staging_order(order_id: int, db: AsyncSession=Depends(get_async_db), current_user: User=Depends(require_any_permission('batch_import', 'order_manage'))):
    """删除暂存订单"""
    async with db_transaction(db):
        await svc.delete_staging_order(db, order_id)
    return StagingResponse(success=True, message='删除成功')

@router.post('/confirm', response_model=StagingOrderConfirmResult, summary='确认暂存订单')
async def confirm_staging_orders(session_id: str=Query('default', description='会话ID'), db: AsyncSession=Depends(get_async_db), current_user: User=Depends(require_any_permission('batch_import', 'order_manage'))):
    """确认暂存订单 - 转移到正式订单表"""
    scoped_session = f'u{current_user.id}:{session_id}'
    async with db_transaction(db):
        confirmed, errors = await svc.confirm_staging_orders(db, scoped_session)
    if confirmed == 0 and errors:
        return StagingOrderConfirmResult(success=False, message=errors[0], confirmed=0, errors=errors)
    return StagingOrderConfirmResult(success=True, message=f'成功确认 {confirmed} 个订单', confirmed=confirmed, errors=errors)
