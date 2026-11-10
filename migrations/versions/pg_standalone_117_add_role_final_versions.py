"""customer_sampling_role 增加 final_versions（部位级最终版本覆盖）

Revision ID: pg_standalone_117_add_role_final_versions
Revises: pg_standalone_116_numbering_short_format
Create Date: 2026-11-10

背景
----
板房「最终版本」原先只能按角色存一个 ``current_version``：给 A 部位选 T2
会把整个角色（含 B 部位）的最终版本一起改成 T2，B 无法独立保留 T1。
现场要求**每个部位各自选择最终版本**。

``final_versions`` 是部位级覆盖映射 ``{部位名称: 版本号}``，与角色级
``current_version`` 的关系是「覆盖 vs 默认」：未在映射里的部位继续沿用
``current_version``（存量项目行为零变化），点选过的部位以映射为准。

存量数据不回填：映射为空即等价于旧行为；打印取数时逐部位解析
（覆盖 -> 角色默认 -> 该部位最新有数据的版本）。

幂等性
------
``ADD COLUMN IF NOT EXISTS``，空库重放（001 已按当前 ORM 元数据建表）
不会重复报错。Downgrade 的 ``DROP COLUMN`` 是标准回滚语句，已登记
destructive_ddl_baseline。
"""
from alembic import op

from migrations._legacy_base_guard import base_schema_absent

revision = 'pg_standalone_117_add_role_final_versions'
down_revision = 'pg_standalone_116_numbering_short_format'
branch_labels = None
depends_on = None


def upgrade():
    if base_schema_absent():
        return
    op.execute(
        "ALTER TABLE customer_sampling_role "
        "ADD COLUMN IF NOT EXISTS final_versions JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    # ORM 声明了 comment，迁移必须同步——否则 alembic check 会报 modify_comment。
    # 文案必须与 shared_models/customer_sampling.py 的列 comment 逐字一致。
    op.execute(
        "COMMENT ON COLUMN customer_sampling_role.final_versions IS "
        "'部位级最终版本覆盖 {部位名称: 版本号}'"
    )


def downgrade():
    if base_schema_absent():
        return
    op.execute(
        'ALTER TABLE customer_sampling_role DROP COLUMN IF EXISTS final_versions'
    )
