"""
采购中心 — 采购订单 CRUD 路由

提供采购订单的创建、查询、更新、删除、完成、批量操作、
一键生成、导出、汇总及打印等 HTTP 端点。
"""
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.exc import DisconnectionError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.purchase_center.schemas import (
    BatchCompleteRequest,
    ExportCompletedRequest,
    FactorySummarySaveRequest,
    OneClickGenerateRequest,
    OrderIdRequest,
    OrderIdsAltRequest,
    OrderIdsRequest,
    PurchaseOrderCreateRequest,
    PurchaseOrderUpdateRequest,
)
from fastapi_app.core.cache import invalidate_cache
from fastapi_app.core.database import get_async_db as get_db
from fastapi_app.core.database import get_async_read_db as get_read_db
from fastapi_app.core.deps import require_any_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.logger import logger
from fastapi_app.core.response import success_response
from fastapi_app.schemas.purchase_center import (
    ActionResponse,
    PurchaseOrderActionResponse,
    PurchaseOrderDetailResponse,
    PurchaseOrderListResponse,
    QuickFilterResponse,
    SuggestionResponse,
    SupplierOrderSummaryResponse,
    SupplierSummaryResponse,
    UnprocessedOrdersResponse,
)
from fastapi_app.services import purchase_center_service as svc

router = APIRouter()


async def _invalidate_orders_cache() -> None:
    """失效采购订单列表 + 湖北订单（beile）列表/计数缓存（L1 + L2）。

    - 失效 get_purchase_orders 的缓存（key_prefix='orders'，key 以 'p' 开头）。
    - 失效湖北订单页（/beile-order）的列表与计数缓存（`orders:beile:*`）：
      采购侧「下单完成 / 批量完成 / 汇总保存 / 增删改」后 beile 页需**写入即失效**，
      否则会读到最长 60s TTL 的旧数量与旧门控状态（PRD P1-1 / AC-10）。
    - 不影响 get_unprocessed_orders 的缓存（key_prefix='orders:unprocessed'），
      因为未处理列表只与客户订单/StockIn 状态相关。
    """
    try:
        await invalidate_cache('orders:p*')
        await invalidate_cache('orders:beile:*')
    except (OSError, ValueError):
        logger.warning('缓存失效失败(order_routes)', exc_info=True)


async def _invalidate_unprocessed_cache() -> None:
    """失效未处理订单列表缓存（L1 + L2）。

    供客户订单状态变更等场景调用，采购订单写操作不应调用此函数。
    P-6 后 get_unprocessed_orders 使用 NOT EXISTS 子查询实时过滤，
    不再依赖 po:processed_ids 缓存，仅失效列表缓存即可。
    """
    try:
        await invalidate_cache('orders:unprocessed:*')
    except (OSError, ValueError):
        logger.warning('缓存失效失败(unprocessed)', exc_info=True)


@router.post('/orders')
async def api_create_purchase_order(
    data: PurchaseOrderCreateRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
) -> dict[str, Any]:
    """创建采购订单。

    Args:
        data: 采购订单创建请求数据。
        db: 异步数据库会话。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和订单数据的字典。

    Raises:
        HTTPException 500: 创建订单失败。
    """
    try:
        async with db_transaction(db):
            result = await svc.create_purchase_order(db, data.model_dump(), include_summary=False, _auto_commit=False)
        await _invalidate_orders_cache()
        # 手动创建的 PO 可能设置 source_order_ids，需失效未处理列表 + processed_ids 缓存
        await _invalidate_unprocessed_cache()
        return success_response(**result)
    except RuntimeError as e:
        logger.exception('创建采购订单失败')
        raise HTTPException(status_code=500, detail='创建订单失败，请稍后重试') from e


