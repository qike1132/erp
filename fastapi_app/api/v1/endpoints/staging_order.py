"""
暂存订单 FastAPI 端点

从 Flask staging_order.py 迁移的暂存订单功能。
"""
import logging
import uuid

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import require_permission
from fastapi_app.shared_models import User
from fastapi_app.schemas.staging import (
    StagingListResponse, StagingResponse, StagingClearResponse,
    StagingOrderUpdate, StagingOrderConfirmResult, StagingOrderImportResult,
)
from fastapi_app.services import staging_service as svc

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=StagingListResponse, summary="获取暂存订单列表")
async def get_staging_orders(
    session_id: str = Query("default", description="会话ID"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission("batch_import")),
):
    """获取指定会话的暂存订单列表"""
    data = await svc.get_staging_orders(db, session_id)
    return StagingListResponse(success=True, data=data, total=len(data))


@router.delete("/clear-session/{session_id}", response_model=StagingClearResponse, summary="清空指定会话的暂存订单")
async def clear_staging_orders_by_session(
    session_id: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission("batch_import")),
):
    """清空指定批次的暂存订单"""
    deleted = await svc.clear_staging_orders_by_session(db, session_id)
    return StagingClearResponse(
        success=True,
        message=f'已清空 {deleted} 个暂存订单',
        deleted=deleted,
    )


@router.post("/import", response_model=StagingOrderImportResult, summary="导入订单到暂存区")
async def import_staging_orders(
    file: UploadFile = File(...),
    session_id: str = Query("default", description="会话ID"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission("batch_import")),
):
    """批量导入订单到暂存区"""
    if not file.filename or not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        return StagingOrderImportResult(success=False, message="只支持 Excel 文件格式")

    content = await file.read()
    imported, message, errors = await svc.import_staging_orders_from_excel(db, content, session_id)

    return StagingOrderImportResult(
        success=imported > 0 or len(errors) == 0,
        message=message,
        imported=imported,
        session_id=session_id,
        errors=errors,
    )


@router.put("/{order_id}", response_model=StagingResponse, summary="更新暂存订单")
async def update_staging_order(
    order_id: int,
    data: StagingOrderUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission("batch_import")),
):
    """更新暂存订单"""
    try:
        result = await svc.update_staging_order(db, order_id, data.model_dump(exclude_unset=True))
        return StagingResponse(success=True, message='更新成功')
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/clear", response_model=StagingResponse, summary="清空当前会话的暂存订单")
async def clear_staging_orders(
    session_id: str = Query("default", description="会话ID"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission("batch_import")),
):
    """清空当前会话的暂存订单"""
    await svc.clear_staging_orders(db, session_id)
    return StagingResponse(success=True, message='清空成功')


@router.delete("/{order_id}", response_model=StagingResponse, summary="删除暂存订单")
async def delete_staging_order(
    order_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission("batch_import")),
):
    """删除暂存订单"""
    try:
        await svc.delete_staging_order(db, order_id)
        return StagingResponse(success=True, message='删除成功')
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/confirm", response_model=StagingOrderConfirmResult, summary="确认暂存订单")
async def confirm_staging_orders(
    session_id: str = Query("default", description="会话ID"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission("batch_import")),
):
    """确认暂存订单 - 转移到正式订单表"""
    confirmed, errors = await svc.confirm_staging_orders(db, session_id)
    if confirmed == 0 and errors:
        return StagingOrderConfirmResult(
            success=False, message=errors[0], confirmed=0, errors=errors
        )
    return StagingOrderConfirmResult(
        success=True,
        message=f'成功确认 {confirmed} 个订单',
        confirmed=confirmed,
        errors=errors,
    )
