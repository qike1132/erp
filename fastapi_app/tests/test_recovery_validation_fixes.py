"""灾备演练/恢复验证的回归测试（2026-11-04，含 QA 复核 High-1/High-2 加严）。

证据文件：``backups/server/recovery_tests/recovery_test_20261101_041001_fbf72c.json``。

被锁住的缺陷（每条都有对应用例）：
1. ``_load_fk_groups`` 曾取 ``information_schema.constraint_column_usage.ordinal_position``
   —— 该视图没有这一列，约束验证每次 ``UndefinedColumnError``。
2. **聚合键不唯一（QA High-1）**：PostgreSQL 只要求约束名在**单表内**唯一，
   ``public.a.fk_x`` 与 ``public.b.fk_x`` 合法共存；按 ``schema.constraint_name``
   聚合会造出跨表的假复合外键。现在键含表名并带 ``con.oid``。
   ``_load_unique_groups`` 同病同治（原实现连 schema 都没有）。
3. ``validate_recovery`` 四族共用一个隐式事务，首族 SQL 失败后 PG 事务 aborted，
   后续族全部 ``InFailedSQLTransactionError``；现验证连接 AUTOCOMMIT + 逐族兜底 +
   ``statement_timeout`` + ``dispose`` 进 finally + 连接阶段异常也返回结构化失败结果。
4. **manifest 行数口径（QA High-2）**：曾用 reltuples 估算，后来用「导出后再 COUNT」，
   两者都不是「备份文件里到底有多少行」。现在行数直接数 dump（SQL 的 COPY 区 /
   JSON 的 count），解析失败才回退精确 COUNT 并在 manifest 标记 ``rows_source``。

本文件默认只用假连接/假引擎（不碰真实库）；真库部分集中在最后一节，库不可达时 skip。
"""
from __future__ import annotations

import gzip
import inspect
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError

from fastapi_app.services.backup.orchestration import core
from fastapi_app.services.backup.orchestration.drill_validator import (
    DrillValidator,
    _check_fk_violations,
    _check_unique_violations,
    _load_fk_groups,
    _load_unique_groups,
)


# ---------------------------------------------------------------------------
# 公共假件
# ---------------------------------------------------------------------------
class _FakeResult:
    def __init__(self, rows=None, scalar=0):
        self._rows = list(rows or [])
        self._value = scalar

    def fetchall(self):
        return list(self._rows)

    def all(self):
        return list(self._rows)

    def scalar(self):
        return self._value


class _FakeNested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def commit(self):
        pass

    async def rollback(self):
        pass


def _undefined_column_error(sql: str = 'SELECT 1') -> ProgrammingError:
    """模拟报告里的 ``UndefinedColumnError``（SQLAlchemy 包成 ProgrammingError）。"""
    return ProgrammingError(sql, {}, Exception('字段 ccu.ordinal_position 不存在'))


def _in_failed_transaction_error(sql: str = 'SELECT 1') -> ProgrammingError:
    return ProgrammingError(sql, {}, Exception('当前事务被终止, 事务块结束之前的查询被忽略'))


def _make_sql_dump(path: Path, tables: dict[str, list[list[str]]]) -> Path:
    """构造 pg_dump 纯文本风格的 gzip SQL（每个表一段 COPY 区，含空表段）。"""
    with gzip.open(path, 'wt', encoding='utf-8') as fh:
        fh.write('--\n-- PostgreSQL database dump\n--\n\n')
        fh.write('SET statement_timeout = 0;\n')
        for target, rows in tables.items():
            fh.write(f'\nCOPY {target} (id, name) FROM stdin;\n')
            for row in rows:
                fh.write('\t'.join(row) + '\n')
            fh.write('\\.\n')
        fh.write('\n--\n-- PostgreSQL database dump complete\n--\n')
    return path


