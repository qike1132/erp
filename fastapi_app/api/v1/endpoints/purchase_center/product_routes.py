"""
采购中心 — 产品/BOM 相关路由
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, OperationalError, DisconnectionError

from fastapi_app.core.database import get_sync_db as get_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.logger import logger
from fastapi_app.services import purchase_center_service as svc
from fastapi_app.api.v1.endpoints.purchase_center.schemas import (
    BomSaveRequest, BomCopyRequest, CalculateMaterialRequest,
)

router = APIRouter()


@router.get("/products")
def api_get_products(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    search: str = Query('', max_length=100),
    has_bom: str = Query('all'),
    category: str = Query('', max_length=100),
    sort_by: str = Query('name'),
    sort_order: str = Query('asc'),
    simple: bool = Query(False),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    result = svc.get_products(
        db, page=page, per_page=per_page, search=search,
        has_bom=has_bom, category=category, sort_by=sort_by, sort_order=sort_order,
        simple=simple,
    )
    return {'success': True, **result}


@router.get("/products/batch-bom")
def api_get_products_batch_bom(
    ids: str = Query(''),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    result = svc.get_products_batch_bom(db, ids)
    return {'success': True, **result}


@router.get("/products/search-suggestions")
def api_get_search_suggestions(
    q: str = Query(''),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    suggestions = svc.get_search_suggestions(db, q)
    return {'success': True, 'suggestions': suggestions}


@router.get("/products/statistics")
def api_get_products_statistics(
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    stats = svc.get_products_statistics(db)
    return {'success': True, 'statistics': stats}


@router.get("/products/search")
def api_search_products_for_bom_copy(
    keyword: str = Query('', min_length=1),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    """搜索产品用于复制BOM"""
    if not keyword:
        raise HTTPException(status_code=400, detail="请输入搜索关键词")
    products = svc.search_products_for_bom_copy(db, keyword)
    return {'success': True, 'products': products}


@router.get("/product/{product_id}/bom")
def api_get_product_bom(
    product_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    result = svc.get_product_bom(db, product_id)
    if not result:
        raise HTTPException(status_code=404, detail="产品不存在")
    return {'success': True, 'product': result, 'materials': result.pop('materials')}


@router.post("/product/{product_id}/bom")
def api_save_product_bom(
    product_id: int,
    data: BomSaveRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    try:
        msg = svc.save_product_bom(db, product_id, data.model_dump(), _user.username)
        return {'success': True, 'message': msg}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (SQLAlchemyError, RuntimeError) as e:
        db.rollback()
        logger.error(f"保存BOM数据失败: {e}")
        raise HTTPException(status_code=500, detail="保存失败，请稍后重试")


@router.get("/products/{source_product_id}/bom-preview")
def api_get_bom_preview(
    source_product_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    """获取源产品BOM预览用于复制确认"""
    try:
        result = svc.get_bom_preview(db, source_product_id)
        return {'success': True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/products/{target_product_id}/copy-bom")
def api_copy_bom_to_product(
    target_product_id: int,
    data: BomCopyRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    """复制BOM到目标产品"""
    try:
        result = svc.copy_bom_to_product(db, target_product_id, data.model_dump())
        return {'success': True, **result}
    except ValueError as e:
        error_msg = str(e)
        if '目标产品已有BOM' in error_msg:
            raise HTTPException(status_code=409, detail=error_msg, headers={'has_existing_bom': 'true'})
        raise HTTPException(status_code=400, detail=error_msg)


@router.post("/calculate")
def api_calculate_material(
    data: CalculateMaterialRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("product_manage")),
):
    try:
        result = svc.calculate_material(db, data.orders)
        return {'success': True, **result}
    except (ValueError, OperationalError, DisconnectionError, RuntimeError) as e:
        logger.error(f"物料计算失败: {e}")
        raise HTTPException(status_code=500, detail="物料计算失败，请稍后重试")


@router.get("/categories")
async def api_get_material_categories(
    _user=Depends(require_permission("product_manage")),
):
    from fastapi_app.shared_models import MATERIAL_CATEGORIES
    return {'success': True, 'categories': MATERIAL_CATEGORIES}


@router.post("/cache/clear")
async def api_clear_cache(
    _user=Depends(require_permission("product_manage")),
):
    return {'success': True, 'message': '缓存已清除'}
