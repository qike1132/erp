"""
添加排产计划导航项和权限到 Permission 表

运行方式（在项目根目录）:
    python scripts/add_production_plan_nav.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Permission


def main():
    # 2026-10-17 审计 P2-73：ORM 直写生产库，接入统一写护栏（fail-closed）
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent('写入导航权限项（生产库）')
    session = SyncSessionLocal()
    try:
        # 检查是否已存在
        existing = session.query(Permission).filter_by(code='production_plan_view').first()
        if existing:
            print(f"[SKIP] 排产计划导航项已存在 (id={existing.id})")
            return

        # 找到 core section 的最大 sort_order
        core_items = session.query(Permission).filter_by(
            section='core', is_nav=True
        ).order_by(Permission.sort_order.desc()).first()
        next_sort = (core_items.sort_order + 10) if core_items else 10

        # 添加导航项（查看权限）
        nav = Permission(
            name='排产计划',
            code='production_plan_view',
            icon='fa-calendar-alt',
            url='production_plan.plan_list',
            section='core',
            section_name='核心业务',
            sort_order=next_sort,
            is_nav=True,
        )
        session.add(nav)

        # 添加管理权限（子权限，不在导航显示）
        manage_perm = Permission(
            name='管理排产计划',
            code='production_plan_manage',
            parent_id=None,
            is_nav=False,
        )
        session.add(manage_perm)

        session.commit()

        # 清除 Redis 导航缓存
        try:
            import asyncio

            from fastapi_app.core.redis_wrapper import safe_delete

            asyncio.run(safe_delete('nav_sections', context="排产计划导航缓存"))
            print("[OK] 已清除导航缓存")
        except Exception as exc:
            print(f"[WARN] 清除导航缓存失败（等待 TTL 过期即可）: {exc}")

        print(f"[OK] 排产计划导航项已添加 (id={nav.id}, sort_order={next_sort})")
        print("[OK] 排产计划管理权限已添加 (code=production_plan_manage)")
    finally:
        session.close()


if __name__ == '__main__':
    main()