# ---------------------------------------------------------------------------
# ①-a 外键定义加载：同名约束不得跨表合并（QA High-1）
# ---------------------------------------------------------------------------
#: (schema, 表, 约束名, oid, 子表列, 引用 schema, 引用表, 引用列, 序号)
_FK_ROWS = [
    # 同一 schema、两张子表、**同名**约束 —— 必须是两条独立外键
    ('public', 'child_a', 'fk_same', '17001', 'parent_id', 'public', 'parent', 'id', 1),
    ('public', 'child_b', 'fk_same', '17002', 'parent_id', 'public', 'parent', 'id', 1),
    # 复合外键（引用列顺序与子表列顺序不同，靠 conkey/confkey 同下标配对）
    ('public', 'child_c', 'fk_composite', '17003', 'pfb', 'public', 'parent', 'pb', 1),
    ('public', 'child_c', 'fk_composite', '17003', 'pfa', 'public', 'parent', 'pa', 2),
]


class _RecordingConn:
    """记录 SQL 并按查询内容返回预置行（不连库）。"""

    def __init__(self, fk_rows=None, unique_rows=None, scalar_value=0):
        self._fk_rows = list(fk_rows or [])
        self._unique_rows = list(unique_rows or [])
        self._scalar = scalar_value
        self.queries: list[str] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.queries.append(sql)
        if "con.contype = 'f'" in sql:
            return _FakeResult(rows=self._fk_rows)
        if "con.contype = 'u'" in sql:
            return _FakeResult(rows=self._unique_rows)
        return _FakeResult(scalar=self._scalar)


async def test_same_named_fk_on_two_tables_stays_separate():
    """High-1 本体：同 schema 两张表的同名外键不得被合并成一条跨表假外键。"""
    conn = _RecordingConn(fk_rows=_FK_ROWS)

    groups = await _load_fk_groups(conn)

    assert set(groups) == {
        'public.child_a.fk_same',
        'public.child_b.fk_same',
        'public.child_c.fk_composite',
    }
    # 两条同名外键各自独立、列不混合
    assert groups['public.child_a.fk_same']['table'] == 'child_a'
    assert groups['public.child_b.fk_same']['table'] == 'child_b'
    assert groups['public.child_a.fk_same']['columns'] == ['parent_id']
    assert groups['public.child_b.fk_same']['columns'] == ['parent_id']
    # con.oid 作为唯一身份被带出（跨表同名、重建同名都能区分）
    assert groups['public.child_a.fk_same']['constraint_oid'] == '17001'
    assert groups['public.child_b.fk_same']['constraint_oid'] == '17002'
    assert groups['public.child_a.fk_same']['constraint_name'] == 'fk_same'


async def test_composite_fk_columns_pair_by_position():
    conn = _RecordingConn(fk_rows=_FK_ROWS)

    groups = await _load_fk_groups(conn)

    composite = groups['public.child_c.fk_composite']
    assert composite['columns'] == ['pfb', 'pfa']
    assert composite['foreign_columns'] == ['pb', 'pa']


async def test_fk_query_uses_pg_constraint_oid_and_not_ccu():
    """守护缺陷 ①：不能再引用 constraint_column_usage（无 ordinal_position 列）。"""
    conn = _RecordingConn()

    await _load_fk_groups(conn)

    sql = conn.queries[0]
    assert 'information_schema.constraint_column_usage' not in sql
    assert 'pg_constraint' in sql
    assert 'con.oid' in sql
    assert 'conkey' in sql and 'confkey' in sql
    assert 'ORDER BY con.oid' in sql
    # 复合键长度必须一致才配对，否则下标错位
    assert 'array_length(con.conkey, 1) = array_length(con.confkey, 1)' in sql


