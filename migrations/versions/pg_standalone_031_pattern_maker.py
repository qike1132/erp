"""pattern maker module - 打样模块客户改版师

为板房打样（/pattern-room）模块引入独立的「版师」分类维度，替代原「客户」：

- 新建 pattern_maker 表（版师姓名唯一）
- 将 customer_sampling_project.customer_id/customer_name 迁移为
  pattern_maker_id/pattern_maker_name
- 回填：从既有客户引用创建版师行，并建立映射

执行方式：标准 DDL + 数据回填，一次性迁移。
回滚：downgrade 恢复 customer_id/customer_name 并删除 pattern_maker 表。

Revision ID: pg_standalone_031_pattern_maker
Revises: pg_standalone_030
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'pg_standalone_031_pattern_maker'
down_revision = 'pg_standalone_030'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # ---- 1. 新建 pattern_maker 表 ----
    op.create_table(
        'pattern_maker',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False, comment='版师姓名'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='更新时间'),
        sa.UniqueConstraint('name', name='uq_pattern_maker_name'),
    )
    op.create_index(
        'idx_pattern_maker_name_trgm', 'pattern_maker', ['name'],
        postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'},
    )

    # ---- 2. 回填版师：从既有客户引用创建版师行 ----
    bind.execute(sa.text(
        "INSERT INTO pattern_maker (name) "
        "SELECT DISTINCT c.name FROM customer_sampling_project p "
        "JOIN customer c ON p.customer_id = c.id "
        "WHERE p.customer_id IS NOT NULL AND c.name IS NOT NULL"
    ))

    # ---- 3. 新增 pattern_maker_id / pattern_maker_name 列 ----
    op.add_column('customer_sampling_project', sa.Column('pattern_maker_id', sa.Integer(), comment='关联版师ID'))
    op.add_column('customer_sampling_project', sa.Column('pattern_maker_name', sa.String(200), comment='版师姓名(冗余)'))

    # ---- 4. 数据回填：按版师姓名 ↔ 客户姓名 映射建立关联 ----
    bind.execute(sa.text(
        "UPDATE customer_sampling_project p "
        "SET pattern_maker_id = pm.id, pattern_maker_name = pm.name "
        "FROM pattern_maker pm "
        "JOIN customer c ON c.name = pm.name "
        "WHERE p.customer_id = c.id"
    ))

    # ---- 5. 删除旧列与其外键/索引 ----
    op.drop_constraint('customer_sampling_project_customer_id_fkey', 'customer_sampling_project', type_='foreignkey')
    op.drop_index('idx_csp_customer', table_name='customer_sampling_project')
    op.drop_column('customer_sampling_project', 'customer_id')
    op.drop_column('customer_sampling_project', 'customer_name')

    # ---- 6. 新增外键与索引 ----
    op.create_foreign_key(
        'customer_sampling_project_pattern_maker_id_fkey',
        'customer_sampling_project', 'pattern_maker',
        ['pattern_maker_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('idx_csp_pattern_maker', 'customer_sampling_project', ['pattern_maker_id'])


def downgrade():
    # ---- 恢复旧列 ----
    op.add_column('customer_sampling_project', sa.Column('customer_id', sa.Integer(), comment='关联客户ID'))
    op.add_column('customer_sampling_project', sa.Column('customer_name', sa.String(200), comment='客户名称(冗余)'))

    # 通过 customer 表按姓名映射回客户（版师姓名源自客户姓名，可逆）
    bind = op.get_bind()
    bind.execute(sa.text(
        "UPDATE customer_sampling_project p "
        "SET customer_id = c.id, customer_name = c.name "
        "FROM customer c "
        "JOIN pattern_maker pm ON pm.name = c.name "
        "WHERE p.pattern_maker_id = pm.id"
    ))

    op.drop_index('idx_csp_pattern_maker', table_name='customer_sampling_project')
    op.drop_constraint('customer_sampling_project_pattern_maker_id_fkey', 'customer_sampling_project', type_='foreignkey')
    op.drop_column('customer_sampling_project', 'pattern_maker_id')
    op.drop_column('customer_sampling_project', 'pattern_maker_name')

    op.create_index('idx_csp_customer', 'customer_sampling_project', ['customer_id'])
    op.create_foreign_key(
        'customer_sampling_project_customer_id_fkey',
        'customer_sampling_project', 'customer',
        ['customer_id'], ['id'], ondelete='SET NULL',
    )

    op.drop_index('idx_pattern_maker_name_trgm', table_name='pattern_maker')
    op.drop_table('pattern_maker')
