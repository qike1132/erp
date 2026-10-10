"""采购单编号前缀 CG → PO（数据迁移，非破坏性）

背景
----
``/purchase``「待生产订单」表把「待生成行」（来源客户订单 ``PO-…``／备货 ``BH-…``）
与「待生产行」（采购单 ``CG-…``）并列同表、共用同一列「订单号」，同一列出现两种
前缀。经确认把采购单编号规则统一为 ``PO``：新单由
``numbering.generate_purchase_order_number`` 直接发 ``PO-…``，存量单号**只换前缀、
数字段不变**。

本迁移做什么
------------
1. ``purchase_order.order_no``：``CG-…`` → ``PO-…``（数字段不变）。
2. ``material_registration.purchase_order_no``：引用副本（创建时的快照），同步换前缀。
3. 抬升 ``numbering_counter`` 的 ``(PO, 日期)`` 水位到「``order`` ∪ ``purchase_order``
   当日最大号」，关闭「迁移落地 → 应用启动对账」之间的取号窗口
   （应用启动时 ``reconcile_numbering_counters`` 亦会做同样的事，此处提前一遍）。

幂等：只命中 ``^CG-[0-9]{8}-[0-9]+$`` 的行，重复执行无变化。无破坏性 DDL。

取舍（已确认）
--------------
采购单与客户订单自此共用 ``(PO, 日期)`` 计数器 —— 同一字符串可能同时存在于
``order`` 与 ``purchase_order``（靠来源/类型区分），但新号绝不重号。备货 ``BH``
前缀不动。

Revision ID: pg_standalone_089_po_prefix_unify
Revises: pg_standalone_088_product_role_private_p1
Create Date: 2026-10-10
"""
from alembic import op

revision = 'pg_standalone_089_po_prefix_unify'
down_revision = 'pg_standalone_088_product_role_private_p1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 存量采购单号：只换前缀，数字段不变（CG-20260918-0008 → PO-20260918-0008）
    op.execute(
        "UPDATE purchase_order "
        "SET order_no = 'PO' || substr(order_no, 3) "
        "WHERE order_no ~ '^CG-[0-9]{8}-[0-9]+$'"
    )

    # 2. 引用副本同步（来料登记的采购单号是创建时快照）
    op.execute(
        "UPDATE material_registration "
        "SET purchase_order_no = 'PO' || substr(purchase_order_no, 3) "
        "WHERE purchase_order_no ~ '^CG-[0-9]{8}-[0-9]+$'"
    )

    # 3. 水位对账：把 (PO, 日期) 抬到两表当日最大号（只升不降，幂等）
    op.execute("""
        INSERT INTO numbering_counter (prefix, number_date, last_seq, updated_at)
        SELECT 'PO', d.number_date, d.mx, now()
        FROM (
            SELECT split_part(order_no, '-', 2) AS number_date,
                   MAX(CAST(split_part(order_no, '-', 3) AS BIGINT)) AS mx
            FROM (
                SELECT order_no FROM "order"        WHERE order_no ~ '^PO-[0-9]{8}-[0-9]+$'
                UNION ALL
                SELECT order_no FROM purchase_order WHERE order_no ~ '^PO-[0-9]{8}-[0-9]+$'
            ) u
            GROUP BY 1
        ) d
        WHERE d.mx IS NOT NULL
        ON CONFLICT (prefix, number_date)
        DO UPDATE SET last_seq = GREATEST(numbering_counter.last_seq, EXCLUDED.last_seq),
                      updated_at = now()
        WHERE EXCLUDED.last_seq > numbering_counter.last_seq
    """)


def downgrade() -> None:
    # 前缀改写可逆（数字段未动）；空库上为 no-op。
    # 注意：升级后新生成的采购单号亦为 PO-，一并回退为 CG-（与「CG 即采购单前缀」的旧语义一致）。
    op.execute(
        "UPDATE purchase_order "
        "SET order_no = 'CG' || substr(order_no, 3) "
        "WHERE order_no ~ '^PO-[0-9]{8}-[0-9]+$'"
    )
    op.execute(
        "UPDATE material_registration "
        "SET purchase_order_no = 'CG' || substr(purchase_order_no, 3) "
        "WHERE purchase_order_no ~ '^PO-[0-9]{8}-[0-9]+$'"
    )