async def test_fk_violation_sql_is_schema_qualified():
    conn = _RecordingConn(fk_rows=_FK_ROWS)
    groups = await _load_fk_groups(conn)

    await _check_fk_violations(conn, groups)

    orphan_sqls = [sql for sql in conn.queries if 'LEFT JOIN' in sql]
    assert len(orphan_sqls) == 3, '每条外键一条检查（同名约束没被合并）'
    composite_sql = next(sql for sql in orphan_sqls if '"child_c"' in sql)
    assert 'FROM "public"."child_c" t' in composite_sql
    assert 'LEFT JOIN "public"."parent" f' in composite_sql
    assert 't."pfb" = f."pb"' in composite_sql
    assert 't."pfa" = f."pa"' in composite_sql
    assert all('FROM "child_c" t' not in sql for sql in orphan_sqls)


async def test_fk_violation_raises_on_column_count_mismatch():
    """列数不一致时不得静默截断（strict=False 会让 orphan 检查永远通过）。"""
    conn = _RecordingConn()
    broken = {
        'public.child.fk': {
            'constraint_name': 'fk', 'schema': 'public', 'table': 'child',
            'columns': ['a', 'b'], 'foreign_schema': 'public',
            'foreign_table': 'parent', 'foreign_columns': ['a'],
        },
    }

    with pytest.raises(ValueError):
        await _check_fk_violations(conn, broken)


# ---------------------------------------------------------------------------
# ①-b 唯一约束定义加载：同名约束不得跨表/跨 schema 合并（QA High-1）
# ---------------------------------------------------------------------------
#: (schema, 表, 约束名, oid, 列, 序号)
_UNIQUE_ROWS = [
    ('public', 'table_a', 'uq_same', '18001', 'code', 1),
    ('public', 'table_b', 'uq_same', '18002', 'code', 1),
    ('archive', 'table_a', 'uq_same', '18003', 'code', 1),
    ('public', 'table_c', 'uq_composite', '18004', 'a', 1),
    ('public', 'table_c', 'uq_composite', '18004', 'b', 2),
]


async def test_same_named_unique_on_two_tables_stays_separate():
    """聚合键必须含表名。

    注：PostgreSQL 里 UNIQUE/PK 约束的名字要与其**自带索引**同名，而索引名在同一
    schema 内唯一，所以「同 schema 两张表的同名 UNIQUE」实际建不出来（真库用例改用
    跨 schema 验证）；此处用假件锁定「聚合键含表名」这一契约，跨 schema 与未来
    PG 行为变化都不会混合列集合。
    """
    conn = _RecordingConn(unique_rows=_UNIQUE_ROWS)

    groups = await _load_unique_groups(conn)

    assert set(groups) == {
        'public.table_a.uq_same',
        'public.table_b.uq_same',
        'archive.table_a.uq_same',
        'public.table_c.uq_composite',
    }
    assert groups['public.table_a.uq_same']['columns'] == ['code']
    assert groups['public.table_c.uq_composite']['columns'] == ['a', 'b']
    assert groups['public.table_a.uq_same']['constraint_oid'] == '18001'


async def test_unique_query_uses_pg_constraint_not_information_schema():
    conn = _RecordingConn()

    await _load_unique_groups(conn)

    sql = conn.queries[0]
    # 不能再用 information_schema 视图（它既不保证 schema 也不保证表名唯一）
    assert 'information_schema.table_constraints' not in sql
    assert 'information_schema.key_column_usage' not in sql
    assert 'pg_constraint' in sql and "con.contype = 'u'" in sql
    assert 'con.oid' in sql
    assert 'ORDER BY con.oid' in sql


async def test_unique_violation_sql_is_schema_qualified():
    conn = _RecordingConn(unique_rows=_UNIQUE_ROWS, scalar_value=0)
    groups = await _load_unique_groups(conn)

    await _check_unique_violations(conn, groups)

    dup_sqls = [sql for sql in conn.queries if 'HAVING COUNT(*) > 1' in sql]
    assert len(dup_sqls) == 4
    assert any('FROM "public"."table_a"' in sql for sql in dup_sqls)
    assert any('FROM "archive"."table_a"' in sql for sql in dup_sqls)
    assert all('FROM "table_a"' not in sql for sql in dup_sqls)


