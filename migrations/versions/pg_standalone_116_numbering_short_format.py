"""单号格式改为月流水（PO-2611-001）—— 重建 9 个编号查询族表达式索引

背景
----
2026-11-09 起单号从 ``<前缀>-<YYYYMMDD>-<4位序号>`` 改为
``<前缀>-<YYMM>-<3位序号>``（如 ``PO-2611-001``）。

``NUMBERING_FORMAT_REGEX`` 同时是 9 张表 ``idx_*_no_date_seq`` 部分表达式索引
的谓词、取号 / 巡检 / 对账 SQL 的过滤器。PostgreSQL **不做正则蕴含推断**：
谓词任一处先漂移，索引即静默失配、查询退回顺扫且**不报错**。

所以运行时常量与本迁移必须成对发布：代码先改常量、索引后改谓词（或反之），
中间窗口内 9 个索引全部不可用——正确性不受影响，但取号会变成全表扫描。

本迁移做什么
------------
对 9 个索引逐个执行"换谓词但不留无索引窗口"的四步：

1. ``CREATE INDEX CONCURRENTLY <idx>_v2``（新谓词，服务照常跑）
2. ``ALTER INDEX <idx> RENAME TO <idx>_old``
3. ``ALTER INDEX <idx>_v2 RENAME TO <idx>``
4. ``DROP INDEX CONCURRENTLY <idx>_old``

索引名最终保持不变，故模型 ``__table_args__`` 无需改名（只随常量换谓词）。
每步都带 ``IF EXISTS`` / ``IF NOT EXISTS``，中断可原样重跑——但**只靠
``IF NOT EXISTS`` 不够**：``CREATE INDEX CONCURRENTLY`` 被取消会留下同名
``_v2`` 且 ``indisvalid = false``，而 PG 的 ``IF NOT EXISTS`` 只按名字判断、
不校验有效性，于是第 3 步会把这个坏索引改名成正式索引，生产静默留一个
不可用索引（查询退回顺扫，无任何报错）。

故第 1 步除 ``_old`` 外**同时 DROP ``_v2``**，保证每次重建前不存在同名索引。
中断在 2/3 之间时 ``<idx>`` 缺失、``_v2`` 与 ``_old`` 俱在，重跑会先删掉两者
再重建，仍收敛到正确状态。

存量单号
--------
**一行都不改**。新正则用交替 ``(?:[0-9]{4}|[0-9]{8})`` 同时接受新 4 位年月与
存量 8 位日期；``'2611'`` 与 ``'20261109'`` 是不同字符串，两个期间键空间
互不覆盖。故本迁移**没有任何 UPDATE**，只有索引重建。

Revision ID: pg_standalone_116_numbering_short_format
Revises: pg_standalone_115_add_product_blind_box_flags
Create Date: 2026-11-09
"""
from alembic import op

revision = 'pg_standalone_116_numbering_short_format'
down_revision = 'pg_standalone_115_add_product_blind_box_flags'
branch_labels = None
depends_on = None

# (table, number_column, index_name) —— 与 NUMBERED_ENTITIES / 模型 __table_args__ 一一对应
_NUMBERING_INDEXES = [
    ('order', 'order_no', 'idx_order_no_date_seq'),
    ('purchase_order', 'order_no', 'idx_purchase_order_no_date_seq'),
    ('purchase_plans', 'plan_no', 'idx_ppl_no_date_seq'),
    ('stock_in', 'stockin_no', 'idx_stockin_no_date_seq'),
    ('case_movement', 'movement_no', 'idx_case_movement_no_date_seq'),
    ('customer_sampling_project', 'sequence_no', 'idx_csp_no_date_seq'),
    ('outsource_shipment', 'shipment_no', 'idx_outsource_shipment_no_date_seq'),
    ('stock_out', 'stockout_no', 'idx_stockout_no_date_seq'),
    ('stock_return', 'return_no', 'idx_stockreturn_no_date_seq'),
]

# 新：4 位年月（YYMM）或存量 8 位日期；中间位数（5/6/7）一律不匹配
_NEW_REGEX = r'^[A-Z]+-(?:[0-9]{4}|[0-9]{8})-[0-9]+$'
# 旧：仅 8 位日期
_OLD_REGEX = r'^[A-Z]+-[0-9]{8}-[0-9]+$'


def _swap_index_predicates(regex: str) -> list[str]:
    """生成 9 个索引的换谓词语句（零无索引窗口，可重跑）。

    第 1 步必须把 ``_old`` 与 ``_v2`` **都**清掉：``_v2`` 可能是上一次
    ``CREATE INDEX CONCURRENTLY`` 被取消后留下的同名 INVALID 索引，而
    ``CREATE ... IF NOT EXISTS`` 只按名字判断、不会重建它（PG 不校验
    ``indisvalid``），留着就会被第 3 步改名成正式索引。
    """
    statements: list[str] = []
    for table, column, index in _NUMBERING_INDEXES:
        statements.extend([
            f'DROP INDEX CONCURRENTLY IF EXISTS {index}_old',
            # 残留的 INVALID _v2 必须先删：IF NOT EXISTS 会跳过同名索引，
            # 不删除就会让坏索引一路转正（静默、无报错）。
            f'DROP INDEX CONCURRENTLY IF EXISTS {index}_v2',
            (
                f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {index}_v2 '
                f'ON "{table}" (split_part({column}, \'-\', 2), '
                f'CAST(split_part({column}, \'-\', 3) AS BIGINT)) '
                f'WHERE {column} ~ \'{regex}\''
            ),
            f'ALTER INDEX IF EXISTS {index} RENAME TO {index}_old',
            f'ALTER INDEX IF EXISTS {index}_v2 RENAME TO {index}',
            f'DROP INDEX CONCURRENTLY IF EXISTS {index}_old',
        ])
    return statements


def upgrade() -> None:
    # CONCURRENTLY 不能在事务块内执行；autocommit_block 保证连接处于自动提交态
    with op.get_context().autocommit_block():
        for stmt in _swap_index_predicates(_NEW_REGEX):
            op.execute(stmt)


def downgrade() -> None:
    # 回退只换回旧谓词，不动任何数据：已发出的 11 位新单号不回收、不改写，
    # 它们暂不进入该部分索引（取号仍正确，只是这几行走顺扫）。
    with op.get_context().autocommit_block():
        for stmt in _swap_index_predicates(_OLD_REGEX):
            op.execute(stmt)
