"""
暂存出货 FastAPI 端点

从 Flask staging_stockout.py 迁移的暂存出货功能。
"""
import logging

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import require_permission
from fastapi_app.shared_models import User
from fastapi_app.schemas.staging import (
    StagingListResponse, StagingResponse,
    StagingStockOutUpdate, StagingStockOutConfirmResult, StagingStockOutImportResult,
)
from fastapi_app.services import staging_service as svc

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=StagingListResponse, summary="获取暂存出货列表")
async def get_staging_stockouts(
    session_id: str = Query(..., description="会话ID"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission("batch_import")),
):
    """获取指定会话的暂存出货列表"""
    data = await svc.get_staging_stockouts(db, session_id)
    return StagingListResponse(success=True, data=data, total=len(data))


@router.post("/import", response_model=StagingStockOutImportResult, summary="导入出货到暂存区")
async def import_staging_stockouts(
    file: UploadFile = File(...),
    session_id: str = Query(..., description="会话ID"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission("batch_import")),
):
    """批量导入出货到暂存区"""
    if not file.filename or not file.filename.endswith('.xlsx'):
        return StagingStockOutImportResult(success=False, message="只支持 .xlsx 格式，.xls 已不再支持")

    content = await file.read()
    imported, message, errors = await svc.import_staging_stockouts_from_excel(db, content, session_id)

    # 发布出货计划上传事件
    if imported > 0:
        from fastapi_app.services.notification_service import publish_stock_event
        await publish_stock_event("shipment_plan_uploaded", {
            "message": f"新的出货计划已上传，共 {imported} 条",
            "imported": imported,
            "session_id": session_id,
        })

    return StagingStockOutImportResult(
        success=imported > 0 or len(errors) == 0,
        message=message,
        imported=imported,
        errors=errors,
    )


@router.put("/{stockout_id}", response_model=StagingResponse, summary="更新暂存出货")
async def update_staging_stockout(
    stockout_id: int,
    data: StagingStockOutUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission("batch_import")),
):
    """更新暂存出货"""
    try:
        await svc.update_staging_stockout(db, stockout_id, data.model_dump(exclude_unset=True))
        return StagingResponse(success=True, message='更新成功')
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/clear", response_model=StagingResponse, summary="清空暂存出货")
async def clear_staging_stockouts(
    session_id: str = Query(..., description="会话ID"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission("batch_import")),
):
    """清空当前会话的暂存出货"""
    await svc.clear_staging_stockouts(db, session_id)
    return StagingResponse(success=True, message='清空成功')


@router.delete("/{stockout_id}", response_model=StagingResponse, summary="删除暂存出货")
async def delete_staging_stockout(
    stockout_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission("batch_import")),
):
    """删除暂存出货"""
    try:
        await svc.delete_staging_stockout(db, stockout_id)
        return StagingResponse(success=True, message='删除成功')
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/confirm", response_model=StagingStockOutConfirmResult, summary="确认暂存出货")
async def confirm_staging_stockouts(
    session_id: str = Query(..., description="会话ID"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission("batch_import")),
):
    """确认暂存出货 - 转移到正式出货表"""
    confirmed, errors = await svc.confirm_staging_stockouts(db, session_id)
    if confirmed > 0:
        from fastapi_app.services.notification_service import publish_stock_event
        await publish_stock_event("stock_changed", {
            "message": f"已确认 {confirmed} 条出货记录",
            "confirmed": confirmed,
        })
    if confirmed == 0 and errors:
        return StagingStockOutConfirmResult(
            success=False, message=errors[0], confirmed=0, errors=errors
        )
    return StagingStockOutConfirmResult(
        success=True,
        message=f'成功确认 {confirmed} 个出货',
        confirmed=confirmed,
        errors=errors,
    )