@router.post('/orders/one-click-generate', response_model=PurchaseOrderActionResponse)
async def api_one_click_generate_order(
    data: OneClickGenerateRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
    x_idempotency_key: str | None = Header(None, alias='X-Idempotency-Key', max_length=64),
) -> dict[str, Any]:
    """一键审核并生成采购订单。

    接收可选的 X-Idempotency-Key 请求头。同键的请求在 10 分钟内会复用上次结果，
    避免前端重试 / 网络重发导致的重复创建。

    唯一约束 uq_po_pending_dedup 是数据库层的最后防线。并发命中该约束时
    由服务层用 savepoint 回滚本段写入并回查已有 pending 单，以幂等方式返回。
    事务边界遵守 docs/TRANSACTION_BOUNDARY_GUIDE.md：端点层不做 commit/rollback。

    Args:
        data: 一键生成请求，包含复合 ID 列表。
        db: 异步数据库会话。
        _current_user: 当前登录用户（权限校验依赖）。
        x_idempotency_key: 幂等键，同键请求复用结果。

    Returns:
        dict[str, Any]: 包含 success 标志、创建数量及订单列表的字典。

    Raises:
        HTTPException 400: 业务校验失败。
        HTTPException 500: 生成采购订单失败。
    """
    def _value_error_to_http(exc: Exception) -> HTTPException:
        return HTTPException(status_code=400, detail=str(exc))

    def _error_to_http(exc: Exception) -> HTTPException:
        logger.exception('一键生成采购订单失败')
        return HTTPException(status_code=500, detail='生成采购订单失败，请稍后重试')

    async with db_transaction(db, error_map={
        ValueError: _value_error_to_http,
        (SQLAlchemyError, RuntimeError): _error_to_http,
    }):
        result = await svc.generate_purchase_orders_from_customer_orders(
            db, data.composite_ids, idempotency_key=x_idempotency_key or '',
        )
    await _invalidate_orders_cache()
    # 一键生成会将客户订单状态从'待备货'改为'已备货'，需同时失效未处理列表缓存
    await _invalidate_unprocessed_cache()
    return success_response(**result)


@router.get('/orders', response_model=PurchaseOrderListResponse)
async def api_get_purchase_orders(
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(20, ge=1, le=500, description='每页数量'),
    status: str = Query('', max_length=50, description='状态筛选'),
    keyword: str = Query('', max_length=100, description='搜索关键词'),
    date_from: str = Query('', max_length=20, description='起始日期'),
    date_to: str = Query('', max_length=20, description='结束日期'),
    supplier_id: int | None = Query(None, description='供应商 ID'),
    sort_by: str = Query('create_time', description='排序字段'),
    sort_order: str = Query('desc', description='排序方向: asc/desc'),
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
) -> dict[str, Any]:
    """获取采购订单列表（分页 + 搜索 + 排序）。

    Args:
        page: 页码，从 1 开始。
        per_page: 每页数量。
        status: 状态筛选。
        keyword: 搜索关键词。
        date_from: 起始日期。
        date_to: 结束日期。
        supplier_id: 供应商 ID 筛选。
        sort_by: 排序字段。
        sort_order: 排序方向，asc 或 desc。
        db: 异步数据库会话（只读副本）。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和订单列表的字典。
    """
    result = await svc.get_purchase_orders(
        db, page=page, per_page=per_page, status=status, keyword=keyword,
        date_from=date_from, date_to=date_to, supplier_id=supplier_id,
        sort_by=sort_by, sort_order=sort_order,
    )
    return success_response(**result)


