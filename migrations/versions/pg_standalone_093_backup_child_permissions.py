"""补种「数据备份」的 4 个细粒度子权限（backup_read / create / restore / delete）

背景：备份端点走 `require_any_permission(<细粒度码>, 'backup_manage')`
（`fastapi_app/api/v1/endpoints/backup/_deps.py` 的 `require_backup_permission`），
即「持 backup_manage 全通，也可只授其中一个」。但这 4 个细粒度码在
**seed_nav / init_permissions / 迁移**里都没有定义，2026-10-12 提权核查生产库
`SELECT … WHERE code IN (…)` 也全部 **NOT_FOUND**——于是 /user 里点不到它们，
`_deps.py` 里那套细粒度授权成了死配置。

本迁移按既有「父权限 + 子权限」范式补种：挂在 `backup_manage` 之下、is_nav=False、
section/排序继承父行（按 code 定位父级，不写死 id）。

⚠️ **不影响现有行为**：`backup_manage` 仍是 `require_any` 的一项，持有它的用户照旧全通；
本迁移只是让「只授只读备份」这类更细的授权变得可勾选。

幂等：按 code 唯一约束 + NOT EXISTS 守卫，重复执行安全。
配套：`scripts/init_permissions.py` 新增 backup 模块，保证空库重建口径一致。

Revision ID: pg_standalone_093_backup_child_permissions
Revises: pg_standalone_092_drop_dead_top_level_permissions
Create Date: 2026-10-12
"""
from alembic import op

revision = 'pg_standalone_093_backup_child_permissions'
down_revision = 'pg_standalone_092_drop_dead_top_level_permissions'
branch_labels = None
depends_on = None

# 列值对齐既有子权限行范式（order_edit / batch_import）：icon/url 为空、is_nav=False、
# section/排序继承父行（按 code 定位父级，不写死 id）。
_ROWS = [
    ('backup_read', '查看备份', 1),
    ('backup_create', '创建备份', 2),
    ('backup_restore', '恢复备份', 3),
    ('backup_delete', '删除备份', 4),
]


def upgrade() -> None:
    for code, name, sort_offset in _ROWS:
        op.execute(
            "INSERT INTO permission (code, name, parent_id, section, section_name, sort_order, is_nav) "
            "SELECT '" + code + "', '" + name + "', p.id, p.section, p.section_name, p.sort_order + " + str(sort_offset) + ", False "
            "FROM permission p WHERE p.code = 'backup_manage' "
            "AND NOT EXISTS (SELECT 1 FROM permission WHERE code = '" + code + "')"
        )  # nosec B608 — 常量表插值，无外部输入


def downgrade() -> None:
    # 仅删权限点本身：user_permission 关联行由外键级联清理；已分配该码的授权随行消失
    codes = "', '".join(code for code, _, _ in _ROWS)
    op.execute(
        "DELETE FROM user_permission WHERE permission_id IN "
        f"(SELECT id FROM permission WHERE code IN ('{codes}'))"
    )
    op.execute(f"DELETE FROM permission WHERE code IN ('{codes}')")
