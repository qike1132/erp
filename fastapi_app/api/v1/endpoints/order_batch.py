"""订单批次号管理路由

职责：
    - 提供订单批次号的查询、分配、更新、归档等接口
    - 维护批次白名单（允许参与批次管理的客户列表）
    - 查询历史批次记录

依赖服务：order_batch_service
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_any_permission, require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.schemas.order_batch import (
    BatchAssignRequest,
    BatchAssignResponse,
    BatchCompleteRequest,
    BatchCompleteResponse,
    BatchNoUpdate,
    BatchNoUpdateResponse,
    BatchQueryListResponse,
    OrderBatchListResponse,
    WhitelistResponse,
)
from fastapi_app.services import order_batch_service
from fastapi_app.shared_models import User

router = APIRouter()


@router.get('/batch-query', response_model=BatchQueryListResponse)
async def batch_query_list(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    batch_no: str | None = Query(None),
    status: str | None = Query(None),
    customer: str | None = Query(None),
    keyword: str | None = Query(None),
    db: AsyncSession = Depends(get_async_read_db),
    _current_user: User = Depends(require_permission('batch_manage')),
) -> BatchQueryListResponse:
    """分页查询批次列表（含订单与入库记录合并视图）。

    Args:
        page: 页码，从 1 开始。
        per_page: 每页条数，1-500。
        batch_no: 批次号过滤（模糊匹配）。
        status: 状态过滤。
        customer: 客户名称过滤。
        keyword: 关键字（订单号/产品名称等）。
        db: 只读数据库会话。
        _current_user: 当前操作用户（用于权限校验）。

    Returns:
        BatchQueryListResponse: 批次查询结果分页响应。
    """
    result = await order_batch_service.get_batch_query_list(
        db, page=page, per_page=per_page, batch_no=batch_no, status=status, customer=customer, keyword=keyword,
    )
    return BatchQueryListResponse(data=result['items'], total=result['total'], page=page, per_page=per_page)


@router.get('/orders', response_model=OrderBatchListResponse)
async def list_batch_orders(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    batch_no: str | None = Query(None),
    status: str | None = Query(None),
    customer: str | None = Query(None),
    keyword: str | None = Query(None),
    db: AsyncSession = Depends(get_async_read_db),
    _current_user: User = Depends(require_any_permission('batch_manage', 'order_manage')),
) -> OrderBatchListResponse:
    """分页查询订单列表（用于批次管理界面）。

    Args:
        page: 页码，从 1 开始。
        per_page: 每页条数，1-500。
        batch_no: 批次号过滤。
        status: 订单状态过滤。
        customer: 客户名称过滤。
        keyword: 关键字搜索。
        db: 只读数据库会话。
        _current_user: 当前操作用户（用于权限校验）。

    Returns:
        OrderBatchListResponse: 订单分页响应。
    """
    result = await order_batch_service.get_batch_orders(
        db, page=page, per_page=per_page, batch_no=batch_no, status=status, customer=customer, keyword=keyword,
    )
    return OrderBatchListResponse(data=result['items'], total=result['total'], page=page, per_page=per_page)


@router.put('/orders/{record_id}/batch-no', response_model=BatchNoUpdateResponse)
async def update_order_batch_no(
    record_id: int,
    data: BatchNoUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_any_permission('batch_manage', 'order_manage')),
) -> BatchNoUpdateResponse:
    """更新单条记录（订单或备货）的批次号，可选同步同批次其他订单。

    Args:
        record_id: 记录 ID（订单或备货，按 data.record_type 决定落到哪张表）。
        data: 批次号更新请求体（含 batch_no / sync_same_batch / record_type）。
        db: 读写数据库会话。
        user: 当前操作用户。

    Returns:
        BatchNoUpdateResponse: 更新结果（含受影响行数）。

    Raises:
        HTTPException: 记录不存在或批次号非法时由 db_transaction 转换抛出。
    """
    async with db_transaction(db):
        if data.record_type == 'stockin':
            result = await order_batch_service.update_stockin_batch_no(
                db, stockin_id=record_id, batch_no=data.batch_no, user=user,
            )
        else:
            result = await order_batch_service.update_batch_no(
                db, order_id=record_id, batch_no=data.batch_no, sync_same_batch=data.sync_same_batch, user=user,
            )
    return BatchNoUpdateResponse(success=True, message='批次号更新成功', updated_count=result['updated_count'])


@router.post('/orders/batch-assign', response_model=BatchAssignResponse)
async def batch_assign_orders(
    data: BatchAssignRequest,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_any_permission('batch_manage', 'order_manage')),
) -> BatchAssignResponse:
    """批量给多个订单设置同一个批次号。

    Args:
        data: 批量分配请求体（含 order_ids 列表与 batch_no）。
        db: 读写数据库会话。
        user: 当前操作用户。

    Returns:
        BatchAssignResponse: 分配结果（含受影响订单数）。
    """
    async with db_transaction(db):
        result = await order_batch_service.batch_assign(
            db, order_ids=data.order_ids, batch_no=data.batch_no, user=user,
        )
    return BatchAssignResponse(success=True, message='批次号设置成功', updated_count=result['updated_count'])


@router.post('/batch/complete', response_model=BatchCompleteResponse)
async def complete_batch(
    data: BatchCompleteRequest,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_any_permission('batch_manage', 'order_manage')),
) -> BatchCompleteResponse:
    """完成指定批次，将批次内「已出货」订单与该批次备货归档。

    Args:
        data: 批次完成请求体（含 batch_no）。
        db: 读写数据库会话。
        user: 当前操作用户。

    Returns:
        BatchCompleteResponse: 归档结果（含订单/备货成功数与失败订单列表）。
    """
    async with db_transaction(db):
        result = await order_batch_service.complete_batch(db, batch_no=data.batch_no, user=user)
    return BatchCompleteResponse(
        success=True,
        message=f"批次完成，{result['completed_count']}个订单、{result.get('completed_stockins', 0)}条备货已归档",
        completed_count=result['completed_count'],
        completed_stockins=result.get('completed_stockins', 0),
        failed_orders=result['failed_orders'],
    )


@router.get('/history', response_model=OrderBatchListResponse)
async def list_batch_history(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    batch_no: str | None = Query(None),
    customer: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    db: AsyncSession = Depends(get_async_read_db),
    _current_user: User = Depends(require_any_permission('batch_manage', 'order_manage')),
) -> OrderBatchListResponse:
    """分页查询历史批次记录（已归档的批次）。

    Args:
        page: 页码，从 1 开始。
        per_page: 每页条数，1-500。
        batch_no: 批次号过滤。
        customer: 客户名称过滤。
        date_from: 起始日期（字符串，如 '2024-01-01'）。
        date_to: 截止日期（字符串）。
        db: 只读数据库会话。
        _current_user: 当前操作用户（用于权限校验）。

    Returns:
        OrderBatchListResponse: 历史批次分页响应。
    """
    result = await order_batch_service.get_batch_history(
        db, page=page, per_page=per_page, batch_no=batch_no, customer=customer, date_from=date_from, date_to=date_to,
    )
    return OrderBatchListResponse(data=result['items'], total=result['total'], page=page, per_page=per_page)


@router.get('/whitelist', response_model=WhitelistResponse)
async def get_whitelist(
    db: AsyncSession = Depends(get_async_read_db),
    _current_user: User = Depends(require_any_permission('batch_manage', 'order_manage')),
) -> WhitelistResponse:
    """获取批次管理客户白名单。

    Args:
        db: 只读数据库会话。
        _current_user: 当前操作用户（用于权限校验）。

    Returns:
        WhitelistResponse: 白名单客户列表。
    """
    customers = await order_batch_service.get_whitelist(db)
    return WhitelistResponse(customers=customers)


@router.put('/whitelist', response_model=WhitelistResponse)
async def update_whitelist(
    data: WhitelistResponse,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_any_permission('batch_manage', 'order_manage')),
) -> WhitelistResponse:
    """更新批次管理客户白名单（全量覆盖）。

    Args:
        data: 白名单更新请求体（含完整客户列表）。
        db: 读写数据库会话。
        user: 当前操作用户。

    Returns:
        WhitelistResponse: 更新后的白名单。
    """
    async with db_transaction(db):
        await order_batch_service.set_whitelist(db, data.customers, user.id)
    return WhitelistResponse(customers=data.customers)
