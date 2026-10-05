"""drop product_image_orphan_backup（0 行、无迁移、无依赖的历史遗留表）

Revision ID: pg_standalone_069_drop_product_image_orphan_backup
Revises: pg_standalone_068_app_version_model
Create Date: 2026-10-05

背景（2026-10-05 只读核实，见 docs/audit-round2/03-data-layer.md）
----
- 0 行；无任何外键指向它、无视图 / 触发器依赖；
- **没有任何迁移创建它**（迁移链之外产生），ORM 也未声明 —— 是 `alembic check`
  的 `remove_table` 漂移项之一；
- 代码引用仅两处，本提交同步处理：
  * `scripts/purge_simulated_data.py` 的 `CLEAR_TABLES`（会 `DELETE FROM` 并复核行数）
    → 移除该条目，否则删表后清库脚本会在核验阶段报表不存在；
  * `fastapi_app/services/backup/orchestration/core.py` 的注释示例 → 更正。

安全性 / 落地方式
----
用 `_legacy_base_guard.drop_table_if_exists`：空库重放时该表本就不存在 → no-op，
不影响 CI 的空库 `upgrade head` + `check`；生产库该表存在 → DROP。
**本文件不代维护者执行**；是否应用到生产库由维护者决定。

downgrade 重建同构空表以保证可回滚（结构取自生产库 information_schema 实测）。
"""
from __future__ import annotations

import sqlalchemy as sa

from migrations._legacy_base_guard import create_table_if_absent, drop_table_if_exists

revision = 'pg_standalone_069_drop_product_image_orphan_backup'
down_revision = 'pg_standalone_068_app_version_model'
branch_labels = None
depends_on = None


def upgrade() -> None:
    drop_table_if_exists('product_image_orphan_backup')


def downgrade() -> None:
    # 重建同构空表（无数据，字段与删前一致），使回滚可逆。
    create_table_if_absent(
        'product_image_orphan_backup',
        sa.Column('id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=100), nullable=True),
        sa.Column('barcode', sa.String(length=50), nullable=True),
        sa.Column('image', sa.String(length=200), nullable=True),
        sa.Column('backed_up_at', sa.DateTime(), nullable=True),
    )
