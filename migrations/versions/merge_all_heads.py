"""merge all migration heads

Revision ID: merge_all_heads
Create Date: 2026-05-10

Merge migration that unifies 7 divergent migration heads into a single
linear history.  No schema changes -- upgrade / downgrade are no-ops.

合并的 7 个 head
----------------
  - pg_standalone_003  (断开在 001->002->003 的独立 pg_standalone 分支)
  - add_order_batch_fields
  - add_order_type_country_stockin
  - add_pp_composite_idx
  - add_stock_return    (659467a97350 -> 004..009 -> 010 -> 011 -> add_backup_record
                         -> add_app_version -> add_stock_return 这条最长链的末端)
  - add_updated_at
  - a8f3c2d1e5b7       (change_order_status_nullable)

`add_country_table` / `add_missing_perf_idx` / `pg_standalone_013` 此时仍是
独立 head，由后续的 `merge_resolve_all_heads` 合并。

修正说明（2026-09-27）
---------------------
原实现写成 `down_revision = 'pg_standalone_010'` + 一长串 `depends_on`。
Alembic 只把 `down_revision` 当作「版本化父节点」，`depends_on` 仅用于排序：

1. `pg_standalone_010` 当时已不是 head（被 011 -> add_backup_record ->
   add_app_version -> add_stock_return 取代），Alembic 在 merge 时会对每个
   非 head 父节点执行 `HeadMaintainer._delete_version()`，于是抛
   `KeyError: 'pg_standalone_010'`，空库 `alembic upgrade head` 永远无法收尾；
2. `depends_on` 里的 7 个 head 不因此变成非 head，全局 head 数不为 1。

现在所有真实 head 一律用元组 `down_revision` 声明：既保证 merge 时全部是
当前 head（不再 KeyError），也让全局 head 收敛为 1 个。

（现网 `erp_system` 的版本表实际是 stamp 出来的，本迁移链历史上从未端到端
跑通；见 `merge_resolve_all_heads` 的注释。）
"""

# revision identifiers, used by Alembic.
revision = 'merge_all_heads'
down_revision = (
    'pg_standalone_003',
    'add_order_batch_fields',
    'add_order_type_country_stockin',
    'add_pp_composite_idx',
    'add_stock_return',
    'add_updated_at',
    'a8f3c2d1e5b7',
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
