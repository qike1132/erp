"""
模板上下文：导航权限注入 - 全异步模式

替代 Flask 的 inject_nav_permissions 上下文处理器。
提供 get_nav_sections() 函数，支持两级缓存（进程内 + Redis）。
"""

import logging
import time

from sqlalchemy.exc import DisconnectionError, OperationalError

logger = logging.getLogger(__name__)

# 每个导航项仅根据自身权限码显示，不再做跨模块映射
SPECIAL_PERMISSION_MAP = {}

# Flask 端点名 → FastAPI 路由路径映射
FLASK_TO_FASTAPI_URL_MAP = {
    'product.products': '/product',
    'customer_order.index': '/customer-order',
    'stock.stockins': '/stock',
    'stock.stockouts': '/stock-out',
    'stock.inventory': '/stock',
    'case.case_management_page': '/case',
    'report.reports': '/report',
    'approval.approval_list': '/approval',
    'user.users': '/user',
    'customer.customers': '/customer',
    'purchase_center.index': '/purchase',
    'material.calculator': '/material-calculator',
    'material_registration.material_registration_page': '/material',
    'material_registration.index': '/material',
    'supplier.suppliers': '/supplier',
    'sku_batch.sku_batch_page': '/batch',
    'production_plan.plan_list': '/production',
    'production_summary.index': '/production',
    'purchase_plan.plan_list': '/purchase-plan',
    'backup.index': '/backup',
    'app_update.index': '/app-update',
    'order_batch.index': '/order-batch',
}

# 分区显示顺序
SECTION_ORDER = ['purchase', 'purchase_tools', 'core', 'data', 'system']

# 两级缓存
_nav_local_cache = {"data": None, "cached_at": 0.0}
_nav_local_ttl = 60  # 进程内缓存 60 秒
_nav_redis_ttl = 300  # Redis 缓存 5 分钟


async def invalidate_nav_cache():
    """清除导航缓存"""
    _nav_local_cache["data"] = None
    _nav_local_cache["cached_at"] = 0.0
    try:
        from utils.redis_cache import redis_cache
        await redis_cache.delete('nav_sections')
        logger.info("导航缓存已清除")
    except (OSError, ConnectionError, ValueError):
        logger.warning("导航缓存清除失败", exc_info=True)


async def get_nav_sections_async() -> dict:
    """
    获取导航分区数据（带两级缓存）- 异步版本。

    返回格式：{section_key: {name: str, items: [{id, name, code, icon, url, permission_codes}]}}
    """
    # Level 1: 进程内缓存
    now = time.time()
    if _nav_local_cache["data"] is not None and (now - _nav_local_cache["cached_at"]) < _nav_local_ttl:
        return _nav_local_cache["data"]

    # Level 2: Redis 缓存
    try:
        from utils.redis_cache import redis_cache
        cached = await redis_cache.get('nav_sections')
        if cached is not None:
            _nav_local_cache["data"] = cached
            _nav_local_cache["cached_at"] = now
            return cached
    except (OSError, ConnectionError, ValueError):
        logger.warning("导航Redis缓存读取失败", exc_info=True)

    # Level 3: 数据库查询（异步）
    try:
        from sqlalchemy import select

        from fastapi_app.core.database import _AsyncSessionLocal
        from fastapi_app.shared_models import Permission

        async with _AsyncSessionLocal() as session:
            result = await session.execute(
                select(Permission)
                .where(
                    Permission.parent_id.is_(None),
                    Permission.is_nav,
                    Permission.url.isnot(None),
                )
                .order_by(Permission.section, Permission.sort_order)
            )
            nav_items = result.scalars().all()

        sections = {}
        for item in nav_items:
            section_key = item.section or 'other'
            if section_key not in sections:
                sections[section_key] = {
                    'name': item.section_name or section_key,
                    'items': []
                }

            perm_codes = SPECIAL_PERMISSION_MAP.get(item.code, [item.code])
            if not isinstance(perm_codes, list):
                perm_codes = [perm_codes]
            # 确保自身 code 也包含在内，这样分配了具体权限（如 supplier_manage）的用户也能看到对应导航项
            if item.code not in perm_codes:
                perm_codes = [item.code] + perm_codes

            mapped_url = FLASK_TO_FASTAPI_URL_MAP.get(item.url)
            if mapped_url is None:
                if item.url and not item.url.startswith('/'):
                    logger.warning("Unmapped Flask endpoint in permission.url: %s (code=%s)", item.url, item.code)
                url = item.url if item.url.startswith('/') else f'/{item.url}'
            else:
                url = mapped_url

            sections[section_key]['items'].append({
                'id': item.id,
                'name': item.name,
                'code': item.code,
                'icon': item.icon,
                'url': url,
                'permission_codes': perm_codes,
            })

        # 按 SECTION_ORDER 排序
        ordered_sections = {}
        for key in SECTION_ORDER:
            if key in sections:
                ordered_sections[key] = sections[key]
        for key in sections:
            if key not in ordered_sections:
                ordered_sections[key] = sections[key]

        # 写入缓存
        try:
            from utils.redis_cache import redis_cache
            await redis_cache.set('nav_sections', ordered_sections, timeout=_nav_redis_ttl)
        except (OSError, ConnectionError, ValueError):
            logger.warning("导航Redis缓存写入失败", exc_info=True)
        _nav_local_cache["data"] = ordered_sections
        _nav_local_cache["cached_at"] = time.time()

        return ordered_sections
    except (OperationalError, DisconnectionError) as e:
        logger.warning("获取导航权限数据失败: %s [%s]", e, type(e).__name__)
        return _nav_local_cache["data"] or {}


def get_nav_sections() -> dict:
    """
    获取导航分区数据 - 同步包装器（已废弃，保留向后兼容）。

    注意：此函数已废弃，请使用 get_nav_sections_async()。
    """
    import warnings
    warnings.warn(
        "get_nav_sections() 已废弃，请使用 get_nav_sections_async()",
        DeprecationWarning,
        stacklevel=2
    )

    # 尝试从缓存获取
    now = time.time()
    if _nav_local_cache["data"] is not None and (now - _nav_local_cache["cached_at"]) < _nav_local_ttl:
        return _nav_local_cache["data"]

    try:
        import asyncio as _aio

        from utils.redis_cache import redis_cache
        try:
            loop = _aio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            cached = _aio.run_coroutine_threadsafe(redis_cache.get('nav_sections'), loop).result(timeout=5)
        else:
            cached = _aio.run(redis_cache.get('nav_sections'))
        if cached is not None:
            _nav_local_cache["data"] = cached
            _nav_local_cache["cached_at"] = now
            return cached
    except (OSError, ConnectionError, ValueError, RuntimeError):
        logger.warning("导航同步缓存读取失败", exc_info=True)

    # 返回空数据，让异步版本填充
    return _nav_local_cache["data"] or {}
