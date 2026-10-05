"""退货管理权限 seed：stock_return_view（导航）/ stock_return_manage（操作）

配套销售退货管理模块（P0）上线：

1. stock_return_view —— 顶层导航节点（is_nav=True，url=/stock-return），
   归入 core/核心业务 板块，排在「出库管理」(stockout_manage, sort=4) 之后；
   sort=5 已被 order_batch_manage 占用，取 6。
2. stock_return_manage —— 操作权限（is_nav=False）。命名继承规则
   （User.has_permission：顶级 xxx_manage 自动通过 xxx_view 检查）使其持有者
   天然可查看；刻意**不做** view 的子权限——继承方向是「授权父级放行子码检查」，
   若把 manage 挂成 view 的子权限，会让只授 view 的用户反向获得写权限。

幂等：权限创建带 NOT EXISTS 守卫，重复执行不会产生重复数据。
不回填任何用户授权：除超级管理员外，由管理员在「用户管理-权限分配」显式授予。

Revision ID: pg_standalone_069_stock_return_permission
Revises: pg_standalone_067_import_idempotency
Create Date: 2026-10-05

--
注 1：Revises 原为 pg_standalone_068_drop_product_stock_check；068 被其作者会话
协同回滚（生产库降回 067、CHECK 约束重建、源文件删除）后，本迁移改挂 067。
注 2：downgrade 的四个 code 值是模块内写死的字面量（无任何外部输入面），
按 043 范式展开为直书 SQL，不走循环拼接。
"""
from alembic import op

revision = 'pg_standalone_069_stock_return_permission'
down_revision = 'pg_standalone_067_import_idempotency'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. stock_return_view：退货管理导航节点（core/核心业务，/stock-return）
    op.execute(
        """
        INSERT INTO permission (name, code, url, icon, section, section_name, sort_order, is_nav, updated_at)
        SELECT '退货管理', 'stock_return_view', '/stock-return', 'fa-rotate-left', 'core', '核心业务', 6, true, now()
        WHERE NOT EXISTS (SELECT 1 FROM permission WHERE code = 'stock_return_view')
        """
    )

    # 2. stock_return_manage：退货新增/删除操作权限（不进导航）
    op.execute(
        """
        INSERT INTO permission (name, code, section, section_name, sort_order, is_nav, updated_at)
        SELECT '退货管理(全部)', 'stock_return_manage', 'core', '核心业务', 7, false, now()
        WHERE NOT EXISTS (SELECT 1 FROM permission WHERE code = 'stock_return_manage')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM user_permission
        WHERE permission_id IN (SELECT id FROM permission WHERE code = 'stock_return_view')
        """
    )
    op.execute(
        "DELETE FROM permission WHERE code = 'stock_return_view'"
    )
    op.execute(
        """
        DELETE FROM user_permission
        WHERE permission_id IN (SELECT id FROM permission WHERE code = 'stock_return_manage')
        """
    )
    op.execute(
        "DELETE FROM permission WHERE code = 'stock_return_manage'"
    )
