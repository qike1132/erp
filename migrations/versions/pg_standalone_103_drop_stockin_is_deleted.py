"""drop stock_in.is_deleted（死状态位）

Revision ID: pg_standalone_103_drop_stockin_is_deleted
Revises: pg_standalone_102_purchase_order_status_check
Create Date: 2026-10-21

2026-10-17 审计 Z03-R5：``stock_in.is_deleted`` 是**有读无写**的死状态位——
全仓没有任何写入点（备货删除入口 ``delete_stockin`` 是硬删），而
``order/beile.py``、``order/unified.py``、``order_batch_service.py`` 共 7 处
读取过滤 ``StockIn.is_deleted.isnot(True)`` 恒真。留着它会让后续维护者误以为
存在备货软删机制，围绕它做错误口径假设。

安全前提（2026-10-21 生产只读核验）：``stock_in`` 表共 0 行，
``is_deleted IS TRUE`` 计数 0。删列不会让任何行重新出现在列表/库存统计里。

防御闸门：升级时若发现 ``is_deleted IS TRUE`` 的行则**拒绝删除**并报错——
硬删列会让这些「手工标记过的」行复活，必须人工确认后再处理。
"""
from alembic import op
from sqlalchemy import Boolean, Column, text

from migrations._legacy_base_guard import (
    add_column_if_absent,
    base_schema_absent,
    drop_column_if_absent,
    drop_index_if_exists,
    table_columns,
)

revision = 'pg_standalone_103_drop_stockin_is_deleted'
down_revision = 'pg_standalone_102_purchase_order_status_check'
branch_labels = None
depends_on = None

_INDEX_NAME = 'ix_stock_in_is_deleted'


def upgrade() -> None:
    if base_schema_absent():
        return
    present = table_columns('stock_in')
    if present is None or 'is_deleted' not in present:
        return
    marked = op.get_bind().execute(
        text('SELECT count(*) FROM stock_in WHERE is_deleted IS TRUE')
    ).scalar()
    if marked:
        raise RuntimeError(
            f'stock_in 有 {marked} 行 is_deleted=TRUE：删列会让这些行重新出现在列表/'
            '库存统计中。请先人工确认并按业务口径处理（恢复或物理删除），再重跑本迁移。'
        )
    drop_index_if_exists(_INDEX_NAME, table_name='stock_in')
    drop_column_if_absent('stock_in', 'is_deleted')


def downgrade() -> None:
    """回滚只恢复列结构（历史值不可恢复），等价于升级前的「恒 NULL/False」。"""
    if base_schema_absent():
        return
    add_column_if_absent(
        'stock_in',
        Column('is_deleted', Boolean, nullable=True, comment='是否已删除'),
    )
    # 列缺席说明表也不在（空库重放路径），无需建索引
    if table_columns('stock_in') is None:
        return
    op.execute(f'CREATE INDEX IF NOT EXISTS {_INDEX_NAME} ON stock_in (is_deleted)')
