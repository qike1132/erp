"""默认作用域 BOM 填充行去重 + partial unique index（AUD-09，2026-10-24 审计 P1）

背景
----
038 把 product_material 的唯一约束从 (product_id) 调整为 (product_id, role_id)
以支持角色 BOM；但 PostgreSQL 唯一约束中 NULL 互不相等——(product_id, NULL)
的「产品级默认 BOM 填充行」自此不受任何 DB 约束兜底（038 注释自认此洞）。
写入侧 save_bom 全程无行锁、查后插：并发两次保存同一产品（双开页面/网络重试）
会双双读到"无默认填充行"并 INSERT，落两条 (product_id, NULL) 行。下游
Product.get_all_materials 对每行都计入棉用量——物料计算/采购量按 2 倍计量
（资金相关字段脏数据），且无任何报错。

作用域（PR#12 CL 修正，2026-10-24）：**仅 product_material（填充表）**——
「每个产品只有一条」是填充表的业务语义（模型 docstring 自证）；布料表
（product_fabric）与配件表（product_accessory）的默认作用域本来就允许
多行（一个产品默认 BOM 有多种布料/配件，test_factory_summary_multisku
等夹具即证据），套 unique 会把合法数据当脏数据拒掉。首版把三张表都套了
unique，CI 的 sqlite 夹具测试当场拒绝合法数据——这正是 CL 的价值。

本次修复（应用层行锁见 bom_service.save_bom，本迁移补 DB 最终防线）：
1. 存量去重：product_material 按 product_id 分组（仅 role_id IS NULL），
   保留最小 id，删除其余；
2. partial unique index：(product_id) WHERE role_id IS NULL——默认作用域
   回归 038 之前的硬 1:1，角色作用域（role_id 非空）不受影响。
   表名与 DDL 逐字展开写死（不走 f-string 循环，避免扫描器误报）。

downgrade：仅 DROP INDEX（去重删除的行不恢复——与 add_po_dedup_unique_index
同口径：数据修正不可逆）。
"""
from alembic import op

revision = 'pg_standalone_104_dedup_default_bom_rows'
down_revision = 'pg_standalone_103_drop_stockin_is_deleted'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 存量去重：每组 (product_id) 的默认作用域填充行保留最小 id，删其余。
    #    索引建在前会因存量重复直接失败，故先删后建。
    op.execute(
        "DELETE FROM product_material a USING product_material b "
        "WHERE a.role_id IS NULL AND b.role_id IS NULL "
        "AND a.product_id = b.product_id AND a.id > b.id"
    )
    # 2. DB 最终防线：默认作用域硬 1:1（角色作用域不受影响）
    op.execute(
        "CREATE UNIQUE INDEX uq_product_material_default_scope "
        "ON product_material (product_id) WHERE role_id IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_product_material_default_scope")
