"""user 表新增「部门」列（组织部门，区别于生产报表部门）

背景
----
/user 用户管理页需要标明每个用户所属的部门，并支持自由调整人员所属部门。
现有 User 已有 factory（东莞/湖北）字段，本迁移按同一模式补一个可空的
department 列，取值固定为 生产部/仓库/业务部/采购部（校验在 schemas/user.py）。

与生产报表部门的关系
----
core/production_scope.py 里的 PRODUCTION_DEPARTMENTS（充棉部/手工部/包装部）
是「生产报表可见范围」的权限域，与用户表上的组织部门是两回事：不同表、
不同用途，互不影响。此处不触碰任何生产报表逻辑。

安全性 / 幂等
----
只 ADD 一个可空列（无默认值、无回填、无约束变更），对存量行零影响，也不触发
破坏性 DDL 守卫；`ADD COLUMN IF NOT EXISTS` 使空库重放与重复执行均安全。
**本文件不代维护者执行**；是否应用到生产由维护者决定。

Revision ID: pg_standalone_085_add_user_department
Revises: pg_standalone_084_drop_redundant_stockout_indexes
Create Date: 2026-10-09
"""
from alembic import op

revision = 'pg_standalone_085_add_user_department'
down_revision = 'pg_standalone_084_drop_redundant_stockout_indexes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS department VARCHAR(20)')
    op.execute(
        'COMMENT ON COLUMN "user".department IS '
        '\'所属部门：生产部/仓库/业务部/采购部/NULL\''
    )


def downgrade() -> None:
    op.execute('ALTER TABLE "user" DROP COLUMN IF EXISTS department')
