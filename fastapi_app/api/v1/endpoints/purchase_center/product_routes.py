"""
采购中心 — 产品/BOM 相关路由
"""
import hashlib
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import DisconnectionError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.purchase_center.schemas import (
    BomCopyRequest,
    BomSaveRequest,
    CalculateMaterialRequest,
)
from fastapi_app.core.database import get_async_db as get_db, get_async_read_db as get_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.logger import logger
from fastapi_app.schemas.purchase_center import (
    ActionResponse,
    CategoriesResponse,
    MaterialCalculateResponse,
    ProductBomResponse,
    ProductListResponse,
    ProductStatisticsResponse,
    SearchSuggestionResponse,
)
from fastapi_app.services import purchase_center_service as svc

router = APIRouter()
_PRODUCTS_L1_CACHE: dict[str, tuple[float, dict]] = {}
_PRODUCTS_CACHE_TTL = 60

def _make_products_cache_key(page, per_page, search, has_bom, category, sort_by, sort_order, simple) -> str:
    raw = json.dumps({'p': page, 'pp': per_page, 's': search, 'hb': has_bom, 'c': category, 'sb': sort_by, 'so': sort_order, 'simp': simple}, sort_keys=True)
    return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()

@router.get('/products', response_model=ProductListResponse)
async def api_get_products(page: int=Query(1, ge=1), per_page: int=Query(50, ge=1, le=500), search: str=Query('', max_length=100), has_bom: str=Query('all'), category: str=Query('', max_length=100), sort_by: str=Query('name'), sort_order: str=Query('asc'), simple: bool=Query(False), db: AsyncSession=Depends(get_read_db), _user=Depends(require_permission('product_manage'))):
    cache_key = _make_products_cache_key(page, per_page, search, has_bom, category, sort_by, sort_order, simple)
    entry = _PRODUCTS_L1_CACHE.get(cache_key)
    if entry is not None:
        cached_at, cached_result = entry
        if time.monotonic() - cached_at < _PRODUCTS_CACHE_TTL:
            return {'success': True, **cached_result}
        del _PRODUCTS_L1_CACHE[cache_key]
    result = await svc.get_products(db, page=page, per_page=per_page, search=search, has_bom=has_bom, category=category, sort_by=sort_by, sort_order=sort_order, simple=simple)
    _PRODUCTS_L1_CACHE[cache_key] = (time.monotonic(), result)
    if len(_PRODUCTS_L1_CACHE) > 200:
        oldest_key = min(_PRODUCTS_L1_CACHE, key=lambda k: _PRODUCTS_L1_CACHE[k][0])
        del _PRODUCTS_L1_CACHE[oldest_key]
    return {'success': True, **result}

@router.get('/products/batch-bom')
async def api_get_products_batch_bom(ids: str=Query(''), db: AsyncSession=Depends(get_read_db), _user=Depends(require_permission('product_manage'))):
    result = await svc.get_products_batch_bom(db, ids)
    return {'success': True, **result}

@router.get('/products/search-suggestions', response_model=SearchSuggestionResponse)
async def api_get_search_suggestions(q: str=Query(''), db: AsyncSession=Depends(get_read_db), _user=Depends(require_permission('product_manage'))):
    suggestions = await svc.get_search_suggestions(db, q)
    return {'success': True, 'suggestions': suggestions}

@router.get('/products/statistics', response_model=ProductStatisticsResponse)
async def api_get_products_statistics(db: AsyncSession=Depends(get_read_db), _user=Depends(require_permission('product_manage'))):
    stats = await svc.get_products_statistics(db)
    return {'success': True, 'statistics': stats}

@router.get('/products/search', response_model=ProductListResponse)
async def api_search_products_for_bom_copy(keyword: str=Query('', min_length=1), db: AsyncSession=Depends(get_read_db), _user=Depends(require_permission('product_manage'))):
    if not keyword:
        raise HTTPException(status_code=400, detail='请输入搜索关键词')
    products = await svc.search_products_for_bom_copy(db, keyword)
    return {'success': True, 'products': products}

@router.get('/product/{product_id}/bom', response_model=ProductBomResponse)
async def api_get_product_bom(product_id: int, db: AsyncSession=Depends(get_read_db), _user=Depends(require_permission('product_manage'))):
    result = await svc.get_product_bom(db, product_id)
    if not result:
        raise HTTPException(status_code=404, detail='产品不存在')
    materials = result.pop('materials')
    return {'success': True, 'product': result, 'materials': materials}

@router.post('/product/{product_id}/bom', response_model=ActionResponse)
async def api_save_product_bom(product_id: int, data: BomSaveRequest, db: AsyncSession=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    try:
        async with db_transaction(db):
            msg = await svc.save_product_bom(db, product_id, data.model_dump(), _user.username)
    except (SQLAlchemyError, RuntimeError) as e:
        logger.error(f'保存BOM数据失败: {e}')
        raise HTTPException(status_code=500, detail='保存失败，请稍后重试') from e
    _PRODUCTS_L1_CACHE.clear()
    return {'success': True, 'message': msg}

@router.get('/products/{source_product_id}/bom-preview')
async def api_get_bom_preview(source_product_id: int, db: AsyncSession=Depends(get_read_db), _user=Depends(require_permission('product_manage'))):
    async with db_transaction(db, commit=False):
        result = await svc.get_bom_preview(db, source_product_id)
    return {'success': True, **result}

@router.post('/products/{target_product_id}/copy-bom', response_model=ActionResponse)
async def api_copy_bom_to_product(target_product_id: int, data: BomCopyRequest, db: AsyncSession=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    try:
        async with db_transaction(db):
            result = await svc.copy_bom_to_product(db, target_product_id, data.model_dump())
    except HTTPException as e:
        if e.status_code == 400 and '目标产品已有BOM' in e.detail:
            raise HTTPException(status_code=409, detail=e.detail, headers={'has_existing_bom': 'true'}) from e
        raise
    _PRODUCTS_L1_CACHE.clear()
    return {'success': True, **result}

@router.post('/calculate', response_model=MaterialCalculateResponse)
async def api_calculate_material(data: CalculateMaterialRequest, db: AsyncSession=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    try:
        result = await svc.calculate_material(db, data.orders)
        return {'success': True, **result}
    except (ValueError, OperationalError, DisconnectionError, RuntimeError) as e:
        logger.error(f'物料计算失败: {e}')
        raise HTTPException(status_code=500, detail='物料计算失败，请稍后重试') from e

@router.get('/categories', response_model=CategoriesResponse)
async def api_get_material_categories(_user=Depends(require_permission('product_manage'))):
    from fastapi_app.shared_models import MATERIAL_CATEGORIES
    return {'success': True, 'categories': MATERIAL_CATEGORIES}

