"""case_movement_indexes_and_comment_align

Revision ID: pg_standalone_065_case_movement_indexes
Revises: pg_standalone_064_oosp_unique_process
Create Date: 2026-10-04

背景（2026-10-04 第十四轮审计收尾）
--------------------------------
`alembic check`（CI 门禁）在 main 上变红 —— 非本轮改动引入，来自皮套管理重写
（迁移 062 `case_management_rebuild`）留下的 ORM↔DB 漂移：

  · `CaseMovement` 模型对 `case_id` / `customer` / `direction` / `movement_date`
    声明了 `index=True`（ORM 期望索引名 `ix_case_movement_<col>`），而迁移 062 只建了
    复合索引 `idx_case_movement_case_date` —— 4 个单列索引缺失；
  · 两处列注释漂移：`backup_record.status`（DB 旧注释 vs ORM 新注释）、
    `case_movement.updated_at`（DB 无注释 vs ORM '更新时间'）。

本迁移把 DB 对齐到 ORM（`alembic check` 的基准），使 CI 恢复绿色。均为加索引/改注释
的**非破坏性**变更；`ix_case_movement_case_date`（复合）保留不动。
"""

from alembic import op

from migrations._legacy_base_guard import alter_column_if_exists, create_index_if_absent

revision = 'pg_standalone_065_case_movement_indexes'
down_revision = 'pg_standalone_064_oosp_unique_process'
branch_labels = None
depends_on = None

_CM_INDEXES = [
    ('ix_case_movement_case_id', ['case_id']),
    ('ix_case_movement_customer', ['customer']),
    ('ix_case_movement_direction', ['direction']),
    ('ix_case_movement_movement_date', ['movement_date']),
]


def upgrade():
    for name, cols in _CM_INDEXES:
        create_index_if_absent(name, 'case_movement', cols)
    alter_column_if_exists('case_movement', 'updated_at', comment='更新时间')
    alter_column_if_exists(
        'backup_record', 'status',
        comment='状态: success/failed/running/partial/unknown',
    )


def downgrade():
    alter_column_if_exists('backup_record', 'status', comment='状态: success/failed/running')
    alter_column_if_exists('case_movement', 'updated_at', comment=None)
    for name, _cols in reversed(_CM_INDEXES):
        op.drop_index(name, table_name='case_movement', if_exists=True)
