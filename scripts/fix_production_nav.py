"""
修复导航项：恢复"排产计划"原始配置，新增独立的"生产计划"导航项

原因：开发"生产计划"模块时，错误地将已有的"排产计划"导航项（ID=224）
覆盖为"生产计划"，导致"排产计划"入口丢失。

运行方式（在项目根目录）:
    python scripts/fix_production_nav.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Permission


def main():
    session = SyncSessionLocal()
    try:

        # ========== 1. 恢复"排产计划"导航项 ==========
        pp_view = session.query(Permission).filter_by(code='production_plan_view').first()
        if pp_view:
            pp_view.name = '排产计划'
            pp_view.icon = 'fa-calendar-alt'
            pp_view.url = 'production_plan.plan_list'
            pp_view.section = 'core'
            pp_view.section_name = '核心业务'
            pp_view.is_nav = True
            print(f"[OK] 恢复排产计划导航项 (id={pp_view.id})")
        else:
            print("[WARN] 未找到 production_plan_view 权限记录，跳过恢复")

        pp_manage = session.query(Permission).filter_by(code='production_plan_manage').first()
        if pp_manage:
            pp_manage.name = '管理排产计划'
            print(f"[OK] 恢复排产计划管理权限名称 (id={pp_manage.id})")

        # ========== 2. 新增独立的"生产计划"导航项 ==========
        ps_view = session.query(Permission).filter_by(code='production_summary_view').first()
        if ps_view:
            print(f"[SKIP] 生产计划导航项已存在 (id={ps_view.id})")
        else:
            # 找到 core section 的最大 sort_order
            core_items = session.query(Permission).filter_by(
                section='core', is_nav=True
            ).order_by(Permission.sort_order.desc()).first()
            next_sort = (core_items.sort_order + 10) if core_items else 10

            nav = Permission(
                name='生产报表',
                code='production_summary_view',
                icon='fa-industry',
                url='production_summary.index',
                section='core',
                section_name='核心业务',
                sort_order=next_sort,
                is_nav=True,
            )
            session.add(nav)

            # 添加管理权限（不在导航显示）
            manage_perm = Permission(
                name='管理生产报表',
                code='production_summary_manage',
                parent_id=None,
                is_nav=False,
            )
            session.add(manage_perm)

            print(f"[OK] 新增生产计划导航项 (sort_order={next_sort})")
            print("[OK] 新增生产计划管理权限 (code=production_summary_manage)")

        session.commit()

        # ========== 3. 清除导航缓存 ==========
        try:
            from utils.redis_cache import redis_cache
            redis_cache.delete('nav_sections')
            print("[OK] 已清除导航缓存")
        except Exception:
            print("[WARN] 清除导航缓存失败，请手动重启或等待缓存过期")

        # ========== 4. 验证 ==========
        print("\n--- 验证结果 ---")
        for code in ['production_plan_view', 'production_plan_manage',
                      'production_summary_view', 'production_summary_manage']:
            p = session.query(Permission).filter_by(code=code).first()
            if p:
                nav_flag = '[NAV]' if p.is_nav else '[HIDDEN]'
                print(f"  {nav_flag} id={p.id}, name={p.name}, code={p.code}, url={p.url or '-'}")
            else:
                print(f"  [MISSING] code={code}")
    finally:
        session.close()


if __name__ == '__main__':
    main()
