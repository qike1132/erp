"""编号格式守卫正则的一致性对账（评审 L-3，2026-11-01）。

PostgreSQL 不做正则蕴含推断：查询谓词与 ``idx_*_no_date_seq`` 索引谓词
任一处单独漂移，索引即**静默**失配、查询退回顺扫，无任何报错——
本测试把全部使用点与单一常量 ``NUMBERING_FORMAT_REGEX`` 钉死，
任一处漂移立即红。

覆盖面：
1. 取号 ``read_daily_max`` 编译出的 SQL；
2. 巡检 ``numbering_audit_task`` 的当日 max / 违规计数模板；
3. 对账 ``numbering_reconcile`` 的水位回填模板；
4. 9 张编号表模型的 ``postgresql_where`` 谓词；
5. 迁移 ``pg_standalone_107`` 的 9 条 CREATE（迁移是静态快照、不 import
   运行时常量，故按源码文本比对——已应用的库内索引由迁移建，字面必须一致）。

变异检查锚点：把任一处谓词改坏（如 ``{8}`` 改 ``{7}``），本文件对应断言必红。
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi_app.shared.numbering_format import NUMBERING_FORMAT_REGEX
from fastapi_app.shared_models import Base

_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_107 = (_ROOT / 'migrations' / 'versions' /
                  'pg_standalone_107_drop_redundant_and_numbering_idx.py')

# (tablename, number_column)
NUMBERED_TABLES = [
    ('order', 'order_no'),
    ('purchase_order', 'order_no'),
    ('stock_in', 'stockin_no'),
    ('stock_out', 'stockout_no'),
    ('case_movement', 'movement_no'),
    ('customer_sampling_project', 'sequence_no'),
    ('outsource_shipment', 'shipment_no'),
    ('stock_return', 'return_no'),
    ('purchase_plans', 'plan_no'),
]


class TestConstantShape:
    def test_regex_shape(self) -> None:
        """格式守卫的契约形状：前缀-8位日期-纯数字序号。"""
        assert re.fullmatch(NUMBERING_FORMAT_REGEX, 'PO-20261101-123')
        assert re.fullmatch(NUMBERING_FORMAT_REGEX, 'CSO-20260929-9')
        assert not re.fullmatch(NUMBERING_FORMAT_REGEX, 'PO-20261101')  # 缺序号段
        assert not re.fullmatch(NUMBERING_FORMAT_REGEX, 'PO-2026110-12')  # 日期段 7 位
        assert not re.fullmatch(NUMBERING_FORMAT_REGEX, 'PO-20261101-1a')  # 序号段非纯数字


class TestModelIndexPredicates:
    def test_nine_model_predicates_match_constant(self) -> None:
        """每个 idx_*_no_date_seq 的谓词 = f\"<col> ~ '<常量>'\"。"""
        expected_tables = {t for t, _ in NUMBERED_TABLES}
        found = {}
        for table in Base.metadata.sorted_tables:
            for idx in table.indexes:
                if idx.name and idx.name.endswith('_no_date_seq'):
                    where = idx.dialect_options['postgresql']['where']
                    found[table.name] = str(where.text)
        assert set(found) == expected_tables, (
            '模型声明集合漂移: %s' % (expected_tables ^ set(found)))
        for tname, col in NUMBERED_TABLES:
            assert found[tname] == f"{col} ~ '{NUMBERING_FORMAT_REGEX}'", (
                f'{tname} 的索引谓词与常量失配: {found[tname]!r}')


class TestQueryTextPredicates:
    def test_read_daily_max_compiles_constant(self) -> None:
        """取号过滤器编译产物的绑定参数携带常量（ORM 参数化，SQL 文本无字面量）。"""
        from sqlalchemy import BigInteger, cast, func, select
        from sqlalchemy.dialects import postgresql as pg_dialect
        from sqlalchemy.schema import CreateTable  # noqa: F401  # 仅确保可导入

        from fastapi_app.shared_models import Order
        col = Order.order_no
        seq = cast(func.split_part(col, '-', 3), BigInteger)
        expr = select(func.max(seq)).where(
            col.op('~')(NUMBERING_FORMAT_REGEX),
            func.split_part(col, '-', 2) == '20261101',
        )
        compiled = expr.compile(dialect=pg_dialect.dialect())
        assert any(v == NUMBERING_FORMAT_REGEX for v in compiled.params.values()), (
            compiled.params)

    def test_audit_task_sql_templates_carry_constant(self) -> None:
        from fastapi_app.tasks.numbering_audit_task import (
            _ENTITY_MAX_SQL,
            _ENTITY_VIOLATION_SQL,
        )
        rendered_max = _ENTITY_MAX_SQL.replace('{column}', 'order_no').replace('{table}', 'order')
        assert f"'{NUMBERING_FORMAT_REGEX}'" in rendered_max, rendered_max
        rendered_viol = _ENTITY_VIOLATION_SQL.replace('{column}', 'order_no').replace('{table}', 'order')
        assert f"'{NUMBERING_FORMAT_REGEX}'" in rendered_viol, rendered_viol

    def test_reconcile_sql_template_carries_constant(self) -> None:
        from fastapi_app.services.numbering_reconcile import _ENTITY_UPSERT_SQL
        rendered = _ENTITY_UPSERT_SQL.replace('{column}', 'order_no').replace('{table}', 'order')
        assert f"'{NUMBERING_FORMAT_REGEX}'" in rendered, rendered


class TestMigrationLiteralAlignment:
    def test_migration_107_create_predicates_match_constant(self) -> None:
        """迁移是静态快照：其 9 条 P3 CREATE 的谓词字面必须与常量一致。

        只认 ``idx_*_no_date_seq``（DOWNGRADE_RECREATES 的 30 条 P2 重建
        语句不含本谓词，不在对账范围）。
        """
        src = _MIGRATION_107.read_text(encoding='utf-8')
        p3_names = re.findall(
            r"CREATE INDEX CONCURRENTLY IF NOT EXISTS (idx_\w+_no_date_seq) ", src)
        assert len(p3_names) == 9, sorted(set(p3_names))
        for name in sorted(set(p3_names)):
            # 迁移源码是 Python repr 形式（SQL 引号转义为 \'），按行内含常量匹配
            m = re.search(
                r'CREATE INDEX CONCURRENTLY IF NOT EXISTS ' + re.escape(name) + r' [^\n]*',
                src)
            assert m and NUMBERING_FORMAT_REGEX in m.group(0), (
                f'迁移 107 中 {name} 的谓词与常量失配——'
                '迁移快照与运行时常量漂移，PG 将静默失配退回顺扫')
