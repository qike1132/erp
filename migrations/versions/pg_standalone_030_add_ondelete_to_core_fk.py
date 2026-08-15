"""add ondelete to core fk

为订单/备货/出货/退货/皮套核心表的外键补全 ondelete 策略。
修复 B6 上线阻断项：56 个 FK 中 37 个缺 ondelete，核心业务表 product_id FK 全员裸奔。

策略（database-operations expand/contract）：
- order.product_id → RESTRICT（禁止删产品留孤儿订单，业务上产品不应硬删）
- order 4 个 user FK → SET NULL（用户注销不阻断订单查询）
- stock_in/stock_out/stock_return.product_id → RESTRICT（库存链路一致性）
- stock_return.stockout_id → CASCADE（退货随出货级联删除）
- case.product_id → SET NULL（皮套可脱离产品独立存在）

执行方式：PostgreSQL ALTER CONSTRAINT 在线操作，仅元数据变更，不锁表、不阻塞读写。
回滚：恢复为无 ondelete 的默认行为（NO ACTION）。

Revision ID: pg_standalone_030
Revises: pg_standalone_029_rename_default_role
Create Date: 2026-08-13
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'pg_standalone_030'
down_revision = 'pg_standalone_029_rename_default_role'
branch_labels = None
depends_on = None


# 约束名规范：PostgreSQL 自动生成的 FK 约束名形如 <table>_<column>_fkey
# 本迁移依赖此默认命名，若生产环境约束名不同需先核对再调整
_FK_CHANGES = [
    # (table, column, constraint_name, ref_table, ref_column, ondelete)
    # 订单表：product_id RESTRICT + 4 个 user FK SET NULL
    ('order', 'product_id', 'order_product_id_fkey', 'product', 'id', 'RESTRICT'),
    ('order', 'locked_by_id', 'order_locked_by_id_fkey', 'user', 'id', 'SET NULL'),
    ('order', 'batch_completed_by_id', 'order_batch_completed_by_id_fkey', 'user', 'id', 'SET NULL'),
    ('order', 'confirmed_by_id', 'order_confirmed_by_id_fkey', 'user', 'id', 'SET NULL'),
    ('order', 'deleted_by_id', 'order_deleted_by_id_fkey', 'user', 'id', 'SET NULL'),
    # 备货/出货/退货：product_id RESTRICT
    ('stock_in', 'product_id', 'stock_in_product_id_fkey', 'product', 'id', 'RESTRICT'),
    ('stock_out', 'product_id', 'stock_out_product_id_fkey', 'product', 'id', 'RESTRICT'),
    ('stock_return', 'product_id', 'stock_return_product_id_fkey', 'product', 'id', 'RESTRICT'),
    # 退货→出货：CASCADE（退货随出货级联删除）
    ('stock_return', 'stockout_id', 'stock_return_stockout_id_fkey', 'stock_out', 'id', 'CASCADE'),
    # 皮套：product_id SET NULL（皮套可脱离产品独立存在）
    ('case', 'product_id', 'case_product_id_fkey', 'product', 'id', 'SET NULL'),
]


def upgrade():
    """为 10 个核心 FK 补全 ondelete 策略。

    PostgreSQL DROP CONSTRAINT + ADD CONSTRAINT 是元数据操作：
    - 不重写数据、不锁表（仅短暂的 AccessExclusiveLock 用于元数据更新，毫秒级）
    - 不阻塞读写
    - 可在生产环境直接执行

    注意：order 表名是 SQL 保留字，须显式引号。
    """
    for table, column, constraint_name, ref_table, ref_column, ondelete in _FK_CHANGES:
        # 引号处理：order/user/case 是 SQL 保留字
        tbl = f'"{table}"' if table in ('order', 'user', 'case') else table
        ref_tbl = f'"{ref_table}"' if ref_table in ('order', 'user', 'case') else ref_table

        op.execute(
            f'ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS {constraint_name}'
        )
        op.execute(
            f'ALTER TABLE {tbl} ADD CONSTRAINT {constraint_name} '
            f'FOREIGN KEY ({column}) REFERENCES {ref_tbl}({ref_column}) '
            f'ON DELETE {ondelete}'
        )

    # 验证：打印约束状态供运维核对
    op.execute(
        "SELECT conname, confdeltype FROM pg_constraint "
        "WHERE conname IN (" + ",".join(f"'{c[2]}'" for c in _FK_CHANGES) + ")"
        " -- 预期: r=RESTRICT, c=CASCADE, n=SET NULL"
    )


def downgrade():
    """回滚：恢复为无 ondelete（NO ACTION，PostgreSQL 默认行为）。"""
    for table, column, constraint_name, ref_table, ref_column, _ in _FK_CHANGES:
        tbl = f'"{table}"' if table in ('order', 'user', 'case') else table
        ref_tbl = f'"{ref_table}"' if ref_table in ('order', 'user', 'case') else ref_table

        op.execute(
            f'ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS {constraint_name}'
        )
        op.execute(
            f'ALTER TABLE {tbl} ADD CONSTRAINT {constraint_name} '
            f'FOREIGN KEY ({column}) REFERENCES {ref_tbl}({ref_column})'
        )
