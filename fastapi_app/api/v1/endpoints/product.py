"""
产品管理 API 端点
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache import CacheDomain
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.cache_keys import (
    PRODUCT_LIST_CACHE_TTL,
    CacheNamespace,
    build_cache_key,
)
from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.redis_wrapper import safe_get, safe_set
from fastapi_app.schemas.product import (
    ProductActionResponse,
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductStockInfo,
    ProductUpdate,
)
from fastapi_app.services import product_service
from fastapi_app.services.product_service import (
    ProductDeleteError,
    ProductHasRelatedOrdersError,
    ProductHasRelatedRecordsError,
    ProductHasRelatedStockInsError,
    ProductHasRelatedStockOutsError,
    ProductNotFoundError,
)
from fastapi_app.shared_models import User

router = APIRouter()


async def _get_cached_product_page(page: int, per_page: int, search: str,
                                   customer_id: int | None = None,
                                   only_unassigned: bool = False) -> ProductListResponse | None:
    """从缓存读取商品列表首页（仅首页且无搜索、无客户筛选时使用）。

    只缓存「首页 + 无搜索」以避免缓存键基数爆炸（与 customer.py 同款策略）；
    带客户筛选的视图直接查库——把筛选维度拼进缓存键会让键基数随客户数膨胀，
    而这类视图是管理员临时查看，不值得缓存。

    Args:
        page: 页码。
        per_page: 每页数量，作为缓存键的一部分。
        search: 搜索关键词，非空时直接跳过缓存。
        customer_id: 客户筛选，非空时跳过缓存。
        only_unassigned: 「未分配」筛选，为真时跳过缓存。

    Returns:
        ProductListResponse | None: 命中缓存返回响应对象，未命中返回 None。
    """
    if page != 1 or search or customer_id is not None or only_unassigned:
        return None
    key = build_cache_key(CacheNamespace.PRODUCT_LIST, per_page)
    cached = await safe_get(key, context='商品列表缓存')
    if cached is None:
        return None
    return ProductListResponse(items=cached['items'], total=cached['total'])


async def _set_cached_product_page(page: int, per_page: int, search: str, items: list[dict], total: int,
                                   customer_id: int | None = None,
                                   only_unassigned: bool = False) -> None:
    """写入商品列表首页缓存（仅首页且无搜索、无客户筛选时使用）。

    Args:
        page: 页码。
        per_page: 每页数量，作为缓存键的一部分。
        search: 搜索关键词，非空时直接跳过缓存。
        items: 商品字典列表。
        total: 总记录数。
        customer_id: 客户筛选，非空时跳过缓存。
        only_unassigned: 「未分配」筛选，为真时跳过缓存。
    """
    if page != 1 or search or customer_id is not None or only_unassigned:
        return
    key = build_cache_key(CacheNamespace.PRODUCT_LIST, per_page)
    await safe_set(
        key, {'items': items, 'total': total},
        PRODUCT_LIST_CACHE_TTL, context='商品列表缓存',
    )


@router.get('/list', response_model=ProductListResponse)
async def list_products(page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=200),
                        search: str = Query('', description='搜索产品名称或69码'),
                        customer_id: int | None = Query(None, description='只看该客户可见的 SKU'),
                        only_unassigned: bool = Query(False, description='只看未挂客户的 SKU'),
                        db: AsyncSession = Depends(get_async_read_db),
                        _user: User = Depends(require_permission('product_manage'))):
    """产品列表（分页+缓存+搜索+客户归属筛选）

    仅「首页且无搜索、无客户筛选」走缓存（TTL 60s），避免缓存键基数爆炸；
    带搜索、翻页或客户筛选直接查库。写操作经 product_service._invalidate_product_list_cache 失效。
    """
    cached = await _get_cached_product_page(page, per_page, search, customer_id, only_unassigned)
    if cached is not None:
        return cached
    result = await product_service.get_products_page(
        db, page=page, per_page=per_page, search=search,
        customer_id=customer_id, only_unassigned=only_unassigned)
    await _set_cached_product_page(page, per_page, search, result['items'], result['total'],
                                   customer_id, only_unassigned)
    return ProductListResponse(items=result['items'], total=result['total'])

@router.post('/create', response_model=ProductActionResponse)
async def create_product(data: ProductCreate, db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('product_manage'))):
    """添加产品"""
    async with db_transaction(db):
        await product_service.create_product(db, name=data.name, barcode=data.barcode, price=data.price, image=data.image, factory=data.factory, initial_stock=data.initial_stock, customer_ids=data.customer_ids)
    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.INVENTORY)
    return ProductActionResponse(success=True, message='产品添加成功！')



@router.get('/search', response_model=list)
async def product_search(q: str=Query('', description='搜索关键词'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('product_manage'))):
    """产品搜索API"""
    products = await product_service.search_products(db, q)
    return products

@router.get('/available-stock', response_model=ProductStockInfo)
async def product_available_stock(product_id: int=Query(..., description='产品ID'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('product_manage'))):
    """获取产品可用库存"""
    try:
        return await product_service.get_product_stock(db, product_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.get('/{product_id}', response_model=ProductResponse)
async def get_product(product_id: int, db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('product_manage'))):
    """获取单个产品详情"""
    try:
        product = await product_service.get_product_by_id(db, product_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return product

@router.put('/edit/{product_id}', response_model=ProductActionResponse)
async def edit_product(product_id: int, data: ProductUpdate, db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('product_manage'))):
    """编辑产品"""
    async with db_transaction(db):
        await product_service.update_product(db, product_id=product_id, name=data.name, barcode=data.barcode, price=data.price, image=data.image, factory=data.factory, initial_stock=data.initial_stock, customer_ids=data.customer_ids)
    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.INVENTORY)
    return ProductActionResponse(success=True, message='产品编辑成功！')

@router.delete('/delete/{product_id}', response_model=ProductActionResponse)
async def delete_product(product_id: int, db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('product_manage'))):
    """删除产品

    错误响应：
    - 400: 产品不存在或有关联单据（订单/备货/出货）
    - 401: 未登录
    - 403: 权限不足
    """
    try:
        async with db_transaction(db):
            await product_service.delete_product(db, product_id)
    except ProductNotFoundError as e:
        raise HTTPException(status_code=400, detail=e.message) from e
    except ProductHasRelatedOrdersError as e:
        raise HTTPException(status_code=400, detail=e.message) from e
    except ProductHasRelatedStockInsError as e:
        raise HTTPException(status_code=400, detail=e.message) from e
    except ProductHasRelatedStockOutsError as e:
        raise HTTPException(status_code=400, detail=e.message) from e
    except ProductHasRelatedRecordsError as e:
        raise HTTPException(status_code=400, detail=e.message) from e
    except ProductDeleteError as e:
        raise HTTPException(status_code=400, detail=settings.sanitize_business_error(e)) from e
    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.INVENTORY)
    return ProductActionResponse(success=True, message='产品删除成功！')