@router.get('/orders/completed', response_model=PurchaseOrderListResponse)
async def api_get_completed_purchase_orders(
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(20, ge=1, le=500, description='每页数量'),
    keyword: str = Query('', max_length=100, description='搜索关键词（兼容字段，模糊匹配订单号/客户/供应商）'),
    date_from: str = Query('', max_length=20, description='起始日期（兼容字段，建议用 start_date）'),
    date_to: str = Query('', max_length=20, description='结束日期（兼容字段，建议用 end_date）'),
    order_no: str = Query('', max_length=100, description='订单号筛选'),
    customer_name: str = Query('', max_length=100, description='客户名称筛选'),
    product_name: str = Query('', max_length=200, description='产品名称筛选'),
    supplier_name: str = Query('', max_length=100, description='供应商名称筛选'),
    barcode: str = Query('', max_length=50, description='产品条码(69码)筛选'),
    material_name: str = Query('', max_length=100, description='物料名称筛选'),
    start_date: str = Query('', max_length=20, description='起始日期'),
    end_date: str = Query('', max_length=20, description='结束日期'),
    supplier_id: int | None = Query(None, description='供应商 ID'),
    quick_filter: str = Query('', description='快捷筛选'),
    is_arrived: str = Query('', description='是否到货'),
    sort_by: str = Query('completed_at', description='排序字段'),
    sort_order: str = Query('desc', description='排序方向: asc/desc'),
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
) -> dict[str, Any]:
    """获取已完成采购订单列表。

    Args:
        page: 页码，从 1 开始。
        per_page: 每页数量。
        keyword: 搜索关键词（兼容字段）。
        date_from: 起始日期（兼容字段，建议用 start_date）。
        date_to: 结束日期（兼容字段，建议用 end_date）。
        order_no: 订单号筛选。
        customer_name: 客户名称筛选。
        product_name: 产品名称筛选。
        supplier_name: 供应商名称筛选。
        barcode: 产品条码(69码)筛选。
        material_name: 物料名称筛选。
        start_date: 起始日期。
        end_date: 结束日期。
        supplier_id: 供应商 ID 筛选。
        quick_filter: 快捷筛选条件。
        is_arrived: 是否到货筛选。
        sort_by: 排序字段。
        sort_order: 排序方向，asc 或 desc。
        db: 异步数据库会话（只读副本）。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和已完成订单列表的字典。
    """
    result = await svc.get_completed_purchase_orders(
        db, page=page, per_page=per_page, keyword=keyword, date_from=date_from,
        date_to=date_to, supplier_id=supplier_id, quick_filter=quick_filter,
        is_arrived=is_arrived, sort_by=sort_by, sort_order=sort_order,
        order_no=order_no, customer_name=customer_name,
        product_name=product_name, supplier_name=supplier_name,
        barcode=barcode, material_name=material_name,
        start_date=start_date, end_date=end_date,
    )
    return success_response(**result)


@router.post('/orders/completed/export')
async def api_export_completed_orders(
    data: ExportCompletedRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
) -> dict[str, Any]:
    """导出已完成订单数据。

    Args:
        data: 导出请求，包含筛选条件。
        db: 异步数据库会话。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和 rows 数据的字典。
    """
    rows = await svc.export_completed_orders(db, **data.model_dump(exclude_none=True))
    return success_response(rows=rows)


@router.get('/orders/completed/suggestions', response_model=SuggestionResponse)
async def api_get_completed_order_suggestions(
    q: str = Query('', description='搜索关键词'),
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
) -> dict[str, Any]:
    """获取已完成订单的搜索建议。

    Args:
        q: 搜索关键词。
        db: 异步数据库会话（只读副本）。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和 suggestions 列表的字典。
    """
    suggestions = await svc.get_completed_order_suggestions(db, q)
    return success_response(suggestions=suggestions)


@router.get('/orders/completed/quick-filters', response_model=QuickFilterResponse)
async def api_get_completed_order_quick_filters(
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
) -> dict[str, Any]:
    """获取已完成订单的快捷筛选标签及计数。

    Args:
        db: 异步数据库会话（只读副本）。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和 quick_filters 字典的字典。
    """
    quick_filters = await svc.get_completed_order_quick_filters(db)
    return success_response(quick_filters=quick_filters)


@router.get('/orders/{order_id}', response_model=PurchaseOrderDetailResponse)
async def api_get_purchase_order(
    order_id: int,
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
) -> dict[str, Any]:
    """获取采购订单详情。

    Args:
        order_id: 订单 ID。
        db: 异步数据库会话（只读副本）。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和 order 详情的字典。

    Raises:
        HTTPException 404: 订单不存在。
    """
    result = await svc.get_purchase_order(db, order_id)
    if not result:
        raise HTTPException(status_code=404, detail='订单不存在')
    return success_response(order=result)


@router.put('/orders/{order_id}', response_model=PurchaseOrderDetailResponse)
async def api_update_purchase_order(
    order_id: int,
    data: PurchaseOrderUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
) -> dict[str, Any]:
    """更新采购订单。

    Args:
        order_id: 订单 ID。
        data: 订单更新数据。
        db: 异步数据库会话。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和 order 详情的字典。

    Raises:
        HTTPException 404: 订单不存在。
    """
    async with db_transaction(db):
        result = await svc.update_purchase_order(db, order_id, data.model_dump(exclude_unset=True), _current_user.username)
    if not result:
        raise HTTPException(status_code=404, detail='订单不存在')
    await _invalidate_orders_cache()
    # 更新可能修改 source_order_ids，需失效未处理列表 + processed_ids 缓存
    await _invalidate_unprocessed_cache()
    return success_response(order=result)


