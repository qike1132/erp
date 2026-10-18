"""
暂存出货 FastAPI 端点

职责：
- 提供暂存出货的列表查询、导入、更新、删除、清空接口
- 提供暂存出货确认接口（转移到正式出货表）
- 协调库存变更通知事件发布
"""
import logging

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_any_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.validators import matches_upload_magic
from fastapi_app.schemas.staging import (
    StagingListResponse,
    StagingResponse,
    StagingStockOutConfirmResult,
    StagingStockOutImportResult,
    StagingStockOutUpdate,
)
from fastapi_app.services import staging_service as svc
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()

# 暂存出货导入文件大小上限（10MB）
MAX_STAGING_FILE_SIZE = 10 * 1024 * 1024
# xlsx 文件的 ZIP 格式魔数（PK\x03\x04）


def _build_scoped_session(user_id: int, session_id: str) -> str:
    """构造用户隔离的会话标识，避免不同用户暂存数据互相污染。

    Args:
        user_id: 当前用户 ID。
        session_id: 客户端传入的会话 ID。

    Returns:
        str: 格式为 `u{user_id}:{session_id}` 的隔离会话标识。
    """
    return f'u{user_id}:{session_id}'


@router.get('', response_model=StagingListResponse, summary='获取暂存出货列表')
async def get_staging_stockouts(
    session_id: str = Query(..., max_length=50, description='会话ID'),
    db: AsyncSession = Depends(get_async_read_db),
    current_user: User = Depends(require_any_permission('batch_import', 'stockout_manage')),
) -> StagingListResponse:
    """获取指定会话的暂存出货列表。

    Args:
        session_id: 客户端会话 ID，用于隔离不同导入批次。
        db: 异步数据库会话（只读副本）。
        current_user: 当前登录用户，用于构造用户隔离的会话标识。

    Returns:
        StagingListResponse: 包含暂存出货列表和总数的响应。
    """
    scoped_session = _build_scoped_session(current_user.id, session_id)
    data = await svc.get_staging_stockouts(db, scoped_session)
    return StagingListResponse(success=True, data=data, total=len(data))


@router.post('/import', response_model=StagingStockOutImportResult, summary='导入出货到暂存区')
async def import_staging_stockouts(
    file: UploadFile = File(...),
    session_id: str = Query(..., max_length=50, description='会话ID'),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_any_permission('batch_import', 'stockout_manage')),
) -> StagingStockOutImportResult:
    """批量导入出货到暂存区。

    对上传文件进行格式与大小校验后，解析 Excel 并写入暂存表。
    导入成功后发布出货计划上传通知事件。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        session_id: 客户端会话 ID，用于隔离不同导入批次。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户，用于构造用户隔离的会话标识。

    Returns:
        StagingStockOutImportResult: 包含导入结果、消息和错误列表的响应。
    """
    if not file.filename or not file.filename.endswith('.xlsx'):
        return StagingStockOutImportResult(success=False, message='只支持 .xlsx 格式，.xls 已不再支持')
    scoped_session = _build_scoped_session(current_user.id, session_id)
    content = await file.read()
    if len(content) > MAX_STAGING_FILE_SIZE:
        return StagingStockOutImportResult(success=False, message='文件大小超过10MB限制')
    # 校验文件头魔数（2026-10-17 审计 P2-20：走公共层，与备货/订单导入同口径）
    if not matches_upload_magic(content, ('xlsx', 'xlsm')):
        return StagingStockOutImportResult(success=False, message='文件内容不是有效的Excel格式')
    async with db_transaction(db):
        imported, message, errors = await svc.import_staging_stockouts_from_excel(db, content, scoped_session)
    if imported > 0:
        from fastapi_app.services.notification_service import StockEvent, publish_stock_event
        await publish_stock_event(
            StockEvent.SHIPMENT_PLAN_UPLOADED,
            {'message': f'新的出货计划已上传，共 {imported} 条', 'imported': imported, 'session_id': scoped_session},
        )
    return StagingStockOutImportResult(
        success=imported > 0 or len(errors) == 0,
        message=message, imported=imported, errors=errors,
    )


@router.put('/{stockout_id}', response_model=StagingResponse, summary='更新暂存出货')
async def update_staging_stockout(
    stockout_id: int,
    data: StagingStockOutUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_any_permission('batch_import', 'stockout_manage')),
) -> StagingResponse:
    """更新暂存出货记录。

    Args:
        stockout_id: 暂存出货记录 ID。
        data: 更新参数（仅包含需要修改的字段）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        StagingResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        # 会话隔离：与 list/clear/confirm 同口径，禁止按 ID 改到他人的暂存行
        await svc.update_staging_stockout(
            db, stockout_id, data.model_dump(exclude_unset=True),
            session_scope=f'u{current_user.id}:',
        )
    return StagingResponse(success=True, message='更新成功')


@router.delete('/clear', response_model=StagingResponse, summary='清空暂存出货')
async def clear_staging_stockouts(
    session_id: str = Query(..., max_length=50, description='会话ID'),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_any_permission('batch_import', 'stockout_manage')),
) -> StagingResponse:
    """清空当前会话的暂存出货。

    Args:
        session_id: 客户端会话 ID，用于定位待清空的暂存数据。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户，用于构造用户隔离的会话标识。

    Returns:
        StagingResponse: 包含成功标志和提示消息的响应。
    """
    scoped_session = _build_scoped_session(current_user.id, session_id)
    async with db_transaction(db):
        await svc.clear_staging_stockouts(db, scoped_session)
    return StagingResponse(success=True, message='清空成功')


@router.delete('/{stockout_id}', response_model=StagingResponse, summary='删除暂存出货')
async def delete_staging_stockout(
    stockout_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_any_permission('batch_import', 'stockout_manage')),
) -> StagingResponse:
    """删除单条暂存出货记录。

    Args:
        stockout_id: 暂存出货记录 ID。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        StagingResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        # 会话隔离：与 list/clear/confirm 同口径，禁止按 ID 删到他人的暂存行
        await svc.delete_staging_stockout(db, stockout_id, session_scope=f'u{current_user.id}:')
    return StagingResponse(success=True, message='删除成功')


@router.post('/confirm', response_model=StagingStockOutConfirmResult, summary='确认暂存出货')
async def confirm_staging_stockouts(
    session_id: str = Query(..., max_length=50, description='会话ID'),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_any_permission('batch_import', 'stockout_manage')),
) -> StagingStockOutConfirmResult:
    """确认暂存出货 - 转移到正式出货表。

    确认成功后发布库存变更通知事件。

    Args:
        session_id: 客户端会话 ID，用于定位待确认的暂存数据。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户，用于构造用户隔离的会话标识。

    Returns:
        StagingStockOutConfirmResult: 包含确认结果、消息和错误列表的响应。
    """
    scoped_session = _build_scoped_session(current_user.id, session_id)
    async with db_transaction(db):
        confirmed, errors = await svc.confirm_staging_stockouts(db, scoped_session)
    if confirmed > 0:
        from fastapi_app.services.notification_service import StockEvent, publish_stock_event
        await publish_stock_event(
            StockEvent.STOCK_CHANGED,
            {'message': f'已确认 {confirmed} 条出货记录', 'confirmed': confirmed},
        )
    # 全部失败时返回首个错误信息
    if confirmed == 0 and errors:
        return StagingStockOutConfirmResult(success=False, message=errors[0], confirmed=0, errors=errors)
    return StagingStockOutConfirmResult(
        success=True, message=f'成功确认 {confirmed} 个出货', confirmed=confirmed, errors=errors,
    )
