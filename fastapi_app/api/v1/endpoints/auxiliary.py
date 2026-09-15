"""辅助API接口 - 补充产品搜索、库存查询、健康检查等"""
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.response import success_response
from fastapi_app.schemas.order import OrderItemSchema
from fastapi_app.services.auxiliary_service import (
    count_inventory_logs,
    get_available_stockins,
    get_inventory_logs_page,
    get_product_by_id,
    get_stockin_by_id,
    list_countries_ordered,
)
from fastapi_app.shared_models import User


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


@router.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """应用健康检查（公开端点，仅返回基本状态）"""
    return {
        "status": "ok",
        "timestamp": time.time(),
    }


@router.get("/ready", response_model=HealthCheckResponse)
async def readiness_check():
    """K8s readiness probe alias"""
    return await health_check()


@router.get("/healthz", response_model=HealthCheckResponse)
async def healthz_check():
    """K8s healthz probe alias"""
    return await health_check()


@router.get("/readyz", response_model=HealthCheckResponse)
async def readyz_check():
    """K8s readyz probe alias"""
    return await health_check()


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
    user: User = Depends(require_permission("product_view")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """产品搜索（支持名称、条码）——统一委托 ProductSearchService（与产品清单共用实现与缓存）"""
    if not q.strip():
        return []
    from fastapi_app.core.container import get_product_search_service
    svc = get_product_search_service()
    return await svc.search_async_with_cache(db, q.strip(), limit=50)


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
    total = await count_inventory_logs(db, product_id)
    logs = await get_inventory_logs_page(db, product_id, page, per_page)

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
    stockins = await get_available_stockins(db, product_id, customer, limit)

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
    stockin = await get_stockin_by_id(db, stockin_id)
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
    return success_response(message='出库删除成功')


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
    user: User = Depends(require_permission("product_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """删除供应商（API方式）"""
    from fastapi_app.services.auxiliary_service import delete_supplier
    await delete_supplier(db, id)
    return success_response(message='供应商删除成功')


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
    from fastapi_app.services.auxiliary_service import orchestrate_batch_orders
    return await orchestrate_batch_orders(db, [item.model_dump() for item in data.orders])


@router.post("/batch-submit-stockins", response_model=BatchStockinResponse)
async def batch_submit_stockins(
    data: BatchStockInRequest,
    user: User = Depends(require_permission("stockin_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """批量提交入库"""
    from fastapi_app.services.auxiliary_service import orchestrate_batch_stockins
    return await orchestrate_batch_stockins(db, [item.model_dump() for item in data.stockins])


@router.post("/batch-submit-stockouts", response_model=BatchStockoutResponse)
async def batch_submit_stockouts(
    data: BatchStockOutRequest,
    user: User = Depends(require_permission("stockout_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """批量提交出库"""
    from fastapi_app.services.auxiliary_service import orchestrate_batch_stockouts
    return await orchestrate_batch_stockouts(db, [item.model_dump() for item in data.stockouts])


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
    countries = await list_countries_ordered(db)
    return [{'id': c.id, 'name': c.name} for c in countries]

@router.post("/countries", response_model=CountryResponse)
async def create_country(
    data: CountryCreateRequest,
    user: User = Depends(require_permission("order_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    from fastapi_app.services.auxiliary_service import create_country as create_country_service
    country = await create_country_service(db, data.name.strip())
    return {'id': country.id, 'name': country.name}

@router.delete("/countries/{country_id}")
async def delete_country(
    country_id: int,
    user: User = Depends(require_permission("order_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    from fastapi_app.services.auxiliary_service import delete_country as delete_country_service
    await delete_country_service(db, country_id)
    return success_response(message='国家删除成功')
