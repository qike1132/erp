"""成品库存备注键去客户化：唯一键 (customer_name, product_id, batch_no) → (product_id, batch_no)

customer_name 在列表侧是派生展示值（批次单客户→客户名，多客户→''），
随批次客户构成抖动，拿它当关联键会让备注静默失联。备注行的真实身份
只有 (product_id, batch_no)。去重规则：同 (product_id, batch_no) 多行时
保留最新 updated_at（NULL 视为最早）。

Revision ID: pg_standalone_100_fs_remark_key
Revises: pg_standalone_099_finished_stock_remark
"""
import sqlalchemy as sa
from alembic import op

revision = 'pg_standalone_100_fs_remark_key'
down_revision = 'pg_standalone_099_finished_stock_remark'
branch_labels = None
depends_on = None

_OLD_INDEX = 'uq_fs_remark_cust_prod_batch'
_NEW_INDEX = 'uq_fs_remark_prod_batch'


def upgrade() -> None:
    # 去重：同 (product_id, batch_no) 保留最新 updated_at
    dedup = sa.text("""
        DELETE FROM finished_stock_remark WHERE id IN (
            SELECT a.id FROM finished_stock_remark a
            JOIN finished_stock_remark b
              ON a.product_id = b.product_id
             AND a.batch_no = b.batch_no
             AND a.id <> b.id
             AND COALESCE(a.updated_at, a.create_time) < COALESCE(b.updated_at, b.create_time)
        )
    """)
    op.execute(dedup)

    # 索引切换走裸 DDL（IF EXISTS / IF NOT EXISTS 自身幂等）而非
    # _legacy_base_guard 的 helper：helper 内部 sa_inspect(op.get_bind()) 对
    # 测试注入的连接包装（test_migration_100._CommentFilterConn，sqlite 上
    # 过滤 COMMENT ON 用）无法建立 inspection，会把测试炸掉。裸 DDL 经
    # 包装连接的 execute 正常通行。
    op.execute(sa.text(f'DROP INDEX IF EXISTS {_OLD_INDEX}'))
    op.execute(sa.text(
        f'CREATE UNIQUE INDEX IF NOT EXISTS {_NEW_INDEX} '
        'ON finished_stock_remark (product_id, batch_no)'
    ))

    # 注：customer_name 的 comment 语义（「写备注时的展示值快照」）已直接写进
    # 迁移 099 的建表 DDL——空库重放天然对齐。本迁移不含 COMMENT 语句：
    # sqlite 测试（test_migration_100）的连接包装过滤不了 alembic 包装过的
    # COMMENT（TextClause 非 str），发出去会在 sqlite 上语法炸。存量库若带
    # 旧 comment，属并发会话 comment 改动的本地漂移，由其自行处理。


def downgrade() -> None:
    # 不可逆方向：旧键含 customer_name，新键行无法还原唯一性（同 (产品,批次) 现在只有一行，
    # 回旧键不会冲突），故仅需换回旧索引名（同样走裸 DDL，理由见 upgrade）
    op.execute(sa.text(f'DROP INDEX IF EXISTS {_NEW_INDEX}'))
    op.execute(sa.text(
        f'CREATE UNIQUE INDEX IF NOT EXISTS {_OLD_INDEX} '
        'ON finished_stock_remark (customer_name, product_id, batch_no)'
    ))