@router.delete('/orders/{order_id}')
async def api_delete_purchase_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
) -> dict[str, Any]:
    """删除采购订单。

    Args:
        order_id: 订单 ID。
        db: 异步数据库会话。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和 message 的字典。

    Raises:
        HTTPException 404: 订单不存在。
    """
    async with db_transaction(db):
        result = await svc.delete_purchase_order(db, order_id)
    if not result:
        raise HTTPException(status_code=404, detail='订单不存在')
    await _invalidate_orders_cache()
    # 删除 PO 后，其 source_order_ids 中的订单应重新出现在未处理列表
    await _invalidate_unprocessed_cache()
    return success_response(message=result)


@router.post('/orders/complete')
async def api_complete_purchase_order(
    data: OrderIdRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
) -> dict[str, Any]:
    """完成采购订单。

    Args:
        data: 完成请求，包含订单 ID。
        db: 异步数据库会话。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和完成结果的字典。

    Raises:
        HTTPException 404: 订单不存在（服务层返回 400 时转为 404）。
        HTTPException 500: 完成订单失败。
    """
    try:
        async with db_transaction(db):
            result = await svc.complete_purchase_order(
                db, data.order_id, _current_user.username, data.spare_rate,
            )
    except HTTPException as e:
        if e.status_code == 400:
            raise HTTPException(status_code=404, detail=e.detail) from e
        raise
    except RuntimeError as e:
        logger.exception('完成订单失败: order_id=%s', data.order_id)
        raise HTTPException(status_code=500, detail='完成订单失败，请稍后重试') from e
    await _invalidate_orders_cache()
    return success_response(**result)


@router.post('/orders/batch-complete')
async def api_batch_complete_purchase_orders(
    data: BatchCompleteRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
) -> dict[str, Any]:
    """批量完成采购订单。

    Args:
        data: 批量完成请求，包含订单 ID 列表。
        db: 异步数据库会话。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和批量完成结果的字典。

    Raises:
        HTTPException 500: 完成订单失败。
    """
    try:
        async with db_transaction(db):
            result = await svc.batch_complete_purchase_orders(
                db, data.ids, _current_user.username, data.spare_rate,
            )
        await _invalidate_orders_cache()
        return success_response(**result)
    except RuntimeError as e:
        logger.exception('批量完成订单失败')
        raise HTTPException(status_code=500, detail='完成订单失败，请稍后重试') from e


@router.post('/orders/batch-delete', response_model=ActionResponse)
async def api_batch_delete_purchase_orders(
    data: OrderIdsAltRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
) -> dict[str, Any]:
    """批量删除采购订单。

    Args:
        data: 批量删除请求，包含订单 ID 列表。
        db: 异步数据库会话。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和批量删除结果的字典。
    """
    async with db_transaction(db):
        result = await svc.batch_delete_purchase_orders(db, data.order_ids)
    await _invalidate_orders_cache()
    # 删除 PO 后，其 source_order_ids 中的订单应重新出现在未处理列表
    await _invalidate_unprocessed_cache()
    return success_response(**result)


@router.post('/orders/batch-print', response_model=PurchaseOrderActionResponse)
async def api_get_orders_batch_print_data(
    data: OrderIdsRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
) -> dict[str, Any]:
    """批量获取采购订单打印数据。

    Args:
        data: 批量打印请求，包含订单 ID 列表。
        db: 异步数据库会话。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和 orders 列表的字典。
    """
    orders = await svc.get_purchase_orders_with_items(db, data.ids)
    return success_response(orders=[o.to_dict() for o in orders])


@router.get('/unprocessed-orders', response_model=UnprocessedOrdersResponse)
async def api_get_unprocessed_orders(
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(15, ge=1, le=500, description='每页数量'),
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
) -> dict[str, Any]:
    """获取未处理订单列表。

    Args:
        page: 页码，从 1 开始。
        per_page: 每页数量。
        db: 异步数据库会话（只读副本）。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和未处理订单列表的字典。
    """
    result = await svc.get_unprocessed_orders(db, page=page, per_page=per_page)
    return success_response(**result)


@router.post('/orders/factory-summary')
async def api_get_factory_order_summary(
    data: OrderIdsRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
) -> dict[str, Any]:
    """获取工厂订单汇总。

    Args:
        data: 汇总请求，包含订单 ID 列表。
        db: 异步数据库会话。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和汇总数据的字典。

    Raises:
        HTTPException 500: 操作失败。
    """
    try:
        result = await svc.get_factory_order_summary(db, data.ids)
        return success_response(**result)
    except (OperationalError, DisconnectionError, ValueError, RuntimeError) as e:
        logger.exception('获取工厂订单汇总失败')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e


