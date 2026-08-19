"""
修复采购中心导航权限记录

确保 permission 表中 purchase_center_manage 记录具有正确的导航字段：
- url = 'purchase_center.index' (映射到前端 /purchase 路由)
- section = 'purchase'
- section_name = '采购中心'
- is_nav = True
- icon = 'fa-store'
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Permission


def fix_purchase_center_nav():
    session = SyncSessionLocal()
    try:
        # 查找采购中心权限记录
        perm = session.query(Permission).filter(
            Permission.code == 'purchase_center_manage'
        ).first()

        if perm is None:
            # 记录不存在，创建新的
            max_sort = session.query(Permission).filter(
                Permission.section == 'purchase'
            ).count()

            perm = Permission(
                name='采购中心(全部)',
                code='purchase_center_manage',
                icon='fa-store',
                url='purchase_center.index',
                section='purchase',
                section_name='采购中心',
                sort_order=max_sort + 1,
                is_nav=True,
            )
            session.add(perm)
            session.commit()
            print(f"已创建采购中心权限记录: id={perm.id}, code={perm.code}, url={perm.url}, section={perm.section}")
        else:
            # 记录存在但可能缺少导航字段，更新之
            changed = False
            if perm.url != 'purchase_center.index':
                old = perm.url
                perm.url = 'purchase_center.index'
                changed = True
                print(f"  更新 url: '{old}' -> 'purchase_center.index'")
            if perm.section != 'purchase':
                old = perm.section
                perm.section = 'purchase'
                changed = True
                print(f"  更新 section: '{old}' -> 'purchase'")
            if perm.section_name != '采购中心':
                old = perm.section_name
                perm.section_name = '采购中心'
                changed = True
                print(f"  更新 section_name: '{old}' -> '采购中心'")
            if perm.icon != 'fa-store':
                old = perm.icon
                perm.icon = 'fa-store'
                changed = True
                print(f"  更新 icon: '{old}' -> 'fa-store'")
            if not perm.is_nav:
                perm.is_nav = True
                changed = True
                print("  更新 is_nav: False -> True")

            if changed:
                session.commit()
                print(f"已更新采购中心权限记录: id={perm.id}, code={perm.code}")
            else:
                print(f"采购中心权限记录已正确配置，无需更新: id={perm.id}")

        # 同时修复所有其他常见导航项的 section/section_name
        _fix_other_nav_sections(session)

        # 清除导航缓存，使修改立即生效
        _clear_nav_cache()

        # 验证结果
        print("\n--- 验证 ---")
        nav_items = session.query(Permission).filter(
            Permission.parent_id.is_(None),
            Permission.is_nav,
            Permission.url.isnot(None),
        ).order_by(Permission.section, Permission.sort_order).all()

        sections = {}
        for item in nav_items:
            key = item.section or 'other'
            if key not in sections:
                sections[key] = []
            sections[key].append(f"  {item.name} (code={item.code}, url={item.url})")

        for key, items in sections.items():
            print(f"\n[{key}]")
            for i in items:
                print(i)

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _clear_nav_cache():
    """清除导航缓存（进程内 + Redis），使修改立即生效"""
    # 清除进程内缓存
    from fastapi_app.core.nav_context import _nav_local_cache
    _nav_local_cache["data"] = None
    _nav_local_cache["cached_at"] = 0.0
    print("已清除进程内导航缓存")

    # 清除 Redis 缓存
    try:
        import asyncio

        from utils.redis_cache import redis_cache
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(redis_cache.delete('nav_sections'), loop).result(timeout=5)
        else:
            asyncio.run(redis_cache.delete('nav_sections'))
        print("已清除Redis导航缓存")
    except (OSError, ConnectionError, ValueError, RuntimeError):
        print("Redis导航缓存清除失败（可忽略，等待5分钟自动过期）")


def _fix_other_nav_sections(session):
    """修复其他权限记录的 section/section_name/url/is_nav 字段"""
    NAV_CONFIG = {
        'product_manage': {'url': 'product.products', 'section': 'core', 'section_name': '核心业务', 'icon': 'fa-box'},
        'order_manage': {'url': 'customer_order.index', 'section': 'core', 'section_name': '核心业务', 'icon': 'fa-shopping-cart'},
        'stockin_manage': {'url': 'stock.stockins', 'section': 'core', 'section_name': '核心业务', 'icon': 'fa-truck-loading'},
        'stockout_manage': {'url': 'stock.stockouts', 'section': 'core', 'section_name': '核心业务', 'icon': 'fa-truck'},
        'case_manage': {'url': 'case.case_management_page', 'section': 'core', 'section_name': '核心业务', 'icon': 'fa-suitcase'},
        'report_manage': {'url': 'report.reports', 'section': 'data', 'section_name': '数据中心', 'icon': 'fa-chart-bar'},
        'approval_manage': {'url': 'approval.approval_list', 'section': 'core', 'section_name': '核心业务', 'icon': 'fa-clipboard-check'},
        'customer_manage': {'url': 'customer.customers', 'section': 'core', 'section_name': '核心业务', 'icon': 'fa-building'},
        'supplier_manage': {'url': 'supplier.suppliers', 'section': 'purchase', 'section_name': '采购中心', 'icon': 'fa-truck'},
        'user_manage': {'url': None, 'section': 'system', 'section_name': '系统管理', 'icon': 'fa-users-cog', 'is_nav': False},
        'permission_manage': {'url': None, 'section': 'system', 'section_name': '系统管理', 'icon': 'fa-shield-alt', 'is_nav': False},
        'production_summary_manage': {'url': 'production_summary.index', 'section': 'core', 'section_name': '核心业务', 'icon': 'fa-industry'},
        'batch_manage': {'url': 'sku_batch.sku_batch_page', 'section': 'core', 'section_name': '核心业务', 'icon': 'fa-table-cells'},
    }

    for code, config in NAV_CONFIG.items():
        perm = session.query(Permission).filter(Permission.code == code).first()
        if perm is None:
            continue

        changed = False
        if config.get('url') is not None and perm.url != config['url']:
            perm.url = config['url']
            changed = True
        if perm.section != config.get('section', perm.section):
            perm.section = config['section']
            changed = True
        if perm.section_name != config.get('section_name', perm.section_name):
            perm.section_name = config['section_name']
            changed = True
        if config.get('icon') and perm.icon != config['icon']:
            perm.icon = config['icon']
            changed = True
        if 'is_nav' in config and perm.is_nav != config['is_nav']:
            perm.is_nav = config['is_nav']
            changed = True

        if changed:
            print(f"  修复 {code}: url={perm.url}, section={perm.section}, section_name={perm.section_name}")

    session.commit()


if __name__ == '__main__':
    fix_purchase_center_nav()
