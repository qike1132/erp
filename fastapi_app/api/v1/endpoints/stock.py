"""
库存管理 API 端点

职责：
- 提供入库、出库的增删改查接口
- 提供库存查看（按客户/产品/国家筛选）与导出（含「库存」结余列）
- 提供库存统计数据（订单数量与备货数量）
"""
import io
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache import cache_result
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_any_permission, require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.limiter import limiter, rate_limit_key
from fastapi_app.schemas.stock import (
    InventoryResponse,
    StockActionResponse,
    StockInCreate,
    StockInUpdate,
    StockListResponse,
    StockOutCreate,
    StockOutUpdate,
)
from fastapi_app.services import stock_service
from fastapi_app.services.stock_inventory_service import get_stockout_records
from fastapi_app.shared_models import StockIn, StockOut, User

logger = logging.getLogger(__name__)
router = APIRouter()

# 导出库存数据的最大条数限制，超过则要求缩小查询范围
MAX_EXPORT_INVENTORY_ROWS = 10000


def _ensure_row_action_permission(user: User, *, is_deduction: bool, action: str) -> None:
    """报表行内操作的权限裁决（出货 / 备货抵扣各自独立）。

    action ∈ {'edit', 'delete'}。抵扣行（stockin_id 非空）认 deduction_*，独立出货
    认 stockout_*；stockout_manage 作为页面级粗锁兜底放行两者（与备货端点
    「manage 或行内子码」同口径）。缺省 fail-closed。
    """
    if user.has_permission('stockout_manage'):
        return
    code = f"{'deduction' if is_deduction else 'stockout'}_{action}"
    if not user.has_permission(code):
        raise HTTPException(status_code=403, detail='权限不足')


@router.get('/in/list', response_model=StockListResponse)
async def list_stockins(
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(50, ge=1, le=500, description='每页数量'),
    customer: str | None = Query(None, description='客户'),
    start_date: str | None = Query(None, description='开始日期'),
    end_date: str | None = Query(None, description='结束日期'),
    db: AsyncSession = Depends(get_async_read_db),
    # 备货写路径（/in/list|create|edit|delete）与 /aux/batch-submit-stockins、
    # /aux/stockin/{id} 同口径：备货是「客户订单」页录入流程的一环，
    # 只认 stockin_manage 会让勾了「客户订单」的人在该页提交备货时 403。
    _user: User = Depends(require_any_permission('stockin_manage', 'order_manage')),
) -> StockListResponse:
    """获取入库列表（支持分页和筛选）。

    Args:
        page: 页码，从 1 开始。
        per_page: 每页数量，1-500。
        customer: 客户名筛选关键字。
        start_date: 开始日期（YYYY-MM-DD）。
        end_date: 结束日期（YYYY-MM-DD）。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        StockListResponse: 包含入库列表和分页信息的响应。
    """
    result = await stock_service.get_stockins(
        db, page=page, per_page=per_page, customer=customer,
        start_date=start_date, end_date=end_date,
    )
    return StockListResponse(
        data=result['items'], total=result['total'],
        page=result['page'], per_page=result['per_page'],
    )


@router.post('/in/create', response_model=StockActionResponse)
async def create_stockin(
    data: StockInCreate,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_any_permission('stockin_manage', 'order_manage')),
) -> StockActionResponse:
    """添加入库记录。

    Args:
        data: 入库创建参数（产品、数量、客户、日期等）。
        db: 异步数据库会话（读写主库）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        StockActionResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        await stock_service.create_stockin(
            db, product_id=data.product_id, quantity=data.quantity,
            customer=data.customer, stockin_date_str=data.stockin_date,
            note=data.note or '', operator_id=_user.id,
        )
    return StockActionResponse(success=True, message='入库添加成功！')


@router.put('/in/edit/{stockin_id}', response_model=StockActionResponse)
async def edit_stockin(
    stockin_id: int,
    data: StockInUpdate,
    db: AsyncSession = Depends(get_async_db),
    # order_edit：报表流水行内编辑（迁移 075，/user「订单流水→编辑」）
    _user: User = Depends(require_any_permission('stockin_manage', 'order_manage', 'order_edit')),
) -> StockActionResponse:
    """编辑入库记录。

    未提供的字段沿用记录原值，实现部分更新语义。

    Args:
        stockin_id: 入库记录 ID。
        data: 入库更新参数（仅包含需要修改的字段）。
        db: 异步数据库会话（读写主库）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        StockActionResponse: 包含成功标志和提示消息的响应。

    Raises:
        HTTPException: 入库记录不存在时抛出 404。
    """
    stockin = await db.get(StockIn, stockin_id)
    if not stockin:
        logger.info('编辑入库失败：stockin_id=%s 不存在', stockin_id)
        raise HTTPException(status_code=404, detail='入库记录不存在')
    quantity = data.quantity if data.quantity is not None else stockin.quantity
    customer = data.customer if data.customer is not None else stockin.customer
    stockin_date = data.stockin_date if data.stockin_date else stockin.stockin_date.strftime('%Y-%m-%d') if stockin.stockin_date else ''
    note = data.note if data.note is not None else stockin.note or ''
    async with db_transaction(db):
        await stock_service.update_stockin(
            db, stockin_id=stockin_id, quantity=quantity, customer=customer,
            stockin_date_str=stockin_date, note=note, operator_id=_user.id,
        )
    return StockActionResponse(success=True, message='入库编辑成功！')


@router.delete('/in/delete/{stockin_id}', response_model=StockActionResponse)
async def delete_stockin(
    stockin_id: int,
    db: AsyncSession = Depends(get_async_db),
    # order_delete：报表流水行内删除（迁移 075，/user「订单流水→删除」）
    _user: User = Depends(require_any_permission('stockin_manage', 'order_manage', 'order_delete')),
) -> StockActionResponse:
    """删除入库记录。

    Args:
        stockin_id: 入库记录 ID。
        db: 异步数据库会话（读写主库）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        StockActionResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        await stock_service.delete_stockin(db, stockin_id, operator_id=_user.id)
    return StockActionResponse(success=True, message='入库删除成功！')


