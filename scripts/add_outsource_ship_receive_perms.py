"""
为外发工序新增「发货 / 收货」权限点，并按现有账号关系回填授权

背景：发货/收货原先按「用户名 == 贝乐」硬编码区分（贝乐账号只收货、其他账号只发货）。
改为权限点后，权限与授权必须先于代码上线灌入数据库，否则所有人都会拿到 403。

授权映射（与改造前行为一致，super 账号天然拥有全部权限，无需显式授权）：
- outsource_ship   ：授予当前拥有 outsource_manage 且用户名不是「贝乐」的账号
- outsource_receive：授予当前拥有 outsource_manage 且用户名是「贝乐」的账号

幂等：重复运行只补缺失的权限项与授权。

运行方式（项目根目录）:
    python scripts/add_outsource_ship_receive_perms.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import insert, select

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Permission, User, user_permission

PERM_MANAGE = 'outsource_manage'
PERM_SHIP = 'outsource_ship'
PERM_RECEIVE = 'outsource_receive'
BEILE_USERNAME = '贝乐'


def _ensure_permission(session, code: str, name: str, parent_id, sort_order: int) -> Permission:
    """按 code 幂等创建非导航权限项（挂在 outsource_manage 之下）"""
    perm = session.query(Permission).filter_by(code=code).first()
    if perm:
        print(f"[SKIP] 权限已存在: {code} (id={perm.id})")
        return perm
    perm = Permission(
        name=name,
        code=code,
        parent_id=parent_id,
        section='core',
        section_name='核心业务',
        sort_order=sort_order,
        is_nav=False,
    )
    session.add(perm)
    session.flush()
    print(f"[OK] 已创建权限: {code} (id={perm.id})")
    return perm


def _grant(session, user_ids: list[int], permission_id: int) -> int:
    """幂等授予：返回新增授权数量"""
    granted = 0
    for uid in user_ids:
        exists = session.execute(
            select(user_permission).where(
                user_permission.c.user_id == uid,
                user_permission.c.permission_id == permission_id,
            )
        ).first()
        if not exists:
            session.execute(
                insert(user_permission).values(user_id=uid, permission_id=permission_id)
            )
            granted += 1
    return granted


def main():
    session = SyncSessionLocal()
    try:
        manage = session.query(Permission).filter_by(code=PERM_MANAGE).first()
        if not manage:
            print(f"[ERR] 未找到 {PERM_MANAGE}，请先运行 scripts/add_outsource_nav.py")
            return

        base_sort = manage.sort_order or 0
        ship = _ensure_permission(session, PERM_SHIP, '湖北外发（发货）', manage.id, base_sort + 2)
        receive = _ensure_permission(session, PERM_RECEIVE, '湖北外发（收货）', manage.id, base_sort + 3)

        # 按改造前的用户名规则回填授权
        manage_user_ids = session.execute(
            select(user_permission.c.user_id).where(user_permission.c.permission_id == manage.id)
        ).scalars().all()
        users = session.query(User).filter(User.id.in_(manage_user_ids)).all() if manage_user_ids else []

        ship_ids = [u.id for u in users if u.username != BEILE_USERNAME]
        receive_ids = [u.id for u in users if u.username == BEILE_USERNAME]
        if not receive_ids:
            print(f"[WARN] 未找到用户名「{BEILE_USERNAME}」的账号，收货权限未授予任何人")

        ship_granted = _grant(session, ship_ids, ship.id)
        receive_granted = _grant(session, receive_ids, receive.id)
        session.commit()

        print(
            f"[OK] 发货权限新增授权 {ship_granted} 人（匹配 {len(ship_ids)} 人）；"
            f"收货权限新增授权 {receive_granted} 人（匹配 {len(receive_ids)} 人）"
        )

        # 清除导航/权限缓存，避免新权限点被旧缓存挡住（与 add_outsource_nav.py 一致）
        try:
            import asyncio as _aio

            from fastapi_app.core.redis_wrapper import safe_delete

            _aio.run(safe_delete('nav_sections', context="外发发货/收货权限"))
            print("[OK] 已清除导航缓存")
        except Exception:
            print("[WARN] 清除导航缓存失败，请手动重启或等待缓存过期")
    finally:
        session.close()


if __name__ == '__main__':
    # AUD-18（2026-10-24 审计）：与 add_*_nav 族同款写守卫
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent('新增外发收发货权限码（生产库）')
    main()
