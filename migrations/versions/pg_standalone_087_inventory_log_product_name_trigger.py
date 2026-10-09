"""inventory_log 产品名快照：写入时自动补齐（存储层兜底）

背景
----
R1（迁移 073）给 inventory_log 加了 product_name / product_barcode 快照，
并约定「写路径带 product_name；删除时由 product_service.delete_product 对
仍为 NULL 的行 coalesce 回填」。但**写路径带不带快照全靠调用点自觉**：
仓库里 26 处直接构造 ``InventoryLog(...)`` 的点都没带 product_name
（order/commands、order/deduction、approval_service、batch_import_*、
staging/*、tasks/batch_tasks、product_service 等），只有 9 处走
``log_inventory_change(...)`` 的带了。

后果不是数据丢失 —— delete_product 仍会回填，R1 不变量成立；而是**审计口径
不一致**：产品改名后再删除，带快照的行记「写时名」、不带的行被回填成「删除时
名」，同一产品的历史里出现两套名字。

修法
----
把「product_name 为空则按 product_id 取当前产品名」下沉到**存储层**：
inventory_log 上的 BEFORE INSERT 行级触发器。一处覆盖所有现有与未来的写点
（含 raw SQL、批量导入、以及将来新增的服务），不再依赖调用点自觉。

口径
----
- 仅在 product_name **为空**时补；显式传入的值（log_inventory_change 路径）原样保留。
- 只补 product_name，**不动 product_barcode**：条码沿用 073 的既有设计
  「只在此处（删除时）快照」，且条码作为业务键几乎不改，保真度无缺口。
- **不回填存量行**：存量 NULL 行在删除时仍由 delete_product 回填，无需对生产
  台账做一次大批量 UPDATE。
- 代价：每次 INSERT 多一次 product 主键点查（行级触发器）。批量导入路径本就逐行
  做 apply_stock_delta_locked（SELECT FOR UPDATE + UPDATE），多一次 PK 点查为边际量。

幂等：CREATE OR REPLACE FUNCTION 天然幂等；触发器用 DROP ... IF EXISTS 后重建，
重复执行安全。
注：SQL 全部内联字面量直书（Mimosa 写入门禁要求，勿提取为模块常量）。

Revision ID: pg_standalone_087_inventory_log_product_name_trigger
Revises: pg_standalone_086_product_customer_link
Create Date: 2026-10-09
"""
from alembic import op

revision = 'pg_standalone_087_inventory_log_product_name_trigger'
down_revision = 'pg_standalone_086_product_customer_link'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION fill_inventory_log_product_name()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.product_name IS NULL AND NEW.product_id IS NOT NULL THEN
                SELECT p.name INTO NEW.product_name
                  FROM product p
                 WHERE p.id = NEW.product_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute('DROP TRIGGER IF EXISTS fill_inventory_log_product_name ON inventory_log')
    op.execute("""
        CREATE TRIGGER fill_inventory_log_product_name
            BEFORE INSERT ON inventory_log
            FOR EACH ROW
            EXECUTE FUNCTION fill_inventory_log_product_name();
    """)
    op.execute(
        'COMMENT ON FUNCTION fill_inventory_log_product_name() IS '
        "'写入 inventory_log 时若 product_name 为空，按 product_id 取当前产品名补齐'"
    )


def downgrade() -> None:
    op.execute('DROP TRIGGER IF EXISTS fill_inventory_log_product_name ON inventory_log')
    op.execute('DROP FUNCTION IF EXISTS fill_inventory_log_product_name()')
