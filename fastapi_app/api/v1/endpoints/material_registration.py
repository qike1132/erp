"""
来料登记 API 端点

职责：
- 提供来料登记的增删改查接口
- 提供采购订单查询、预览和可用列表接口
- 提供物料收货登记接口
- 提供统计概览、趋势、分布和导出接口
- 提供历史记录和搜索联想建议接口
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache import CacheDomain
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_any_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.schemas.material_registration import (
    ActionResponse,
    AvailablePurchaseOrdersResponse,
    ExportRequest,
    MaterialRegistrationCreate,
    MaterialRegistrationUpdate,
    PurchaseOrderItemsResponse,
    ReceiveMaterialRequest,
    RegistrationDetailResponse,
    RegistrationHistoryResponse,
    RegistrationListResponse,
    StatsDistributionResponse,
    StatsOverviewResponse,
    SuggestionsResponse,
    SupplierDetailResponse,
    TrendResponse,
)
from fastapi_app.services import material_registration_service as mr_service
from fastapi_app.services.notification_service import StockEvent, publish_stock_event
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get('/registrations', response_model=RegistrationListResponse)
async def list_registrations(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: str = Query(''),
    order_no: str = Query(''),
    supplier: str = Query(''),
    customer_name: str = Query(''),
    material_category: str = Query(''),
    start_date: str = Query(''),
    end_date: str = Query(''),
    exclude_completed: bool = Query(False),
    user: User = Depends(require_any_permission('product_manage', 'material_registration')),
    db: AsyncSession = Depends(get_async_read_db),
) -> RegistrationListResponse:
    """获取来料登记列表（支持分页和多维度筛选）。

    Args:
        page: 页码，从 1 开始。
        per_page: 每页数量，1-100。
        status: 状态筛选（与 exclude_completed 互斥，status 优先）。
        order_no: 采购订单号筛选。
        supplier: 供应商筛选。
        customer_name: 客户名称筛选。
        material_category: 物料类别筛选。
        start_date: 开始日期（YYYY-MM-DD）。
        end_date: 结束日期（YYYY-MM-DD）。
        exclude_completed: 排除已完成的登记（用于来料进度 tab）。
        user: 当前登录用户（仅需通过权限校验）。
        db: 异步数据库会话（只读副本）。

    Returns:
        RegistrationListResponse: 包含来料登记列表和分页信息的响应。
    """
    return await mr_service.get_registrations(
        db, page, per_page, status, order_no, supplier,
        customer_name, material_category, start_date, end_date,
        exclude_completed,
    )


@router.get('/registrations/{reg_id}', response_model=RegistrationDetailResponse)
async def get_registration(
    reg_id: int,
    user: User = Depends(require_any_permission('product_manage', 'material_registration')),
    db: AsyncSession = Depends(get_async_read_db),
) -> RegistrationDetailResponse:
    """获取来料登记详情。

    Args:
        reg_id: 来料登记 ID。
        user: 当前登录用户（仅需通过权限校验）。
        db: 异步数据库会话（只读副本）。

    Returns:
        RegistrationDetailResponse: 来料登记详情。

    Raises:
        HTTPException: 登记记录不存在时抛出 404。
    """
    try:
        return await mr_service.get_registration(db, reg_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get('/supplier-detail', response_model=SupplierDetailResponse)
async def get_supplier_detail(
    order_no: str = Query(..., min_length=1),
    user: User = Depends(require_any_permission('product_manage', 'material_registration')),
    db: AsyncSession = Depends(get_async_read_db),
) -> SupplierDetailResponse:
    """获取按供应商分组的来料聚合详情（服务端预聚合）。

    查询指定订单号的未完成登记，在服务端按供应商分组、按物料型号合并数量，
    直接返回前端可用的聚合结构，消除客户端 60+ 行同步计算。

    Args:
        order_no: 采购订单号（精确匹配）。
        user: 当前登录用户（仅需通过权限校验）。
        db: 异步数据库会话（只读副本）。

    Returns:
        SupplierDetailResponse: 按供应商分组的聚合详情。
    """
    return await mr_service.get_supplier_detail(db, order_no)


@router.post('/registrations', response_model=RegistrationDetailResponse)
async def create_registration(
    data: MaterialRegistrationCreate,
    user: User = Depends(require_any_permission('product_manage', 'material_registration')),
    db: AsyncSession = Depends(get_async_db),
) -> RegistrationDetailResponse:
    """创建来料登记。

    创建成功后失效物料缓存并发布物料更新通知事件。

    Args:
        data: 来料登记创建参数（采购订单 ID、备注、明细列表）。
        user: 当前登录用户，作为登记创建人。
        db: 异步数据库会话（读写主库）。

    Returns:
        RegistrationDetailResponse: 包含新创建登记详情的响应。

    Raises:
        HTTPException: 数据库异常时抛出 500。
    """
    try:
        async with db_transaction(db):
            result = await mr_service.create_registration(
                db, data.purchase_order_id, user.id, user.username,
                data.remark, [item.model_dump() for item in data.items],
            )
        await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.MATERIAL)
        try:
            await publish_stock_event(
                StockEvent.MATERIAL_UPDATED,
                {'change_type': '来料登记', 'purchase_order_id': data.purchase_order_id},
            )
        except (OSError, ValueError) as e:
            logger.warning('来料登记事件发布失败（不影响数据）: %s', e)
        return RegistrationDetailResponse(registration=result['registration'])
    except ValueError as e:
        msg = str(e)
        status_code = 404 if '不存在' in msg else 400
        raise HTTPException(status_code=status_code, detail=msg) from e
    except SQLAlchemyError as e:
        logger.exception('创建来料登记失败: %s', e)
        raise HTTPException(status_code=500, detail='创建来料登记失败，请稍后重试') from e


@router.put('/registrations/{reg_id}', response_model=RegistrationDetailResponse)
async def update_registration(
    reg_id: int,
    data: MaterialRegistrationUpdate,
    user: User = Depends(require_any_permission('product_manage', 'material_registration')),
    db: AsyncSession = Depends(get_async_db),
) -> RegistrationDetailResponse:
    """更新来料登记。

    更新成功后失效物料缓存并发布物料更新通知事件。

    Args:
        reg_id: 来料登记 ID。
        data: 来料登记更新参数（状态、备注、明细）。
        user: 当前登录用户（仅需通过权限校验）。
        db: 异步数据库会话（读写主库）。

    Returns:
        RegistrationDetailResponse: 包含更新后登记详情的响应。

    Raises:
        HTTPException: 数据库异常时抛出 500。
    """
    try:
        async with db_transaction(db):
            result = await mr_service.update_registration(db, reg_id, data.status, data.remark, data.items)
        await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.MATERIAL)
        try:
            await publish_stock_event(
                StockEvent.MATERIAL_UPDATED,
                {'change_type': '来料登记编辑', 'reg_id': reg_id},
            )
        except (OSError, ValueError) as e:
            logger.warning('来料登记编辑事件发布失败（不影响数据）: %s', e)
        return RegistrationDetailResponse(registration=result['registration'])
    except ValueError as e:
        msg = str(e)
        status_code = 404 if '不存在' in msg else 400
        raise HTTPException(status_code=status_code, detail=msg) from e
    except SQLAlchemyError as e:
        logger.exception('更新来料登记失败: %s', e)
        raise HTTPException(status_code=500, detail='更新来料登记失败，请稍后重试') from e


@router.delete('/registrations/{reg_id}', response_model=ActionResponse)
async def delete_registration(
    reg_id: int,
    user: User = Depends(require_any_permission('product_manage', 'material_registration')),
    db: AsyncSession = Depends(get_async_db),
) -> ActionResponse:
    """删除来料登记。

    删除成功后失效物料缓存并发布物料更新通知事件。

    Args:
        reg_id: 来料登记 ID。
        user: 当前登录用户（仅需通过权限校验）。
        db: 异步数据库会话（读写主库）。

    Returns:
        ActionResponse: 包含提示消息的响应。

    Raises:
        HTTPException: 数据库异常时抛出 500。
    """
    try:
        async with db_transaction(db):
            result = await mr_service.delete_registration(db, reg_id)
        await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.MATERIAL)
        try:
            await publish_stock_event(
                StockEvent.MATERIAL_UPDATED,
                {'change_type': '来料登记删除', 'reg_id': reg_id},
            )
        except (OSError, ValueError) as e:
            logger.warning('来料登记删除事件发布失败（不影响数据）: %s', e)
        return ActionResponse(message=result['message'])
    except ValueError as e:
        msg = str(e)
        status_code = 404 if '不存在' in msg else 400
        raise HTTPException(status_code=status_code, detail=msg) from e
    except SQLAlchemyError as e:
        logger.exception('删除来料登记失败: %s', e)
        raise HTTPException(status_code=500, detail='删除来料登记失败，请稍后重试') from e


@router.get('/purchase-orders/available', response_model=AvailablePurchaseOrdersResponse)
async def available_purchase_orders(
    status: str = Query('pending'),
    user: User = Depends(require_any_permission('product_manage', 'material_registration')),
    db: AsyncSession = Depends(get_async_read_db),
) -> AvailablePurchaseOrdersResponse:
    """获取可用采购订单列表。

    Args:
        status: 采购订单状态筛选，默认 pending。
        user: 当前登录用户（仅需通过权限校验）。
        db: 异步数据库会话（只读副本）。

    Returns:
        AvailablePurchaseOrdersResponse: 包含可用采购订单列表的响应。
    """
    return await mr_service.get_available_purchase_orders(db, status)


@router.get('/stats/overview', response_model=StatsOverviewResponse)
async def stats_overview(
    user: User = Depends(require_any_permission('product_manage', 'material_registration')),
    db: AsyncSession = Depends(get_async_read_db),
) -> StatsOverviewResponse:
    """获取来料登记统计概览。

    Args:
        user: 当前登录用户（仅需通过权限校验）。
        db: 异步数据库会话（只读副本）。

    Returns:
        StatsOverviewResponse: 包含统计概览数据的响应。
    """
    return await mr_service.get_stats_overview(db)


@router.get('/stats/trend', response_model=TrendResponse)
async def stats_trend(
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(require_any_permission('product_manage', 'material_registration')),
    db: AsyncSession = Depends(get_async_read_db),
) -> TrendResponse:
    """获取来料登记趋势数据。

    Args:
        days: 统计天数，1-365，默认 30。
        user: 当前登录用户（仅需通过权限校验）。
        db: 异步数据库会话（只读副本）。

    Returns:
        TrendResponse: 包含趋势数据的响应。
    """
    return await mr_service.get_stats_trend(db, days)


@router.post('/items/{item_id}/receive', response_model=RegistrationDetailResponse)
async def receive_material(
    item_id: int,
    data: ReceiveMaterialRequest,
    user: User = Depends(require_any_permission('product_manage', 'material_registration')),
    db: AsyncSession = Depends(get_async_db),
) -> RegistrationDetailResponse:
    """物料收货登记。

    收货成功后失效物料缓存并发布物料更新通知事件。

    Args:
        item_id: 物料明细 ID。
        data: 收货请求参数（收货数量、备注）。
        user: 当前登录用户（仅需通过权限校验）。
        db: 异步数据库会话（读写主库）。

    Returns:
        RegistrationDetailResponse: 包含更新后登记详情的响应。

    Raises:
        HTTPException: 数据库或运行时异常时抛出 500。
    """
    try:
        async with db_transaction(db):
            result = await mr_service.receive_material(db, item_id, data.received_quantity, data.remark)
        await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.MATERIAL)
        try:
            await publish_stock_event(
                StockEvent.MATERIAL_UPDATED,
                {'change_type': '物料收货', 'item_id': item_id, 'quantity': data.received_quantity},
            )
        except (OSError, ValueError) as e:
            logger.warning('物料收货事件发布失败（不影响数据）: %s', e)
        return RegistrationDetailResponse(registration=result['registration'])
    except ValueError as e:
        msg = str(e)
        status_code = 404 if '不存在' in msg else 400
        raise HTTPException(status_code=status_code, detail=msg) from e
    except (SQLAlchemyError, RuntimeError) as e:
        logger.exception('收货登记失败 item_id=%s: %s', item_id, e)
        raise HTTPException(status_code=500, detail='收货登记失败，请稍后重试') from e


@router.get('/purchase-orders/{order_id}/items', response_model=PurchaseOrderItemsResponse)
async def get_purchase_order_items(
    order_id: int,
    user: User = Depends(require_any_permission('product_manage', 'material_registration')),
    db: AsyncSession = Depends(get_async_read_db),
) -> PurchaseOrderItemsResponse:
    """获取采购订单物料明细。

    Args:
        order_id: 采购订单 ID。
        user: 当前登录用户（仅需通过权限校验）。
        db: 异步数据库会话（只读副本）。

    Returns:
        PurchaseOrderItemsResponse: 包含采购订单物料明细的响应。

    Raises:
        HTTPException: 采购订单不存在时抛出 404。
    """
    try:
        return await mr_service.get_purchase_order_items(db, order_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post('/export')
async def export_registrations(
    data: ExportRequest,
    user: User = Depends(require_any_permission('product_manage', 'material_registration')),
    db: AsyncSession = Depends(get_async_read_db),
) -> StreamingResponse:
    """导出来料登记数据（真 xlsx 文件下载）。

    Args:
        data: 导出筛选参数（POST body）。
        user: 当前登录用户（仅需通过权限校验）。
        db: 异步数据库会话（只读副本）。

    Returns:
        StreamingResponse: xlsx 文件流（含 Content-Disposition 头）。

    Raises:
        HTTPException: 导出失败时抛出 500。
    """
    try:
        buffer = await mr_service.export_registrations(
            db, data.order_no, data.supplier, data.customer_name,
            data.material_category, data.start_date, data.end_date,
        )
    except (ValueError, OSError) as e:
        logger.warning('导出来料登记失败: %s', e)
        raise HTTPException(status_code=500, detail='导出来料登记失败') from e
    return StreamingResponse(
        buffer,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': 'attachment; filename=material_registrations.xlsx'},
    )


@router.get('/history', response_model=RegistrationHistoryResponse)
async def get_history(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    order_no: str = Query(''),
    supplier: str = Query(''),
    customer_name: str = Query(''),
    material_category: str = Query(''),
    start_date: str = Query(''),
    end_date: str = Query(''),
    user: User = Depends(require_any_permission('product_manage', 'material_registration')),
    db: AsyncSession = Depends(get_async_read_db),
) -> RegistrationHistoryResponse:
    """获取来料登记历史记录（支持分页和多维度筛选）。

    Args:
        page: 页码，从 1 开始。
        per_page: 每页数量，1-100。
        order_no: 采购订单号筛选。
        supplier: 供应商筛选。
        customer_name: 客户名称筛选。
        material_category: 物料类别筛选。
        start_date: 开始日期（YYYY-MM-DD）。
        end_date: 结束日期（YYYY-MM-DD）。
        user: 当前登录用户（仅需通过权限校验）。
        db: 异步数据库会话（只读副本）。

    Returns:
        RegistrationHistoryResponse: 包含历史记录和分页信息的响应。
    """
    return await mr_service.get_history(
        db, page, per_page, order_no, supplier, customer_name, material_category, start_date, end_date,
    )


@router.get('/suggestions', response_model=SuggestionsResponse)
async def get_suggestions(
    field: str = Query(''),
    keyword: str = Query(''),
    limit: int = Query(10, ge=1, le=50),
    user: User = Depends(require_any_permission('product_manage', 'material_registration')),
    db: AsyncSession = Depends(get_async_read_db),
) -> SuggestionsResponse:
    """获取搜索联想建议。

    Args:
        field: 搜索字段名。
        keyword: 搜索关键字。
        limit: 返回条数上限，1-50，默认 10。
        user: 当前登录用户（仅需通过权限校验）。
        db: 异步数据库会话（只读副本）。

    Returns:
        SuggestionsResponse: 包含联想建议列表的响应。
    """
    return await mr_service.get_suggestions(db, field, keyword, limit)


@router.get('/stats/distribution', response_model=StatsDistributionResponse)
async def stats_distribution(
    user: User = Depends(require_any_permission('product_manage', 'material_registration')),
    db: AsyncSession = Depends(get_async_read_db),
) -> StatsDistributionResponse:
    """获取来料登记状态分布统计。

    Args:
        user: 当前登录用户（仅需通过权限校验）。
        db: 异步数据库会话（只读副本）。

    Returns:
        StatsDistributionResponse: 包含状态分布数据的响应。
    """
    return await mr_service.get_stats_distribution(db)
