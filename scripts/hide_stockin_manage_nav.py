"""
隐藏导航栏中的"备货管理(全部)"项
"""
import os
import sys

# 确保可以导入项目模块
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Permission


def hide_stockin_manage_nav():
    """隐藏'备货管理(全部)'导航项"""
    session = SyncSessionLocal()
    try:
        print("=" * 70)
        print("隐藏导航栏中的'备货管理(全部)'项")
        print("=" * 70)

        # 查找名称为"备货管理(全部)"的权限
        permissions = session.query(Permission).filter(
            Permission.name == '备货管理(全部)'
        ).all()

        if not permissions:
            print("\n未找到'备货管理(全部)'的权限记录")
            # 尝试用code查找
            permissions = session.query(Permission).filter(
                Permission.code == 'stockin_manage'
            ).all()
            if not permissions:
                print("也未找到code为'stockin_manage'的记录")
                return

        print(f"\n找到 {len(permissions)} 条记录：")
        for perm in permissions:
            print(f"  - ID: {perm.id}, 名称: {perm.name}, 代码: {perm.code}, is_nav: {perm.is_nav}")

        # 更新is_nav为False
        for perm in permissions:
            old_is_nav = perm.is_nav
            perm.is_nav = False
            print(f"\n已更新: is_nav {old_is_nav} -> {perm.is_nav}")

        session.commit()

        # 清除Redis缓存
        try:
            import asyncio

            from fastapi_app.core.redis_wrapper import safe_delete

            asyncio.run(safe_delete('nav_sections', context="备货导航缓存"))
            print("\n[OK] Redis缓存已清除")
        except Exception as e:
            print(f"\n[WARN] 清除Redis缓存失败: {e}")
            print("请手动重启服务以使更改生效")

        print("\n" + "=" * 70)
        print("更新完成！")
        print("=" * 70)
    finally:
        session.close()


if __name__ == '__main__':
    # AUD-18（2026-10-24 审计）：与 add_*_nav 族同款写守卫
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent('隐藏备货管理导航项（生产库）')
    hide_stockin_manage_nav()
