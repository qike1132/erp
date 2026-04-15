"""
添加财务统计导航项到 Permission 表

运行方式（在项目根目录）:
    python scripts/add_finance_nav.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import create_app, db
from app.models import Permission


def main():
    app = create_app()
    with app.app_context():
        # 检查是否已存在
        existing = Permission.query.filter_by(code='finance_view').first()
        if existing:
            print(f"[SKIP] 财务统计导航项已存在 (id={existing.id})")
            return

        # 找到合适的 sort_order（放在 finance section 的第一个位置）
        finance_items = Permission.query.filter_by(
            section='finance', is_nav=True
        ).order_by(Permission.sort_order.desc()).first()
        next_sort = (finance_items.sort_order + 10) if finance_items else 10

        # 添加导航项
        nav = Permission(
            name='财务统计',
            code='finance_view',
            icon='fa-yen-sign',
            url='finance.statistics',
            section='finance',
            section_name='财务',
            sort_order=next_sort,
            is_nav=True,
        )
        db.session.add(nav)

        # 同时添加子权限（用于细粒度控制，预留）
        view_perm = Permission(
            name='查看财务',
            code='finance_view',
            parent_id=None,  # 与导航项相同code，导航项本身就是查看权限
            is_nav=False,
        )
        # 不重复添加相同code的权限，导航项已包含finance_view权限

        db.session.commit()

        # 清除 Redis 导航缓存
        try:
            from utils.redis_cache import redis_cache
            redis_cache.delete('nav_sections')
            print("[OK] 已清除导航缓存")
        except Exception:
            print("[WARN] 清除导航缓存失败，请手动重启或等待缓存过期")

        print(f"[OK] 财务统计导航项已添加 (id={nav.id}, sort_order={next_sort})")


if __name__ == '__main__':
    main()
