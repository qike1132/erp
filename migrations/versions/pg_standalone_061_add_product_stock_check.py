"""给 product.current_stock 加非负兜底 CHECK 约束（P1-6）

背景
----
`product.current_stock` 此前只有应用层校验（`shared/stock_concurrency.py` 的
`check_stock_available` / `assert_stock_available`），数据库层没有任何兜底：任何绕过
该入口的写点（历史内联判断、脚本、手工 SQL、并发竞态）都能把库存写成负数。
`docs/architecture-audit-round3-2026-10-01.md:52` 记录 product 表此前无任何 CHECK。

后果
----
负库存不会被 DB 拒绝，只能靠事后发现：库存对不平、可用量计算失真（超卖）。
本迁移与 `shared/stock_concurrency.py` 的原子扣减（`UPDATE ... WHERE
`current_stock + delta >= 0`）构成双层保障：应用层给精确文案，DB 层做最终拒绝。

存量数据处理（自适应）
----
加约束前先扫描存量负值（只读）：

    SELECT id, name, current_stock FROM product WHERE current_stock < 0 ORDER BY id;

本仓库 dev 库实测结果：0 条（`COUNT(*) FILTER (WHERE current_stock < 0)` = 0，
`MIN(current_stock)` = 0，product 共 6 行）⇒ 直接以 VALID 约束加入，不阻塞上线。
若在其它环境扫到负值，则自动改用 `NOT VALID` 加入并打印 WARNING（约束对新写入
立即生效，但不校验存量行，避免迁移整体失败）；人工对平存量后手工执行：

    ALTER TABLE product VALIDATE CONSTRAINT ck_product_current_stock_nonneg;

幂等性：product 表不存在（空库重放）或约束已存在时整体跳过。

Revision ID: pg_standalone_061_add_product_stock_check
Revises: pg_standalone_060_fix_updated_at_varchar_columns
Create Date: 2026-10-01
"""
import logging

from alembic import context, op
from sqlalchemy import text

from migrations._legacy_base_guard import table_exists

logger = logging.getLogger(__name__)

revision = 'pg_standalone_061_add_product_stock_check'
down_revision = 'pg_standalone_060_fix_updated_at_varchar_columns'
branch_labels = None
depends_on = None

_TABLE = 'product'
_CONSTRAINT = 'ck_product_current_stock_nonneg'
_CHECK = 'current_stock >= 0'

_ADD_VALID = f'ALTER TABLE "{_TABLE}" ADD CONSTRAINT {_CONSTRAINT} CHECK ({_CHECK})'
_ADD_NOT_VALID = _ADD_VALID + " NOT VALID"
_DROP = f'ALTER TABLE "{_TABLE}" DROP CONSTRAINT IF EXISTS {_CONSTRAINT}'


def _constraint_exists() -> bool:
    """约束是否已经存在（离线模式无法探测，按不存在处理）。"""
    if context.is_offline_mode():
        return False
    found = op.get_bind().execute(
        text('SELECT 1 FROM pg_constraint WHERE conname = :n AND conrelid = to_regclass(:t)'),
        {'n': _CONSTRAINT, 't': _TABLE},
    ).scalar()
    return found is not None


def _negative_stock_ids() -> list[int]:
    """存量负库存的 product_id 列表（只读扫描，用于决定 VALID / NOT VALID）。"""
    rows = op.get_bind().execute(
        text(f'SELECT id FROM "{_TABLE}" WHERE current_stock < 0 ORDER BY id')
    ).fetchall()
    return [int(row[0]) for row in rows]


def upgrade() -> None:
    if not table_exists(_TABLE):
        # 空库重放：product 表稍后才由其它分支迁移建出，跳过（与其它迁移守卫同风格）
        logger.info("product 表不存在，跳过 %s 约束创建", _CONSTRAINT)
        return
    if _constraint_exists():
        logger.info("约束 %s 已存在，跳过", _CONSTRAINT)
        return
    # 离线（--sql）模式无法探测存量，按已验证假设（存量负值 0 条）输出 VALID DDL
    negatives = [] if context.is_offline_mode() else _negative_stock_ids()
    if negatives:
        logger.warning(
            "product 存量负库存 %d 条（product_id=%s），约束以 NOT VALID 加入；"
            "人工对平后请执行 ALTER TABLE product VALIDATE CONSTRAINT %s",
            len(negatives), negatives, _CONSTRAINT,
        )
        op.execute(_ADD_NOT_VALID)
        return
    op.execute(_ADD_VALID)


def downgrade() -> None:
    """移除约束（幂等；product 表不存在时跳过）。"""
    if not table_exists(_TABLE):
        return
    op.execute(_DROP)
