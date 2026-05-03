"""
添加供应商管理导航项到 Permission 表

运行方式（在项目根目录）:
    python scripts/add_supplier_nav.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Permission


def main():
    session = SyncSessionLocal()
    try:
        # 检查是否已存在
        existing = session.query(Permission).filter_by(code='supplier_manage').first()
        if existing:
            print(f"[SKIP] 供应商管理导航项已存在 (id={existing.id})")
            return

        # 找到合适的 sort_order（放在 purchase section 的采购中心之后）
        purchase_items = session.query(Permission).filter_by(
            section='purchase', is_nav=True
        ).order_by(Permission.sort_order.desc()).first()
        next_sort = (purchase_items.sort_order + 10) if purchase_items else 50

        nav = Permission(
            name='供应商管理',
            code='supplier_manage',
            icon='fa-truck',
            url='supplier.suppliers',
            section='purchase',
            section_name='采购管理',
            sort_order=next_sort,
            is_nav=True,
        )
        session.add(nav)
        session.commit()

        # 清除 Redis 导航缓存
        try:
            from utils.redis_cache import redis_cache
            redis_cache.delete('nav_sections')
            print("[OK] 已清除导航缓存")
        except Exception:
            print("[WARN] 清除导航缓存失败，请手动重启或等待缓存过期")

        print(f"[OK] 供应商管理导航项已添加 (id={nav.id}, sort_order={next_sort})")
    finally:
        session.close()


if __name__ == '__main__':
    main()
