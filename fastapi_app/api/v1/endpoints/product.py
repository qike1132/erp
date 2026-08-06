"""
产品管理 API 端点
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache import CacheDomain
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import db_transaction
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
    ProductHasRelatedStockInsError,
    ProductHasRelatedStockOutsError,
    ProductNotFoundError,
)
from fastapi_app.shared_models import User

router = APIRouter()

@router.get('/list', response_model=ProductListResponse)
async def list_products(page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=200),
                        search: str = Query('', description='搜索产品名称或69码'),
                        db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('product_manage'))):
    """产品列表（分页+缓存+搜索）"""
    result = await product_service.get_products_page(db, page=page, per_page=per_page, search=search)
    return ProductListResponse(items=result['items'], total=result['total'])

@router.post('/create', response_model=ProductActionResponse)
async def create_product(data: ProductCreate, db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('product_manage'))):
    """添加产品"""
    async with db_transaction(db):
        await product_service.create_product(db, name=data.name, barcode=data.barcode, price=data.price, image=data.image, factory=data.factory, initial_stock=data.initial_stock)
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
        await product_service.update_product(db, product_id=product_id, name=data.name, barcode=data.barcode, price=data.price, image=data.image, factory=data.factory, initial_stock=data.initial_stock)
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
    except ProductDeleteError as e:
        raise HTTPException(status_code=400, detail=settings.sanitize_business_error(e)) from e
    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.INVENTORY)
    return ProductActionResponse(success=True, message='产品删除成功！')