# ---------------------------------------------------------------------------
# ② 单族失败隔离 / 连接阶段异常 / engine 释放 / statement_timeout
# ---------------------------------------------------------------------------
class _AbortModelConn:
    """按 PostgreSQL 语义模拟「非 AUTOCOMMIT 下失败即 aborted」。"""

    def __init__(self, autocommit: bool):
        self.autocommit = autocommit
        self.aborted = False
        self.queries: list[str] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.queries.append(sql)
        if self.aborted:
            raise _in_failed_transaction_error(sql)
        try:
            return self._respond(sql)
        except SQLAlchemyError:
            if not self.autocommit:
                self.aborted = True
            raise

    def _respond(self, sql: str):
        if "con.contype = 'f'" in sql:  # 缺陷 ① 的原始失败点
            raise _undefined_column_error(sql)
        if 'COUNT(*) FROM information_schema.tables' in sql:
            return _FakeResult(scalar=1)
        if 'information_schema.tables' in sql:
            return _FakeResult(rows=[('orders',)])
        if 'COUNT(*)' in sql:
            return _FakeResult(scalar=3)
        if 'version()' in sql:
            return _FakeResult(rows=[('PostgreSQL 16.4',)])
        if 'pg_database_size' in sql:
            return _FakeResult(scalar=8192)
        return _FakeResult()


class _FakeConnectCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        return False


class _FakeEngine:
    def __init__(self, conn=None, connect_error: Exception | None = None):
        self._conn = conn
        self._connect_error = connect_error
        self.disposed = False

    def connect(self):
        if self._connect_error is not None:
            raise self._connect_error
        return _FakeConnectCtx(self._conn)

    async def dispose(self):
        self.disposed = True


def _validator_config() -> dict:
    return {
        'validate_schema': True,
        'validate_data_integrity': True,
        'validate_constraints': True,
        'cleanup_test_db': True,
    }


def _test_env() -> dict:
    return {
        'test_db_user': 'drill',
        'test_db_password': 'drill',
        'test_db_host': '127.0.0.1',
        'test_db_port': 5432,
        'test_db_name': 'erp_system_drill',
    }


def _backup_info() -> dict:
    return {'manifest': {'tables': {'orders': {'rows': 3}}}}


def _patch_engine(monkeypatch, factory):
    monkeypatch.setattr(
        'fastapi_app.services.backup.orchestration.drill_validator.create_async_engine',
        factory,
    )


async def test_family_failure_isolated_from_later_families(monkeypatch):
    """守卫缺陷 ②：constraint 族报错后，performance 族仍必须能跑出结果。"""
    created: list[_AbortModelConn] = []
    engines: list[_FakeEngine] = []

    def _fake_create_engine(url, **kwargs):
        # 假连接的 aborted 语义取决于代码实际申请的隔离级别：
        # 若有人回退掉 AUTOCOMMIT，这里会自动退化成「后续族全灭」，用例即失败。
        conn = _AbortModelConn(autocommit=kwargs.get('isolation_level') == 'AUTOCOMMIT')
        engine = _FakeEngine(conn)
        created.append(conn)
        engines.append(engine)
        return engine

    _patch_engine(monkeypatch, _fake_create_engine)

    result = await DrillValidator(_validator_config()).validate_recovery(
        'test-1', _test_env(), _backup_info(),
    )

    assert created and created[0].autocommit is True, '验证连接必须是 AUTOCOMMIT'
    families = result['results']

    assert families['schema_validation']['passed'] is True
    assert families['data_validation']['passed'] is True

    constraint = families['constraint_validation']
    assert constraint['passed'] is False
    assert 'ordinal_position' in constraint['error']
    assert 'InFailedSQLTransaction' not in str(constraint)

    performance = families['performance_validation']
    assert performance['passed'] is True, performance
    assert all(m['status'] == 'success' for m in performance['details'].values())
    assert 'InFailedSQLTransaction' not in str(result)
    assert engines[0].disposed is True


