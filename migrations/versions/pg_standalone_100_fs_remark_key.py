"""成品库存备注键去客户化：唯一键 (customer_name, product_id, batch_no) → (product_id, batch_no)

customer_name 在列表侧是派生展示值（批次单客户→客户名，多客户→''），
随批次客户构成抖动，拿它当关联键会让备注静默失联。备注行的真实身份
只有 (product_id, batch_no)。去重规则：同 (product_id, batch_no) 多行时
保留最新 updated_at（NULL 视为最早）。

Revision ID: pg_standalone_100_fs_remark_key
Revises: pg_standalone_099_finished_stock_remark
"""
import sqlalchemy as sa
from alembic import context, op

revision = 'pg_standalone_100_fs_remark_key'
down_revision = 'pg_standalone_099_finished_stock_remark'
branch_labels = None
depends_on = None

_OLD_INDEX = 'uq_fs_remark_cust_prod_batch'
_NEW_INDEX = 'uq_fs_remark_prod_batch'


def upgrade() -> None:
    # 去重：同 (product_id, batch_no) 保留最新 updated_at。
    # 2026-10-17 审计 AUD-11：旧实现用 JOIN 只删「严格更旧」的行——两行
    # COALESCE(updated_at, create_time) 完全相等时谁也不删，随后 CREATE UNIQUE
    # INDEX 必然失败、整个迁移回滚。改用 ROW_NUMBER 并以 id 做确定性 tie-break
    # （同时间戳保留 id 最大者，即最后写入的那行）。
    dedup = sa.text("""
        DELETE FROM finished_stock_remark WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY product_id, batch_no
                           ORDER BY COALESCE(updated_at, create_time) DESC, id DESC
                       ) AS rn
                FROM finished_stock_remark
            ) ranked
            WHERE rn > 1
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

    # customer_name 的 comment 语义（「写备注时的展示值快照」）在 099 建表时
    # 用的还是旧文案——空库重放到头后与 ORM 漂移，CI Verify Alembic 报
    # modify_comment（2026-10-17 实测）。此处同步（幂等）：PG 专属语法 +
    # 非 offline 守卫；sqlite 测试路径由 _CommentFilterConn 过滤。
    if not context.is_offline_mode() and op.get_bind().dialect.name == 'postgresql':
        op.execute(sa.text(
            "COMMENT ON COLUMN finished_stock_remark.customer_name IS "
            "'客户名称（写备注时的展示值快照，不参与关联）'"
        ))


def downgrade() -> None:
    # 不可逆方向：旧键含 customer_name，新键行无法还原唯一性（同 (产品,批次) 现在只有一行，
    # 回旧键不会冲突），故仅需换回旧索引名（同样走裸 DDL，理由见 upgrade）
    op.execute(sa.text(f'DROP INDEX IF EXISTS {_NEW_INDEX}'))
    op.execute(sa.text(
        f'CREATE UNIQUE INDEX IF NOT EXISTS {_OLD_INDEX} '
        'ON finished_stock_remark (customer_name, product_id, batch_no)'
    ))
