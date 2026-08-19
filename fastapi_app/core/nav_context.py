"""
导航权限注入 - 全异步模式

提供 get_nav_sections() 函数，支持两级缓存（进程内 + Redis）。
"""

import asyncio
import logging
import time
from typing import Any

from sqlalchemy.exc import DisconnectionError, OperationalError

logger = logging.getLogger(__name__)

# 每个导航项仅根据自身权限码显示，不再做跨模块映射
# 例外：湖北外发导航由两个权限共同可见（查看 + 管理）
# 湖北订单与湖北外发为两个独立路由页面，各按自身权限显示
SPECIAL_PERMISSION_MAP = {
    'outsource_manage': ['outsource_manage', 'outsource_view'],
}

# 已下线的导航项：不再显示独立导航入口，但权限保留（用户仍可访问页面与接口）
HIDDEN_NAV_CODES = {'order_batch_manage'}

# 权限端点名 → 前端路由路径映射
PERMISSION_URL_MAP = {
    'product.products': '/product',
    'customer_order.index': '/customer-order',
    'beile_order.index': '/beile-order',
    'outsource_manage': '/outsource',
    'outsource_view': '/outsource',
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
}

# 分区显示顺序
SECTION_ORDER = ['dev', 'hubei', 'purchase', 'purchase_tools', 'core', 'data', 'system']

# 两级缓存
_nav_local_cache: dict[str, Any] = {"data": None, "cached_at": 0.0}
_nav_local_ttl = 60
_nav_redis_ttl = 300
_nav_cache_lock = asyncio.Lock()


async def invalidate_nav_cache():
    async with _nav_cache_lock:
        _nav_local_cache["data"] = None
        _nav_local_cache["cached_at"] = 0.0
    from fastapi_app.core.redis_wrapper import safe_delete
    deleted = await safe_delete('nav_sections', context="导航缓存")
    if deleted:
        logger.info("导航缓存已清除")
    else:
        logger.warning("导航缓存清除失败或Redis不可用")


async def get_nav_sections_async() -> dict:
    """
    获取导航分区数据（带两级缓存）- 异步版本。

    返回格式：{section_key: {name: str, items: [{id, name, code, icon, url, permission_codes}]}}
    """
    now = time.time()
    async with _nav_cache_lock:
        if _nav_local_cache["data"] is not None and (now - _nav_local_cache["cached_at"]) < _nav_local_ttl:
            return _nav_local_cache["data"]

    # Level 2: Redis 缓存
    from fastapi_app.core.redis_wrapper import safe_get
    cached = await safe_get('nav_sections', context="导航缓存")
    if cached is not None:
        async with _nav_cache_lock:
            _nav_local_cache["data"] = cached
            _nav_local_cache["cached_at"] = now
        return cached

    # Level 3: 数据库查询（异步）
    try:
        from sqlalchemy import select

        from fastapi_app.core.database import _AsyncSessionLocal
        from fastapi_app.shared_models import Permission

        async with _AsyncSessionLocal() as session:  # type: ignore[misc]
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

        sections: dict[str, dict[str, Any]] = {}
        for item in nav_items:
            section_key = item.section or 'other'
            if section_key not in sections:
                sections[section_key] = {
                    'name': item.section_name or section_key,
                    'items': []
                }

            # 已合并/下线的模块不再显示导航入口
            if item.code in HIDDEN_NAV_CODES or item.url == 'order_batch.index':
                continue

            perm_codes = SPECIAL_PERMISSION_MAP.get(item.code, [item.code])
            if not isinstance(perm_codes, list):
                perm_codes = [perm_codes]
            # 确保自身 code 也包含在内，这样分配了具体权限（如 supplier_manage）的用户也能看到对应导航项
            if item.code not in perm_codes:
                perm_codes = [item.code, *perm_codes]

            mapped_url = PERMISSION_URL_MAP.get(item.url)  # type: ignore[arg-type]
            if mapped_url is None:
                if item.url and not item.url.startswith('/'):
                    logger.warning("Unmapped permission endpoint: %s (code=%s)", item.url, item.code)
                url = item.url if item.url.startswith('/') else f'/{item.url}'  # type: ignore[union-attr]
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
        from fastapi_app.core.redis_wrapper import safe_set
        await safe_set('nav_sections', ordered_sections, timeout=_nav_redis_ttl, context="导航缓存")
        async with _nav_cache_lock:
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

        from fastapi_app.core.redis_wrapper import safe_get
        try:
            loop = _aio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            cached = _aio.run_coroutine_threadsafe(safe_get('nav_sections', context="导航缓存(同步)"), loop).result(timeout=5)
        else:
            cached = _aio.run(safe_get('nav_sections', context="导航缓存(同步)"))
        if cached is not None:
            _nav_local_cache["data"] = cached
            _nav_local_cache["cached_at"] = now
            return cached
    except (OSError, ConnectionError, ValueError, RuntimeError):
        logger.warning("导航同步缓存读取失败", exc_info=True)

    # 返回空数据，让异步版本填充
    return _nav_local_cache["data"] or {}
