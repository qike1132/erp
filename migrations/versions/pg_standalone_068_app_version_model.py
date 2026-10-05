"""app_version: 把历史手工表纳回 ORM（消除 remove_table 漂移）

Revision ID: pg_standalone_068_app_version_model
Revises: pg_standalone_067_import_idempotency
Create Date: 2026-10-05

背景
----
`app_version` 由 `add_app_version.py` 的注释记载为「Alembic 之外手工创建」，
此前**没有任何迁移在空库上重建它**；而把它纳入 ORM（
`fastapi_app/shared_models/app_version.py`）后，CI 的空库
`upgrade head` + `check` 会因「ORM 有、迁移重放无」而报 `add_table`。

本迁移补齐这一环：在空库上创建出与 ORM 声明一致的 `app_version` 及其索引，
使「空库重放 == ORM」成立；对生产库则因表已存在而整体跳过（不改变现网结构）。

为何用幂等包装
--------------
生产库该表早于本迁移存在，且列定义以库为准（见模型文档）。`create_table_if_absent`
/ `create_index_if_absent`（`migrations/_legacy_base_guard.py`）在对象已存在时是
no-op，故本迁移在现网与空库上都安全。

downgrade 刻意空转
------------------
回滚若删表，会毁掉早于本迁移就存在于生产库的数据（该表并非由本迁移创建）。
"""
from __future__ import annotations

import sqlalchemy as sa

from migrations._legacy_base_guard import create_index_if_absent, create_table_if_absent

revision = 'pg_standalone_068_app_version_model'
down_revision = 'pg_standalone_067_import_idempotency'
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_absent(
        'app_version',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('platform', sa.String(length=20), nullable=False,
                  server_default=sa.text("'android'")),
        sa.Column('version_code', sa.Integer(), nullable=False),
        sa.Column('version_name', sa.String(length=50), nullable=False),
        sa.Column('download_url', sa.String(length=500), nullable=False),
        sa.Column('changelog', sa.Text(), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('md5_hash', sa.String(length=64), nullable=True),
        sa.Column('force_update', sa.Boolean(), nullable=True,
                  server_default=sa.text('false')),
        sa.Column('is_active', sa.Boolean(), nullable=True,
                  server_default=sa.text('true')),
        sa.Column('pushed', sa.Boolean(), nullable=True,
                  server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=True,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    create_index_if_absent(
        'idx_app_version_platform_code', 'app_version', ['platform', 'version_code'],
    )


def downgrade() -> None:
    # 刻意空转：app_version 早于本迁移就存在于生产库，删表会毁掉既有数据。
    # 本迁移只做「空库重放收口」，回滚不应对现网结构做任何破坏性变更。
    pass
