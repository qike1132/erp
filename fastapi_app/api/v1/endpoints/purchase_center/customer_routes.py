"""
采购中心 — 客户管理相关路由

提供采购中心模块下的客户列表、同步、批量查询、统计及详情等 HTTP 端点。
"""
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import DisconnectionError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.purchase_center.schemas import (
    CustomerBatchRequest,
    CustomerSyncRequest,
)
from fastapi_app.core.database import get_async_db as get_db
from fastapi_app.core.database import get_async_read_db as get_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.schemas.purchase_center import CustomerStatisticsResponse
from fastapi_app.services import purchase_center_service as svc

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/customers")
async def api_get_customers(
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(20, ge=1, le=100, description='每页数量'),
    status: str = Query('all', description='状态筛选: all/active/inactive'),
    keyword: str = Query('', max_length=100, description='搜索关键词'),
    sort_by: str = Query('name', description='排序字段'),
    sort_order: str = Query('asc', description='排序方向: asc/desc'),
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_permission("product_manage")),
) -> dict[str, Any]:
    """获取采购中心客户列表（分页 + 搜索 + 排序）。

    Args:
        page: 页码，从 1 开始。
        per_page: 每页数量，1-100。
        status: 状态筛选，可选 all/active/inactive。
        keyword: 搜索关键词。
        sort_by: 排序字段。
        sort_order: 排序方向，asc 或 desc。
        db: 异步数据库会话（只读副本）。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和客户列表的字典。

    Raises:
        HTTPException 500: 数据库操作异常。
    """
    try:
        result = await svc.get_customers(
            db, page=page, per_page=min(per_page, 100), status=status,
            keyword=keyword, sort_by=sort_by, sort_order=sort_order,
        )
        return {'success': True, **result}
    except (OperationalError, DisconnectionError, SQLAlchemyError) as e:
        logger.exception('获取客户列表失败')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e


@router.post("/customers/sync")
async def api_sync_customers(
    data: CustomerSyncRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_permission("product_manage")),
) -> dict[str, Any]:
    """同步客户数据。

    可按 customer_ids 批量同步，不指定则同步全部客户。

    Args:
        data: 客户同步请求，包含可选的 customer_ids 列表。
        db: 异步数据库会话。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志、同步数量及详情的字典。

    Raises:
        HTTPException 500: 数据库操作异常。
    """
    try:
        customers = await svc.get_customers_for_sync(db, data.customer_ids)
    except (OperationalError, DisconnectionError, SQLAlchemyError) as e:
        logger.exception('同步客户数据失败')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e

    now_str = datetime.now().isoformat()
    # 当前实现为只读快照模式：返回客户完整数据供调用方同步至外部系统。
    # TODO(待业务方明确外部同步目标系统后实现写入逻辑，如更新 sync_time 字段或推送至采购中心服务)
    if data.force:
        # force 参数当前未实现（无写入逻辑），仅记录警告便于排查
        logger.warning('api_sync_customers: force=True 已接收但当前快照模式下未生效')
    details = [
        {
            'id': c.id,
            'customer_code': c.customer_code,
            'name': c.name,
            'contact': c.contact,
            'phone': c.phone,
            'address': c.address,
            'status': 'success',
            'snapshot_time': now_str,
        }
        for c in customers
    ]

    logger.info('采购中心客户快照读取完成: 读取%d条', len(customers))
    return {
        'success': True,
        'message': f'客户快照读取完成: {len(customers)}条（当前为只读快照模式，未写入同步状态）',
        # synced_count 保留以兼容旧调用方；新增 read_count 字段为推荐使用别名
        'synced_count': len(customers),
        'read_count': len(customers),
        'skipped_count': 0,
        'snapshot_mode': True,
        'force_applied': False,  # 显式声明 force 未生效，避免契约误导
        'details': details,
    }


@router.post("/customers/batch")
async def api_batch_get_customers(
    data: CustomerBatchRequest,
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_permission("product_manage")),
) -> dict[str, Any]:
    """批量获取客户信息。

    Args:
        data: 批量查询请求，包含客户 ID 列表。
        db: 异步数据库会话（只读副本）。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和 customers 列表的字典。

    Raises:
        HTTPException 500: 数据库操作异常。
    """
    try:
        customers = await svc.batch_get_customers(db, data.ids)
        return {'success': True, 'customers': customers}
    except (OperationalError, DisconnectionError, SQLAlchemyError) as e:
        logger.exception('批量获取客户失败')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e


@router.get("/customers/statistics", response_model=CustomerStatisticsResponse)
async def api_get_customers_statistics(
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_permission("product_manage")),
) -> dict[str, Any]:
    """获取客户统计数据。

    Args:
        db: 异步数据库会话（只读副本）。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和 statistics 数据的字典。

    Raises:
        HTTPException 500: 数据库操作异常。
    """
    try:
        stats = await svc.get_customers_statistics(db)
        return {'success': True, 'statistics': stats}
    except (OperationalError, DisconnectionError, SQLAlchemyError) as e:
        logger.exception('获取客户统计失败')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e


@router.get("/customers/{customer_id}")
async def api_get_customer_detail(
    customer_id: int,
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_permission("product_manage")),
) -> dict[str, Any]:
    """获取客户详情。

    Args:
        customer_id: 客户 ID。
        db: 异步数据库会话（只读副本）。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和 customer 详情的字典。

    Raises:
        HTTPException 404: 客户不存在。
        HTTPException 500: 数据库操作异常。
    """
    try:
        result = await svc.get_customer_detail(db, customer_id)
    except (OperationalError, DisconnectionError, SQLAlchemyError) as e:
        logger.exception('获取客户详情失败: customer_id=%s', customer_id)
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e
    if not result:
        raise HTTPException(status_code=404, detail="客户不存在")
    return {'success': True, 'customer': result}