@router.get('/out/list', response_model=StockListResponse)
async def list_stockouts(
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(50, ge=1, le=500, description='每页数量'),
    customer: str | None = Query(None, description='客户'),
    start_date: str | None = Query(None, description='开始日期'),
    end_date: str | None = Query(None, description='结束日期'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('stockout_manage')),
) -> StockListResponse:
    """获取出库列表（仅独立出库，支持分页和筛选）。

    Args:
        page: 页码，从 1 开始。
        per_page: 每页数量，1-500。
        customer: 客户名筛选关键字。
        start_date: 开始日期（YYYY-MM-DD）。
        end_date: 结束日期（YYYY-MM-DD）。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        StockListResponse: 包含出库列表和分页信息的响应。
    """
    result = await stock_service.get_stockouts(
        db, page=page, per_page=per_page, customer=customer,
        start_date=start_date, end_date=end_date,
    )
    return StockListResponse(
        data=result['items'], total=result['total'],
        page=result['page'], per_page=result['per_page'],
    )


@router.post('/out/create', response_model=StockActionResponse)
async def create_stockout(
    data: StockOutCreate,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission('stockout_manage')),
) -> StockActionResponse:
    """添加出库记录。

    Args:
        data: 出库创建参数（产品、数量、客户、日期等）。
        db: 异步数据库会话（读写主库）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        StockActionResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        await stock_service.create_stockout(
            db, product_id=data.product_id, quantity=data.quantity,
            customer=data.customer, stockout_date_str=data.stockout_date,
            note=data.note or '', operator_id=_user.id,
        )
    return StockActionResponse(success=True, message='出库添加成功！')


@router.put('/out/edit/{stockout_id}', response_model=StockActionResponse)
async def edit_stockout(
    stockout_id: int,
    data: StockOutUpdate,
    db: AsyncSession = Depends(get_async_db),
    # 报表流水行内编辑（迁移 079）：独立出货认 stockout_edit，抵扣认 deduction_edit；
    # 具体按行类型在处理器内裁决（见 _ensure_row_action_permission）。
    _user: User = Depends(require_any_permission('stockout_manage', 'stockout_edit', 'deduction_edit')),
) -> StockActionResponse:
    """编辑出库记录（独立出货与备货抵扣均支持）。

    未提供的字段沿用记录原值，实现部分更新语义。抵扣行（stockin_id 非空）的客户
    由订单/备货带出、不允许改；改数量时后端同步调整产品库存、备货可用量并重算订单状态。

    Args:
        stockout_id: 出库记录 ID。
        data: 出库更新参数（仅包含需要修改的字段）。
        db: 异步数据库会话（读写主库）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        StockActionResponse: 包含成功标志和提示消息的响应。

    Raises:
        HTTPException: 出库记录不存在时抛出 404；无对应行内权限时抛出 403。
    """
    stockout = await db.get(StockOut, stockout_id)
    if not stockout:
        logger.info('编辑出库失败：stockout_id=%s 不存在', stockout_id)
        raise HTTPException(status_code=404, detail='出库记录不存在')
    is_deduction = stockout.stockin_id is not None
    _ensure_row_action_permission(_user, is_deduction=is_deduction, action='edit')
    quantity = data.quantity if data.quantity is not None else stockout.quantity
    # 抵扣行的客户由订单/备货带出，忽略前端传入值（改客户会与订单/备货脱钩）
    if is_deduction:
        customer = stockout.customer or ''
    else:
        customer = data.customer if data.customer is not None else stockout.customer or ''
    stockout_date = data.stockout_date if data.stockout_date else stockout.stockout_date.strftime('%Y-%m-%d') if stockout.stockout_date else ''
    note = data.note if data.note is not None else stockout.note or ''
    async with db_transaction(db):
        await stock_service.update_stockout(
            db, stockout_id=stockout_id, new_quantity=quantity, customer=customer,
            stockout_date_str=stockout_date, note=note, operator_id=_user.id,
        )
    return StockActionResponse(success=True, message='出库编辑成功！')


@router.delete('/out/delete/{stockout_id}', response_model=StockActionResponse)
async def delete_stockout(
    stockout_id: int,
    db: AsyncSession = Depends(get_async_db),
    # 报表流水行内删除（迁移 079）：独立出货认 stockout_delete，抵扣认 deduction_delete
    _user: User = Depends(require_any_permission('stockout_manage', 'stockout_delete', 'deduction_delete')),
) -> StockActionResponse:
    """删除出库记录（独立出货与备货抵扣均支持）。

    删除会回补产品库存；抵扣行删除后所属备货可用量随之释放、关联订单状态重算。
    存在未取消退货记录的出货不能删除（已取消的退货会先解除关联再删除，退货记录保留）。

    Args:
        stockout_id: 出库记录 ID。
        db: 异步数据库会话（读写主库）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        StockActionResponse: 包含成功标志和提示消息的响应。

    Raises:
        HTTPException: 出库记录不存在时抛出 404；无对应行内权限时抛出 403。
    """
    stockout = await db.get(StockOut, stockout_id)
    if not stockout:
        logger.info('删除出库失败：stockout_id=%s 不存在', stockout_id)
        raise HTTPException(status_code=404, detail='出库记录不存在')
    _ensure_row_action_permission(_user, is_deduction=stockout.stockin_id is not None, action='delete')
    async with db_transaction(db):
        await stock_service.delete_stockout(db, stockout_id, operator_id=_user.id)
    return StockActionResponse(success=True, message='出库删除成功！')


@router.get('/out/records', response_model=StockListResponse)
async def list_stockout_records(
    kind: str = Query('stockout', pattern='^(stockout|deduction)$', description='stockout=独立出货，deduction=备货抵扣'),
    nos: str = Query('', description='逗号分隔单号（出货=stockout_no，抵扣=order_no）'),
    product: str = Query('', description='产品名（收窄还原范围，避免同单多产品串行）'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_any_permission(
        'stockout_manage', 'stockout_edit', 'stockout_delete', 'deduction_edit', 'deduction_delete',
    )),
) -> StockListResponse:
    """按单号还原出货/抵扣明细行（报表聚合行 → 具体记录，供行内编辑/删除）。

    Args:
        kind: 'stockout' 独立出货（stockin_id IS NULL）或 'deduction' 备货抵扣（按订单号匹配）。
        nos: 逗号分隔的单号；出货为 stockout_no，抵扣为关联订单 order_no。
        product: 产品名；同一订单可能对多个产品分别抵扣，按产品收窄避免还原出他产品的行。
        db: 只读数据库会话。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        StockListResponse: 匹配的明细行（带 id/数量/客户/日期/备注等）。
    """
    items = await get_stockout_records(db, kind=kind, nos=nos, product=product)
    return StockListResponse(data=items, total=len(items), page=1, per_page=len(items))


@router.get('/inventory', response_model=InventoryResponse)
async def inventory(
    customer: str = Query('', description='客户名称筛选'),
    product: str = Query('', description='产品名称筛选'),
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(50, ge=1, le=200, description='每页数量'),
    db: AsyncSession = Depends(get_async_read_db),
    # 库存汇总同时服务「订单列表」(stock_view) 与「备货管理(全部)」(stockin_manage)。
    # stockin_manage 的 is_nav=False，导航里指向本页的只有 stock_view；
    # 只认 stockin_manage 会让按导航勾选权限的用户 403。
    _user: User = Depends(require_any_permission('stockin_manage', 'stock_view')),
) -> InventoryResponse:
    """库存查看（SQL CTE 分页优化版，过滤和分页在数据库层面完成）。

    Args:
        customer: 客户名称筛选关键字。
        product: 产品名称筛选关键字。
        page: 页码，从 1 开始。
        per_page: 每页数量，1-200。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        InventoryResponse: 包含库存数据、汇总统计和分页信息的响应。
    """
    result = await stock_service.get_inventory_paginated(
        db, search_customer=customer, search_product=product,
        page=page, per_page=per_page,
    )
    return InventoryResponse(
        data=result['inventory_data'],
        total_order_quantity=result['total_order_qty'],
        total_stockin_quantity=result['total_stockin_qty'],
        total_stock=result['total_stock'],
        total_available_stock=result['total_available_stock'],
        all_customers=result['all_customers'],
        total_items=result['total_items'],
        page=result['page'],
        per_page=result['per_page'],
    )


def _build_inventory_excel(inventory_data: list, result: dict) -> tuple[bytes, str]:
    """生成库存导出 Excel 文件（在线程中调用）。

    Args:
        inventory_data: 库存明细数据列表。
        result: 包含汇总统计的字典。

    Returns:
        tuple[bytes, str]: (Excel 文件字节流, 文件名)。
    """
    from utils.report_exporter import ReportExporter, generate_filename
    stats = {
        'total_count': len(inventory_data),
        'total_order_quantity': result['total_order_qty'],
        'total_stockin_quantity': result['total_stockin_qty'],
        'total_stock': result['total_stock'],
    }
    exporter = ReportExporter()
    excel_data = exporter.export_inventory_data(inventory_data, stats)
    filename = generate_filename('inventory')
    return (excel_data, filename)


@router.get('/export-inventory')
@limiter.limit("100/minute", key_func=rate_limit_key)  # 内网宽松：导出接口取消严格限流；P0-6(d) 显式绑键
async def export_inventory(
    request: Request,
    customer: str = Query('', description='客户名称筛选'),
    product: str = Query('', description='产品名称筛选'),
    db: AsyncSession = Depends(get_async_read_db),
    # 与 /inventory 同口径：导出的是同一份库存汇总，由「订单列表」页的工具条触发。
    _user: User = Depends(require_any_permission('stockin_manage', 'stock_view')),
) -> StreamingResponse:
    """导出库存数据为 Excel 文件。

    优化：单次 CTE 查询替代双次（原 per_page=1 取总数 + per_page=total 取全量）。
    CTE 的 COUNT(*) OVER() 窗口函数返回真实总数，无需单独预查询。

    Args:
        customer: 客户名称筛选关键字。
        product: 产品名称筛选关键字。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        StreamingResponse: Excel 文件流响应。

    Raises:
        HTTPException: 数据量超过限制时抛出 400。
    """
    import asyncio

    # 单次查询：CTE 的 COUNT(*) OVER() 窗口函数返回真实总数，
    # LIMIT 截断行数但窗口函数仍计算全量总数，避免双次 CTE 计算
    result = await stock_service.get_inventory_paginated(
        db, search_customer=customer, search_product=product,
        page=1, per_page=MAX_EXPORT_INVENTORY_ROWS,
    )
    total_items = result.get('total_items', 0)
    if total_items > MAX_EXPORT_INVENTORY_ROWS:
        raise HTTPException(
            status_code=400,
            detail=f'数据量过大({total_items}条)，请缩小查询范围后重试',
        )

    inventory_data = result['inventory_data']

    # 在线程中生成 Excel，避免阻塞事件循环
    excel_data, filename = await asyncio.to_thread(_build_inventory_excel, inventory_data, result)
    buffer = io.BytesIO(excel_data)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


class StockStatsData(BaseModel):
    """库存统计数据模型"""
    order_quantity: int = 0   # 订单数量
    stockin_quantity: int = 0  # 备货数量


class StockStatsResponse(BaseModel):
    """库存统计响应模型"""
    success: bool = True
    data: StockStatsData = StockStatsData()


@cache_result(key_prefix="stock:stats", ttl=60, local_ttl=30,
              key_builder=lambda *args, **kwargs: "global")
async def _fetch_stock_stats(db: AsyncSession) -> dict:
    """库存统计数据（60s 缓存）：3 个全量聚合查询，数据变更频率低。"""
    return await stock_service.get_stock_overview_stats(db)


@router.get('/stats', response_model=StockStatsResponse)
async def get_stock_stats(
    # 与同文件其它库存端点同口径。原先只依赖 get_current_user_id（登录即可），
    # 任何通过认证但无库存权限的用户都能读到订单/备货聚合值。
    _user: User = Depends(require_any_permission('stockin_manage', 'order_manage')),
    db: AsyncSession = Depends(get_async_read_db),
) -> StockStatsResponse:
    """库存统计数据：订单数量与备货数量。

    与 /stock 页面 inventory 数据口径一致。60s 缓存降低 DB 压力。

    Args:
        user_id: 当前用户 ID（由依赖注入提供）。
        db: 异步数据库会话（只读副本）。

    Returns:
        StockStatsResponse: 包含订单和备货数量统计的响应。
    """
    data = await _fetch_stock_stats(db)
    return StockStatsResponse(
        success=True,
        data=StockStatsData(**data),
    )
