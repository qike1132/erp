"""cleanup redundant default role

Revision ID: pg_standalone_050_cleanup_default_role
Revises: pg_standalone_049_stockin_soft_delete
Create Date: 2026-09-24

历史行为：create_project 无论用户是否填写自定义角色名，都会先插入一个
role_name='默认'（is_default=true, sort_order=0）的兜底角色，再把用户填写的
角色追加到后面。结果是自定义角色项目里多出一个无用的「默认」标签。

新行为：用户填写了自定义角色名时，首个角色即兜底角色（is_default=true,
sort_order=0），不再创建「默认」。

本迁移清理已产生的历史数据，仅处理满足全部条件的项目：
1. 存在 role_name='默认' 且 is_default=true 的角色（老模型特征）
2. 该项目存在至少一个 is_default=false 的角色（用户确实自定义过角色）
3. 该「默认」角色下没有任何部位（有数据则不动，避免误删/冲突）

处理动作：
- 把「默认」角色下的版本快照（T1 基线）改挂到接替角色
- 接替角色（sort_order 最小的自定义角色）提升为兜底角色：is_default=true, sort_order=0
- 删除多余的「默认」角色

downgrade 为空实现：这是一次性数据清理，回滚不会（也不应）恢复重复的
「默认」角色；代码侧 create_project 的新逻辑同样不会回退。
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'pg_standalone_050_cleanup_default_role'
down_revision = 'pg_standalone_049_stockin_soft_delete'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 待处理项目：老模型的空「默认」角色 + 其接替角色（sort_order 最小的自定义角色）
    op.execute("""
        CREATE TEMP TABLE tmp_cs_promote_role AS
        SELECT dr.id AS default_role_id,
               dr.project_id AS project_id,
               nr.id AS target_role_id
        FROM customer_sampling_role dr
        JOIN LATERAL (
            SELECT r.id
            FROM customer_sampling_role r
            WHERE r.project_id = dr.project_id
              AND r.is_default = FALSE
            ORDER BY r.sort_order, r.id
            LIMIT 1
        ) nr ON TRUE
        WHERE dr.is_default = TRUE
          AND dr.role_name = '默认'
          AND NOT EXISTS (
              SELECT 1 FROM customer_sampling_part p WHERE p.role_id = dr.id
          )
    """)

    # 1. 版本快照改挂到接替角色（自定义角色本身不持有版本快照，不会产生重复）
    op.execute("""
        UPDATE customer_sampling_fabric_version v
        SET role_id = t.target_role_id
        FROM tmp_cs_promote_role t
        WHERE v.role_id = t.default_role_id
    """)

    # 2. 接替角色成为兜底角色（is_default=true 且排到最前）
    op.execute("""
        UPDATE customer_sampling_role r
        SET is_default = TRUE,
            sort_order = 0,
            updated_at = now()
        FROM tmp_cs_promote_role t
        WHERE r.id = t.target_role_id
    """)

    # 3. 删除多余的「默认」角色
    op.execute("""
        DELETE FROM customer_sampling_role r
        USING tmp_cs_promote_role t
        WHERE r.id = t.default_role_id
    """)

    op.execute('DROP TABLE tmp_cs_promote_role')


def downgrade() -> None:
    """不可逆：一次性数据清理，不恢复重复的「默认」角色。"""
    pass
