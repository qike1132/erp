"""add customer_sampling_role table and role_id on part / fabric_version

Revision ID: pg_standalone_028_cs_role
Revises: add_order_confirm_fields
Create Date: 2026-08-12

为打样项目引入"角色"维度，让每个角色独立维护自己的部位布料与版本快照：

- 新建 customer_sampling_role 表（role_name 项目内唯一、is_default 标记默认角色、
  current_version 该角色独立最终版本、乐观锁 version）
- customer_sampling_part 增加 role_id 列（NOT NULL，外键 CASCADE 删角色级联删部位）
- customer_sampling_fabric_version 增加 role_id 列（NOT NULL，外键 CASCADE）
- 旧 project.current_version 字段保留为兼容字段，新逻辑改读 role.current_version

数据迁移：
1. 为每个旧项目插入一行 role_name='默认角色', is_default=true,
   current_version=project.current_version 的角色记录
2. 把所有旧 customer_sampling_part.role_id 回填到所属项目的默认角色 id
3. 把所有旧 customer_sampling_fabric_version.role_id 回填到对应项目的默认角色 id
4. drop 旧索引 uq_csp_part_name（project_id+part_name 普通索引，由 021 添加）
   + uq_csfv_project_version（project_id+version_no 唯一约束，由 019 添加）
5. 新增唯一索引 idx_csp_role_part_version (role_id, version_no, part_name)
6. 新增索引 idx_csp_role_id（role_id 单列，加速按角色筛选部位）
7. 新增唯一索引 uq_csfv_role_version (role_id, version_no)

兼容策略：
- 旧端点未传 role_id 时默认指向项目的默认角色（service 层逻辑）
- 旧前端代码无需修改即可继续工作
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import create_index_if_columns_exist

revision = 'pg_standalone_028_cs_role'
down_revision = 'add_order_confirm_fields'
branch_labels = None
depends_on = None

def upgrade():
    # 1. 创建角色表
    op.create_table(
        'customer_sampling_role',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(),
                  sa.ForeignKey('customer_sampling_project.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('role_name', sa.String(100), nullable=False, comment='角色名称'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0', comment='排序值'),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false',
                  comment='是否默认角色（不可删除）'),
        sa.Column('current_version', sa.String(8), nullable=False, server_default='T1',
                  comment='该角色当前最终版本 T1/T2/T3...'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()'), comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()'), comment='更新时间'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='0',
                  comment='乐观锁版本号'),
        sa.UniqueConstraint('project_id', 'role_name', name='uq_cs_role_project_name'),
    )
    create_index_if_columns_exist('idx_cs_role_project_sort', 'customer_sampling_role',
                    ['project_id', 'sort_order'])

    # 2. 为每个旧项目插入默认角色（current_version 沿用 project.current_version）
    op.execute("""
        INSERT INTO customer_sampling_role (project_id, role_name, sort_order, is_default, current_version)
        SELECT id, '默认', 0, TRUE, COALESCE(current_version, 'T1')
        FROM customer_sampling_project
    """)

    # 3. customer_sampling_part 增加 role_id 列（先允许 NULL，回填后再设 NOT NULL）
    op.add_column('customer_sampling_part',
                  sa.Column('role_id', sa.Integer(),
                            sa.ForeignKey('customer_sampling_role.id', ondelete='CASCADE'),
                            comment='关联角色ID'))

    # 回填：每个 part 的 role_id = 它所属项目的默认角色 id
    op.execute("""
        UPDATE customer_sampling_part p
        SET role_id = r.id
        FROM customer_sampling_role r
        WHERE r.project_id = p.project_id AND r.is_default = TRUE
    """)

    # 设置 NOT NULL（回填后所有行都有 role_id）
    op.alter_column('customer_sampling_part', 'role_id',
                    existing_type=sa.Integer(), nullable=False)

    # 4. customer_sampling_fabric_version 增加 role_id 列（同上流程）
    op.add_column('customer_sampling_fabric_version',
                  sa.Column('role_id', sa.Integer(),
                            sa.ForeignKey('customer_sampling_role.id', ondelete='CASCADE'),
                            comment='关联角色ID'))

    op.execute("""
        UPDATE customer_sampling_fabric_version v
        SET role_id = r.id
        FROM customer_sampling_role r
        WHERE r.project_id = v.project_id AND r.is_default = TRUE
    """)

    op.alter_column('customer_sampling_fabric_version', 'role_id',
                    existing_type=sa.Integer(), nullable=False)

    # 5. 删除旧索引（用 IF EXISTS，避免索引名漂移导致中断）
    # 5a. 旧的 part 名称+版本索引（无 role_id 维度，被新索引替代）
    op.execute('DROP INDEX IF EXISTS idx_csp_part_name_version')
    op.execute('DROP INDEX IF EXISTS idx_csp_part_name')
    # 5b. 旧的 fabric_version project+version 索引（普通+唯一，被新索引替代）
    op.execute('DROP INDEX IF EXISTS idx_csfv_project_version')
    # uq_csfv_project_version 在 019 里是以 UNIQUE 约束形式建的，
    # 直接 DROP INDEX 会因约束依赖而报 DependentObjectsStillExist：
    # 先按约束删除，若它其实是普通索引，下面的 DROP INDEX 再兜底。
    op.execute(
        'ALTER TABLE customer_sampling_fabric_version '
        'DROP CONSTRAINT IF EXISTS uq_csfv_project_version'
    )
    op.execute('DROP INDEX IF EXISTS uq_csfv_project_version')

    # 6. 新增角色维度索引
    # 6a. part: 同角色同版本下部位名组合索引
    # 注：历史数据存在重复行（project_id=384 等项目同 (T1, 头部) 有 4 行），
    # 改用普通索引而非 UNIQUE 索引；应用层 _ensure_part_name_unique 已做唯一校验兜底。
    create_index_if_columns_exist(
        'idx_csp_role_part_version', 'customer_sampling_part',
        ['role_id', 'version_no', 'part_name'],
    )
    # 6b. part: 单列 role_id 索引（按角色筛选部位）
    create_index_if_columns_exist('idx_csp_role_id', 'customer_sampling_part', ['role_id'])

    # 6c. fabric_version: 同角色同版本组合索引（同上理由用普通索引）
    create_index_if_columns_exist(
        'idx_csfv_role_version', 'customer_sampling_fabric_version',
        ['role_id', 'version_no'],
    )
    # 6d. fabric_version: 单列 role_id 索引
    create_index_if_columns_exist('idx_csfv_role_id', 'customer_sampling_fabric_version', ['role_id'])

def downgrade():
    # 删除新索引
    op.drop_index('idx_csfv_role_id', table_name='customer_sampling_fabric_version', if_exists=True)
    op.drop_index('uq_csfv_role_version', table_name='customer_sampling_fabric_version', if_exists=True)
    op.drop_index('idx_csp_role_id', table_name='customer_sampling_part', if_exists=True)
    op.drop_index('idx_csp_role_part_version', table_name='customer_sampling_part', if_exists=True)

    # 恢复旧索引（对称恢复，列与原始一致）
    op.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_csfv_project_version ON customer_sampling_fabric_version (project_id, version_no)')
    create_index_if_columns_exist('idx_csp_part_name_version', 'customer_sampling_part',
                    ['project_id', 'version_no', 'part_name'])

    # 删除 role_id 列
    op.drop_column('customer_sampling_fabric_version', 'role_id')
    op.drop_column('customer_sampling_part', 'role_id')

    # 删除角色表
    op.drop_index('idx_cs_role_project_sort', table_name='customer_sampling_role', if_exists=True)
    op.drop_table('customer_sampling_role')