async def test_engine_gets_statement_timeout(monkeypatch):
    """验证引擎必须带单语句超时，避免一条卡死 SQL 把整轮演练拖到外层超时。"""
    kwargs_seen: dict = {}

    def _fake_create_engine(url, **kwargs):
        kwargs_seen.update(kwargs)
        return _FakeEngine(_AbortModelConn(autocommit=True))

    _patch_engine(monkeypatch, _fake_create_engine)

    await DrillValidator(_validator_config()).validate_recovery(
        'test-timeout', _test_env(), _backup_info(),
    )

    server_settings = kwargs_seen['connect_args']['server_settings']
    assert server_settings['statement_timeout'] == '30000'


async def test_connect_stage_exception_returns_structured_failure(monkeypatch):
    """连接阶段抛出非 SQLAlchemy 异常（asyncpg PostgresError 形态）也必须结构化返回。"""
    engine = _FakeEngine(connect_error=RuntimeError('invalid_catalog_name: 库不存在'))
    _patch_engine(monkeypatch, lambda url, **kwargs: engine)

    result = await DrillValidator(_validator_config()).validate_recovery(
        'test-connect', _test_env(), _backup_info(),
    )

    assert result['success'] is False
    assert result['all_passed'] is False
    assert result['test_id'] == 'test-connect'
    assert 'invalid_catalog_name' in result['error']
    assert result['results'] == {}, '连接失败时没有族结果，但结构必须完整可归档'
    assert engine.disposed is True, '连接失败也必须释放引擎'


async def test_run_family_swallows_unexpected_exception():
    validator = DrillValidator(_validator_config())

    async def _boom(conn):
        raise TypeError('意外异常类型')

    guarded = await validator._run_family('constraints', _boom, object())

    assert guarded['passed'] is False
    assert '意外异常类型' in guarded['error']


# ---------------------------------------------------------------------------
# ③ 行数口径 = dump 自身（QA High-2）
# ---------------------------------------------------------------------------
async def test_sql_dump_copy_rows_are_counted(tmp_path):
    dump = _make_sql_dump(tmp_path / 'dump.sql.gz', {
        'public.audit_log': [['1', 'a'], ['2', 'b'], ['3', 'c']],
        'public."order"': [['1', 'x']],
        'public.empty_table': [],  # 空表也必须有 COPY 段（0 行 ≠ 未导出）
        'archive.customer': [['1', 'y'], ['2', 'z']],
    })

    counts = core.count_rows_in_sql_dump(dump)

    assert counts[('public', 'audit_log')] == 3
    assert counts[('public', 'order')] == 1
    assert counts[('public', 'empty_table')] == 0
    assert counts[('archive', 'customer')] == 2


async def test_manifest_rows_equal_dump_rows(tmp_path):
    """核心证明：manifest['tables'][*]['rows'] 必须等于备份文件里实际的行数。"""
    dump = _make_sql_dump(tmp_path / 'dump.sql.gz', {
        'public.audit_log': [['1', 'a']] * 5,
        'public.customer': [['1', 'x'], ['2', 'y']],
    })
    table_names = ['audit_log', 'customer']

    table_stats, rows_source = await core._collect_table_row_counts(
        None, dump, True, table_names, {'audit_log', 'customer'},
    )

    assert rows_source == core.ROWS_SOURCE_DUMP
    assert table_stats == {'audit_log': 5, 'customer': 2}

    class _User:
        username = 'tester'

    coverage = core._build_coverage(
        {'audit_log', 'customer'}, table_names, table_stats, True, False,
    )
    manifest = core._build_manifest(
        _User(), 'remark', False, None, None,
        {'pg_version': '16.4', 'db_name': 'erp_system', 'format': 'sql'},
        '2026-11-04 00:00:00', table_stats, coverage['count_failed_tables'],
        coverage, {}, {}, {}, rows_source=rows_source,
    )

    assert {k: v['rows'] for k, v in manifest['tables'].items()} == {
        'audit_log': 5, 'customer': 2,
    }
    assert manifest['total_rows'] == 7
    assert manifest['rows_source'] == core.ROWS_SOURCE_DUMP
    assert manifest['coverage']['complete'] is True


