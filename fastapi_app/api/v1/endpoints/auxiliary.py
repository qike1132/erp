"""辅助API接口 - 补充产品搜索、库存查询、健康检查等"""
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.services import escape_like
from fastapi_app.shared_models import InventoryLog, Product, StockIn, User
from fastapi_app.shared_models.country import Country

class HealthCheckResponse(BaseModel):
    status: str
    timestamp: float

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
    regular_available: int = 0
    custom_available: int = 0

class AuxActionResponse(BaseModel):
    success: bool
    message: str = ''

class BatchOrderResultItem(BaseModel):
    success: bool
    order_no: str = ''
    id: int | None = None
    error: str | None = None

class BatchOrderResponse(BaseModel):
    success: bool
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


@router.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """应用健康检查（公开端点，仅返回基本状态）"""
    return {
        "status": "ok",
        "timestamp": time.time(),
    }


@router.get("/cache/stats", response_model=dict)
async def cache_stats(
    user: User = Depends(require_permission("admin")),
):
    """获取缓存统计信息（需管理员权限）"""
    from utils.redis_cache import redis_cache
    return await redis_cache.get_stats()


@router.post("/cache/clear", response_model=CacheClearResponse)
async def clear_cache(
    pattern: str = Query("*", description="清除匹配的缓存键"),
    user: User = Depends(require_permission("admin")),
):
    """清除缓存（需管理员权限）"""
    from utils.redis_cache import redis_cache
    deleted = await redis_cache.delete_pattern(pattern)
    return {"success": True, "deleted": deleted, "pattern": pattern}


