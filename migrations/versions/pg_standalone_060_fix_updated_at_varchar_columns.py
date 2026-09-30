"""修复 approval_request / approval_log / app_version 的 updated_at 列类型漂移

背景
----
`add_updated_at_to_all_tables.py` 用 `ADD COLUMN ... TIMESTAMP WITHOUT TIME ZONE`
给 27 张表补 `updated_at`，但整段包在 IF NOT EXISTS 里：这三张表早已存在同名列
（character varying），于是类型从未被纠正。

`pg_standalone_054_sync_schema_with_orm_metadata.py` 又只把 `postgresql.TIMESTAMP()`
传给了 `existing_type=`（声明当前类型）而没有 `type_=`，因此同样不会执行 ALTER TYPE
—— 纠正意图写在注释里，漂移长期留存（该文件 :81-88 即现场）。

后果（两条均已实证）
----
1. ORM 把 `updated_at` 声明为 DateTime 且 `default=datetime.now`
   （`shared_models/approval.py:61` 与 `:130`）；asyncpg 拒绝把 datetime 绑到
   varchar 参数（`asyncpg.exceptions.DataError: expected str, got datetime`），
   故 `services/approval_log_service.py:20` 与 `services/order/approval_flow.py:88,125`
   的写入会失败 —— 两张表长期 0 行（审批功能写不进库）。
2. 增量备份按 `updated_at >= :since` 过滤同样触发该错误，异常被 incremental.py
   吞掉，导致这两张表长期没有进入增量备份（已在 8d0bf91f 修复为
   DBAPIError 回退 + failed_tables 上抛）。

本迁移把三列改回 ORM 声明的 timestamp without time zone（与其余 62 个候选时间列一致）。
三张表当前均为 0 行，转换无数据风险；USING 仍按「空串/非法值 → NULL」书写，
以便将来在非空表上重放也安全。`app_version` 全仓无代码引用（是手工建的历史表），
一并纠正以消除同类隐患。

注意：这三列都带着退化默认值 `NULL::character varying`，PostgreSQL 不会把它自动转型，
必须先 DROP DEFAULT 再 ALTER TYPE（否则报 DatatypeMismatchError）。该默认值本就等价于
「默认 NULL」，去掉后语义不变。

Revision ID: pg_standalone_060_fix_updated_at_varchar_columns
Revises: pg_standalone_059_numbering_audit
Create Date: 2026-09-30
"""
from alembic import context, op
from sqlalchemy import text

from migrations._legacy_base_guard import table_columns

revision = 'pg_standalone_060_fix_updated_at_varchar_columns'
down_revision = 'pg_standalone_059_numbering_audit'
branch_labels = None
depends_on = None

_COLUMN = 'updated_at'
_TABLES = ('approval_request', 'approval_log', 'app_version')
_TIMESTAMP_TYPE = 'timestamp without time zone'


def _data_type(table: str):
    """当前列类型（information_schema 口径），列不存在时返回 None。"""
    return op.get_bind().execute(
        text(
            'SELECT data_type FROM information_schema.columns '
            'WHERE table_name = :t AND column_name = :c'
        ),
        {'t': table, 'c': _COLUMN},
    ).scalar()


def _needs_alter(table: str, target_type: str) -> bool:
    """判断该表是否需要执行 ALTER TYPE（离线渲染时不探测，一律输出）。"""
    if context.is_offline_mode():
        return True
    present = table_columns(table)
    if present is None or _COLUMN not in present:
        return False
    return _data_type(table) != target_type


def upgrade() -> None:
    for table in _TABLES:
        if not _needs_alter(table, _TIMESTAMP_TYPE):
            continue
        # 必须先 DROP DEFAULT：这三列的现有默认值是退化值 `NULL::character varying`，
        # PostgreSQL 无法把它自动转型成 timestamp，会直接拒绝 ALTER TYPE
        # （实测 DatatypeMismatchError：字段 "updated_at" 的默认值无法自动转换成类型
        # timestamp without time zone）。去掉它语义不变 —— 原本也默认 NULL，
        # ORM 侧由 `default=datetime.now` 提供值。
        op.execute(f'ALTER TABLE "{table}" ALTER COLUMN {_COLUMN} DROP DEFAULT')
        op.execute(
            f'ALTER TABLE "{table}" ALTER COLUMN {_COLUMN} '
            f'TYPE timestamp without time zone '
            f"USING (CASE WHEN {_COLUMN} IS NULL OR {_COLUMN} = '' THEN NULL "
            f'ELSE {_COLUMN}::timestamp END)'
        )


def downgrade() -> None:
    """退回 character varying，保留可读文本（原样回写 ISO 字符串）。"""
    for table in _TABLES:
        if not _needs_alter(table, 'character varying'):
            continue
        op.execute(
            f'ALTER TABLE "{table}" ALTER COLUMN {_COLUMN} '
            f'TYPE character varying '
            f'USING {_COLUMN}::text'
        )
        op.execute(
            f'ALTER TABLE "{table}" ALTER COLUMN {_COLUMN} '
            f'SET DEFAULT NULL::character varying'
        )
