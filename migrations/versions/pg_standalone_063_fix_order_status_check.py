"""fix_order_status_check_constraint

Revision ID: pg_standalone_063_fix_order_status_check
Revises: pg_standalone_062_case_management_rebuild
Create Date: 2026-10-02

背景（2026-10-02 存量审计 P6）
------------------------------
迁移**执行顺序伪影**使由迁移链重建的库里 `order_status_check` 是**错的**：

  · `pg_standalone_008`（集合含 '批次已完成'、不含 '已完成'）在**应用第 18 步**执行；
  · `pg_standalone_002`（集合含 '已完成'、**不含 '批次已完成'**）在**应用第 33 步**执行。

两者都是 `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` 同名约束 → **后者覆盖前者**，
而 002 **没有任何守卫**（已核对其 upgrade）。于是重建库的最终约束**拒绝合法状态
'批次已完成'**，而 ORM 的权威定义 `VALID_ORDER_STATUSES` 正相反。
批次完成写入（`order_deduction_service` / `order_batch_service`）会 CheckViolationError。

现网 `erp_system` 是 stamp 出来的：已核实 `pg_get_constraintdef(order_status_check)`
返回 **NULL（根本没有该约束）**，且行值只有 '待备货'/'已备货'（均合法）——
故本迁移只是把这个缺失的约束**按权威集合补上**，对存量数据安全。

本迁移位于**链尾**，无论前面顺序如何，最终状态都正确。
PostgreSQL 不支持 ALTER CONSTRAINT，故 DROP + ADD。
"""

from alembic import op

from migrations._legacy_base_guard import base_schema_absent

revision = 'pg_standalone_063_fix_order_status_check'
down_revision = 'pg_standalone_062_case_management_rebuild'
branch_labels = None
depends_on = None

# ⚠️ 必须与 fastapi_app/shared_models/order.py 的 VALID_ORDER_STATUSES **逐字一致**。
# 由 tests/test_order_status_check_migration.py 断言（并断言本迁移是链上**最后一个**
# 声明该约束的迁移），防止将来再被顺序伪影覆盖。
ORDER_STATUSES = ('待备货', '部分备货', '已备货', '待出货', '已出货', '已取消', '批次已完成')


def _add_constraint_sql() -> str:
    values = ', '.join(f"'{s}'" for s in ORDER_STATUSES)
    return (
        'ALTER TABLE "order" ADD CONSTRAINT order_status_check '
        f'CHECK ("status" IN ({values}))'
    )


def upgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条迁移空转。
    if base_schema_absent():
        return
    op.execute('ALTER TABLE "order" DROP CONSTRAINT IF EXISTS order_status_check')
    op.execute(_add_constraint_sql())


def downgrade():
    if base_schema_absent():
        return
    # 回滚只移除该约束：**不**恢复 002 那套已知错误的集合（恢复一个会拒绝合法状态的
    # 约束没有意义），且现网原本也没有该约束，故与现网形态一致。
    op.execute('ALTER TABLE "order" DROP CONSTRAINT IF EXISTS order_status_check')
