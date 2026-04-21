"""
添加生产计划导航项到 Permission 表

将现有的"排产计划"导航更新为"生产计划"，指向新的生产计划页面
（包含手工部、包装部、汇总报表三个Tab）

运行方式（在项目根目录）:
    python scripts/add_production_summary_nav.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Permission


def main():
    session = SyncSessionLocal()
    try:
        # 查找已有的排产计划导航项
        existing = session.query(Permission).filter_by(code='production_plan_view').first()

        if existing:
            # 更新现有导航项指向新页面
            existing.name = '生产计划'
            existing.icon = 'fa-industry'
            existing.url = 'production_summary.index'
            existing.section = 'core'
            existing.section_name = '核心业务'
            session.commit()
            print(f"[OK] 已更新排产计划导航项 -> 生产计划 (id={existing.id})")
        else:
            # 不存在则创建新的导航项
            core_items = session.query(Permission).filter_by(
                section='core', is_nav=True
            ).order_by(Permission.sort_order.desc()).first()
            next_sort = (core_items.sort_order + 10) if core_items else 10

            nav = Permission(
                name='生产计划',
                code='production_plan_view',
                icon='fa-industry',
                url='production_summary.index',
                section='core',
                section_name='核心业务',
                sort_order=next_sort,
                is_nav=True,
            )
            session.add(nav)

            # 添加管理权限
            manage_perm = Permission(
                name='管理生产计划',
                code='production_plan_manage',
                parent_id=None,
                is_nav=False,
            )
            session.add(manage_perm)

            session.commit()
            print(f"[OK] 生产计划导航项已添加 (id={nav.id}, sort_order={next_sort})")
            print(f"[OK] 生产计划管理权限已添加 (code=production_plan_manage)")

        # 确保 production_plan_manage 权限也存在
        manage_existing = session.query(Permission).filter_by(code='production_plan_manage').first()
        if not manage_existing:
            manage_perm = Permission(
                name='管理生产计划',
                code='production_plan_manage',
                parent_id=None,
                is_nav=False,
            )
            session.add(manage_perm)
            session.commit()
            print(f"[OK] 生产计划管理权限已添加 (code=production_plan_manage)")

        # 清除 Redis 导航缓存
        try:
            from utils.redis_cache import redis_cache
            redis_cache.delete('nav_sections')
            print("[OK] 已清除导航缓存")
        except Exception:
            print("[WARN] 清除导航缓存失败，请手动重启或等待缓存过期")
    finally:
        session.close()


if __name__ == '__main__':
    main()
