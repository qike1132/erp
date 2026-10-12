"""删除三个「有权限行、无任何功能」的死顶层权限

背景：/user「分配权限」弹窗的「其他操作权限」区会列出所有 is_nav=false 的顶层权限。
其中这三个在库里存在，但**全仓零引用**——没有前端路由、没有视图、没有后端端点、
没有 nginx 配置（2026-10-12 用户报障「我都没有这 2 个路由」）：

    finance_view         财务统计        url=finance.statistics
    permission_manage    权限管理(全部)   url=user.users（与 user_manage 同页面，历史重复项）
    app_update_manage    版本管理        url=/app-update

它们的来源是历史开发遗留（`scripts/seed_nav.py` 内嵌的是「生产库 2026-10-08 只读导出的
父权限全部」，导出那天就带着这三行）。2026-10-12 提权只读核查：三者 kids=0、holders=0，
删除不会影响任何已授权用户。

⚠️ 只删库不够：`seed_nav.py` 是幂等重种的（缺则 INSERT），不删种子定义的话下次跑种子
脚本会把它们种回来。同一提交已从 NAV_SEED 移除这三条，并加回归测试锁住。

配套（同一提交）：
- scripts/seed_nav.py 的 NAV_SEED 删掉三条定义；
- fastapi_app/tests/test_dead_top_level_permissions_removed.py 锁住两边一致。

幂等：DELETE 天然幂等；downgrade 用 NOT EXISTS 守卫重种。
downgrade 会把三行按原值还原（不还原 user_permission 关联——原本就 0 条）。

Revision ID: pg_standalone_092_drop_dead_top_level_permissions
Revises: pg_standalone_091_report_row_action_per_tab
Create Date: 2026-10-12
"""
from alembic import op

revision = 'pg_standalone_092_drop_dead_top_level_permissions'
down_revision = 'pg_standalone_091_report_row_action_per_tab'
branch_labels = None
depends_on = None

# 待删的码
_DROP_CODES = ('finance_view', 'permission_manage', 'app_update_manage')

# downgrade 还原用的原始列值（取自 seed_nav.py 删除前的定义）
_RESTORE_ROWS = [
    ('finance_view', '财务统计', 'fa-yen-sign', 'finance.statistics', 'finance', '财务', 10),
    ('permission_manage', '权限管理(全部)', 'fa-shield-alt', 'user.users', 'system', '系统管理', 2),
    ('app_update_manage', '版本管理', 'fa-mobile-alt', '/app-update', 'system', '系统管理', 24),
]


def upgrade() -> None:
    codes = "', '".join(_DROP_CODES)
    # 先清关联与子行（本机实测均为 0 条，防御性写上：别的安装端可能不是 0）
    op.execute(
        "DELETE FROM user_permission WHERE permission_id IN "
        f"(SELECT id FROM permission WHERE code IN ('{codes}'))"
    )
    op.execute(
        "DELETE FROM user_permission WHERE permission_id IN "
        f"(SELECT id FROM permission WHERE parent_id IN "
        f"(SELECT id FROM permission WHERE code IN ('{codes}')))"
    )
    op.execute(
        f"DELETE FROM permission WHERE parent_id IN (SELECT id FROM permission WHERE code IN ('{codes}'))"
    )
    op.execute(f"DELETE FROM permission WHERE code IN ('{codes}')")


def downgrade() -> None:
    for code, name, icon, url, section, section_name, sort_order in _RESTORE_ROWS:
        op.execute(
            "INSERT INTO permission (code, name, icon, url, section, section_name, sort_order, is_nav, parent_id) "
            "SELECT '" + code + "', '" + name + "', '" + icon + "', '" + url + "', '"
            + section + "', '" + section_name + "', " + str(sort_order) + ", False, NULL "
            "WHERE NOT EXISTS (SELECT 1 FROM permission WHERE code = '" + code + "')"
        )  # nosec B608 — 常量表插值，无外部输入
