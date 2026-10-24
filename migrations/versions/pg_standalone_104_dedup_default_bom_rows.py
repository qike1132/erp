"""默认作用域 BOM 行去重 + partial unique index（AUD-09，2026-10-24 审计 P1）

背景
----
038 把三张物料表的唯一约束从 (product_id) 调整为 (product_id, role_id) 以支持
角色 BOM；但 PostgreSQL 唯一约束中 NULL 互不相等——(product_id, NULL) 的
「产品级默认 BOM 填充行」自此不受任何 DB 约束兜底（038 注释自认此洞）。
写入侧 save_bom 全程无行锁、查后插：并发两次保存同一产品（双开页面/网络重试）
会双双读到"无默认填充行"并 INSERT，落两条 (product_id, NULL) 行。下游
Product.get_all_materials 对每行都计入棉用量——物料计算/采购量按 2 倍计量
（资金相关字段脏数据），且无任何报错。

本次修复（应用层行锁见 bom_service.save_bom，本迁移补 DB 最终防线）：
1. 存量去重：每张表按 product_id 分组（仅 role_id IS NULL 的行），保留最小 id，
   删除其余；
2. partial unique index：(product_id) WHERE role_id IS NULL —— 默认作用域回归
   038 之前的硬 1:1，角色作用域（role_id 非空）不受影响。
   表名逐字展开写死（不走 f-string 循环，038 的同款循环写法曾被扫描器误报）。

downgrade：仅 DROP INDEX（去重删除的行不恢复——与 add_po_dedup_unique_index
同口径：数据修正不可逆）。
"""
from alembic import op

revision = 'pg_standalone_104_dedup_default_bom_rows'
down_revision = 'pg_standalone_103_drop_stockin_is_deleted'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 存量去重：每组 (product_id) 的默认作用域行保留最小 id，删其余。
    #    索引建在前会因存量重复直接失败，故先删后建。
    op.execute(
        "DELETE FROM product_fabric a USING product_fabric b "
        "WHERE a.role_id IS NULL AND b.role_id IS NULL "
        "AND a.product_id = b.product_id AND a.id > b.id"
    )
    op.execute(
        "DELETE FROM product_accessory a USING product_accessory b "
        "WHERE a.role_id IS NULL AND b.role_id IS NULL "
        "AND a.product_id = b.product_id AND a.id > b.id"
    )
    op.execute(
        "DELETE FROM product_material a USING product_material b "
        "WHERE a.role_id IS NULL AND b.role_id IS NULL "
        "AND a.product_id = b.product_id AND a.id > b.id"
    )
    # 2. DB 最终防线：默认作用域硬 1:1（角色作用域不受影响）
    op.execute(
        "CREATE UNIQUE INDEX uq_product_fabric_default_scope "
        "ON product_fabric (product_id) WHERE role_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_product_accessory_default_scope "
        "ON product_accessory (product_id) WHERE role_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_product_material_default_scope "
        "ON product_material (product_id) WHERE role_id IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_product_fabric_default_scope")
    op.execute("DROP INDEX IF EXISTS uq_product_accessory_default_scope")
    op.execute("DROP INDEX IF EXISTS uq_product_material_default_scope")
