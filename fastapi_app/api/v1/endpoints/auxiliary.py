"""辅助API接口 - 补充产品搜索、库存查询等

健康检查探针统一由 fastapi_app/core/health.py 在 app 层注册
(/api/health、/api/health/live、/api/health/ready)，本模块不再重复提供。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.business_time import fmt_business
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_any_permission, require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.response import success_response
from fastapi_app.schemas.order import OrderItemSchema
from fastapi_app.services.auxiliary_service import (
    count_inventory_logs,
    get_available_stockins,
    get_inventory_logs_page,
    get_product_by_id,
    get_stockin_by_id,
)
from fastapi_app.shared.factory_scope import assert_product_factory_scoped
from fastapi_app.shared_models import Customer, StockIn, StockOut, User


def _factory_scope(user: User) -> str:
    """工厂隔离口径（P0-2）：非超管且绑定工厂时只返回本厂数据，否则空串=不限制。"""
    return user.factory if (user.factory and not user.is_super) else ''


class CacheClearResponse(BaseModel):
    success: bool
    deleted: int = 0
    pattern: str = ''

class ProductSearchItem(BaseModel):
    id: int
    name: str
    barcode: str
    price: float = 0
    current_stock: int = 0

class ProductAvailableStockResponse(BaseModel):
    product_id: int
    name: str
    current_stock: int = 0
    available_stock: int = 0

class InventoryLogItem(BaseModel):
    id: int
    change_type: str = ''
    change_quantity: int = 0
    related_id: int | str | None = None
    note: str | None = None
    change_date: str = ''

class InventoryLogsResponse(BaseModel):
    items: list[InventoryLogItem] = []
    total: int = 0
    page: int = 1
    per_page: int = 50

class AvailableStockinItem(BaseModel):
    id: int
    product_id: int
    product_name: str = ''
    quantity: int = 0
    customer: str = ''
    stockin_date: str = ''
    available: int = 0

class StockinInfoResponse(BaseModel):
    id: int
    product_id: int
    product_name: str = ''
    quantity: int = 0
    customer: str = ''
    stockin_date: str = ''
    note: str = ''

class AvailableShipmentResponse(BaseModel):
    order_quantity: int = 0
    shipped_quantity: int = 0
    available_quantity: int = 0

class AuxActionResponse(BaseModel):
    success: bool
    message: str = ''

class BatchOrderResultItem(BaseModel):
    success: bool
    order_no: str = ''
    id: int | None = None
    customer: str = ''
    items: list[OrderItemSchema] = []
    error: str | None = None

class BatchOrderResponse(BaseModel):
    success: bool
    created_count: int = 0
    results: list[BatchOrderResultItem] = []

class BatchStockinResultItem(BaseModel):
    success: bool
    stockin_no: str = ''
    id: int | str | None = None
    error: str | None = None

class BatchStockinResponse(BaseModel):
    success: bool
    results: list[BatchStockinResultItem] = []

class BatchStockoutResultItem(BaseModel):
    success: bool
    stockout_no: str = ''
    id: int | str | None = None
    error: str | None = None

class BatchStockoutResponse(BaseModel):
    success: bool
    results: list[BatchStockoutResultItem] = []

class SystemStatsResponse(BaseModel):
    cache: dict = {}
    performance: dict = {}

router = APIRouter()


@router.get("/cache/stats", response_model=dict)
async def cache_stats(
    user: User = Depends(require_permission("admin")),
):
    """获取缓存统计信息（需管理员权限）"""
    from fastapi_app.core.redis_wrapper import safe_get_stats
    return await safe_get_stats(context="缓存统计")


@router.post("/cache/clear", response_model=CacheClearResponse)
async def clear_cache(
    pattern: str = Query("*", description="清除匹配的缓存键"),
    user: User = Depends(require_permission("admin")),
):
    """清除缓存（需管理员权限）"""
    from fastapi_app.core.redis_wrapper import safe_delete_pattern
    deleted = await safe_delete_pattern(pattern, context="缓存清除")
    return success_response(deleted=deleted, pattern=pattern)


@router.get("/product-search", response_model=list[ProductSearchItem])
async def product_search(
    q: str = Query('', max_length=100, description="搜索关键词"),
    customer_id: int | None = Query(None, description="只看该客户可见的 SKU（属于该客户或未挂客户）"),
    customer: str | None = Query(None, max_length=100, description="客户名称（与 customer_id 二选一）"),
    limit: int = Query(50, ge=1, le=200, description="返回条数上限（浏览模式一次列一批，搜索时保持小值）"),
    # 产品自动补全被三个页面共用：客户订单(order_manage)、出库管理(stockout_manage)、
    # 出货计划(production_plan_view)。原先只认 product_view（该码不在权限表里，只由
    # product_manage 经 manage→view 继承得来），按导航勾选的用户一律 403。
    user: User = Depends(require_any_permission(
        "product_view", "order_manage", "stockout_manage", "production_plan_view")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """产品搜索（支持名称、条码；可按客户过滤可见范围）

    两种用法：
    - **搜索模式**：带 `q` 关键字，按名称/69码模糊匹配（下单/出货/备货/备货计划的自动补全）。
    - **浏览模式**：`q` 留空 + 带客户 —— 列出该客户可见的全部 SKU（下单页点开 SKU 列表用）。
      留空且**不带客户**时返回空数组：宁可什么都不给，也不要把全部 SKU 放出来，
      前端据此提示「请先选择客户」。

    客户过滤口径见 services/product_visibility.py：**未挂客户的 SKU 对所有客户可见**，
    按客户过滤在下单 / 出货 / 备货 / 备货计划四处共用本端点，故收在此一处。
    """
    from fastapi_app.services.product_search_service import product_search_service

    resolved_customer_id = customer_id
    if resolved_customer_id is None and customer and customer.strip():
        resolved_customer_id = (await db.execute(
            select(Customer.id).where(Customer.name == customer.strip())
        )).scalar()
        if resolved_customer_id is None:
            # 客户名不存在 → 视为无可见 SKU，而不是「不过滤」：
            # 后者会让一个拼错的客户名把全部 SKU 都放出来，与过滤目的相反。
            return []

    keyword = q.strip()
    if not keyword and resolved_customer_id is None:
        return []

    return await product_search_service.search_visible_to_customer_async_with_cache(
        db, keyword, resolved_customer_id, limit=limit)


@router.get("/product-available-stock", response_model=ProductAvailableStockResponse)
async def product_available_stock(
    product_id: int = Query(..., description="产品ID"),
    user: User = Depends(require_permission("product_view")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """获取产品可用库存"""
    product = await get_product_by_id(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="产品不存在")

    return {
        'product_id': product.id,
        'name': product.name,
        'current_stock': product.current_stock,
        'available_stock': product.current_stock,
    }


@router.get("/inventory-logs/{product_id}", response_model=InventoryLogsResponse)
async def get_inventory_logs(
    product_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(require_permission("stock_view")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """获取产品库存日志（分页）"""
    await assert_product_factory_scoped(db, product_id, user, what='库存日志')
    total = await count_inventory_logs(db, product_id)
    logs = await get_inventory_logs_page(db, product_id, page, per_page)

    return {
        'items': [{
            'id': log.id, 'change_type': log.change_type,
            'change_quantity': log.change_quantity,
            'related_id': log.related_id,
            'note': log.note,
            'change_date': fmt_business(log.change_date, '%Y-%m-%d %H:%M:%S') if log.change_date else '',
        } for log in logs],
        'total': total, 'page': page, 'per_page': per_page,
    }


@router.get("/available-stockins", response_model=list[AvailableStockinItem])
async def available_stockins(
    product_id: int | None = Query(None),
    customer: str = Query('', max_length=100),
    limit: int = Query(100, ge=1, le=200),
    # order_edit/stockin_edit：报表流水编辑弹窗的「可用备货量」提示（迁移 075/091）；失败不致命但别让它必然 403
    user: User = Depends(require_any_permission("stock_view", "order_edit", "stockin_edit")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """获取可用入库记录（限制返回数量）"""
    if product_id is not None:
        await assert_product_factory_scoped(db, product_id, user, what='备货记录')
    stockins = await get_available_stockins(db, product_id, customer, limit, factory=_factory_scope(user))

    return [{
        'id': s.id, 'product_id': s.product_id,
        'product_name': s.product.name if s.product else '',
        'quantity': s.quantity, 'customer': s.customer,
        'stockin_date': fmt_business(s.stockin_date, '%Y-%m-%d') if s.stockin_date else '',
        'available': s.quantity - sum(st.quantity for st in s.stockin_stockouts) if s.stockin_stockouts else s.quantity,
    } for s in stockins]


@router.get("/stockin-info/{stockin_id}", response_model=StockinInfoResponse)
async def stockin_info(
    stockin_id: int,
    user: User = Depends(require_permission("stock_view")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """获取入库信息详情"""
    stockin = await get_stockin_by_id(db, stockin_id)
    if not stockin:
        raise HTTPException(status_code=404, detail="入库记录不存在")
    await assert_product_factory_scoped(db, stockin.product_id, user, what='入库记录')

    return {
        'id': stockin.id, 'product_id': stockin.product_id,
        'product_name': stockin.product.name if stockin.product else '',
        'quantity': stockin.quantity, 'customer': stockin.customer,
        'stockin_date': fmt_business(stockin.stockin_date, '%Y-%m-%d') if stockin.stockin_date else '',
        'note': stockin.note or '',
    }


@router.get("/available-shipment", response_model=AvailableShipmentResponse)
async def available_shipment(
    product_id: int | None = Query(None),
    customer: str = Query('', max_length=100),
    user: User = Depends(require_permission("stock_view")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """获取可出货量（按客户+产品维度）。"""
    if not product_id or not customer.strip():
        return {'order_quantity': 0, 'shipped_quantity': 0, 'available_quantity': 0}

    await assert_product_factory_scoped(db, product_id, user, what='可出货量')

    from fastapi_app.services.batch_service import calculate_available_shipment_quantity
    # 本端点会话来自只读副本（get_async_read_db），副本无法执行行锁查询；
    # 这里仅作展示，行锁与超额校验由出货提交事务自身完成
    shipment_info = await calculate_available_shipment_quantity(
        db, product_id, customer, lock_orders=False
    )

    return {
        'order_quantity': shipment_info['order_quantity'],
        'shipped_quantity': shipment_info['shipped_quantity'],
        'available_quantity': shipment_info['available_quantity'],
    }


# ==================== 删除接口 ====================

@router.delete("/stockout/{id}", response_model=AuxActionResponse)
async def delete_stockout_api(
    id: int,
    user: User = Depends(require_permission("stockout_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """删除出库记录（API方式；厂绑定用户先过工厂闸门，2026-10-19 OCR 第四轮 H2）"""
    from fastapi_app.services.stock_service import delete_stockout as svc_delete
    # 工厂闸门（OCR 第四轮 H2）：stock.py 的 /stock/out/delete 与本文件批量
    # 端点均已校验，本端点漏网——厂绑定用户可按 id 跨厂删他厂出货行。
    # 行不存在时 product_id 为 None：必须与「跨厂」同为 404，否则
    # 「不存在→400 / 他厂→404」构成按 id 枚举他厂数据的 oracle（与 stock.py 同口径）。
    _product_id = (await db.execute(
        select(StockOut.product_id).where(StockOut.id == id)
    )).scalar_one_or_none()
    if _product_id is None:
        raise HTTPException(status_code=404, detail='出库记录不存在')
    await assert_product_factory_scoped(db, _product_id, user, what='出库记录')
    async with db_transaction(db, commit=False):
        await svc_delete(db, id)
    return success_response(message='出库删除成功')


@router.delete("/stockin/{id}", response_model=AuxActionResponse)
async def delete_stockin_api(
    id: int,
    user: User = Depends(require_any_permission("stockin_manage", "order_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """删除入库记录（API方式；厂绑定用户先过工厂闸门，2026-10-19 OCR 第四轮 H2）"""
    from fastapi_app.services.stock_service import delete_stockin as svc_delete
    # 工厂闸门（OCR 第四轮 H2）：与 stockout 端点同款漏网，同款修法——
    # 行不存在必须与「跨厂」同为 404（否则 400/404 差异可被用来枚举他厂记录）。
    _product_id = (await db.execute(
        select(StockIn.product_id).where(StockIn.id == id)
    )).scalar_one_or_none()
    if _product_id is None:
        raise HTTPException(status_code=404, detail='入库记录不存在')
    await assert_product_factory_scoped(db, _product_id, user, what='入库记录')
    async with db_transaction(db, commit=False):
        await svc_delete(db, id)
    return success_response(message='入库删除成功')


@router.delete("/customer/{id}", response_model=AuxActionResponse)
async def delete_customer_api(
    id: int,
    user: User = Depends(require_permission("customer_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """删除客户（API方式）"""
    from fastapi_app.services.customer_service import delete_customer as svc_delete
    async with db_transaction(db):
        await svc_delete(db, id)
    return success_response(message='客户删除成功')


@router.delete("/supplier/{id}", response_model=AuxActionResponse)
async def delete_supplier_api(
    id: int,
    # 供应商的写操作应认**本模块**的权限码 supplier_manage（supplier.py 的写端点即用它），
    # 原先误用了 product_manage：授「供应商管理」的用户删不掉，只持 product_manage 的
    # 反而能越模块删。保留 product_manage 以免未知调用方回归（与 staging_order.py 同款写法）。
    user: User = Depends(require_any_permission("supplier_manage", "product_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """删除供应商（API方式）"""
    from fastapi_app.services.auxiliary_service import delete_supplier
    await delete_supplier(db, id)
    return success_response(message='供应商删除成功')


# ==================== 批量提交 Pydantic 模型 ====================

class BatchShipmentPlanSplit(BaseModel):
    """单个出货计划批次（2026-10-06 v2：单订单可拆多批，总和必须排满订单量）"""
    plan_date: str
    quantity: int = Field(..., ge=1, le=9999999)
    note: str = ""

class BatchOrderItem(BaseModel):
    product_id: int = Field(..., gt=0)
    customer: str
    quantity: int = Field(..., gt=0, le=9999999)
    deduct_stock: bool | None = None
    deduct_quantity: int | None = None
    note: str = ""
    order_date: str | None = None
    # 分批出货计划（2026-10-06 v2）：非空时订单创建后同事务写入采购计划明细，
    # 每批一条；批次数与总和校验在 order_batch_create._validate_one_item。
    # max_length 收口极端 payload 的落库放大（内网场景 50 批已远超业务可能）。
    shipment_plans: list[BatchShipmentPlanSplit] = Field(default_factory=list, max_length=50)

class BatchStockInItem(BaseModel):
    product_id: int = Field(..., gt=0)
    customer: str
    quantity: int = Field(..., gt=0, le=9999999)
    note: str = ""
    stockin_date: str | None = None

class BatchStockOutItem(BaseModel):
    product_id: int = Field(..., gt=0)
    customer: str
    quantity: int = Field(..., gt=0, le=9999999)
    note: str = ""
    stockout_date: str | None = None
    batch_no: str | None = Field(None, max_length=100, description="批次号（指定则按该批次扣减成品库存）")

class BatchOrderRequest(BaseModel):
    orders: list[BatchOrderItem]

class BatchStockInRequest(BaseModel):
    stockins: list[BatchStockInItem]

class BatchStockOutRequest(BaseModel):
    stockouts: list[BatchStockOutItem]

# ==================== 批量提交 API ====================

async def _factory_gate_batch_items(
    db: AsyncSession, user: User, items: list, *, reject_message: str,
) -> tuple[list[dict], list[int], list[dict | None]]:
    """批量提交端点的逐项工厂闸门（2026-10-19 OCR 第三轮 H1）。

    单条路径（/stock/in|out/create）已有 assert_product_factory_scoped，但
    /aux/batch-submit-stockins|stockouts 的编排内部无任何工厂校验——厂绑定
    （User.factory 非空）非超管可混入他厂 product_id 批量建备货/出货（越权）。
    本 helper 在编排前逐项执行闸门，**不破坏整批语义**：他厂项标
    success=False + 明确文案留在原下标（前端按下标对位判定部分失败），
    放行项交给编排。

    Returns:
        (放行项的 model_dump 列表, 放行项原始下标列表, 全长度结果占位数组)。
        被拒下标已填 ``{'success': False, 'error': ...}``，放行下标为 None
        待编排结果回填。未绑定厂/超管用户闸门内部直接放行，零额外查询。
    """
    allowed: list[dict] = []
    slots: list[int] = []
    results: list[dict | None] = [None] * len(items)
    for idx, item in enumerate(items):
        try:
            await assert_product_factory_scoped(db, item.product_id, user, what='库存记录')
        except HTTPException:
            results[idx] = {'success': False, 'error': reject_message}
        else:
            allowed.append(item.model_dump())
            slots.append(idx)
    return allowed, slots, results


@router.post("/batch-submit-orders", response_model=BatchOrderResponse)
async def batch_submit_orders(
    data: BatchOrderRequest,
    user: User = Depends(require_permission("order_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """批量提交订单"""
    from fastapi_app.services.auxiliary_service import orchestrate_batch_orders
    # 工厂隔离：按 spec 要求整批拒绝（库存批量端点是逐项部分成功，口径不同）
    for item in data.orders:
        await assert_product_factory_scoped(db, item.product_id, user, what="产品")
    return await orchestrate_batch_orders(
        db, [item.model_dump() for item in data.orders], created_by=user.username,
    )


@router.post("/batch-submit-stockins", response_model=BatchStockinResponse)
async def batch_submit_stockins(
    data: BatchStockInRequest,
    user: User = Depends(require_any_permission("stockin_manage", "order_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """批量提交入库（厂绑定用户先过逐项工厂闸门，2026-10-19 OCR 第三轮 H1）"""
    from fastapi_app.services.auxiliary_service import orchestrate_batch_stockins
    allowed, slots, results = await _factory_gate_batch_items(
        db, user, data.stockins,
        reject_message='产品不在你的工厂范围，已拒绝该条入库',
    )
    if allowed:
        orchestrated = await orchestrate_batch_stockins(db, allowed, operator_id=user.id)
        for slot, r in zip(slots, orchestrated['results'], strict=True):
            results[slot] = r or {'success': False, 'error': '入库处理失败，请稍后重试'}
    # 顶层 success 与 /batch-submit-stockouts 同口径：全成功才为 True；
    # 逐条失败仍由 results[].success 表达（服务层已不再恒 True）。
    return {
        'success': all(r is not None and r.get('success') for r in results),
        'results': results,
    }


@router.post("/batch-submit-stockouts", response_model=BatchStockoutResponse)
async def batch_submit_stockouts(
    data: BatchStockOutRequest,
    user: User = Depends(require_permission("stockout_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """批量提交出库（厂绑定用户先过逐项工厂闸门，2026-10-19 OCR 第三轮 H1）"""
    from fastapi_app.services.auxiliary_service import orchestrate_batch_stockouts
    allowed, slots, results = await _factory_gate_batch_items(
        db, user, data.stockouts,
        reject_message='产品不在你的工厂范围，已拒绝该条出货',
    )
    if allowed:
        orchestrated = await orchestrate_batch_stockouts(db, allowed, operator_id=user.id)
        for slot, r in zip(slots, orchestrated['results'], strict=True):
            results[slot] = r or {'success': False, 'error': '出货处理失败，请稍后重试'}
    # 顶层 success 对齐 batch_create_stockouts 的 all_success：被拒项也计入失败
    return {
        'success': all(r is not None and r.get('success') for r in results),
        'results': results,
    }


# ==================== 系统状态 API ====================

@router.get("/system/stats", response_model=SystemStatsResponse)
async def system_stats(
    user: User = Depends(require_permission("admin")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """系统统计信息（缓存命中率/性能数据）"""
    from fastapi_app.services.auxiliary_service import get_system_stats
    return await get_system_stats()


# ==================== 国家管理 API ====================
