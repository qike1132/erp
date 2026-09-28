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

from migrations._legacy_base_guard import base_schema_absent

# revision identifiers, used by Alembic.
revision = 'pg_standalone_004'
down_revision = '659467a97350'
branch_labels = None
# 本迁移及其后继（005..010）假定 pg_standalone_001 已建出基础 schema，
# 但它们的 down_revision 挂在 MySQL 时代的 659467a97350 上。用 depends_on
# 显式声明依赖，保证空库重放时 001 先执行（否则 product_fabric 等表还不存在）。
depends_on = ('pg_standalone_001',)

def upgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
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
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.execute('DROP INDEX IF EXISTS idx_customer_phone_trgm')
    op.execute('DROP INDEX IF EXISTS idx_customer_contact_trgm')
    op.execute('DROP INDEX IF EXISTS idx_customer_name_trgm')
    op.execute('DROP INDEX IF EXISTS idx_product_barcode_trgm')
    op.execute('DROP INDEX IF EXISTS idx_product_name_trgm')
    # 注意：不自动删除 pg_trgm 扩展，其他功能可能依赖它
