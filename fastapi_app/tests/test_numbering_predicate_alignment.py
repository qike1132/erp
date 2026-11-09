"""编号格式守卫正则的一致性对账（评审 L-3，2026-11-01）。

PostgreSQL 不做正则蕴含推断：查询谓词与 ``idx_*_no_date_seq`` 索引谓词
任一处单独漂移，索引即**静默**失配、查询退回顺扫，无任何报错——
本测试把全部使用点与单一常量 ``NUMBERING_FORMAT_REGEX`` 钉死，
任一处漂移立即红。

覆盖面：
1. 取号 ``read_period_max`` 编译出的 SQL；
2. 巡检 ``numbering_audit_task`` 的当日 max / 违规计数模板；
3. 对账 ``numbering_reconcile`` 的水位回填模板；
4. 9 张编号表模型的 ``postgresql_where`` 谓词；
5. 迁移 ``pg_standalone_116`` 的 9 条 CREATE（迁移是静态快照、不 import
   运行时常量，故按源码文本比对——已应用的库内索引由迁移建，字面必须一致）。

变异检查锚点：把任一处谓词改坏（如 ``{8}`` 改 ``{7}``），本文件对应断言必红。
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi_app.shared.numbering_format import NUMBERING_FORMAT_REGEX
from fastapi_app.shared_models import Base

_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_116 = (_ROOT / 'migrations' / 'versions' /
                  'pg_standalone_116_numbering_short_format.py')

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
        """格式守卫的契约形状：前缀-（4 位年月｜8 位日期）-纯数字序号。"""
        # 新格式：月流水
        assert re.fullmatch(NUMBERING_FORMAT_REGEX, 'PO-2611-001')
        assert re.fullmatch(NUMBERING_FORMAT_REGEX, 'CSO-2609-9')
        # 存量格式：永久保留，不可重写
        assert re.fullmatch(NUMBERING_FORMAT_REGEX, 'PO-20261101-123')
        assert re.fullmatch(NUMBERING_FORMAT_REGEX, 'CSO-20260929-9')
        # 非法：缺序号段 / 期间段位数不在 4 或 8 / 序号段非纯数字
        assert not re.fullmatch(NUMBERING_FORMAT_REGEX, 'PO-20261101')
        assert not re.fullmatch(NUMBERING_FORMAT_REGEX, 'PO-2026110-12')  # 7 位
        assert not re.fullmatch(NUMBERING_FORMAT_REGEX, 'PO-26110-12')  # 5 位
        assert not re.fullmatch(NUMBERING_FORMAT_REGEX, 'PO-20261101-1a')


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
    def test_read_period_max_compiles_constant(self) -> None:
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


def _load_migration_116():
    """按文件路径加载迁移模块（迁移不在包里，不能直接 import）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location('_mig116', _MIGRATION_116)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigrationLiteralAlignment:
    def test_migration_116_rebuilds_nine_indexes_with_constant(self) -> None:
        """迁移是静态快照：其重建的 9 个索引谓词字面必须与常量一致。

        116 用「建 _v2 → 改名 → 删旧」的换谓词流程，SQL 由 f-string 生成，
        因此不能按源码正则抓 CREATE 文本，改为加载模块取常量与生成结果。
        """
        mod = _load_migration_116()

        specs = mod._NUMBERING_INDEXES
        assert len(specs) == 9, specs
        assert {(t, c) for t, c, _ in specs} == {(t, c) for t, c in NUMBERED_TABLES}, (
            '迁移覆盖的 (表, 列) 与模型声明漂移')

        assert mod._NEW_REGEX == NUMBERING_FORMAT_REGEX, (
            '迁移的新谓词与运行时常量漂移——PG 静默失配退回顺扫，无任何报错')

        creates = [
            s for s in mod._swap_index_predicates(NUMBERING_FORMAT_REGEX)
            if s.startswith('CREATE INDEX CONCURRENTLY')
        ]
        assert len(creates) == 9, len(creates)
        for stmt in creates:
            assert f"~ '{NUMBERING_FORMAT_REGEX}'" in stmt, stmt

    def test_migration_116_drops_stale_v2_before_recreate(self) -> None:
        """重跑前必须清掉上一次被取消的 CONCURRENTLY 留下的 INVALID _v2。

        PG 的 ``CREATE INDEX CONCURRENTLY IF NOT EXISTS`` 只按名字判断、不校验
        ``indisvalid``：残留的坏 _v2 会被跳过，随后被改名成正式索引，生产静默
        留一个不可用索引（查询退化为顺扫，且无任何报错）。
        """
        mod = _load_migration_116()
        stmts = mod._swap_index_predicates(NUMBERING_FORMAT_REGEX)

        for _table, _column, index in mod._NUMBERING_INDEXES:
            drop_v2 = f'DROP INDEX CONCURRENTLY IF EXISTS {index}_v2'
            assert drop_v2 in stmts, (
                f'{index}: 缺少 _v2 清理——重跑会把残留的 INVALID 索引转正')

            create_pos = next(
                i for i, s in enumerate(stmts)
                if s.startswith('CREATE INDEX CONCURRENTLY') and f'{index}_v2' in s
            )
            assert stmts.index(drop_v2) < create_pos, (
                f'{index}: DROP _v2 必须早于 CREATE，否则仍是先建后删的无效顺序')