async def test_table_missing_from_dump_is_minus_one(tmp_path):
    """产物里没有这张表 → 记 -1 并进 coverage，绝不用 0 或 COUNT 去猜。"""
    dump = _make_sql_dump(tmp_path / 'dump.sql.gz', {'public.audit_log': [['1', 'a']]})

    table_stats, rows_source = await core._collect_table_row_counts(
        None, dump, True, ['audit_log', 'ghost'], {'audit_log', 'ghost'},
    )

    assert rows_source == core.ROWS_SOURCE_DUMP
    assert table_stats == {'audit_log': 1, 'ghost': -1}
    coverage = core._build_coverage(
        {'audit_log', 'ghost'}, ['audit_log', 'ghost'], table_stats, True, False,
    )
    assert coverage['count_failed_tables'] == ['ghost']
    assert coverage['complete'] is False


async def test_corrupt_dump_falls_back_to_exact_count_and_is_marked(tmp_path):
    """产物不可解析才回退精确 COUNT，且 rows_source 必须显式标记。"""
    broken = tmp_path / 'dump.sql.gz'
    broken.write_bytes(b'not a gzip stream')

    db = _CountingSession()
    table_stats, rows_source = await core._collect_table_row_counts(
        db, broken, True, ['big'], {'big'},
    )

    assert rows_source == core.ROWS_SOURCE_EXACT_COUNT_FALLBACK
    assert table_stats == {'big': 4_321}
    assert any('COUNT' in sql for sql in db.calls), '回退路径必须真的发 COUNT(*)'


async def test_json_dump_counts(tmp_path):
    path = tmp_path / 'dump.json'
    path.write_text(json.dumps({
        'version': '1.0',
        'tables': {
            'order': {'count': 3, 'rows': [{}, {}, {}]},
            'legacy': {'rows': [{}, {}]},           # 旧格式没有 count
            'broken': {'error': '备份失败', 'count': 0, 'rows': []},
        },
    }), encoding='utf-8')

    counts = core.count_rows_in_json_dump(path)

    assert counts[('public', 'order')] == 3
    assert counts[('public', 'legacy')] == 2
    # 带 error 的表数据没进备份 → 不计数（上游记 -1）
    assert ('public', 'broken') not in counts


class _CountingSession:
    def __init__(self):
        self.calls: list[str] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append(sql)
        if 'pg_class' in sql:
            return _FakeResult(rows=[('big', 5_000_000), ('small', 10)])
        if 'COUNT' in sql:
            return _FakeResult(scalar=4_321)
        return _FakeResult()

    async def begin_nested(self):
        return _FakeNested()


async def test_exact_mode_counts_large_table_instead_of_reltuples():
    db = _CountingSession()

    stats = await core._count_tables(db, ['big', 'small'], {'big', 'small'}, exact=True)

    assert stats == {'big': 4_321, 'small': 4_321}
    assert not any('pg_class' in sql for sql in db.calls), 'exact 模式不应再读 reltuples'
    assert sum(1 for sql in db.calls if 'COUNT' in sql and '"big"' in sql) == 1


async def test_default_mode_keeps_reltuples_estimate_for_large_tables():
    """默认估算路径保持不变（与 tests/test_backup_count_estimate.py 的 L16 同口径）。"""
    db = _CountingSession()

    stats = await core._count_tables(db, ['big', 'small'], {'big', 'small'})

    assert stats['big'] == 5_000_000
    assert stats['small'] == 4_321


