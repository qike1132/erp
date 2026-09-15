"""
客户管理接口

提供客户的 CRUD、状态切换、搜索及启用名称列表等 HTTP 端点。
列表查询使用 Redis 缓存以降低数据库压力，
所有写操作（创建/编辑/删除/切换状态）会失效相关缓存。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache_keys import CACHE_KEY_PREFIX, CacheNamespace, build_cache_key
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.redis_wrapper import safe_delete, safe_delete_pattern, safe_get, safe_set
from fastapi_app.schemas.customer import (
    CustomerActionResponse,
    CustomerActiveNameItem,
    CustomerCreate,
    CustomerListResponse,
    CustomerResponse,
    CustomerToggleResponse,
    CustomerUpdate,
)
from fastapi_app.services import customer_service
from fastapi_app.shared_models import Customer, User

logger = logging.getLogger(__name__)
router = APIRouter()

# 客户列表缓存 TTL（秒），首页无搜索时缓存 5 分钟
CUSTOMER_LIST_CACHE_TTL = 300
# 客户列表缓存的键模式，用于写操作后批量失效。
# 注意：模式已带 'erp:' 前缀，物理模式是**单前缀** 'erp:customer:list:*'，
# 与 build_cache_key('customer','list',...) 生成的 'erp:customer:list:*' 同层。
# redis_cache._make_key（utils/redis_cache.py）对已带 'erp:' 前缀的 key 原样返回
# （幂等，见 fastapi_app/tests/test_redis_key_namespace.py 的
# test_make_key_is_idempotent_for_prefixed_key 断言）。
# ⚠️ 切勿写成双前缀 'erp:erp:...' —— 那样会匹配不到任何键且静默失效。
CUSTOMER_LIST_CACHE_PATTERN = f"{CACHE_KEY_PREFIX}:{CacheNamespace.CUSTOMER_LIST}:*"
# 启用客户名称缓存键，与 customer_service._ACTIVE_CUSTOMER_CACHE_KEY 保持一致
ACTIVE_CUSTOMER_CACHE_KEY = "active_customer_names"


def _customer_to_resp(c: Customer) -> CustomerResponse:
    """将 Customer ORM 对象转换为 CustomerResponse 响应模型。

    Args:
        c: Customer ORM 实例。

    Returns:
        CustomerResponse: 客户响应数据。
    """
    return CustomerResponse(
        id=c.id, customer_code=c.customer_code, name=c.name, contact=c.contact,
        phone=c.phone, address=c.address, note=c.note, status=c.status,
        create_time=c.create_time.strftime('%Y-%m-%d %H:%M') if c.create_time else None,
    )


async def _invalidate_customer_caches() -> None:
    """失效客户相关缓存（列表缓存 + 启用名称缓存）。

    在所有写操作（创建/编辑/删除/切换状态）后调用，
    确保后续读取获取最新数据。
    """
    await safe_delete_pattern(CUSTOMER_LIST_CACHE_PATTERN, context="客户列表缓存")
    await safe_delete(ACTIVE_CUSTOMER_CACHE_KEY, context="客户启用名称缓存")


async def _get_cached_customer_list(status: str | None, per_page: int) -> CustomerListResponse | None:
    """从缓存读取客户列表（仅首页无搜索时使用）。

    Args:
        status: 状态筛选条件（active/inactive/None），作为缓存键的一部分。
        per_page: 每页数量，作为缓存键的一部分。

    Returns:
        CustomerListResponse | None: 命中缓存返回响应对象，未命中返回 None。
    """
    cache_key = build_cache_key(CacheNamespace.CUSTOMER_LIST, status or 'all', per_page)
    cached = await safe_get(cache_key, context="客户列表缓存")
    if cached is None:
        return None
    return CustomerListResponse(
        customers=[CustomerResponse(**c) for c in cached['items']],
        total=cached['total'],
    )


async def _set_cached_customer_list(status: str | None, per_page: int, items: list[dict], total: int) -> None:
    """写入客户列表缓存。

    Args:
        status: 状态筛选条件（active/inactive/None），作为缓存键的一部分。
        per_page: 每页数量，作为缓存键的一部分。
        items: 客户字典列表。
        total: 总记录数。
    """
    cache_key = build_cache_key(CacheNamespace.CUSTOMER_LIST, status or 'all', per_page)
    await safe_set(
        cache_key, {'items': items, 'total': total},
        CUSTOMER_LIST_CACHE_TTL, context="客户列表缓存",
    )


def _customer_in_use_error(_exc: IntegrityError) -> HTTPException:
    """客户被引用触发外键约束 —— 属预期业务场景，降级为 INFO 日志并返回 400。

    作为 db_transaction 的 error_map 回调使用：rollback 由 db_transaction 统一
    执行，端点无需手写 try/except/commit。

    注意：保持 detail 为纯字符串，与本项目既有端点风格一致（133 处），
    避免改变前端已依赖的响应结构。
    """
    logger.info('删除客户被拒（存在关联单据）')
    return HTTPException(
        status_code=400,
        detail='该客户已有相关单据，无法删除！建议禁用该客户。',
    )


@router.get('/list', response_model=CustomerListResponse)
async def list_customers(
    status: str | None = Query(None, description='状态筛选: active/inactive'),
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(50, ge=1, le=200, description='每页数量'),
    search: str = Query('', max_length=100, description='搜索关键词'),
    _current_user: User = Depends(require_permission('customer_manage')),
    db: AsyncSession = Depends(get_async_db),
) -> CustomerListResponse:
    """客户列表（带缓存，支持分页和搜索）。

    仅首页（page=1）且无搜索关键词时启用缓存，其余情况直接查询数据库。

    注意：本端点使用主库而非只读副本。客户管理是低频管理端页面，
    且写操作（创建/编辑/删除）后需立即看到最新数据，使用只读副本会因
    主从复制延迟导致"添加后仍显示暂无数据"的问题。

    Args:
        status: 状态筛选，可选值 active/inactive/None（全部）。
        page: 页码，从 1 开始。
        per_page: 每页数量，1-200。
        search: 搜索关键词，按名称/联系人/电话模糊匹配。
        _current_user: 当前登录用户（权限校验依赖）。
        db: 异步数据库会话（主库，确保读写一致性）。

    Returns:
        CustomerListResponse: 客户列表及总数。
    """
    # 首页无搜索时尝试命中缓存
    if not search and page == 1:
        cached_resp = await _get_cached_customer_list(status, per_page)
        if cached_resp is not None:
            return cached_resp

    result = await customer_service.get_customers(db, status, page=page, per_page=per_page, search=search)
    customer_dicts = [_customer_to_resp(c).model_dump() for c in result['items']]

    # 首页无搜索时写入缓存
    if not search and page == 1:
        await _set_cached_customer_list(status, per_page, customer_dicts, result['total'])

    return CustomerListResponse(
        customers=[_customer_to_resp(c) for c in result['items']],
        total=result['total'],
    )


@router.get('/search', response_model=list[CustomerResponse])
async def search_customers(
    q: str = Query('', description='搜索关键词'),
    _current_user: User = Depends(require_permission('customer_manage')),
    db: AsyncSession = Depends(get_async_read_db),
) -> list[CustomerResponse]:
    """客户搜索。

    按名称/联系人/电话模糊匹配，仅返回启用状态的客户，最多 20 条。

    Args:
        q: 搜索关键词，空字符串返回空列表。
        _current_user: 当前登录用户（权限校验依赖）。
        db: 异步数据库会话（只读副本）。

    Returns:
        list[CustomerResponse]: 匹配的客户列表。
    """
    if not q.strip():
        return []
    customers = await customer_service.search_customers(db, q.strip())
    return [_customer_to_resp(c) for c in customers]


@router.get('/active-names', response_model=list[CustomerActiveNameItem])
async def active_names(
    _current_user: User = Depends(require_permission('customer_manage')),
    db: AsyncSession = Depends(get_async_read_db),
) -> list[CustomerActiveNameItem]:
    """获取所有启用客户名称列表（用于下拉选择）。

    Args:
        _current_user: 当前登录用户（权限校验依赖）。
        db: 异步数据库会话（只读副本）。

    Returns:
        list[CustomerActiveNameItem]: 启用状态的客户 ID 和名称列表。
    """
    return await customer_service.get_active_customer_names(db)


@router.get('/{customer_id}', response_model=CustomerResponse)
async def get_customer(
    customer_id: int,
    _current_user: User = Depends(require_permission('customer_manage')),
    db: AsyncSession = Depends(get_async_read_db),
) -> CustomerResponse:
    """获取单个客户详情。

    Args:
        customer_id: 客户 ID。
        _current_user: 当前登录用户（权限校验依赖）。
        db: 异步数据库会话（只读副本）。

    Returns:
        CustomerResponse: 客户详情。

    Raises:
        HTTPException 404: 客户不存在。
    """
    customer = await customer_service.get_customer(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail='客户不存在')
    return _customer_to_resp(customer)


@router.post('/create', response_model=CustomerActionResponse)
async def create_customer(
    data: CustomerCreate,
    _current_user: User = Depends(require_permission('customer_manage')),
    db: AsyncSession = Depends(get_async_db),
) -> CustomerActionResponse:
    """添加客户。

    Args:
        data: 客户创建数据。
        _current_user: 当前登录用户（权限校验依赖）。
        db: 异步数据库会话。

    Returns:
        CustomerActionResponse: 操作结果。
    """
    async with db_transaction(db):
        await customer_service.create_customer(db, data.name, data.contact, data.phone, data.address, data.note)
    await _invalidate_customer_caches()
    return CustomerActionResponse(message='客户添加成功')


@router.put('/edit/{customer_id}', response_model=CustomerActionResponse)
async def edit_customer(
    customer_id: int,
    data: CustomerUpdate,
    _current_user: User = Depends(require_permission('customer_manage')),
    db: AsyncSession = Depends(get_async_db),
) -> CustomerActionResponse:
    """编辑客户。

    Args:
        customer_id: 客户 ID。
        data: 客户更新数据。
        _current_user: 当前登录用户（权限校验依赖）。
        db: 异步数据库会话。

    Returns:
        CustomerActionResponse: 操作结果。
    """
    async with db_transaction(db):
        await customer_service.update_customer(
            db, customer_id, data.name, data.contact, data.phone,
            data.address, data.note, data.status,
        )
    await _invalidate_customer_caches()
    return CustomerActionResponse(message='客户编辑成功')


@router.delete('/delete/{customer_id}', response_model=CustomerActionResponse)
async def delete_customer(
    customer_id: int,
    _current_user: User = Depends(require_permission('customer_manage')),
    db: AsyncSession = Depends(get_async_db),
) -> CustomerActionResponse:
    """删除客户。

    事务模式：db_transaction + error_map 异常映射。
    commit/rollback 由 db_transaction 统一执行，端点只声明 HTTP 语义
    （与 outsource.py / purchase_plan.py 保持一致）。

    异常映射：
        - IntegrityError（客户被引用）→ 400 友好提示
        - SQLAlchemyError → 500 "数据库操作失败"（db_transaction 默认规则）

    Args:
        customer_id: 客户 ID。
        _current_user: 当前登录用户（权限校验依赖）。
        db: 异步数据库会话。

    Returns:
        CustomerActionResponse: 操作结果。

    Raises:
        HTTPException 400: 该客户已有相关单据，无法删除。
        HTTPException 500: 数据库操作异常。
    """
    async with db_transaction(db, error_map={IntegrityError: _customer_in_use_error}):
        await customer_service.delete_customer(db, customer_id)
    await _invalidate_customer_caches()
    return CustomerActionResponse(message='客户删除成功')


@router.post('/toggle-status/{customer_id}', response_model=CustomerToggleResponse)
async def toggle_status(
    customer_id: int,
    _current_user: User = Depends(require_permission('customer_manage')),
    db: AsyncSession = Depends(get_async_db),
) -> CustomerToggleResponse:
    """切换客户启用/禁用状态。

    Args:
        customer_id: 客户 ID。
        _current_user: 当前登录用户（权限校验依赖）。
        db: 异步数据库会话。

    Returns:
        CustomerToggleResponse: 切换后的状态及提示消息。
    """
    async with db_transaction(db):
        customer = await customer_service.toggle_customer_status(db, customer_id)
    await _invalidate_customer_caches()
    status_text = '启用' if customer.status else '禁用'
    return CustomerToggleResponse(status=customer.status, message=f'客户已{status_text}')
