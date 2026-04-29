"""
产品管理 API 端点

从 Flask product.py 迁移的 REST API。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.cache import invalidate_cache
from fastapi_app.shared_models import User, Product
from fastapi_app.schemas.product import (
    ProductCreate, ProductUpdate, ProductActionResponse,
    ProductListResponse, ProductResponse, ProductStockInfo,
)
from fastapi_app.services import product_service
from fastapi_app.services.product_service import (
    ProductDeleteError,
    ProductNotFoundError,
    ProductHasRelatedOrdersError,
    ProductHasRelatedStockInsError,
    ProductHasRelatedStockOutsError,
)
from utils.redis_cache import redis_cache

router = APIRouter()

PRODUCT_LIST_CACHE_KEY = "product:list:all"
PRODUCT_LIST_CACHE_TTL = 300


@router.get("/list", response_model=ProductListResponse)
async def list_products(
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("product_manage")),
):
    """产品列表（带缓存）"""
    cached = await redis_cache.get(PRODUCT_LIST_CACHE_KEY)
    if cached is not None:
        return ProductListResponse(data=cached, total=len(cached))

    products = await product_service.get_products(db)

    await redis_cache.set(PRODUCT_LIST_CACHE_KEY, products, PRODUCT_LIST_CACHE_TTL)

    return ProductListResponse(data=products, total=len(products))


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("product_manage")),
):
    """获取单个产品详情"""
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="产品不存在")
    return product


@router.post("/create", response_model=ProductActionResponse)
async def create_product(
    data: ProductCreate,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("product_manage")),
):
    """添加产品"""
    try:
        await product_service.create_product(
            db, name=data.name, barcode=data.barcode,
            price=data.price, image=data.image, initial_stock=data.initial_stock
        )
        await redis_cache.delete(PRODUCT_LIST_CACHE_KEY)
        await invalidate_cache("inventory:*")
        return ProductActionResponse(success=True, message="产品添加成功！")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/edit/{product_id}", response_model=ProductActionResponse)
async def edit_product(
    product_id: int,
    data: ProductUpdate,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("product_manage")),
):
    """编辑产品"""
    try:
        await product_service.update_product(
            db, product_id=product_id, name=data.name,
            barcode=data.barcode, price=data.price, image=data.image,
            initial_stock=data.initial_stock
        )
        await redis_cache.delete(PRODUCT_LIST_CACHE_KEY)
        await invalidate_cache("inventory:*")
        return ProductActionResponse(success=True, message="产品编辑成功！")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/delete/{product_id}", response_model=ProductActionResponse)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("product_manage")),
):
    """删除产品

    错误响应：
    - 400: 产品不存在或有关联单据（订单/备货/出货）
    - 401: 未登录
    - 403: 权限不足
    """
    try:
        await product_service.delete_product(db, product_id)
        await redis_cache.delete(PRODUCT_LIST_CACHE_KEY)
        await invalidate_cache("inventory:*")
        return ProductActionResponse(success=True, message="产品删除成功！")
    except ProductNotFoundError as e:
        raise HTTPException(status_code=400, detail=e.message)
    except ProductHasRelatedOrdersError as e:
        raise HTTPException(status_code=400, detail=e.message)
    except ProductHasRelatedStockInsError as e:
        raise HTTPException(status_code=400, detail=e.message)
    except ProductHasRelatedStockOutsError as e:
        raise HTTPException(status_code=400, detail=e.message)
    except ProductDeleteError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/search", response_model=list)
async def product_search(
    q: str = Query("", description="搜索关键词"),
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("product_manage")),
):
    """产品搜索API"""
    products = await product_service.search_products(db, q)
    return products


@router.get("/available-stock", response_model=ProductStockInfo)
async def product_available_stock(
    product_id: int = Query(..., description="产品ID"),
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("product_manage")),
):
    """获取产品可用库存"""
    try:
        return await product_service.get_product_stock(db, product_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
