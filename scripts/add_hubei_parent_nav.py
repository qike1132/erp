"""
新增「湖北订单」父菜单，并将「湖北订单」「湖北外发」移入该分组。

导航分组由 Permission 表的 section/section_name 字段决定：
- beile_order_view（湖北订单）原属于 core/核心业务，现改为 hubei/湖北订单。
- outsource_manage（湖北外发）原属于 core/核心业务，现改为 hubei/湖北订单。
- 分区显示顺序由 fastapi_app/core/nav_context.py 的 SECTION_ORDER 控制，
  已将 'hubei' 置于 'dev' 之后，使「湖北订单」父菜单位于开发部之后。

运行方式（在项目根目录）:
    python scripts/add_hubei_parent_nav.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Permission

TARGET_SECTION = 'hubei'
TARGET_SECTION_NAME = '湖北订单'

# 需移入新分组的导航权限项
MOVE_CODES = [
    ('beile_order_view', '湖北订单'),
    ('outsource_manage', '湖北外发'),
]


def _apply(session, code, label):
    perm = session.query(Permission).filter_by(code=code).first()
    if perm is None:
        print(f"[WARN] 未找到权限记录 code={code}，请确认数据库已初始化")
        return False
    changed = False
    if perm.section != TARGET_SECTION:
        perm.section = TARGET_SECTION
        changed = True
    if perm.section_name != TARGET_SECTION_NAME:
        perm.section_name = TARGET_SECTION_NAME
        changed = True
    if changed:
        print(f"[OK] {label} (code={code}, id={perm.id}) -> {TARGET_SECTION_NAME}")
    else:
        print(f"[SKIP] {label} 已属于 {TARGET_SECTION_NAME} 分组 (id={perm.id})")
    return changed


def main():
    # 2026-10-17 审计 P2-73：ORM 直写生产库，接入统一写护栏（fail-closed）
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent('写入导航权限项（生产库）')
    session = SyncSessionLocal()
    try:
        changed_any = False
        for code, label in MOVE_CODES:
            changed_any |= _apply(session, code, label)

        if changed_any:
            session.commit()
        else:
            print("[SKIP] 无字段变更，跳过提交")

        # 清除 Redis 导航缓存，使改动立即生效
        try:
            import asyncio as _aio

            from fastapi_app.core.redis_wrapper import safe_delete

            _aio.run(safe_delete('nav_sections', context="湖北订单导航缓存"))
            print("[OK] 已清除导航缓存")
        except Exception:
            print("[WARN] 清除导航缓存失败，请手动重启或等待缓存过期")
    finally:
        session.close()


if __name__ == '__main__':
    main()
