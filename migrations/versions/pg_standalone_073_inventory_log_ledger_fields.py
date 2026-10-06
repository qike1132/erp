"""inventory_log 台账化：操作人/结存列 + 产品名快照（产品删除不再抹掉流水）

背景
----
一、流水缺「谁改的、改前改后是多少」
   inventory_log 现有 change_type / change_quantity / change_date / related_id /
   note / customer，但没有操作人，也没有运行结存。需求（库存查询模块 2.4）要求
   「记录所有库存数量变更操作，包括操作人、时间、变动前后数量」。本次补三列。

二、产品删除会连历史一起抹掉（R1）
   inventory_log.product_id 原为 ``FOREIGN KEY ... ON DELETE CASCADE``，
   product_service.delete_product 还会先显式 DELETE 一遍流水，
   结果：删产品 = 该产品全部库存流水永久消失，变动历史与审计能力凭空归零。
   三家主流开源 ERP 一致反着做：
     · ERPNext  Stock Ledger Entry 的 item_code 是软引用（DF.Link），不级联；
     · InvenTree 文档明示「即使 stock item 被删除，关联 tracking 记录仍保留」；
     · Odoo      stock.move.line 不随产品删除而消失。
   故本迁移把外键改为 ON DELETE SET NULL，并在流水行上冗余产品名/条码快照，
   使产品删除后历史仍可读（口径：product_name 优先取快照，回退 JOIN product）。

三、对比度选择说明
   未采用「存在流水即禁止删除产品」方案：那会让现在能删的产品突然删不掉，
   属行为回退；且 delete_product 已用 订单/备货/出货 三类关联计数兜底，
   真正会走到「有流水但无单据」的产品本就很少（抵扣回滚/导入/生产等路径）。
   外键改 SET NULL 严格弱于「禁止删除」，不削弱任何既有守卫。

幂等：全部 ADD COLUMN / INDEX / DROP CONSTRAINT 带 IF (NOT) EXISTS 守卫，
重复执行安全。
注：SQL 全部内联字面量直书（Mimosa 写入门禁要求，勿提取为模块常量）。
不回填 operator_id / quantity_before / quantity_after：历史行无据可推，
留 NULL 由前端显示「—」；product_name/product_barcode 则**回填**，
因为这两项对现存产品是事实数据，不属猜测。

Revision ID: pg_standalone_073_inventory_log_ledger_fields
Revises: pg_standalone_072_stock_return_fk_restrict
Create Date: 2026-10-06
"""
from alembic import op

revision = 'pg_standalone_073_inventory_log_ledger_fields'
down_revision = 'pg_standalone_072_stock_return_fk_restrict'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- 1. 操作人（可空：ARQ/脚本等无用户上下文的写点留 NULL） ----
    op.execute(
        'ALTER TABLE inventory_log ADD COLUMN IF NOT EXISTS operator_id INTEGER '
        'REFERENCES "user"(id) ON DELETE SET NULL'
    )
    # ---- 2. 运行结存（记账时序的前后值；历史行 NULL） ----
    op.execute('ALTER TABLE inventory_log ADD COLUMN IF NOT EXISTS quantity_before INTEGER')
    op.execute('ALTER TABLE inventory_log ADD COLUMN IF NOT EXISTS quantity_after INTEGER')
    # ---- 3. 产品标识快照（产品删除后历史仍可读） ----
    op.execute('ALTER TABLE inventory_log ADD COLUMN IF NOT EXISTS product_name VARCHAR(100)')
    op.execute('ALTER TABLE inventory_log ADD COLUMN IF NOT EXISTS product_barcode VARCHAR(50)')

    op.execute('CREATE INDEX IF NOT EXISTS ix_inventory_log_operator_id ON inventory_log (operator_id)')

    op.execute('COMMENT ON COLUMN inventory_log.operator_id IS \'操作人ID（产品/脚本路径为 NULL）\'')
    op.execute('COMMENT ON COLUMN inventory_log.quantity_before IS \'变动前库存（记账时序；历史行为 NULL）\'')
    op.execute('COMMENT ON COLUMN inventory_log.quantity_after IS \'变动后库存（记账时序；历史行为 NULL）\'')
    op.execute('COMMENT ON COLUMN inventory_log.product_name IS \'产品名称快照（产品删除后仍可读）\'')
    op.execute('COMMENT ON COLUMN inventory_log.product_barcode IS \'产品条码快照\'')
    op.execute('COMMENT ON COLUMN inventory_log.product_id IS \'产品ID（产品删除后置空，历史保留）\'')

    # ---- 4. 回填产品标识快照（对现存产品是事实数据，非推断） ----
    op.execute(
        'UPDATE inventory_log il SET product_name = p.name, product_barcode = p.barcode '
        'FROM product p WHERE il.product_id = p.id AND il.product_name IS NULL'
    )

    # ---- 5. 外键 CASCADE -> SET NULL，并放开 NOT NULL ----
    # 顺序：先放开 NOT NULL 再换外键（反之会在 SET NULL 语义下短暂违反 NOT NULL）
    op.execute('ALTER TABLE inventory_log ALTER COLUMN product_id DROP NOT NULL')
    op.execute('ALTER TABLE inventory_log DROP CONSTRAINT IF EXISTS inventory_log_product_id_fkey')
    op.execute(
        'ALTER TABLE inventory_log ADD CONSTRAINT inventory_log_product_id_fkey '
        'FOREIGN KEY (product_id) REFERENCES product(id) ON DELETE SET NULL'
    )


def downgrade() -> None:
    # 回退到旧的「NOT NULL + CASCADE」模型时，product_id 为空的行无法表示：
    # 这些正是产品已删除后保留下来的历史（本迁移的存在意义），只能删除。
    op.execute('DELETE FROM inventory_log WHERE product_id IS NULL')

    op.execute('ALTER TABLE inventory_log DROP CONSTRAINT IF EXISTS inventory_log_product_id_fkey')
    op.execute('ALTER TABLE inventory_log ALTER COLUMN product_id SET NOT NULL')
    op.execute(
        'ALTER TABLE inventory_log ADD CONSTRAINT inventory_log_product_id_fkey '
        'FOREIGN KEY (product_id) REFERENCES product(id) ON DELETE CASCADE'
    )

    op.execute('DROP INDEX IF EXISTS ix_inventory_log_operator_id')
    op.execute('ALTER TABLE inventory_log DROP COLUMN IF EXISTS product_barcode')
    op.execute('ALTER TABLE inventory_log DROP COLUMN IF EXISTS product_name')
    op.execute('ALTER TABLE inventory_log DROP COLUMN IF EXISTS quantity_after')
    op.execute('ALTER TABLE inventory_log DROP COLUMN IF EXISTS quantity_before')
    op.execute('ALTER TABLE inventory_log DROP COLUMN IF EXISTS operator_id')
