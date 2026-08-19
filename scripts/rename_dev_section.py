"""
将导航分组「开发部」(dev) 改名为「板房管理」。

导航分组名称由 Permission 表的 section_name 字段决定，
该分组下的所有记录（section='dev'）需统一更新。

运行方式（在项目根目录）:
    python scripts/rename_dev_section.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Permission

TARGET_SECTION = 'dev'
OLD_SECTION_NAME = '开发部'
NEW_SECTION_NAME = '板房管理'


def main():
    session = SyncSessionLocal()
    try:
        rows = session.query(Permission).filter(Permission.section == TARGET_SECTION).all()
        if not rows:
            print(f"[WARN] 未找到 section={TARGET_SECTION} 的记录，请确认数据库已初始化")
            return

        changed = 0
        for perm in rows:
            if perm.section_name != NEW_SECTION_NAME:
                perm.section_name = NEW_SECTION_NAME
                changed += 1
                print(f"[OK] {perm.code} (id={perm.id}) section_name: {OLD_SECTION_NAME} -> {NEW_SECTION_NAME}")

        if changed:
            session.commit()
            print(f"[OK] 已更新 {changed} 条记录")
        else:
            print("[SKIP] 无字段变更，跳过提交")

        # 清除 Redis 导航缓存，使改动立即生效
        try:
            from fastapi_app.core.redis_wrapper import safe_delete

            asyncio.run(safe_delete('nav_sections', context="导航缓存"))
            print("[OK] 已清除导航缓存")
        except Exception:
            print("[WARN] 清除导航缓存失败，请手动重启或等待缓存过期")
    finally:
        session.close()


if __name__ == '__main__':
    main()
