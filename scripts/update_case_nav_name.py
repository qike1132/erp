"""
修改导航栏名称：库存查询 -> 客户订单库存
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
        print("修改导航栏名称：库存查询 -> 客户订单库存")
        print("=" * 70)

        # 查找名称为"库存查询"的权限
        permissions = session.query(Permission).filter(
            Permission.name.contains('库存查询')
        ).all()

        if not permissions:
            print("\n未找到包含'库存查询'的权限记录")
            return

        print(f"\n找到 {len(permissions)} 条记录：")
        for perm in permissions:
            print(f"  - ID: {perm.id}, 名称: {perm.name}, 代码: {perm.code}")

        # 更新名称
        for perm in permissions:
            old_name = perm.name
            if perm.name == '库存查询':
                perm.name = '客户订单库存'
            elif '库存查询' in perm.name:
                perm.name = perm.name.replace('库存查询', '客户订单库存')

            print(f"\n已更新: {old_name} -> {perm.name}")

        session.commit()

        # 清除Redis缓存
        try:
            from utils.redis_cache import redis_cache
            redis_cache.delete('nav_sections')
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
    update_nav_name()