@router.post('/orders/factory-summary/save')
async def api_save_factory_summary_edits(
    data: FactorySummarySaveRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
) -> dict[str, Any]:
    """保存工厂订单汇总编辑。

    Args:
        data: 保存请求，包含编辑列表。
        db: 异步数据库会话。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和保存结果的字典。

    Raises:
        HTTPException 422: 请求无任何可落库内容（既无编辑项，也无「损耗率 + 目标采购单」组合）。
        HTTPException 500: 操作失败。
    """
    # 契约护栏（FIX-5 收紧）：
    # `edits` 放宽为可空是为支持「仅改损耗率也要落库」（PRD Q1）——该路径前端恒发
    # edits=[] + spare_rate + order_ids（见 useSummaryModal.sendLossRate）。除此之外：
    #   - 仅 `{order_ids:[...]}`（有目标无内容）：无 edit 也无 rate，不会产生任何写入；
    #   - 仅 `{spare_rate:...}`（无目标订单）：后端无从定位要写入的采购单；
    # 两者都是「无可保存内容」，必须 422 而非静默 200（否则客户端以为已落库）。
    # 判据：存在可落库内容 ⇔ edits 非空，或（order_ids 非空 且 spare_rate 非 None）。
    #
    # ⚠️ 「edits 非空」必须理解为**存在真正可落库的编辑项**，而非列表长度 > 0：
    #   服务层对每个条目有 `if not item_ids or new_quantity is None: continue` 的跳过逻辑
    #   （purchase_order_crud.apply_factory_summary_edits），因此 `edits=[{}]`、
    #   `edits=[{'item_ids': []}]`、`edits=[{'quantity': None}]` 都会**零写入却返回 200**，
    #   正是本护栏要消灭的「静默成功」。故此处按服务层同一判据过滤后再判空。
    effective_edits = [e for e in data.edits if e.item_ids and e.quantity is not None]
    has_content = bool(effective_edits) or (bool(data.order_ids) and data.spare_rate is not None)
    if not has_content:
        raise HTTPException(status_code=422, detail='无可保存内容')
    try:
        async with db_transaction(db):
            result = await svc.save_factory_summary_edits(
                db, [e.model_dump() for e in data.edits], _current_user.username,
                data.spare_rate, data.order_ids,
            )
        # 保存会写损耗率/备品（影响 beile 页数量与门控），写入即失效
        await _invalidate_orders_cache()
        return success_response(**result)
    except RuntimeError as e:
        logger.exception('保存工厂订单编辑失败')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e


@router.post('/orders/supplier-summary', response_model=SupplierOrderSummaryResponse)
async def api_get_supplier_order_summary(
    data: OrderIdsRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
) -> dict[str, Any]:
    """获取供应商订单汇总。

    Args:
        data: 汇总请求，包含订单 ID 列表。
        db: 异步数据库会话。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和供应商订单汇总的字典。

    Raises:
        HTTPException 500: 操作失败。
    """
    try:
        result = await svc.get_supplier_order_summary(db, data.ids)
        return success_response(**result)
    except (OperationalError, DisconnectionError, ValueError, RuntimeError) as e:
        logger.exception('获取供应商订单汇总失败')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e


@router.post('/orders/supplier-summary-by-vendor', response_model=SupplierSummaryResponse)
async def api_get_supplier_summary_by_vendor(
    data: OrderIdsRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_any_permission('product_manage', 'purchase_center_manage')),
) -> dict[str, Any]:
    """按供应商汇总订单。

    Args:
        data: 汇总请求，包含订单 ID 列表。
        db: 异步数据库会话。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志、供应商列表及计数的字典。

    Raises:
        HTTPException 500: 操作失败。
    """
    try:
        sorted_suppliers = await svc.query_supplier_groups(db)
        return success_response(
            suppliers=sorted_suppliers,
            supplier_count=len(sorted_suppliers),
            order_count=len(data.ids),
        )
    except (OperationalError, DisconnectionError, ValueError, RuntimeError) as e:
        logger.exception('按供应商汇总失败')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e
