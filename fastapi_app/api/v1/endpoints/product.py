"""
产品管理 API 端点

从 Flask product.py 迁移的 REST API。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import require_permission
from fastapi_app.shared_models import User
from fastapi_app.schemas.product import (
    ProductCreate, ProductUpdate, ProductActionResponse,
    ProductListResponse, ProductStockInfo,
)
from fastapi_app.services import product_service

router = APIRouter()


@router.get("/list", response_model=ProductListResponse)
async def list_products(
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("product_manage")),
):
    """产品列表"""
    products = await product_service.get_products(db)
    return ProductListResponse(data=products, total=len(products))


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
        return ProductActionResponse(success=True, message="产品编辑成功！")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/delete/{product_id}", response_model=ProductActionResponse)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission("product_manage")),
):
    """删除产品"""
    try:
        await product_service.delete_product(db, product_id)
        return ProductActionResponse(success=True, message="产品删除成功！")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/search")
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
        raise HTTPException(status_code=404, detail=str(e))
