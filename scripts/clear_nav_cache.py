"""
清除导航缓存
"""
import os
import sys
import asyncio

# 确保可以导入项目模块
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


async def clear_nav_cache():
    """清除导航缓存"""
    print("=" * 70)
    print("清除导航缓存")
    print("=" * 70)

    try:
        from fastapi_app.core.nav_context import invalidate_nav_cache
        await invalidate_nav_cache()
        print("\n[OK] 导航缓存已清除")
    except Exception as e:
        print(f"\n[ERROR] 清除导航缓存失败: {e}")

    print("\n" + "=" * 70)
    print("完成！")
    print("=" * 70)


if __name__ == '__main__':
    asyncio.run(clear_nav_cache())