@router.get("/product-search", response_model=list[ProductSearchItem])
async def product_search(
    q: str = Query('', max_length=100, description="搜索关键词"),
    user: User = Depends(require_permission("product_view")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """产品搜索（支持名称、条码）"""
    if not q.strip():
        return []

    query_str = q.strip()
    result = await db.execute(
        select(Product).where(
            or_(Product.name.like(f'%{escape_like(query_str)}%'), Product.barcode.like(f'%{escape_like(query_str)}%'))
        ).limit(50)
    )
    products = list(result.scalars().all())

    return [{
        'id': p.id, 'name': p.name, 'barcode': p.barcode,
        'price': float(p.price) if p.price else 0,
        'current_stock': p.current_stock,
    } for p in products]


@router.get("/product-available-stock", response_model=ProductAvailableStockResponse)
async def product_available_stock(
    product_id: int = Query(..., description="产品ID"),
    user: User = Depends(require_permission("product_view")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """获取产品可用库存"""
    product = await db.get(Product, product_id)
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
    from sqlalchemy import func
    count_result = await db.execute(
        select(func.count(InventoryLog.id)).where(InventoryLog.product_id == product_id)
    )
    total = count_result.scalar() or 0
    result = await db.execute(
        select(InventoryLog).where(InventoryLog.product_id == product_id)
        .order_by(InventoryLog.change_date.desc())
        .offset((page - 1) * per_page).limit(per_page)
    )
    logs = list(result.scalars().all())

    return {
        'items': [{
            'id': log.id, 'change_type': log.change_type,
            'change_quantity': log.change_quantity,
            'related_id': log.related_id,
            'note': log.note,
            'change_date': log.change_date.strftime('%Y-%m-%d %H:%M:%S') if log.change_date else '',
        } for log in logs],
        'total': total, 'page': page, 'per_page': per_page,
    }


@router.get("/available-stockins", response_model=list[AvailableStockinItem])
async def available_stockins(
    product_id: int | None = Query(None),
    customer: str = Query('', max_length=100),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(require_permission("stock_view")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """获取可用入库记录（限制返回数量）"""
    query = select(StockIn).options(
        joinedload(StockIn.stockin_stockouts), joinedload(StockIn.product)
    )

    if product_id:
        query = query.where(StockIn.product_id == product_id)
    if customer:
        query = query.where(StockIn.customer == customer)

    query = query.order_by(StockIn.stockin_date.asc()).limit(limit)
    result = await db.execute(query)
    stockins = list(result.unique().scalars().all())

    return [{
        'id': s.id, 'product_id': s.product_id,
        'product_name': s.product.name if s.product else '',
        'quantity': s.quantity, 'customer': s.customer,
        'stockin_date': s.stockin_date.strftime('%Y-%m-%d') if s.stockin_date else '',
        'available': s.quantity - sum(st.quantity for st in s.stockin_stockouts) if s.stockin_stockouts else s.quantity,
    } for s in stockins]


@router.get("/stockin-info/{stockin_id}", response_model=StockinInfoResponse)
async def stockin_info(
    stockin_id: int,
    user: User = Depends(require_permission("stock_view")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """获取入库信息详情"""
    stockin = await db.get(StockIn, stockin_id)
    if not stockin:
        raise HTTPException(status_code=404, detail="入库记录不存在")

    return {
        'id': stockin.id, 'product_id': stockin.product_id,
        'product_name': stockin.product.name if stockin.product else '',
        'quantity': stockin.quantity, 'customer': stockin.customer,
        'stockin_date': stockin.stockin_date.strftime('%Y-%m-%d') if stockin.stockin_date else '',
        'note': stockin.note or '',
    }


@router.get("/available-shipment", response_model=AvailableShipmentResponse)
async def available_shipment(
    product_id: int | None = Query(None),
    customer: str = Query('', max_length=100),
    order_type: str | None = Query(None, max_length=20),
    country: str | None = Query(None, max_length=100),
    user: User = Depends(require_permission("stock_view")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """获取可出货量（按客户+产品维度，支持按订单类型隔离）

    复用 batch_service 的完整实现，消除内联重复逻辑。
    order_type 参数用于逻辑隔离：指定后仅计算该类型的订单可出货量。
    """
    if not product_id or not customer.strip():
        return {'order_quantity': 0, 'shipped_quantity': 0, 'available_quantity': 0, 'regular_available': 0, 'custom_available': 0}

    from fastapi_app.services.batch_service import calculate_available_shipment_quantity
    shipment_info = await calculate_available_shipment_quantity(
        db, product_id, customer, order_type=order_type, country=country
    )

    return {
        'order_quantity': shipment_info['order_quantity'],
        'shipped_quantity': shipment_info['shipped_quantity'],
        'available_quantity': shipment_info['available_quantity'],
        'regular_available': shipment_info.get('regular_available', 0),
        'custom_available': shipment_info.get('custom_available', 0),
    }


# ==================== 删除接口 ====================

@router.delete("/stockout/{id}", response_model=AuxActionResponse)
async def delete_stockout_api(
    id: int,
    user: User = Depends(require_permission("stockout_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """删除出库记录（API方式）"""
    from fastapi_app.services.stock_service import delete_stockout as svc_delete
    async with db_transaction(db, commit=False):
        await svc_delete(db, id)
    return {'success': True, 'message': '出库删除成功'}


@router.delete("/stockin/{id}", response_model=AuxActionResponse)
async def delete_stockin_api(
    id: int,
    user: User = Depends(require_permission("stockin_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """删除入库记录（API方式）"""
    from fastapi_app.services.stock_service import delete_stockin as svc_delete
    async with db_transaction(db, commit=False):
        await svc_delete(db, id)
    return {'success': True, 'message': '入库删除成功'}


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
    return {'success': True, 'message': '客户删除成功'}


@router.delete("/supplier/{id}", response_model=AuxActionResponse)
async def delete_supplier_api(
    id: int,
    user: User = Depends(require_permission("product_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """删除供应商（API方式）"""
    from sqlalchemy import select

    from fastapi_app.shared_models import (
        ProductAccessory,
        ProductFabric,
        ProductMaterial,
        PurchaseOrder,
        Supplier,
    )
    try:
        async with db_transaction(db):
            supplier = (await db.execute(select(Supplier).where(Supplier.id == id))).scalar_one_or_none()
            if not supplier:
                raise HTTPException(status_code=404, detail="供应商不存在")

            has_bom = (
                (await db.execute(select(ProductMaterial.id).where(ProductMaterial.supplier_id == id).limit(1))).scalar() or
                (await db.execute(select(ProductFabric.id).where(ProductFabric.supplier_id == id).limit(1))).scalar() or
                (await db.execute(select(ProductAccessory.id).where(ProductAccessory.supplier_id == id).limit(1))).scalar()
            )
            has_orders = (await db.execute(select(PurchaseOrder.id).where(PurchaseOrder.supplier_id == id).limit(1))).scalar()

            if has_bom or has_orders:
                raise HTTPException(status_code=400, detail="该供应商已有相关BOM或采购订单数据，无法删除")

            await db.delete(supplier)
        return {'success': True, 'message': '供应商删除成功'}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {settings.sanitize_error(e)}") from e


# ==================== 批量提交 Pydantic 模型 ====================

class BatchOrderItem(BaseModel):
    product_id: int = Field(..., gt=0)
    customer: str
    quantity: int = Field(..., gt=0, le=9999999)
    deduct_stock: bool | None = None
    deduct_quantity: int | None = None
    note: str = ""
    order_type: str = Field("regular", pattern="^(regular|custom)$")
    country: str | None = None
    order_date: str | None = None

    @model_validator(mode='after')
    def validate_custom_order(self):
        if self.order_type == 'custom' and not self.country:
            raise ValueError('定制订单必须填写国家名称')
        return self

class BatchStockInItem(BaseModel):
    product_id: int = Field(..., gt=0)
    customer: str
    quantity: int = Field(..., gt=0, le=9999999)
    note: str = ""
    order_type: str = Field("regular", pattern="^(regular|custom)$")
    country: str | None = None
    stockin_date: str | None = None

class BatchStockOutItem(BaseModel):
    product_id: int = Field(..., gt=0)
    customer: str
    quantity: int = Field(..., gt=0, le=9999999)
    note: str = ""
    order_type: str = Field("regular", pattern="^(regular|custom)$")
    country: str | None = None
    stockout_date: str | None = None

class BatchOrderRequest(BaseModel):
    orders: list[BatchOrderItem]

class BatchStockInRequest(BaseModel):
    stockins: list[BatchStockInItem]

class BatchStockOutRequest(BaseModel):
    stockouts: list[BatchStockOutItem]

# ==================== 批量提交 API ====================

@router.post("/batch-submit-orders", response_model=BatchOrderResponse)
async def batch_submit_orders(
    data: BatchOrderRequest,
    user: User = Depends(require_permission("order_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """批量提交订单"""
    import logging as _logging

    from fastapi_app.services.order_service import batch_create_orders
    try:
        async with db_transaction(db):
            result = await batch_create_orders(db, [item.model_dump() for item in data.orders])

        from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
        await invalidate_related_caches(CacheDomain.ORDER_AND_INVENTORY)

        created_order_ids = result.pop('created_order_ids', [])

        if created_order_ids:
            try:
                from fastapi_app.services.notification_service import StockEvent, publish_stock_event
                await publish_stock_event(StockEvent.ORDER_CREATED, {
                    'order_ids': created_order_ids,
                    'count': len(created_order_ids),
                })
            except (RuntimeError, OSError, ValueError):
                _logging.warning("批量订单事件发布失败", exc_info=True)

        return result
    except (SQLAlchemyError, RuntimeError):
        raise


@router.post("/batch-submit-stockins", response_model=BatchStockinResponse)
async def batch_submit_stockins(
    data: BatchStockInRequest,
    user: User = Depends(require_permission("stockin_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """批量提交入库"""
    from fastapi_app.services.stock_service import batch_create_stockins
    try:
        async with db_transaction(db):
            result = await batch_create_stockins(db, [item.model_dump() for item in data.stockins])

        from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
        await invalidate_related_caches(CacheDomain.ORDER_AND_INVENTORY | CacheDomain.STOCKIN)

        return result
    except (SQLAlchemyError, RuntimeError):
        raise


@router.post("/batch-submit-stockouts", response_model=BatchStockoutResponse)
async def batch_submit_stockouts(
    data: BatchStockOutRequest,
    user: User = Depends(require_permission("stockout_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """批量提交出库"""
    import logging as _logging

    from fastapi_app.services.stock_service import batch_create_stockouts
    async with db_transaction(db):
        result = await batch_create_stockouts(db, [item.model_dump() for item in data.stockouts])

    # Post-commit: cache invalidation + event publishing
    try:
        from fastapi_app.core.cache import CacheDomain, invalidate_related_caches
        await invalidate_related_caches(CacheDomain.ORDER_AND_INVENTORY)

        # 采购计划重算 + 事件发布
        successful_pairs: set[tuple[int, str]] = set()
        for idx, item in enumerate(data.stockouts):
            r = result['results'][idx]
            if r.get('success'):
                successful_pairs.add((item.product_id, item.customer))

        if successful_pairs:
            from fastapi_app.services.purchase_plan_service import recalc_plans_after_stockout_create, _invalidate_plan_caches
            from datetime import UTC as _UTC, datetime as _dt
            unique_product_ids = {pid for pid, _ in successful_pairs}
            product_result = await db.execute(
                select(Product.id, Product.name).where(Product.id.in_(unique_product_ids))
            )
            product_name_map = {row[0]: row[1] for row in product_result.all()}
            for product_id, customer in successful_pairs:
                product_name = product_name_map.get(product_id, '')
                if product_name:
                    await recalc_plans_after_stockout_create(db, customer, product_name)

            now_month = _dt.now(_UTC).strftime('%Y-%m')
            await _invalidate_plan_caches(now_month)

            from fastapi_app.core.exception_handler import safe_publish_event
            from fastapi_app.services.notification_service import StockEvent, publish_stock_event
            for product_id, _ in successful_pairs:
                product = await db.get(Product, product_id)
                if product is not None:
                    total_qty = sum(item.quantity for item in data.stockouts if item.product_id == product_id)
                    await safe_publish_event(publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': product_id, 'product_name': product.name, 'change_type': '出库', 'quantity': total_qty, 'current_stock': product.current_stock}, context="批量出库事件发布")
    except Exception as e:
        _logging.getLogger(__name__).warning(f"出库后置操作部分失败（不影响出库结果）: {e}", exc_info=True)

    return result


# ==================== 系统状态 API ====================

@router.get("/system/stats", response_model=SystemStatsResponse)
async def system_stats(
    user: User = Depends(require_permission("admin")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """系统统计信息（缓存命中率/性能数据）"""
    try:
        from utils.performance_monitor import performance_monitor, query_tracker

        stats = {
            'cache': {},
            'performance': {
                **performance_monitor.get_stats(),
                'queries': query_tracker.get_stats()
            }
        }
        return stats
    except ImportError:
        return {'cache': {}, 'performance': {}}


# ==================== 国家管理 API ====================

class CountryResponse(BaseModel):
    id: int
    name: str

class CountryCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

@router.get("/countries", response_model=list[CountryResponse])
async def list_countries(
    user: User = Depends(require_permission("order_manage")),
    db: AsyncSession = Depends(get_async_read_db),
):
    result = await db.execute(select(Country).order_by(Country.name))
    countries = result.scalars().all()
    return [{'id': c.id, 'name': c.name} for c in countries]

@router.post("/countries", response_model=CountryResponse)
async def create_country(
    data: CountryCreateRequest,
    user: User = Depends(require_permission("order_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="国家名称不能为空")
    existing = await db.execute(select(Country).where(Country.name == name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="该国家已存在")
    country = Country(name=name)
    db.add(country)
    await db.flush()
    await db.refresh(country)
    return {'id': country.id, 'name': country.name}

@router.delete("/countries/{country_id}")
async def delete_country(
    country_id: int,
    user: User = Depends(require_permission("order_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(Country).where(Country.id == country_id))
    country = result.scalar_one_or_none()
    if not country:
        raise HTTPException(status_code=404, detail="国家不存在")
    await db.delete(country)
    return {'success': True, 'message': '国家删除成功'}
