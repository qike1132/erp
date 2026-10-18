"""Alembic 版本表加宽逻辑（独立模块，便于单测直接 import）。

为什么单独成模块：`migrations/env.py` 在模块级执行 `config = context.config`
与 `config.set_main_option(...)`，只有在 alembic 运行时环境里才可导入；
单元测试若直接 `from migrations.env import ensure_version_table_width` 会以
`AttributeError: module 'alembic.context' has no attribute 'config'` 失败。
把纯 DDL 逻辑放在这里，env.py 只负责接线。

2026-10-18 OCR 评审：`ensure_version_table_width` 的兜底此前写成
`except (SQLAlchemyError, OSError)`（更早是裸 `except Exception`），两者都达不到
「不吞真正错误」的目的——SQL 语法错/连接断开/驱动不兼容等都以 ProgrammingError、
OperationalError 等 **SQLAlchemyError 子类**抛出，照吞不误。一旦 DDL 写错，
症状是「加宽静默没生效」，排查时看不到任何报错。

改为按 **SQLSTATE** 白名单判定「预期内」：只有明确的权限不足与只读连接才允许跳过
（这两种情况确实不该阻断迁移，本函数本就是尽力而为的幂等预处理）。语法错误、
连接失败等一律照常抛出。

驱动差异：psycopg3 的 DBAPI 异常带 `.sqlstate`，psycopg2 带 `.pgcode`；
两者都读不到时（非 PG 驱动/被包装过的异常）不猜，直接放过由上层处理。
"""
from __future__ import annotations

import logging

from sqlalchemy import text as sa_text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger('alembic.env')

_SWALLOWED_SQLSTATES = frozenset({
    '42501',  # insufficient_privilege：无建表/改列权限
    '25006',  # read_only_sql_transaction：只读连接（如连到 standby）
})

# Alembic 默认把版本表的 version_num 建成 VARCHAR(32)，而本仓库有 34 个 revision id
# 超过 32 字符（最长 53，如 pg_standalone_018_purchase_plan_unique_month_customer）。
# 空库上这会在写入版本号时以 StringDataRightTruncation 失败，导致 upgrade head 无法收尾，
# 故此处预先建表/加宽到 VARCHAR(100)（与现网 erp_system 的实际列宽一致）。
_VERSION_TABLE_DDL = (
    'CREATE TABLE IF NOT EXISTS {table} ('
    'version_num VARCHAR(100) NOT NULL, '
    'CONSTRAINT {table}_pkc PRIMARY KEY (version_num))'
)
_VERSION_TABLE_WIDTH_DDL = 'ALTER TABLE {table} ALTER COLUMN version_num TYPE VARCHAR(100)'


def _is_expected_permission_failure(exc: BaseException) -> bool:
    """判断是否为「预期内」的加宽失败（无权限 / 只读连接）。"""
    orig = getattr(exc, 'orig', None)
    sqlstate = getattr(orig, 'sqlstate', None) or getattr(orig, 'pgcode', None)
    return sqlstate in _SWALLOWED_SQLSTATES


def ensure_version_table_width(connection, version_table: str) -> None:
    """确保 alembic 版本表容得下最长 revision id。幂等，无权限/只读时静默跳过。"""
    try:
        connection.execute(sa_text(_VERSION_TABLE_DDL.format(table=version_table)))
        connection.execute(sa_text(_VERSION_TABLE_WIDTH_DDL.format(table=version_table)))
    except (SQLAlchemyError, OSError) as e:
        # 只对「预期内」的失败静默；SQL 语法错误等非预期失败原样抛出。
        if not _is_expected_permission_failure(e):
            raise
        logger.debug('跳过 alembic 版本表加宽（无权限或只读连接）', exc_info=True)
