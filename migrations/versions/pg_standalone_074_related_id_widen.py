"""inventory_log.related_id 提长 VARCHAR(50)→VARCHAR(500)（designs BLOCKER 2）

背景：create_stockout_core/_process_single_stockout 将一次 FIFO 出货拆出的
多条 stock_out.id 以逗号拼接写入 related_id（stock_out_service.py:72,339）。
5 位数 id 下约 9 条订单即超 50 字符 → StringDataRightTruncation → 正常出货 500。
与 067 将 idem_key 提 TEXT 同范式（pg_standalone_067_import_idempotency.py:85）。

幂等：ALTER COLUMN ... TYPE 重复执行安全；related_id 无索引，无索引重建。
不回填、不截断存量。

Revision ID: pg_standalone_074_related_id_widen
Revises: pg_standalone_073_inventory_log_ledger_fields
Create Date: 2026-10-06
"""
from alembic import op

revision = 'pg_standalone_074_related_id_widen'
down_revision = 'pg_standalone_073_inventory_log_ledger_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE inventory_log ALTER COLUMN related_id TYPE VARCHAR(500)")
    op.execute("COMMENT ON COLUMN inventory_log.related_id IS "
               "'关联单据编号（出库 FIFO 多单为逗号拼接的 stock_out.id 串）'")


def downgrade() -> None:
    # 回缩前若已存在 >50 字符数据，PG 将报错拒降（string right truncation）——
    # 这是刻意的守卫：不可静默截断审计关联。真要回滚且已有超长数据时，
    # 走「恢复 pg_dump」路径，不要就地截断。
    op.execute("COMMENT ON COLUMN inventory_log.related_id IS NULL")
    op.execute("ALTER TABLE inventory_log ALTER COLUMN related_id TYPE VARCHAR(50)")