def test_full_backup_manifest_counts_come_from_dump():
    """源码守卫：manifest 行数必须走产物解析，不能再回到「导出后 COUNT」。"""
    src = inspect.getsource(core._do_create_full_backup)
    assert '_collect_table_row_counts(' in src
    assert 'rows_source=rows_source' in src
    assert not re.search(r'table_stats = await _count_tables\(', src)


def test_recovery_data_validation_keeps_exact_equality():
    """不允许用「放宽相等断言」的方式绕过大表行数问题。"""
    src = inspect.getsource(DrillValidator._validate_data_integrity)
    assert 'row_count == expected_rows' in src


# ---------------------------------------------------------------------------
# ④ 真库验证（测试库不可达时 skip，逻辑可复核）
# ---------------------------------------------------------------------------
def _test_db_url() -> str:
    override = os.getenv('TEST_DATABASE_URL')
    if override:
        url = override
    else:
        from fastapi_app.core.config import settings
        db_name = os.getenv('DB_NAME', 'erp_system')
        parsed = urlparse(settings.ASYNC_DATABASE_URL)
        if parsed.path.rstrip('/').endswith('_test'):
            url = settings.ASYNC_DATABASE_URL
        else:
            url = urlunparse(
                parsed._replace(path=parsed.path.replace(f'/{db_name}', f'/{db_name}_test', 1))
            )
    from fastapi_app.tests._test_db_guard import assert_is_test_database
    assert_is_test_database(url)
    return url


