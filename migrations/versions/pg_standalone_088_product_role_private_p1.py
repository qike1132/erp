"""BOM 角色改为「产品私有」阶段 1：放宽约束、加产品内唯一（非破坏性）

背景
----
现有 BOM 角色是**跨产品共享的全局字典**：`role` 表存角色名，`product_role` 是
「产品 × 全局角色」关联行；改名时 `apply_global_rename` 会把所有引用该角色的
产品一起改。业务上每个 SKU 的角色互相独立、不存在跨 SKU 复用，故本批（088/089）
把它退回「产品私有」。

为什么分两阶段
--------------
新代码不再写 `product_role.global_role_id`，但它当前是 **NOT NULL + FK**：不先放宽，
新代码 INSERT 就失败。本阶段只做**非破坏性**改动，放宽后**旧代码仍可正常跑**
（照常写值、app 层自带去重），从而可平滑切换、随时回滚。真正的删列/删表留到 089。

本阶段做什么
------------
1. 前置守卫（fail-closed）：`role_name` 无空值；且不存在同一产品内
   `lower(btrim(role_name))` 重复（现有数据因全局唯一必然满足，作为护栏——一旦
   不满足会让后续唯一索引建失败，故先显式报错要求人工处理）。
2. 归一化存量 `role_name`（btrim）——语义对齐应用层 `_name_key = lower(trim(name))`；
   归一后所有行都对齐，故第 4 步的索引可直接用可移植的 `lower(role_name)`
   （不写 btrim，避免给 SQLite 测试库引入 btrim UDF 依赖）。
3. `DROP CONSTRAINT uq_product_role_product_global`；`global_role_id DROP NOT NULL`。
4. 新建产品内唯一索引 `uq_product_role_product_name_lower (product_id, lower(role_name))`。

`role` 表与 FK `fk_product_role_global_role` **本阶段保留**（089 才删）。

降级
----
结构可还原（drop 新索引 / 重建旧唯一约束 / SET NOT NULL），但：
- `SET NOT NULL` 在新代码已写入 NULL 行时会失败（新代码不再写该列）；
- 045 的跨产品共享语义**不还原**。
故本降级只保证「结构对齐」，语义不回溯。

注：SQL 全部内联字面量直书（Mimosa 写入门禁要求，勿提取为模块常量）。

Revision ID: pg_standalone_088_product_role_private_p1
Revises: pg_standalone_087_inventory_log_product_name_trigger
Create Date: 2026-10-10
"""
from alembic import op

revision = 'pg_standalone_088_product_role_private_p1'
down_revision = 'pg_standalone_087_inventory_log_product_name_trigger'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 守卫：role_name 非空 + 产品内 lower(btrim(name)) 无重复（fail-closed）
    op.execute("""
        DO $$
        DECLARE n bigint;
        BEGIN
            SELECT count(*) INTO n
              FROM product_role
             WHERE role_name IS NULL OR btrim(role_name) = '';
            IF n > 0 THEN
                RAISE EXCEPTION '088 中止：product_role 存在 % 行 role_name 为空，需先人工处理', n;
            END IF;

            SELECT count(*) INTO n FROM (
                SELECT product_id, lower(btrim(role_name))
                  FROM product_role
                 GROUP BY 1, 2
                HAVING count(*) > 1
            ) d;
            IF n > 0 THEN
                RAISE EXCEPTION '088 中止：% 组同产品内 lower(btrim(role_name)) 重复，建唯一索引会失败，需先人工处理', n;
            END IF;
        END $$;
    """)

    # 2. 归一化存量镜像名（对齐应用层 lower(trim(name)) 口径）
    op.execute(
        "UPDATE product_role SET role_name = btrim(role_name) WHERE role_name <> btrim(role_name)"
    )

    # 3. 放宽：去掉旧唯一约束、列改可空
    op.execute('ALTER TABLE product_role DROP CONSTRAINT IF EXISTS uq_product_role_product_global')
    op.execute('ALTER TABLE product_role ALTER COLUMN global_role_id DROP NOT NULL')

    # 4. 产品内角色名唯一（可移植：lower() 在 PG 与 SQLite 均可用）
    op.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_product_role_product_name_lower '
        'ON product_role (product_id, lower(role_name))'
    )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS uq_product_role_product_name_lower')
    # 若新代码已写入 NULL 行，SET NOT NULL 会失败——属已知限制（见模块 docstring）
    op.execute('ALTER TABLE product_role ALTER COLUMN global_role_id SET NOT NULL')
    op.execute(
        'ALTER TABLE product_role ADD CONSTRAINT uq_product_role_product_global '
        'UNIQUE (product_id, global_role_id)'
    )
