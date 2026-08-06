"""
采购中心 — 产品/BOM 相关路由

提供产品列表（Redis 缓存）、BOM 查询/保存/复制、物料计算、
搜索建议及分类列表等 HTTP 端点。
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import DisconnectionError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.purchase_center.schemas import (
    BomCopyRequest,
    BomSaveRequest,
    CalculateMaterialRequest,
)
from fastapi_app.core.cache import CacheDomain
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.database import get_async_db as get_db
from fastapi_app.core.database import get_async_read_db as get_read_db
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


@router.get('/products', response_model=ProductListResponse)
async def api_get_products(
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(50, ge=1, le=500, description='每页数量'),
    search: str = Query('', max_length=100, description='搜索关键词'),
    has_bom: str = Query('all', description='BOM 筛选: all/yes/no'),
    category: str = Query('', max_length=100, description='分类筛选'),
    sort_by: str = Query('name', description='排序字段'),
    sort_order: str = Query('asc', description='排序方向: asc/desc'),
    simple: bool = Query(False, description='是否精简模式'),
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_permission('product_manage')),
) -> dict[str, Any]:
    """获取产品列表（Redis 缓存，TTL 60s，通过 CacheDomain.PRODUCT 失效）。

    缓存由 purchase_product_service.get_products 上的 @cache_result 装饰器管理，
    多 worker 实例下共享同一 Redis 缓存，避免进程内字典不一致问题。
    """
    result = await svc.get_products(
        db, page=page, per_page=per_page, search=search, has_bom=has_bom,
        category=category, sort_by=sort_by, sort_order=sort_order, simple=simple,
    )
    return {'success': True, **result}


@router.get('/products/batch-bom')
async def api_get_products_batch_bom(
    ids: str = Query('', description='产品 ID 列表，逗号分隔'),
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_permission('product_manage')),
) -> dict[str, Any]:
    """批量获取产品 BOM 信息。

    Args:
        ids: 产品 ID 列表，逗号分隔的字符串。
        db: 异步数据库会话（只读副本）。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和批量 BOM 数据的字典。

    Raises:
        HTTPException 500: 数据库操作异常。
    """
    try:
        result = await svc.get_products_batch_bom(db, ids)
        return {'success': True, **result}
    except (OperationalError, DisconnectionError, SQLAlchemyError) as e:
        logger.exception('批量获取产品BOM失败')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e


@router.get('/products/search-suggestions', response_model=SearchSuggestionResponse)
async def api_get_search_suggestions(
    q: str = Query('', description='搜索关键词'),
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_permission('product_manage')),
) -> dict[str, Any]:
    """获取产品搜索建议（联想）。

    Args:
        q: 搜索关键词。
        db: 异步数据库会话（只读副本）。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和 suggestions 列表的字典。

    Raises:
        HTTPException 500: 数据库操作异常。
    """
    try:
        suggestions = await svc.get_search_suggestions(db, q)
        return {'success': True, 'suggestions': suggestions}
    except (OperationalError, DisconnectionError, SQLAlchemyError) as e:
        logger.exception('获取搜索建议失败')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e


@router.get('/products/statistics', response_model=ProductStatisticsResponse)
async def api_get_products_statistics(
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_permission('product_manage')),
) -> dict[str, Any]:
    """获取产品统计数据。

    Args:
        db: 异步数据库会话（只读副本）。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和 statistics 数据的字典。

    Raises:
        HTTPException 500: 数据库操作异常。
    """
    try:
        stats = await svc.get_products_statistics(db)
        return {'success': True, 'statistics': stats}
    except (OperationalError, DisconnectionError, SQLAlchemyError) as e:
        logger.exception('获取产品统计失败')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e


@router.get('/products/search', response_model=ProductListResponse)
async def api_search_products_for_bom_copy(
    keyword: str = Query('', min_length=1, description='搜索关键词'),
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_permission('product_manage')),
) -> dict[str, Any]:
    """搜索产品（用于 BOM 复制场景）。

    Args:
        keyword: 搜索关键词，至少 1 个字符。
        db: 异步数据库会话（只读副本）。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和产品列表的字典。

    Raises:
        HTTPException 400: 未输入搜索关键词。
        HTTPException 500: 数据库操作异常。
    """
    if not keyword:
        raise HTTPException(status_code=400, detail='请输入搜索关键词')
    try:
        products = await svc.search_products_for_bom_copy(db, keyword)
        return {'success': True, 'products': products}
    except (OperationalError, DisconnectionError, SQLAlchemyError) as e:
        logger.exception('搜索产品失败（BOM复制）: keyword=%s', keyword)
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e


@router.get('/product/{product_id}/bom', response_model=ProductBomResponse)
async def api_get_product_bom(
    product_id: int,
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_permission('product_manage')),
) -> dict[str, Any]:
    """获取产品 BOM 详情。

    Args:
        product_id: 产品 ID。
        db: 异步数据库会话（只读副本）。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志、product 信息和 materials 列表的字典。

    Raises:
        HTTPException 404: 产品不存在。
        HTTPException 500: 数据库操作异常。
    """
    try:
        result = await svc.get_product_bom(db, product_id)
    except (OperationalError, DisconnectionError, SQLAlchemyError) as e:
        logger.exception('获取产品BOM失败: product_id=%s', product_id)
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e
    if not result:
        raise HTTPException(status_code=404, detail='产品不存在')
    materials = result.pop('materials')
    return {'success': True, 'product': result, 'materials': materials}


@router.post('/product/{product_id}/bom', response_model=ActionResponse)
async def api_save_product_bom(
    product_id: int,
    data: BomSaveRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_permission('product_manage')),
) -> dict[str, Any]:
    """保存产品 BOM 数据。

    Args:
        product_id: 产品 ID。
        data: BOM 保存请求数据。
        db: 异步数据库会话。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和 message 的字典。

    Raises:
        HTTPException 500: 保存失败。
    """
    try:
        async with db_transaction(db):
            msg = await svc.save_product_bom(db, product_id, data.model_dump(), _current_user.username)
    except (SQLAlchemyError, RuntimeError) as e:
        logger.exception('保存BOM数据失败: product_id=%s', product_id)
        raise HTTPException(status_code=500, detail='保存失败，请稍后重试') from e
    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.PRODUCT)
    return {'success': True, 'message': msg}


@router.get('/products/{source_product_id}/bom-preview')
async def api_get_bom_preview(
    source_product_id: int,
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_permission('product_manage')),
) -> dict[str, Any]:
    """预览源产品的 BOM（用于复制前确认）。

    Args:
        source_product_id: 源产品 ID。
        db: 异步数据库会话（只读副本）。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和 BOM 预览数据的字典。
    """
    async with db_transaction(db, commit=False):
        result = await svc.get_bom_preview(db, source_product_id)
    return {'success': True, **result}


@router.post('/products/{target_product_id}/copy-bom', response_model=ActionResponse)
async def api_copy_bom_to_product(
    target_product_id: int,
    data: BomCopyRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_permission('product_manage')),
) -> dict[str, Any]:
    """将源产品 BOM 复制到目标产品。

    Args:
        target_product_id: 目标产品 ID。
        data: BOM 复制请求，包含源产品 ID 和是否覆盖标志。
        db: 异步数据库会话。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和复制结果的字典。

    Raises:
        HTTPException 409: 目标产品已有 BOM（冲突）。
    """
    try:
        async with db_transaction(db):
            result = await svc.copy_bom_to_product(db, target_product_id, data.model_dump())
    except HTTPException as e:
        if e.status_code == 400 and '目标产品已有BOM' in e.detail:
            raise HTTPException(status_code=409, detail=e.detail, headers={'has_existing_bom': 'true'}) from e
        raise
    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.PRODUCT)
    return {'success': True, **result}


@router.post('/calculate', response_model=MaterialCalculateResponse)
async def api_calculate_material(
    data: CalculateMaterialRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_permission('product_manage')),
) -> dict[str, Any]:
    """根据订单列表计算物料需求。

    Args:
        data: 物料计算请求，包含订单物料列表。
        db: 异步数据库会话。
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和物料计算结果的字典。

    Raises:
        HTTPException 500: 物料计算失败。
    """
    try:
        result = await svc.calculate_material(db, [o.model_dump() for o in data.orders])
        return {'success': True, **result}
    except (ValueError, OperationalError, DisconnectionError, RuntimeError) as e:
        logger.exception('物料计算失败')
        raise HTTPException(status_code=500, detail='物料计算失败，请稍后重试') from e


@router.get('/categories', response_model=CategoriesResponse)
async def api_get_material_categories(
    _current_user=Depends(require_permission('product_manage')),
) -> dict[str, Any]:
    """获取物料分类列表。

    Args:
        _current_user: 当前登录用户（权限校验依赖）。

    Returns:
        dict[str, Any]: 包含 success 标志和 categories 字典的字典。
    """
    from fastapi_app.shared_models import MATERIAL_CATEGORIES
    return {'success': True, 'categories': MATERIAL_CATEGORIES}
