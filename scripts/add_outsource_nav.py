"""
添加湖北外发模块导航项到 Permission 表，并授予权限

权限设计（对齐 beile_order 单权限模式 + 管理/查看分离）：
- outsource_manage：湖北外发（管理）— 工序预设 CRUD + 工序状态管理
- outsource_view：湖北外发（查看）— 订单列表 / 看板 / 工序只读
导航项 code=outsource_manage，permission_codes 同时包含两个权限，
持有任一权限的用户均可看到导航入口。

运行方式（在项目根目录）:
    python scripts/add_outsource_nav.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import insert, select

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Permission, user_permission

PERM_MANAGE = 'outsource_manage'
PERM_VIEW = 'outsource_view'
PERM_NAME = '湖北外发'
PERM_ICON = 'fa-shuttle-van'
PERM_URL = '/outsource'
PERM_SECTION = 'core'
PERM_SECTION_NAME = '核心业务'


def main():
    # 2026-10-17 审计 P2-73：ORM 直写生产库，接入统一写护栏（fail-closed）
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent('写入导航权限项（生产库）')
    session = SyncSessionLocal()
    try:
        # 1. 检查是否已存在
        existing = session.query(Permission).filter_by(code=PERM_MANAGE).first()
        if existing:
            print(f"[SKIP] 湖北外发导航项已存在 (id={existing.id})")
            return

        # 2. 找到目标 section 最后一个导航项，确定 sort_order
        section_items = (
            session.query(Permission)
            .filter_by(section=PERM_SECTION, is_nav=True)
            .order_by(Permission.sort_order.desc())
            .first()
        )
        next_sort = (section_items.sort_order + 10) if section_items else 10

        # 3. 创建导航权限项（管理）
        nav = Permission(
            name=PERM_NAME,
            code=PERM_MANAGE,
            icon=PERM_ICON,
            url=PERM_URL,
            section=PERM_SECTION,
            section_name=PERM_SECTION_NAME,
            sort_order=next_sort,
            is_nav=True,
        )
        session.add(nav)
        session.flush()  # 拿到 nav.id

        # 4. 创建查看权限项（非导航，挂在管理权限下）
        view = Permission(
            name='湖北外发（查看）',
            code=PERM_VIEW,
            parent_id=nav.id,
            icon=PERM_ICON,
            url=PERM_URL,
            section=PERM_SECTION,
            section_name=PERM_SECTION_NAME,
            sort_order=next_sort + 1,
            is_nav=False,
        )
        session.add(view)
        session.flush()

        # 5. 为已拥有 beile_order_view / order_manage / stockin_manage 的用户授予管理权限
        granted = 0
        source_codes = ('beile_order_view', 'order_manage', 'stockin_manage')
        source_perms = session.query(Permission).filter(Permission.code.in_(source_codes)).all()
        user_ids: set[int] = set()
        for sp in source_perms:
            ids = session.execute(
                select(user_permission.c.user_id).where(
                    user_permission.c.permission_id == sp.id
                )
            ).scalars().all()
            user_ids.update(ids)

        # 超管用户（is_super）自动可见，无需显式授权；此处仅处理普通用户
        for uid in user_ids:
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

        # 6. 清除 Redis 导航缓存
        try:
            import asyncio as _aio

            from fastapi_app.core.redis_wrapper import safe_delete

            _aio.run(safe_delete('nav_sections', context="湖北外发导航缓存"))
            print("[OK] 已清除导航缓存")
        except Exception:
            print("[WARN] 清除导航缓存失败，请手动重启或等待缓存过期")

        print(
            f"[OK] 湖北外发导航项已添加 (id={nav.id}, sort_order={next_sort}, "
            f"已为 {granted} 名用户授予管理权限)"
        )
    finally:
        session.close()


if __name__ == '__main__':
    main()
