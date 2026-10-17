"""成品库存：daily_production_record 加批次/定制列，stock_out 加批次号

包装部录入成品库存需要批次号（复用订单批次体系）与定制标记；出货要能指定
批次做批次级扣减。纯新增可空列 + 索引，不改既有数据、不做破坏性 DDL。
批次号格式：0464(固定) + 年 + 年内第几天 + 序号，共 10 位，字符串存储。

Revision ID: pg_standalone_098_finished_stock_batch
Revises: pg_standalone_097_add_daily_production_customer
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import (
    add_column_if_absent,
    create_index_if_absent,
    drop_column_if_exists,
    drop_index_if_exists,
)

revision = 'pg_standalone_098_finished_stock_batch'
down_revision = 'pg_standalone_097_add_daily_production_customer'
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_absent('daily_production_record',
                         sa.Column('batch_no', sa.String(length=100), nullable=True, comment='批次号（复用订单批次体系，自由文本）'))
    add_column_if_absent('daily_production_record',
                         sa.Column('is_custom', sa.Boolean(), nullable=True, comment='是否定制（NULL/false 均视为常规）'))
    add_column_if_absent('daily_production_record',
                         sa.Column('custom_country', sa.String(length=100), nullable=True, comment='定制国家（仅 is_custom=true 时有意义）'))
    create_index_if_absent('idx_dpr_batch_no', 'daily_production_record', ['batch_no'])

    add_column_if_absent('stock_out',
                         sa.Column('batch_no', sa.String(length=100), nullable=True, comment='批次号（指定则按该批次扣减成品库存）'))
    # 部分索引：批次聚合恒带 stockin_id IS NULL（排除备货抵扣行），与批次可用量口径一致。
    # 走裸 DDL（照 083 的 partial 索引惯例），CREATE INDEX IF NOT EXISTS 幂等。
    op.execute(sa.text(
        'CREATE INDEX IF NOT EXISTS idx_stockout_batch_no '
        'ON stock_out (batch_no) WHERE stockin_id IS NULL'
    ))

    # 导航权限行：permission 表是运行时的权限权威源（/user 分配弹窗、侧栏导航都读它），
    # 默认安装路径只跑 alembic upgrade（不跑 scripts/seed_nav.py，那是 -Blank 分支专用），
    # 故必须在此幂等种入，否则旧库升级/镜像恢复的实例没有「成品库存」入口。照 069 写法。
    op.execute(
        """
        INSERT INTO permission (name, code, url, icon, section, section_name, sort_order, is_nav, updated_at)
        SELECT '成品库存', 'finished_stock_view', '/finished-stock', 'fa-boxes-stacked', 'core', '核心业务', 8, true, now()
        WHERE NOT EXISTS (SELECT 1 FROM permission WHERE code = 'finished_stock_view')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM user_permission
        WHERE permission_id IN (SELECT id FROM permission WHERE code = 'finished_stock_view')
        """
    )
    op.execute("DELETE FROM permission WHERE code = 'finished_stock_view'")
    drop_index_if_exists('idx_stockout_batch_no', table_name='stock_out')
    drop_column_if_exists('stock_out', 'batch_no')
    drop_index_if_exists('idx_dpr_batch_no', table_name='daily_production_record')
    drop_column_if_exists('daily_production_record', 'custom_country')
    drop_column_if_exists('daily_production_record', 'is_custom')
    drop_column_if_exists('daily_production_record', 'batch_no')
