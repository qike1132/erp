"""StockIn 增加 is_deleted 软删除字段（与 Order 软删除语义对齐）

背景：湖北订单（beile-order）页面将 Order 与 StockIn 通过 UNION ALL
合并展示。Order 已有 is_deleted 软删除过滤（列表 / 未确认计数 / 确认
行锁查询三处），而 StockIn 缺失该字段，导致已软删的备货记录仍会出现在
湖北订单列表与未确认计数中。

方案：
- stock_in 表新增 is_deleted 列（可空 BOOLEAN，默认 FALSE，带索引），
  与 Order.is_deleted 语义完全一致。
- beile.py 三处查询补 StockIn.is_deleted.isnot(True) 过滤。

幂等：ADD COLUMN IF NOT EXISTS + DO 块守卫索引创建。

Revision ID: pg_standalone_049_stockin_soft_delete
Revises: pg_standalone_048_seed_beile_confirm
Create Date: 2026-09-21
"""
from alembic import op

revision = 'pg_standalone_049_stockin_soft_delete'
down_revision = 'pg_standalone_048_seed_beile_confirm'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 新增 is_deleted 列（可空，应用层 default=False 填充；与 Order.is_deleted 对齐）
    op.execute(
        """
        ALTER TABLE stock_in
        ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN;
        """
    )

    # 2. 幂等创建部分索引（仅索引未删除行，与 Order 的过滤查询模式匹配）
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'stock_in'
                  AND indexname = 'idx_stockin_not_deleted'
            ) THEN
                CREATE INDEX idx_stockin_not_deleted
                    ON stock_in (id)
                    WHERE is_deleted = false;
            END IF;
        END $$;
        """
    )

    # 3. 列注释
    op.execute(
        """
        COMMENT ON COLUMN stock_in.is_deleted IS '是否已删除';
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_stockin_not_deleted")
    op.execute("ALTER TABLE stock_in DROP COLUMN IF EXISTS is_deleted")
