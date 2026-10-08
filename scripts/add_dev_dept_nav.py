"""
新增「开发部」父菜单，并将「板房管理」移入该分组。

导航分组由 Permission 表的 section/section_name 字段决定：
- pattern_room_manage（板房管理）原属于 core/核心业务，现改为 dev/开发部。
- 修正：此前误将 case_manage（皮套管理）移入开发部，此处将其还原到 core/核心业务。
- 分区显示顺序由 fastapi_app/core/nav_context.py 的 SECTION_ORDER 控制，
  已将 'dev' 置于首位，使「开发部」出现在最前面。

运行方式（在项目根目录）:
    python scripts/add_dev_dept_nav.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Permission

# 目标：板房管理移入开发部
TARGET_CODE = 'pattern_room_manage'
TARGET_SECTION = 'dev'
TARGET_SECTION_NAME = '开发部'

# 误移对象：皮套管理还原到核心业务
REVERT_CODE = 'case_manage'
REVERT_SECTION = 'core'
REVERT_SECTION_NAME = '核心业务'


def _apply(session, code, section, section_name, label):
    perm = session.query(Permission).filter_by(code=code).first()
    if perm is None:
        print(f"[WARN] 未找到权限记录 code={code}，请确认数据库已初始化")
        return False
    changed = False
    if perm.section != section:
        perm.section = section
        changed = True
    if perm.section_name != section_name:
        perm.section_name = section_name
        changed = True
    if changed:
        print(f"[OK] {label} (code={code}, id={perm.id}) -> {section_name}")
    else:
        print(f"[SKIP] {label} 已属于 {section_name} 分组 (id={perm.id})")
    return changed


def main():
    session = SyncSessionLocal()
    try:
        changed_any = False
        changed_any |= _apply(session, TARGET_CODE, TARGET_SECTION, TARGET_SECTION_NAME, '板房管理')
        changed_any |= _apply(session, REVERT_CODE, REVERT_SECTION, REVERT_SECTION_NAME, '皮套管理')

        if changed_any:
            session.commit()
        else:
            print("[SKIP] 无字段变更，跳过提交")

        # 清除 Redis 导航缓存，使改动立即生效
        try:
            import asyncio as _aio

            from fastapi_app.core.redis_wrapper import safe_delete

            _aio.run(safe_delete('nav_sections', context="开发部导航缓存"))
            print("[OK] 已清除导航缓存")
        except Exception:
            print("[WARN] 清除导航缓存失败，请手动重启或等待缓存过期")
    finally:
        session.close()


if __name__ == '__main__':
    main()
