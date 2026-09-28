"""merge all current heads into a single head

Revision ID: merge_resolve_all_heads
Create Date: 2026-06-11

This merge unifies the divergent migration heads into one.  The
upgrade/downgrade bodies are no-ops.

合并的 head（3 个，另加 merge_all_heads 作为 down_revision）
----------------------------------------------------------
  - add_country_table
  - add_missing_perf_idx
  - pg_standalone_013

修正说明（2026-09-27）
---------------------
原实现列了 11 个父节点，其中 7 个（`a8f3c2d1e5b7`、`add_order_batch_fields`、
`add_order_type_country_stockin`、`add_pp_composite_idx`、`add_stock_return`、
`add_updated_at`、`pg_standalone_003`）在当时已不是 head（它们都是
`merge_all_heads` 的祖先）。Alembic merge 时会对非 head 父节点执行
`HeadMaintainer._delete_version()` 而抛 `KeyError`，使空库
`alembic upgrade head` 无法收尾。现只保留真实 head，DAG 可达性不变。

（原注释提到「All parent migrations have been stamped as applied because
the target schema is already present in the database (built by a combination
of alembic runs and manual ``Base.metadata.create_all`` calls)」——这正是本
迁移链历史上从未端到端跑通的证据；本轮修复后空库重放可完整执行。）
"""

revision = 'merge_resolve_all_heads'
down_revision = (
    'merge_all_heads',
    'add_country_table',
    'add_missing_perf_idx',
    'pg_standalone_013',
)
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
