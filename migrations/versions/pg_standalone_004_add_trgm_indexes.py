"""添加 pg_trgm 扩展和 GIN 三字组索引

启用 PostgreSQL 内置的 pg_trgm 扩展，为产品名称、条码和客户
名称、联系人、电话字段创建 GIN 三字组索引。

这将使 ILIKE '%keyword%' 查询能够利用索引，大幅提升模糊搜索性能，
无需引入 Elasticsearch 等外部搜索引擎。

Revision ID: pg_standalone_004
Revises: 659467a97350
Create Date: 2026-04-23
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'pg_standalone_004'
down_revision = '659467a97350'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 启用 pg_trgm 扩展（PostgreSQL 自带，无需安装）
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')

    # 2. 为产品表搜索字段创建 GIN 三字组索引
    # 注意：Alembic 迁移在事务中运行，CONCURRENTLY 不支持事务，
    # 因此使用普通 CREATE INDEX（数据量不大时不锁表太久）
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_product_name_trgm '
        "ON product USING gin (name gin_trgm_ops)"
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_product_barcode_trgm '
        "ON product USING gin (barcode gin_trgm_ops)"
    )

    # 3. 为客户表搜索字段创建 GIN 三字组索引
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_customer_name_trgm '
        "ON customer USING gin (name gin_trgm_ops)"
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_customer_contact_trgm '
        "ON customer USING gin (contact gin_trgm_ops)"
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_customer_phone_trgm '
        "ON customer USING gin (phone gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS idx_customer_phone_trgm')
    op.execute('DROP INDEX IF EXISTS idx_customer_contact_trgm')
    op.execute('DROP INDEX IF EXISTS idx_customer_name_trgm')
    op.execute('DROP INDEX IF EXISTS idx_product_barcode_trgm')
    op.execute('DROP INDEX IF EXISTS idx_product_name_trgm')
    # 注意：不自动删除 pg_trgm 扩展，其他功能可能依赖它
