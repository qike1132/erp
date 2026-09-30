"""
暂存备货 FastAPI 端点
"""
import logging

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_any_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.schemas.staging import (
    StagingListResponse,
    StagingResponse,
    StagingStockInConfirmResult,
    StagingStockInImportResult,
    StagingStockInUpdate,
)
from fastapi_app.services import staging_service as svc
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get('', response_model=StagingListResponse, summary='获取暂存备货列表')
async def get_staging_stockins(session_id: str=Query('default', description='会话ID'), db: AsyncSession=Depends(get_async_read_db), current_user: User=Depends(require_any_permission('batch_import', 'order_manage', 'stockin_manage'))):
    """获取指定会话的暂存备货列表"""
    scoped_session = f'u{current_user.id}:{session_id}'
    data = await svc.get_staging_stockins(db, scoped_session)
    return StagingListResponse(success=True, data=data, total=len(data))

@router.post('/import', response_model=StagingStockInImportResult, summary='导入备货到暂存区')
async def import_staging_stockins(file: UploadFile=File(...), session_id: str=Query('default', description='会话ID'), db: AsyncSession=Depends(get_async_db), current_user: User=Depends(require_any_permission('batch_import', 'order_manage', 'stockin_manage'))):
    """批量导入备货到暂存区"""
    if not file.filename or not file.filename.endswith('.xlsx'):
        return StagingStockInImportResult(success=False, message='只支持 .xlsx 格式，.xls 已不再支持')
    scoped_session = f'u{current_user.id}:{session_id}'
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        return StagingStockInImportResult(success=False, message='文件大小超过10MB限制')
    if content[:4] != b'PK\x03\x04':
        return StagingStockInImportResult(success=False, message='文件内容不是有效的Excel格式')
    async with db_transaction(db):
        imported, message, errors = await svc.import_staging_stockins_from_excel(db, content, scoped_session)
    return StagingStockInImportResult(success=imported > 0 or len(errors) == 0, message=message, imported=imported, errors=errors)

@router.put('/{stockin_id}', response_model=StagingResponse, summary='更新暂存备货')
async def update_staging_stockin(stockin_id: int, data: StagingStockInUpdate, db: AsyncSession=Depends(get_async_db), current_user: User=Depends(require_any_permission('batch_import', 'order_manage', 'stockin_manage'))):
    """更新暂存备货"""
    async with db_transaction(db):
        await svc.update_staging_stockin(db, stockin_id, data.model_dump(exclude_unset=True))
    return StagingResponse(success=True, message='更新成功')

@router.delete('/clear', response_model=StagingResponse, summary='清空暂存备货')
async def clear_staging_stockins(session_id: str=Query('default', description='会话ID'), db: AsyncSession=Depends(get_async_db), current_user: User=Depends(require_any_permission('batch_import', 'order_manage', 'stockin_manage'))):
    """清空当前会话的暂存备货"""
    scoped_session = f'u{current_user.id}:{session_id}'
    async with db_transaction(db):
        await svc.clear_staging_stockins(db, scoped_session)
    return StagingResponse(success=True, message='清空成功')

@router.delete('/{stockin_id}', response_model=StagingResponse, summary='删除暂存备货')
async def delete_staging_stockin(stockin_id: int, db: AsyncSession=Depends(get_async_db), current_user: User=Depends(require_any_permission('batch_import', 'order_manage', 'stockin_manage'))):
    """删除暂存备货"""
    async with db_transaction(db):
        await svc.delete_staging_stockin(db, stockin_id)
    return StagingResponse(success=True, message='删除成功')

@router.post('/confirm', response_model=StagingStockInConfirmResult, summary='确认暂存备货')
async def confirm_staging_stockins(session_id: str=Query('default', description='会话ID'), db: AsyncSession=Depends(get_async_db), current_user: User=Depends(require_any_permission('batch_import', 'order_manage', 'stockin_manage'))):
    """确认暂存备货 - 转移到正式备货表"""
    scoped_session = f'u{current_user.id}:{session_id}'
    async with db_transaction(db):
        confirmed, errors = await svc.confirm_staging_stockins(db, scoped_session)
    if confirmed == 0 and errors:
        return StagingStockInConfirmResult(success=False, message=errors[0], confirmed=0, errors=errors)
    return StagingStockInConfirmResult(success=True, message=f'成功确认 {confirmed} 个备货', confirmed=confirmed, errors=errors)
