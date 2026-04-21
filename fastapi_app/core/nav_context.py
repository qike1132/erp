"""
模板上下文：导航权限注入

替代 Flask 的 inject_nav_permissions 上下文处理器。
提供 get_nav_sections() 函数，支持两级缓存（进程内 + Redis），
供 FastAPI Jinja2 模板渲染时使用。
"""

import time
import logging
import os

from fastapi_app.core.config import settings

logger = logging.getLogger(__name__)

# 权限映射：某些导航项需要多权限码任一匹配即显示
SPECIAL_PERMISSION_MAP = {
    'material_calculator': 'product_manage',
    'material_registration': 'product_manage',
    'supplier_manage': 'product_manage',
    'stock_view': ['stock_view', 'stockin_manage', 'stockout_manage'],
    'order_manage': ['order_manage', 'stockin_manage'],
    'production_plan_view': ['production_plan_view', 'production_plan_manage'],
    'production_summary_view': ['production_summary_view', 'production_summary_manage'],
}

# Flask 端点名 → FastAPI 路由路径映射
# 数据库 permission.url 存储的是 Flask url_for 端点名（如 product.products），
# 但 FastAPI 不识别这些路径，需要映射为实际的路由路径。
FLASK_TO_FASTAPI_URL_MAP = {
    'product.products': '/product/list',
    'customer_order.index': '/customer-order/',
    'stock.stockins': '/stock/stockins',
    'stock.stockouts': '/stock/stockouts',
    'stock.inventory': '/stock/inventory',
    'case.case_management_page': '/case/',
    'report.reports': '/report/reports',
    'approval.approval_list': '/order/my-approvals',
    'user.users': '/user/list',
    'customer.customers': '/customer/list',
    'purchase_center.index': '/purchase-center/',
    'material.calculator': '/material/calculator',
    'material_registration.material_registration_page': '/material-registration/page',
    'material_registration.index': '/material-registration/page',
    'supplier.suppliers': '/supplier/list',
    'sku_batch.sku_batch_page': '/batch/management',
    'finance.statistics': '/finance/statistics',
    'production_plan.plan_list': '/production-plan/list',
    'production_summary.index': '/production-summary/list',
    'purchase_plan.plan_list': '/plans/list',
}

# 分区显示顺序
SECTION_ORDER = ['purchase', 'purchase_tools', 'core', 'finance', 'data', 'system']

# 两级缓存
_nav_local_cache = {"data": None, "cached_at": 0.0}
_nav_local_ttl = 60  # 进程内缓存 60 秒
_nav_redis_ttl = 300  # Redis 缓存 5 分钟


def invalidate_nav_cache():
    """清除导航缓存，使下次请求重新从数据库加载并应用 URL 映射。"""
    _nav_local_cache["data"] = None
    _nav_local_cache["cached_at"] = 0.0
    try:
        from utils.redis_cache import redis_cache
        redis_cache.delete('nav_sections')
        logger.info("导航缓存已清除")
    except Exception:
        pass


def get_nav_sections() -> dict:
    """
    获取导航分区数据（带两级缓存）。

    返回格式：{section_key: {name: str, items: [{id, name, code, icon, url, permission_codes}]}}
    """
    # Level 1: 进程内缓存
    now = time.time()
    if _nav_local_cache["data"] is not None and (now - _nav_local_cache["cached_at"]) < _nav_local_ttl:
        return _nav_local_cache["data"]

    # Level 2: Redis 缓存
    try:
        from utils.redis_cache import redis_cache
        cached = redis_cache.get('nav_sections')
        if cached is not None:
            _nav_local_cache["data"] = cached
            _nav_local_cache["cached_at"] = now
            return cached
    except Exception:
        pass

    # Level 3: 数据库查询
    try:
        from fastapi_app.core.database import SyncSessionLocal
        from fastapi_app.shared_models import Permission
        from sqlalchemy import select

        db = SyncSessionLocal()
        try:
            result = db.execute(
                select(Permission)
                .where(
                    Permission.parent_id.is_(None),
                    Permission.is_nav == True,
                    Permission.url.isnot(None),
                )
                .order_by(Permission.section, Permission.sort_order)
            )
            nav_items = result.scalars().all()
        finally:
            db.close()

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

            sections[section_key]['items'].append({
                'id': item.id,
                'name': item.name,
                'code': item.code,
                'icon': item.icon,
                'url': FLASK_TO_FASTAPI_URL_MAP.get(item.url, item.url if item.url.startswith('/') else f'/{item.url}'),
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
            redis_cache.set('nav_sections', ordered_sections, timeout=_nav_redis_ttl)
        except Exception:
            pass
        _nav_local_cache["data"] = ordered_sections
        _nav_local_cache["cached_at"] = time.time()

        return ordered_sections
    except Exception as e:
        logger.warning("获取导航权限数据失败: %s [%s]", e, type(e).__name__)
        return _nav_local_cache["data"] or {}
