"""
添加湖北外发模块导航项到 Permission 表

权限设计（对齐 beile_order 单权限模式 + 管理/查看分离）：
- outsource_manage：湖北外发（管理）— 页面入口 + 订单级写操作
- outsource_view：湖北外发（查看）— 订单列表 / 看板 / 工序只读
导航项 code=outsource_manage，permission_codes 同时包含两个权限，
持有任一权限的用户均可看到导航入口。

授权历史（缺陷 #5，2026-11-16 上线前审计）：**该脚本历史上把 outsource_manage
授给了贝乐**——按「已持有 beile_order_view / order_manage / stockin_manage」批量授予，
而贝乐恰好持有 beile_order_view，于是贝乐自动拿到 outsource_manage，连带拿到当时
挂在它名下的「删工序预设」权限，属于**过宽授权**。工序预设的增删改现已拆出细粒度码
outsource_preset_manage（fastapi_app/api/v1/endpoints/outsource.py），本脚本只保留
导航项的创建与「显式配置」授权：不再按任何既有权限反推，必须用环境变量点名。

运行方式（在项目根目录）:
    # 只建导航项（不授权；超管 is_super 天然全通）
    python scripts/add_outsource_nav.py
    # 显式指定要给 outsource_manage 的账号（逗号分隔用户名）
    OUTSOURCE_GRANT_USERNAMES=zhangsan,lisi python scripts/add_outsource_nav.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import insert, select

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Permission, User, user_permission

PERM_MANAGE = 'outsource_manage'
PERM_VIEW = 'outsource_view'
PERM_NAME = '湖北外发'
PERM_ICON = 'fa-shuttle-van'
PERM_URL = '/outsource'
PERM_SECTION = 'core'
PERM_SECTION_NAME = '核心业务'

# 显式授权名单（逗号分隔用户名）。默认空 = 不授予任何普通账号，
# 避免再次出现「按其它权限反推」的过宽授权。
GRANT_USERNAMES_ENV = 'OUTSOURCE_GRANT_USERNAMES'


def _grant_explicit_users(session, nav_id: int) -> tuple[int, list[str]]:
    """只为显式配置的用户名授予导航权限（幂等）。

    Returns:
        (实际新增的授权条数, 配置了但库里找不到的用户名列表)
    """
    names = [
        n.strip() for n in (os.environ.get(GRANT_USERNAMES_ENV) or '').split(',')
        if n.strip()
    ]
    granted = 0
    missing: list[str] = []
    for name in names:
        user = session.query(User).filter_by(username=name).first()
        if user is None:
            missing.append(name)
            continue
        exists = session.execute(
            select(user_permission).where(
                user_permission.c.user_id == user.id,
                user_permission.c.permission_id == nav_id,
            )
        ).first()
        if exists:
            continue
        session.execute(
            insert(user_permission).values(user_id=user.id, permission_id=nav_id)
        )
        granted += 1
    return granted, missing


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

        # 5. 只给显式配置的用户名授权（超管 is_super 自动可见，无需授权）。
        #    原逻辑按 beile_order_view / order_manage / stockin_manage 反推批量授予，
        #    把管理权连带给贝乐（过宽授权），已删除。
        granted, missing = _grant_explicit_users(session, nav.id)
        for name in missing:
            print(f"[WARN] 用户名不存在，跳过授权: {name}")

        session.commit()

        # 6. 清除 Redis 导航缓存
        try:
            import asyncio as _aio

            from fastapi_app.core.redis_wrapper import safe_delete

            _aio.run(safe_delete('nav_sections', context="湖北外发导航缓存"))
            print("[OK] 已清除导航缓存")
        except Exception:  # broad-except: 清缓存失败不影响已提交的权限数据，仅提示手工处理
            print("[WARN] 清除导航缓存失败，请手动重启或等待缓存过期")

        print(
            f"[OK] 湖北外发导航项已添加 (id={nav.id}, sort_order={next_sort}, "
            f"已为 {granted} 名显式配置的用户授予管理权限)"
        )
    finally:
        session.close()


if __name__ == '__main__':
    main()