def _create_engine_or_skip():
    """建真库引擎；连接不通（含驱动/权限/库不存在）一律 skip 并说明原因。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(_test_db_url(), poolclass=NullPool)

    async def _probe() -> None:
        try:
            async with engine.connect() as conn:
                await conn.execute(text('SELECT 1'))
        except Exception as e:  # broad-except: 环境不具备（不可达/无权限/无库）→ skip 而非失败
            await engine.dispose()
            pytest.skip(f'测试库不可达，跳过真库验证：{type(e).__name__}: {e}')

    return engine, _probe


async def test_composite_fk_mapping_on_real_pg():
    """真库端到端：复合外键按位置配对；外键覆盖数与 information_schema 一致。"""
    from sqlalchemy import text

    engine, probe = _create_engine_or_skip()
    await probe()
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                await conn.execute(text(
                    'CREATE TABLE drill_fk_parent_t ('
                    ' pa integer NOT NULL, pb integer NOT NULL,'
                    ' CONSTRAINT drill_fk_parent_t_pkey PRIMARY KEY (pa),'
                    ' CONSTRAINT drill_fk_parent_t_ab_key UNIQUE (pa, pb))'
                ))
                await conn.execute(text(
                    'CREATE TABLE drill_fk_child_t ('
                    ' pfb integer, pfa integer,'
                    ' CONSTRAINT drill_fk_child_t_fk FOREIGN KEY (pfb, pfa)'
                    '   REFERENCES drill_fk_parent_t (pb, pa))'
                ))

                groups = await _load_fk_groups(conn)

                group = groups['public.drill_fk_child_t.drill_fk_child_t_fk']
                assert group['table'] == 'drill_fk_child_t'
                assert group['foreign_table'] == 'drill_fk_parent_t'
                # 引用列顺序与主键顺序相反：靠 conkey/confkey 同下标配对才不会错位
                assert group['columns'] == ['pfb', 'pfa']
                assert group['foreign_columns'] == ['pb', 'pa']

                expected_fk_count = (await conn.execute(text(
                    "SELECT count(*) FROM information_schema.table_constraints"
                    " WHERE constraint_type = 'FOREIGN KEY'"
                    "   AND table_schema = 'public'"
                ))).scalar()
                public_groups = [g for g in groups.values() if g['schema'] == 'public']
                assert len(public_groups) == expected_fk_count
                for g in groups.values():
                    assert len(g['columns']) == len(g['foreign_columns']), g
            finally:
                await trans.rollback()
    finally:
        await engine.dispose()


async def test_same_named_fk_on_two_tables_on_real_pg():
    """真库证明 High-1：同一 schema 内两张表的同名外键必须得到两组、且不混合。

    PostgreSQL 允许 ``CONSTRAINT fk_same`` 同时存在于两张不同的表上，
    ``_load_fk_groups`` 若按 ``schema.constraint_name`` 聚合就会把它们并成一条
    「(a.parent_id, b.parent_id) → parent」的假复合外键。
    """
    from sqlalchemy import text

    engine, probe = _create_engine_or_skip()
    await probe()
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                await conn.execute(text(
                    'CREATE TABLE drill_dup_fk_parent ('
                    ' pa integer PRIMARY KEY, pb integer UNIQUE)'
                ))
                await conn.execute(text(
                    'CREATE TABLE drill_dup_fk_child_a ('
                    ' pid integer, CONSTRAINT drill_dup_fk_same'
                    ' FOREIGN KEY (pid) REFERENCES drill_dup_fk_parent (pa))'
                ))
                await conn.execute(text(
                    'CREATE TABLE drill_dup_fk_child_b ('
                    ' pid integer, CONSTRAINT drill_dup_fk_same'
                    ' FOREIGN KEY (pid) REFERENCES drill_dup_fk_parent (pb))'
                ))

                groups = await _load_fk_groups(conn)

                key_a = 'public.drill_dup_fk_child_a.drill_dup_fk_same'
                key_b = 'public.drill_dup_fk_child_b.drill_dup_fk_same'
                assert key_a in groups and key_b in groups, sorted(groups)
                assert groups[key_a]['table'] == 'drill_dup_fk_child_a'
                assert groups[key_b]['table'] == 'drill_dup_fk_child_b'
                # 各自单列，且没有把另一张表的列混进来
                assert groups[key_a]['columns'] == ['pid']
                assert groups[key_b]['columns'] == ['pid']
                assert groups[key_a]['constraint_oid'] != groups[key_b]['constraint_oid']
            finally:
                await trans.rollback()
    finally:
        await engine.dispose()


async def test_same_named_unique_across_schemas_on_real_pg():
    """真库证明 High-1（UNIQUE 侧）：跨 schema 同名唯一约束按 (schema, 表) 区分。

    同 schema 内 UNIQUE 约束名不能重复（约束名与索引名绑定，索引名在 schema 内唯一），
    所以真库能造出的「同名唯一约束」场景是跨 schema；旧实现按 constraint_name 聚合，
    且 JOIN 连 schema 都没有，会把两个 schema 的列集合串成不存在的复合键。
    """
    from sqlalchemy import text

    engine, probe = _create_engine_or_skip()
    await probe()
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                await conn.execute(text('CREATE SCHEMA drill_alt'))
                await conn.execute(text(
                    'CREATE TABLE drill_dup_uq_a ('
                    ' code text, extra text,'
                    ' CONSTRAINT drill_dup_uq_same UNIQUE (code, extra))'
                ))
                await conn.execute(text(
                    'CREATE TABLE drill_alt.drill_dup_uq_b ('
                    ' code text,'
                    ' CONSTRAINT drill_dup_uq_same UNIQUE (code))'
                ))

                groups = await _load_unique_groups(conn)

                key_a = 'public.drill_dup_uq_a.drill_dup_uq_same'
                key_b = 'drill_alt.drill_dup_uq_b.drill_dup_uq_same'
                assert key_a in groups and key_b in groups, sorted(
                    k for k in groups if 'drill_dup_uq' in k
                )
                assert groups[key_a]['columns'] == ['code', 'extra']
                assert groups[key_b]['columns'] == ['code']
                assert groups[key_a]['constraint_oid'] != groups[key_b]['constraint_oid']
            finally:
                await trans.rollback()
    finally:
        await engine.dispose()
