"""
添加板房管理导航项到 Permission 表，并为已拥有 product_manage 的用户授予该权限

运行方式（在项目根目录）:
    python scripts/add_pattern_room_nav.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Permission, user_permission

PERM_CODE = 'pattern_room_manage'
PERM_NAME = '板房管理'
PERM_ICON = 'fa-scissors'
PERM_URL = '/pattern-room'
PERM_SECTION = 'core'
PERM_SECTION_NAME = '核心业务'


def main():
    session = SyncSessionLocal()
    try:
        # 1. 检查权限是否已存在
        existing = session.query(Permission).filter_by(code=PERM_CODE).first()
        if existing:
            print(f"[SKIP] 板房管理导航项已存在 (id={existing.id})")
            return

        # 2. 找到目标 section 最后一个导航项，确定 sort_order
        section_items = (
            session.query(Permission)
            .filter_by(section=PERM_SECTION, is_nav=True)
            .order_by(Permission.sort_order.desc())
            .first()
        )
        next_sort = (section_items.sort_order + 10) if section_items else 10

        # 3. 创建权限项
        nav = Permission(
            name=PERM_NAME,
            code=PERM_CODE,
            icon=PERM_ICON,
            url=PERM_URL,
            section=PERM_SECTION,
            section_name=PERM_SECTION_NAME,
            sort_order=next_sort,
            is_nav=True,
        )
        session.add(nav)
        session.flush()  # 拿到 nav.id

        # 4. 为已拥有 product_manage 权限的用户授予该权限（板房是产品域的扩展）
        #    通过 user_permission 关联表批量插入
        from sqlalchemy import insert, select

        product_perm = session.query(Permission).filter_by(code='product_manage').first()
        granted = 0
        if product_perm:
            # 找出所有拥有 product_manage 的用户
            user_ids = session.execute(
                select(user_permission.c.user_id).where(
                    user_permission.c.permission_id == product_perm.id
                )
            ).scalars().all()
            if user_ids:
                # 批量插入（跳过已存在的组合）
                for uid in user_ids:
                    # 检查是否已存在
                    exists = session.execute(
                        select(user_permission).where(
                            user_permission.c.user_id == uid,
                            user_permission.c.permission_id == nav.id,
                        )
                    ).first()
                    if not exists:
                        session.execute(
                            insert(user_permission).values(
                                user_id=uid, permission_id=nav.id
                            )
                        )
                        granted += 1

        session.commit()

        # 5. 清除 Redis 导航缓存
        try:
            import asyncio as _aio

            from fastapi_app.core.redis_wrapper import safe_delete

            _aio.run(safe_delete('nav_sections', context="板房导航缓存"))
            print("[OK] 已清除导航缓存")
        except Exception:
            print("[WARN] 清除导航缓存失败，请手动重启或等待缓存过期")

        print(
            f"[OK] 板房管理导航项已添加 (id={nav.id}, sort_order={next_sort}, "
            f"已为 {granted} 名用户授予权限)"
        )
    finally:
        session.close()


if __name__ == '__main__':
    main()
