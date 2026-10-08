"""
添加数据备份导航项到 Permission 表

运行方式（在项目根目录）:
    python scripts/add_backup_nav.py
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
        existing = session.query(Permission).filter_by(code='backup_manage').first()
        if existing:
            print(f"[SKIP] 数据备份导航项已存在 (id={existing.id})")
            return

        # 找到 system section 最后一个导航项
        system_items = session.query(Permission).filter_by(
            section='system', is_nav=True
        ).order_by(Permission.sort_order.desc()).first()
        next_sort = (system_items.sort_order + 10) if system_items else 10

        nav = Permission(
            name='数据备份',
            code='backup_manage',
            icon='fa-database',
            url='/backup',
            section='system',
            section_name='系统管理',
            sort_order=next_sort,
            is_nav=True,
        )
        session.add(nav)
        session.commit()

        # 清除 Redis 导航缓存
        try:
            import asyncio

            from fastapi_app.core.redis_wrapper import safe_delete

            asyncio.run(safe_delete('nav_sections', context="备份导航缓存"))
            print("[OK] 已清除导航缓存")
        except Exception as exc:
            print(f"[WARN] 清除导航缓存失败（等待 TTL 过期即可）: {exc}")

        print(f"[OK] 数据备份导航项已添加 (id={nav.id}, sort_order={next_sort})")
    finally:
        session.close()


if __name__ == '__main__':
    main()
