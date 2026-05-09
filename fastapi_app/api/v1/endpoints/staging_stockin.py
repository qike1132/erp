"""
暂存备货 FastAPI 端点

从 Flask staging_stockin.py 迁移的暂存备货功能。
"""
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
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
async def get_staging_stockins(session_id: str=Query('default', description='会话ID'), db: AsyncSession=Depends(get_async_read_db), current_user: User=Depends(require_permission('batch_import'))):
    """获取指定会话的暂存备货列表"""
    data = await svc.get_staging_stockins(db, session_id)
    return StagingListResponse(success=True, data=data, total=len(data))

@router.post('/import', response_model=StagingStockInImportResult, summary='导入备货到暂存区')
async def import_staging_stockins(file: UploadFile=File(...), session_id: str=Query('default', description='会话ID'), db: AsyncSession=Depends(get_async_db), current_user: User=Depends(require_permission('batch_import'))):
    """批量导入备货到暂存区"""
    if not file.filename or not file.filename.endswith('.xlsx'):
        return StagingStockInImportResult(success=False, message='只支持 .xlsx 格式，.xls 已不再支持')
    content = await file.read()
    imported, message, errors = await svc.import_staging_stockins_from_excel(db, content, session_id)
    return StagingStockInImportResult(success=imported > 0 or len(errors) == 0, message=message, imported=imported, errors=errors)

@router.put('/{stockin_id}', response_model=StagingResponse, summary='更新暂存备货')
async def update_staging_stockin(stockin_id: int, data: StagingStockInUpdate, db: AsyncSession=Depends(get_async_db), current_user: User=Depends(require_permission('batch_import'))):
    """更新暂存备货"""
    try:
        await svc.update_staging_stockin(db, stockin_id, data.model_dump(exclude_unset=True))
        return StagingResponse(success=True, message='更新成功')
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

@router.delete('/clear', response_model=StagingResponse, summary='清空暂存备货')
async def clear_staging_stockins(session_id: str=Query('default', description='会话ID'), db: AsyncSession=Depends(get_async_db), current_user: User=Depends(require_permission('batch_import'))):
    """清空当前会话的暂存备货"""
    await svc.clear_staging_stockins(db, session_id)
    return StagingResponse(success=True, message='清空成功')

@router.delete('/{stockin_id}', response_model=StagingResponse, summary='删除暂存备货')
async def delete_staging_stockin(stockin_id: int, db: AsyncSession=Depends(get_async_db), current_user: User=Depends(require_permission('batch_import'))):
    """删除暂存备货"""
    try:
        await svc.delete_staging_stockin(db, stockin_id)
        return StagingResponse(success=True, message='删除成功')
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

@router.post('/confirm', response_model=StagingStockInConfirmResult, summary='确认暂存备货')
async def confirm_staging_stockins(session_id: str=Query('default', description='会话ID'), db: AsyncSession=Depends(get_async_db), current_user: User=Depends(require_permission('batch_import'))):
    """确认暂存备货 - 转移到正式备货表"""
    confirmed, errors = await svc.confirm_staging_stockins(db, session_id)
    if confirmed == 0 and errors:
        return StagingStockInConfirmResult(success=False, message=errors[0], confirmed=0, errors=errors)
    return StagingStockInConfirmResult(success=True, message=f'成功确认 {confirmed} 个备货', confirmed=confirmed, errors=errors)
