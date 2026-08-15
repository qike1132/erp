"""
供应商管理接口

提供供应商的 CRUD、状态切换等 HTTP 端点。
列表查询使用 Redis 缓存以降低数据库压力，
所有写操作（创建/编辑/删除/切换状态）会失效相关缓存。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache_keys import CACHE_KEY_PREFIX, CacheNamespace, build_cache_key
from fastapi_app.core.database import get_async_db as get_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.redis_wrapper import safe_delete_pattern, safe_get, safe_set
from fastapi_app.schemas.supplier import (
    SupplierActionResponse,
    SupplierCreate,
    SupplierListResponse,
    SupplierResponse,
    SupplierToggleResponse,
    SupplierUpdate,
)
from fastapi_app.services import purchase_supplier_service
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()

# 供应商列表缓存 TTL（秒），首页无搜索时缓存 5 分钟
SUPPLIER_LIST_CACHE_TTL = 300
# 供应商列表缓存的键模式，用于写操作后批量失效
# 注意：必须包含 CACHE_KEY_PREFIX（'erp'），与 build_cache_key 生成的键保持一致
SUPPLIER_LIST_CACHE_PATTERN = f"{CACHE_KEY_PREFIX}:{CacheNamespace.SUPPLIER_LIST}:*"


async def _invalidate_supplier_caches() -> None:
    """失效供应商列表缓存。

    在所有写操作（创建/编辑/删除/切换状态）后调用，
    确保后续读取获取最新数据。
    """
    await safe_delete_pattern(SUPPLIER_LIST_CACHE_PATTERN, context="供应商列表缓存")


async def _get_cached_supplier_list(per_page: int) -> SupplierListResponse | None:
    """从缓存读取供应商列表（仅首页无搜索时使用）。

    Args:
        per_page: 每页数量，作为缓存键的一部分。

    Returns:
        SupplierListResponse | None: 命中缓存返回响应对象，未命中返回 None。
    """
    cache_key = build_cache_key(CacheNamespace.SUPPLIER_LIST, per_page)
    cached = await safe_get(cache_key, context="供应商列表缓存")
    if cached is None:
        return None
    return SupplierListResponse(
        suppliers=[SupplierResponse(**c) for c in cached['items']],
        total=cached['total'],
    )


async def _set_cached_supplier_list(per_page: int, items: list[dict], total: int) -> None:
    """写入供应商列表缓存。

    Args:
        per_page: 每页数量，作为缓存键的一部分。
        items: 供应商字典列表。
        total: 总记录数。
    """
    cache_key = build_cache_key(CacheNamespace.SUPPLIER_LIST, per_page)
    await safe_set(
        cache_key, {'items': items, 'total': total},
        SUPPLIER_LIST_CACHE_TTL, context="供应商列表缓存",
    )


@router.get('/list', response_model=SupplierListResponse)
async def list_suppliers(
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(50, ge=1, le=200, description='每页数量'),
    search: str = Query('', max_length=100, description='搜索关键词'),
    _current_user: User = Depends(require_permission('supplier_manage')),
    db: AsyncSession = Depends(get_db),
) -> SupplierListResponse:
    """供应商列表（支持分页和搜索，带缓存）。

    仅首页（page=1）且无搜索关键词时启用缓存，其余情况直接查询数据库。

    注意：本端点使用主库而非只读副本。供应商管理是低频管理端页面，
    且写操作（创建/编辑/删除）后需立即看到最新数据，使用只读副本会因
    主从复制延迟导致"添加后仍显示暂无数据"的问题。

    Args:
        page: 页码，从 1 开始。
        per_page: 每页数量，1-200。
        search: 搜索关键词，按供应商名称模糊匹配。
        _current_user: 当前登录用户（权限校验依赖）。
        db: 异步数据库会话（主库，确保读写一致性）。

    Returns:
        SupplierListResponse: 供应商列表及总数。
    """
    # 首页无搜索时尝试命中缓存
    if not search and page == 1:
        cached_resp = await _get_cached_supplier_list(per_page)
        if cached_resp is not None:
            return cached_resp

    result = await purchase_supplier_service.get_suppliers(db, page=page, per_page=per_page, search=search)

    # 首页无搜索时写入缓存（服务层已返回 dict 列表，直接缓存）
    if not search and page == 1:
        await _set_cached_supplier_list(per_page, result['items'], result['total'])

    return SupplierListResponse(
        suppliers=[SupplierResponse(**s) for s in result['items']],
        total=result['total'],
    )


@router.post('/create', response_model=SupplierActionResponse)
async def create_supplier(
    data: SupplierCreate,
    _current_user: User = Depends(require_permission('supplier_manage')),
    db: AsyncSession = Depends(get_db),
) -> SupplierActionResponse:
    """添加供应商。

    Args:
        data: 供应商创建数据。
        _current_user: 当前登录用户（权限校验依赖）。
        db: 异步数据库会话。

    Returns:
        SupplierActionResponse: 操作结果。

    Raises:
        HTTPException 400: 供应商名称已存在等业务校验失败。
        HTTPException 500: 数据库操作异常。
    """
    try:
        await purchase_supplier_service.create_supplier(db, {
            'name': data.name, 'contact_person': data.contact_person,
            'phone': data.phone, 'address': data.address, 'remark': data.remark,
        })
        await _invalidate_supplier_caches()  # 提交前失效，避免并发读回填旧缓存
        await db.commit()
    except ValueError as e:
        await db.rollback()
        logger.warning('创建供应商失败（业务校验）: %s', e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except SQLAlchemyError as e:
        await db.rollback()
        logger.exception('创建供应商失败')
        raise HTTPException(status_code=500, detail='供应商添加失败，请稍后重试') from e
    await _invalidate_supplier_caches()  # 提交后再失效一次，确保窗口期内回填的旧缓存被清除
    return SupplierActionResponse(message='供应商添加成功')


@router.put('/edit/{supplier_id}', response_model=SupplierActionResponse)
async def edit_supplier(
    supplier_id: int,
    data: SupplierUpdate,
    _current_user: User = Depends(require_permission('supplier_manage')),
    db: AsyncSession = Depends(get_db),
) -> SupplierActionResponse:
    """编辑供应商。

    Args:
        supplier_id: 供应商 ID。
        data: 供应商更新数据。
        _current_user: 当前登录用户（权限校验依赖）。
        db: 异步数据库会话。

    Returns:
        SupplierActionResponse: 操作结果。

    Raises:
        HTTPException 404: 供应商不存在。
        HTTPException 400: 供应商名称已存在等业务校验失败。
        HTTPException 500: 数据库操作异常。
    """
    try:
        await purchase_supplier_service.update_supplier(db, supplier_id, {
            'name': data.name, 'contact_person': data.contact_person,
            'phone': data.phone, 'address': data.address, 'remark': data.remark,
        })
        await _invalidate_supplier_caches()  # 提交前失效
        await db.commit()
    except ValueError as e:
        await db.rollback()
        if '不存在' in str(e):
            logger.warning('编辑供应商失败（不存在）: supplier_id=%s', supplier_id)
            raise HTTPException(status_code=404, detail='供应商不存在') from e
        logger.warning('编辑供应商失败（业务校验）: supplier_id=%s, %s', supplier_id, e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except SQLAlchemyError as e:
        await db.rollback()
        logger.exception('编辑供应商失败: supplier_id=%s', supplier_id)
        raise HTTPException(status_code=500, detail='供应商编辑失败，请稍后重试') from e
    await _invalidate_supplier_caches()  # 提交后再失效
    return SupplierActionResponse(message='供应商编辑成功')


@router.delete('/delete/{supplier_id}', response_model=SupplierActionResponse)
async def delete_supplier(
    supplier_id: int,
    _current_user: User = Depends(require_permission('supplier_manage')),
    db: AsyncSession = Depends(get_db),
) -> SupplierActionResponse:
    """删除供应商。

    事务模式：手动 commit + catch IntegrityError。
    原因：db_transaction 会将 IntegrityError 转为 HTTP 500，无法对外层提供 400 友好提示。

    Args:
        supplier_id: 供应商 ID。
        _current_user: 当前登录用户（权限校验依赖）。
        db: 异步数据库会话。

    Returns:
        SupplierActionResponse: 操作结果。

    Raises:
        HTTPException 400: 该供应商已有相关单据，无法删除。
        HTTPException 500: 数据库操作异常。
    """
    try:
        await purchase_supplier_service.delete_supplier(db, supplier_id)
        await _invalidate_supplier_caches()  # 提交前失效
        await db.commit()
    except ValueError as e:
        # 服务层抛出：供应商不存在（404）或已关联 BOM/订单（400）
        await db.rollback()
        msg = str(e)
        if '不存在' in msg:
            logger.warning('删除供应商失败（不存在）: supplier_id=%s', supplier_id)
            raise HTTPException(status_code=404, detail='供应商不存在') from e
        logger.info('删除供应商被拒（存在关联单据）: supplier_id=%s', supplier_id)
        raise HTTPException(status_code=400, detail=msg) from e
    except IntegrityError:
        # 兜底：服务层未覆盖到的外键引用（如 MaterialRegistration）
        await db.rollback()
        logger.info('删除供应商被拒（存在关联单据）: supplier_id=%s', supplier_id)
        raise HTTPException(status_code=400, detail='该供应商已有相关单据，无法删除！建议禁用该供应商。') from None
    except SQLAlchemyError as e:
        await db.rollback()
        logger.exception('删除供应商失败: supplier_id=%s', supplier_id)
        raise HTTPException(status_code=500, detail='数据库操作失败') from e
    await _invalidate_supplier_caches()  # 提交后再失效
    return SupplierActionResponse(message='供应商删除成功')


@router.post('/toggle-status/{supplier_id}', response_model=SupplierToggleResponse)
async def toggle_status(
    supplier_id: int,
    _current_user: User = Depends(require_permission('supplier_manage')),
    db: AsyncSession = Depends(get_db),
) -> SupplierToggleResponse:
    """切换供应商启用/禁用状态。

    Args:
        supplier_id: 供应商 ID。
        _current_user: 当前登录用户（权限校验依赖）。
        db: 异步数据库会话。

    Returns:
        SupplierToggleResponse: 切换后的状态及提示消息。

    Raises:
        HTTPException 404: 供应商不存在。
        HTTPException 500: 数据库操作异常。
    """
    # SELECT ... FOR UPDATE 取行锁后再修改状态，防止并发 toggle 互相覆盖（锁逻辑下沉在 service 层）
    supplier = await purchase_supplier_service.get_supplier_for_update(db, supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail='供应商不存在')
    # status 字段可为 None（旧数据），用 bool() 规范化后取反
    supplier.status = not bool(supplier.status)
    try:
        await _invalidate_supplier_caches()  # 提交前失效
        await db.commit()
        await db.refresh(supplier)
    except SQLAlchemyError as e:
        await db.rollback()
        logger.exception('切换供应商状态失败: supplier_id=%s', supplier_id)
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e
    await _invalidate_supplier_caches()  # 提交后再失效
    status_text = '启用' if supplier.status else '禁用'
    return SupplierToggleResponse(status=supplier.status, message=f'供应商已{status_text}')
