"""
添加批次号查询导航项到 Permission 表

运行方式（在项目根目录）:
    python scripts/add_batch_nav.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Permission


def main():
    session = SyncSessionLocal()
    try:
        existing = session.query(Permission).filter_by(code='batch_manage').first()
        if existing:
            if existing.is_nav and existing.url:
                print(f"[SKIP] 批次号查询导航项已存在且配置正确 (id={existing.id}, url={existing.url}, is_nav={existing.is_nav})")
                return
            print(f"[FIX] 批次号查询导航项存在但配置不完整，正在修复 (id={existing.id})")
            existing.url = 'sku_batch.sku_batch_page'
            existing.icon = existing.icon or 'fa-table-cells'
            existing.section = existing.section or 'core'
            existing.section_name = existing.section_name or '核心业务'
            existing.is_nav = True
            session.commit()
        else:
            core_items = session.query(Permission).filter_by(
                section='core', is_nav=True
            ).order_by(Permission.sort_order.desc()).first()
            next_sort = (core_items.sort_order + 10) if core_items else 50

            nav = Permission(
                name='批次号查询',
                code='batch_manage',
                icon='fa-table-cells',
                url='sku_batch.sku_batch_page',
                section='core',
                section_name='核心业务',
                sort_order=next_sort,
                is_nav=True,
            )
            session.add(nav)
            session.commit()
            print(f"[OK] 批次号查询导航项已添加 (id={nav.id}, sort_order={next_sort})")

        from fastapi_app.core.nav_context import _nav_local_cache
        _nav_local_cache["data"] = None
        _nav_local_cache["cached_at"] = 0.0
        print("[OK] 已清除进程内导航缓存")

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
            print("[OK] 已清除Redis导航缓存")
        except (OSError, ConnectionError, ValueError, RuntimeError):
            print("[WARN] 清除导航缓存失败，请手动重启或等待5分钟缓存过期")

    finally:
        session.close()


if __name__ == '__main__':
    main()
