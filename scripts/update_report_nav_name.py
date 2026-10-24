"""
修改导航栏名称：报表管理 -> 订单流水
"""
import os
import sys

# 确保可以导入项目模块
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Permission


def update_nav_name():
    """更新导航栏名称"""
    session = SyncSessionLocal()
    try:
        print("=" * 70)
        print("修改导航栏名称：报表管理 -> 订单流水")
        print("=" * 70)

        # 查找代码为 report_manage 的权限
        perm = session.query(Permission).filter(
            Permission.code == 'report_manage'
        ).first()

        if not perm:
            print("\n未找到代码为 'report_manage' 的权限记录")
            return

        print("\n找到记录：")
        print(f"  - ID: {perm.id}, 名称: {perm.name}, 代码: {perm.code}")

        # 更新名称
        old_name = perm.name
        perm.name = '订单流水'

        session.commit()
        print(f"\n已更新: {old_name} -> {perm.name}")

        # 清除Redis缓存
        try:
            import asyncio

            from fastapi_app.core.redis_wrapper import safe_delete

            asyncio.run(safe_delete('nav_sections', context="报表导航缓存"))
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
    require_prod_write_consent('更新报表导航名称（生产库）')
    update_nav_name()
