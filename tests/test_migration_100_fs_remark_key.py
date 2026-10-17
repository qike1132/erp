"""迁移 100：成品库存备注键去客户化（(cust,prod,batch) → (prod,batch)）。

锁住两个要求：
1. 存量去重——同 (product_id, batch_no) 多行时保留最新 updated_at（NULL 视为最早）；
2. 索引切换——删旧索引 uq_fs_remark_cust_prod_batch，建新索引 uq_fs_remark_prod_batch。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / 'migrations' / 'versions' / 'pg_standalone_100_fs_remark_key.py'
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location('migration_100', MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_db(rows: list[tuple[int, str, str, str, int]]):
    """rows: (id, customer_name, batch_no, remark, updated_at_day)"""
    engine = sa.create_engine('sqlite://')
    conn = engine.connect()
    conn.execute(sa.text(
        'CREATE TABLE finished_stock_remark ('
        ' id INTEGER PRIMARY KEY AUTOINCREMENT,'
        ' customer_name VARCHAR(100) NOT NULL DEFAULT \'\','
        ' product_id INTEGER NOT NULL,'
        ' batch_no VARCHAR(100) NOT NULL DEFAULT \'\','
        ' remark TEXT NOT NULL DEFAULT \'\','
        ' create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,'
        ' updated_at TIMESTAMP)'
    ))
    for rid, cust, bno, remark, day in rows:
        conn.execute(
            sa.text(
                'INSERT INTO finished_stock_remark'
                ' (id, customer_name, product_id, batch_no, remark, create_time, updated_at)'
                ' VALUES (:i, :c, :p, :b, :r, datetime(\'2026-01-01\'),'
                ' datetime(\'2026-01-01\', :d))'
            ),
            {'i': rid, 'c': cust, 'p': 7, 'b': bno, 'r': remark, 'd': f'+{day} days'},
        )
    return engine, conn


def _run_upgrade(conn):
    mod = _load_migration_module()
    ops = Operations(MigrationContext.configure(_CommentFilterConn(conn)))
    import migrations._legacy_base_guard as guard
    # 全局 guard.op / guard.context 是进程级单例：替换后必须恢复原值，
    # 否则同批次后续测试（如 test_product_stock_check_constraint 的 offline
    # 渲染）会拿到 _CommentFilterConn 包装连接，sa_inspect 直接炸
    #（曾致 offline 测试跨文件假红）。
    orig_op, orig_ctx = guard.op, guard.context
    orig_mod_ctx = getattr(mod, 'context', None)
    try:
        mod.op = ops
        guard.op = ops
        guard.context = _CtxStub()
        # 迁移内的 context.is_offline_mode() 用模块自己的 import（alembic.context
        # proxy 在非 alembic 运行环境下未建立 → NameError）；注入 stub 同款豁免。
        mod.context = _CtxStub()
        mod.upgrade()
    finally:
        guard.op, guard.context = orig_op, orig_ctx
        if orig_mod_ctx is not None:
            mod.context = orig_mod_ctx


class _CommentFilterConn:
    """sqlite 不认 COMMENT ON（PG 专属）；迁移里的 COMMENT 同步语句在此跳过。"""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, stmt, params=None):
        if isinstance(stmt, str) and stmt.lstrip().upper().startswith('COMMENT'):
            class _R:
                rowcount = 0
            return _R()
        return self._conn.execute(stmt, params)

    def exec_driver_sql(self, stmt, params=None):
        if stmt.lstrip().upper().startswith('COMMENT'):
            class _R:
                rowcount = 0
            return _R()
        return self._conn.exec_driver_sql(stmt, params)

    def __getattr__(self, name):
        return getattr(self._conn, name)


class _CtxStub:
    @staticmethod
    def is_offline_mode():
        return False


def test_dedup_keeps_latest_updated_at():
    """同 (7,'B1') 三行（A' 2天 / '' 1天 / B 5天）→ 保留 updated_at 最新的 B 行。"""
    _engine, conn = _make_db([
        (1, 'A', 'B1', '最新备注B', 5),
        (2, 'A', 'B1', '旧备注A', 2),
        (3, '', 'B1', '旧备注空', 1),
        (4, 'C', 'B2', '别的批次', 1),
    ])
    _run_upgrade(conn)
    rows = conn.execute(sa.text(
        'SELECT id, customer_name, batch_no, remark FROM finished_stock_remark ORDER BY id'
    )).fetchall()
    # id=2,3 被去重；id=1（最新）与 id=4（不同键）保留
    assert [(r[0], r[2], r[3]) for r in rows] == [(1, 'A', '最新备注B'), (4, 'C', 'B2', )] or \
           [(r[0], r[3]) for r in rows] == [(1, '最新备注B'), (4, '别的批次')]
    # 新唯一索引已建
    idx = conn.execute(sa.text(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='finished_stock_remark'"
    )).fetchall()
    names = {r[0] for r in idx}
    assert 'uq_fs_remark_prod_batch' in names
    assert 'uq_fs_remark_cust_prod_batch' not in names
    conn.close()


def test_upgrade_idempotent_when_no_dups():
    """无重复时仅换索引，数据原样保留。"""
    _engine, conn = _make_db([
        (1, 'A', 'B1', 'r1', 1),
        (2, 'B', 'B2', 'r2', 1),
    ])
    _run_upgrade(conn)
    rows = conn.execute(sa.text(
        'SELECT id, remark FROM finished_stock_remark ORDER BY id'
    )).fetchall()
    assert [(r[0], r[1]) for r in rows] == [(1, 'r1'), (2, 'r2')]
    conn.close()
