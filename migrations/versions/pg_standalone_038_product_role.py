"""BOM 配置·角色字段：product_role 表 + 三张物料表增加 role_id

P0-2(2026-09-10 设计确认): 支持一个 SKU 关联不定数量的角色，每个角色拥有独立的
面料/填充/辅料物料清单。新增 product_role 表；product_fabric / product_accessory /
product_material 各增加可空 role_id（NULL = 产品级默认 BOM，存量行不受影响）；
product_material 唯一约束由 (product_id) 调整为 (product_id, role_id)，以支持
每个角色一条填充物。删除角色由 FK ON DELETE CASCADE 级联清理其物料。

Revision ID: pg_standalone_038_product_role
Revises: pg_standalone_037_backup_dr_monthly
Create Date: 2026-09-10
"""
from alembic import op

revision = 'pg_standalone_038_product_role'
down_revision = 'pg_standalone_037_backup_dr_monthly'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 角色表
    op.execute(
        "CREATE TABLE product_role ("
        "    id SERIAL NOT NULL,"
        "    product_id INTEGER NOT NULL,"
        "    role_name VARCHAR(100) NOT NULL,"
        "    create_time TIMESTAMPTZ DEFAULT now(),"
        "    update_time TIMESTAMPTZ DEFAULT now(),"
        "    PRIMARY KEY (id),"
        "    FOREIGN KEY(product_id) REFERENCES product (id) ON DELETE CASCADE"
        ")"
    )
    op.execute('CREATE INDEX idx_product_role_product ON product_role (product_id);')
    op.execute("COMMENT ON COLUMN product_role.product_id IS '关联产品ID';")
    op.execute("COMMENT ON COLUMN product_role.role_name IS '角色名称';")
    op.execute("COMMENT ON COLUMN product_role.create_time IS '创建时间';")
    op.execute("COMMENT ON COLUMN product_role.update_time IS '更新时间';")

    # 2. 三张物料表增加可空 role_id（NULL = 产品级默认 BOM）
    for table in ('product_fabric', 'product_accessory', 'product_material'):
        op.execute(f'ALTER TABLE {table} ADD COLUMN role_id INTEGER;')
        op.execute(
            f'ALTER TABLE {table} ADD CONSTRAINT fk_{table}_role '
            f'FOREIGN KEY (role_id) REFERENCES product_role (id) ON DELETE CASCADE;'
        )
        op.execute(f'CREATE INDEX idx_{table}_role_id ON {table} (role_id);')
        op.execute(f"COMMENT ON COLUMN {table}.role_id IS '角色ID(NULL=产品级默认BOM)';")

    # 3. product_material 唯一约束 (product_id) → (product_id, role_id)
    #    PostgreSQL 唯一约束中 NULL 互不相等，多个产品级(NULL)填充行在语义上仍唯一
    op.execute('ALTER TABLE product_material DROP CONSTRAINT product_material_product_id_key;')
    op.execute(
        'ALTER TABLE product_material ADD CONSTRAINT uq_product_material_product_role '
        'UNIQUE (product_id, role_id);'
    )


def downgrade() -> None:
    # 逆序回滚：先还原唯一约束，再删物料表 role_id 列，最后删角色表
    op.execute('ALTER TABLE product_material DROP CONSTRAINT uq_product_material_product_role;')
    op.execute('ALTER TABLE product_material ADD CONSTRAINT product_material_product_id_key UNIQUE (product_id);')
    for table in ('product_fabric', 'product_accessory', 'product_material'):
        op.execute(f'ALTER TABLE {table} DROP CONSTRAINT fk_{table}_role;')
        op.execute(f'DROP INDEX idx_{table}_role_id;')
        op.execute(f'ALTER TABLE {table} DROP COLUMN role_id;')
    op.execute('DROP TABLE product_role;')
