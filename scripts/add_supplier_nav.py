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
    # 2026-10-17 审计 P2-73：ORM 直写生产库，接入统一写护栏（fail-closed）
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent('写入导航权限项（生产库）')
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
            import asyncio

            from fastapi_app.core.redis_wrapper import safe_delete

            asyncio.run(safe_delete('nav_sections', context="供应商导航缓存"))
            print("[OK] 已清除导航缓存")
        except Exception as exc:
            print(f"[WARN] 清除导航缓存失败（等待 TTL 过期即可）: {exc}")

        print(f"[OK] 供应商管理导航项已添加 (id={nav.id}, sort_order={next_sort})")
    finally:
        session.close()


if __name__ == '__main__':
    main()
