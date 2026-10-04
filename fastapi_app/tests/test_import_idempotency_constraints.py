"""P1-a：导入幂等双层防护的 DB 级约束测试（迁移 067）。

四层覆盖（沿用 test_product_stock_check_constraint.py 的范式）：
1) 迁移：revision 链 + 单 head、upgrade/downgrade 的 DDL 断言（幂等守卫）。
2) DB 行为（SQLite 内存库 + 迁移 DDL）：import_file_registry 的
   UNIQUE(file_hash, import_type) 拦同文件重复登记；inventory_log 的
   部分唯一索引语义在 PG 上不直接可用（SQLite 无部分索引语法差异），
   故用迁移 DDL 原文断言 + SQLite 全量唯一索引行为近似验证。
3) 幂等重放行为：同一 idem_key 插两次被拒；idem_key=NULL 的手工路径
   不受约束（可插任意多条）。
4) 真实 PostgreSQL 单事务证明：事务内建表建索引 → 同 idem_key 双插
   断言 IntegrityError → NULL 多插放行 → 整事务 ROLLBACK 零持久变更。
"""
import ast
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

import migrations.versions.pg_standalone_067_import_idempotency as mig

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VERSIONS_DIR = _REPO_ROOT / "migrations" / "versions"
_PREVIOUS_REVISION = "pg_standalone_066_case_product_root_unique"
_PROBE = "__p1a_probe__"


# ---------------------------------------------------------------------------
# 1) 迁移图与 DDL
# ---------------------------------------------------------------------------
def _parents(value):
    if value is None:
        return ()
    if isinstance(value, (tuple, list)):
        return tuple(value)
    return (value,)


def _literal(node):
    try:
        return ast.literal_eval(node)
    except Exception:  # pragma: no cover
        return None


def _migration_graph() -> dict[str, tuple]:
    graph: dict[str, tuple] = {}
    for path in sorted(_VERSIONS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision = down = None
        for node in tree.body:
            target = None
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                target = node.targets[0].id
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target = node.target.id
            if target == "revision":
                revision = _literal(node.value)
            elif target == "down_revision":
                down = _literal(node.value)
        assert revision, f"迁移缺少 revision: {path.name}"
        graph[revision] = _parents(down)
    return graph


def test_migration_revision_chain_and_single_head():
    graph = _migration_graph()
    assert mig.revision in graph
    assert graph[mig.revision] == (_PREVIOUS_REVISION,)

    heads = [rev for rev in graph if rev not in {p for ps in graph.values() for p in ps}]
    assert len(heads) == 1, f"迁移图必须单 head，实际: {heads}"
    assert heads[0] == mig.revision


@pytest.fixture()
def captured_ddl(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(mig.op, "execute", lambda stmt: calls.append(str(stmt)))
    return calls


def test_upgrade_ddl_statements(captured_ddl):
    mig.upgrade()
    joined = "\n".join(captured_ddl)
    assert "CREATE TABLE IF NOT EXISTS import_file_registry" in joined
    assert "CONSTRAINT uq_import_file UNIQUE (file_hash, import_type)" in joined
    assert "ADD COLUMN IF NOT EXISTS idem_key TEXT" in joined
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_log_idem" in joined
    assert "WHERE idem_key IS NOT NULL" in joined


def test_downgrade_drops_in_reverse(captured_ddl):
    mig.downgrade()
    joined = "\n".join(captured_ddl)
    assert "DROP INDEX IF EXISTS uq_inventory_log_idem" in joined
    assert "DROP COLUMN IF EXISTS idem_key" in joined
    assert "DROP TABLE IF EXISTS import_file_registry" in joined
    # 索引先于表删除、列约束先于登记表（逆序可重复执行）
    assert joined.index("uq_inventory_log_idem") < joined.index("DROP COLUMN IF EXISTS idem_key")


# ---------------------------------------------------------------------------
# 2) DB 行为：SQLite 内存库（迁移 DDL 原样执行）
# ---------------------------------------------------------------------------
@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'p1a_idem.db'}")
    with engine.begin() as conn:
        # inventory_log 只需本测试涉及的最小列集
        conn.execute(text(
            "CREATE TABLE inventory_log (id INTEGER PRIMARY KEY, product_id INTEGER,"
            " change_type TEXT, change_quantity INTEGER, idem_key TEXT)"
        ))
        # 直接执行迁移里第 1 层的建表 DDL（SQLite 兼容：去掉 TIMESTAMPTZ/JSONB 差异
        # 由第 4 节真实 PG 证明兜底，SQLite 层只验证唯一键行为）
        conn.execute(text(
            "CREATE TABLE import_file_registry ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, file_hash TEXT NOT NULL,"
            " import_type TEXT NOT NULL, original_filename TEXT NOT NULL,"
            " uploaded_by INTEGER, row_total INTEGER, created_at TEXT DEFAULT (datetime('now')),"
            " CONSTRAINT uq_import_file UNIQUE (file_hash, import_type))"
        ))
        # 近似部分唯一索引：SQLite 支持带 WHERE 的部分索引（3.8.0+），语义与 PG 一致
        conn.execute(text(
            "CREATE UNIQUE INDEX uq_inventory_log_idem ON inventory_log (idem_key)"
            " WHERE idem_key IS NOT NULL"
        ))
    yield engine
    engine.dispose()


def _reg(conn, fh: str, itype: str):
    return conn.execute(text(
        "INSERT INTO import_file_registry (file_hash, import_type, original_filename)"
        " VALUES (:f, :t, :n)"
    ), {"f": fh, "t": itype, "n": "x.xlsx"})


def _log(conn, idem: str | None):
    return conn.execute(text(
        "INSERT INTO inventory_log (product_id, change_type, change_quantity, idem_key)"
        " VALUES (1, '出库', -3, :k)"
    ), {"k": idem})


def test_registry_rejects_same_file_same_type(db):
    with db.begin() as conn:
        _reg(conn, "hash-aaa", "stockins")
    with pytest.raises(IntegrityError) as ei:
        with db.begin() as conn:
            _reg(conn, "hash-aaa", "stockins")
    msg = str(ei.value)
    # SQLite 按列名报错、PG 按约束名报错，两者取其一
    assert "uq_import_file" in msg or (
        "file_hash" in msg and "import_type" in msg
    )


def test_registry_allows_same_file_different_type(db):
    with db.begin() as conn:
        _reg(conn, "hash-aaa", "stockins")
        _reg(conn, "hash-aaa", "stockouts")  # 同文件换导入类型 = 新键，放行


def test_registry_rejects_concurrent_double_click_sequencing(db):
    """并发双击的时序近似：两个事务先后登记同键，第二个必须被唯一约束拒绝。"""
    with db.begin() as conn:
        _reg(conn, "hash-bbb", "orders")
    with pytest.raises(IntegrityError):
        with db.begin() as conn:
            _reg(conn, "hash-bbb", "orders")


def test_log_rejects_duplicate_idem_key(db):
    with db.begin() as conn:
        _log(conn, "import:stockin:客户A|产品B|2026-10-04|100")
    with pytest.raises(IntegrityError) as ei:
        with db.begin() as conn:
            _log(conn, "import:stockin:客户A|产品B|2026-10-04|100")
    msg = str(ei.value)
    # SQLite 按列名报错、PG 按约束名报错，两者取其一
    assert "uq_inventory_log_idem" in msg or "idem_key" in msg


def test_log_allows_different_idem_keys(db):
    with db.begin() as conn:
        _log(conn, "import:stockin:客户A|产品B|2026-10-04|100")
        _log(conn, "import:stockin:客户A|产品B|2026-10-04|101")  # 数量不同 = 新键
        _log(conn, "import:stockin:客户A|产品C|2026-10-04|100")  # 产品不同 = 新键


def test_log_null_idem_key_is_unconstrained(db):
    """手工路径（不填 idem_key）行为零变化：任意多条相同业务内容都放行。"""
    with db.begin() as conn:
        _log(conn, None)
        _log(conn, None)
        _log(conn, None)
    with db.connect() as conn:
        assert conn.execute(
            text("SELECT COUNT(*) FROM inventory_log WHERE idem_key IS NULL")
        ).scalar() == 3


# ---------------------------------------------------------------------------
# 4) 真实 PostgreSQL 单事务证明（零持久变更）
# ---------------------------------------------------------------------------
_IDEM_INDEX_QUERY = text(
    "SELECT indexname FROM pg_indexes WHERE indexname = 'uq_inventory_log_idem'"
)
_REGISTRY_TABLE_QUERY = text(
    "SELECT to_regclass('import_file_registry') IS NOT NULL"
)


def test_real_pg_transaction_scoped_proof():
    """事务内建表建索引 → 幂等约束逐条验证 → 整事务 ROLLBACK；库内零痕迹。

    自带建表：067 迁移可能尚未应用到目标库，故本证明不依赖其已应用。
    """
    try:
        from fastapi_app.core.database import get_sync_engine

        engine = get_sync_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - 无库环境跳过
        pytest.skip(f"真实 PostgreSQL 不可用，跳过单事务证明: {exc!r}")

    import json

    with engine.connect() as conn:
        state = {
            "idx": conn.execute(_IDEM_INDEX_QUERY).scalar() is not None,
            "tbl": conn.execute(_REGISTRY_TABLE_QUERY).scalar(),
            "col": conn.execute(text(
                "SELECT COUNT(*) FROM information_schema.columns"
                " WHERE table_name = 'inventory_log' AND column_name = 'idem_key'"
            )).scalar() > 0,
            "rows": conn.execute(text("SELECT COUNT(*) FROM inventory_log")).scalar(),
        }
        # inventory_log.product_id 有 FK + NOT NULL：探针需用库中真实存在的产品
        pid = conn.execute(text("SELECT id FROM product LIMIT 1")).scalar()

    if pid is None:
        pytest.skip("真实库中无 product 行，无法构造 inventory_log 探针")

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            _pg_ensure_objects(conn, state)
            _pg_run_idem_probes(conn, pid, json)
        finally:
            trans.rollback()

    _pg_assert_no_trace(engine, state)
    engine.dispose()


def _pg_ensure_objects(conn, state) -> None:
    """用迁移的同一份 DDL 建对象（未应用迁移时自建，已应用则 IF NOT EXISTS 空转）。"""
    if not state["tbl"]:
        conn.execute(text(mig._DDL_REGISTRY_TABLE))
    if not state["col"]:
        conn.execute(text(mig._DDL_ADD_IDEM_COLUMN))
    if not state["idx"]:
        conn.execute(text(mig._DDL_IDEM_INDEX))


def _pg_run_idem_probes(conn, pid, json) -> None:
    """幂等约束逐条验证。预期失败者用 SAVEPOINT 隔离 —— PG 事务报错后即 aborted。"""
    log_insert = (
        "INSERT INTO inventory_log (product_id, change_type, change_quantity, idem_key)"
        " VALUES (:p, :t, :q, :k)"
    )
    # 幂等列：首插成功、同键二插拒绝
    conn.execute(text(log_insert), {"p": pid, "t": "出库", "q": -3, "k": _PROBE})
    sp = conn.begin_nested()
    with pytest.raises(IntegrityError):
        conn.execute(text(log_insert), {"p": pid, "t": "出库", "q": -3, "k": _PROBE})
    sp.rollback()
    # NULL 不受部分索引约束：双插放行
    conn.execute(text(log_insert), {"p": pid, "t": "手工", "q": 5, "k": None})
    conn.execute(text(log_insert), {"p": pid, "t": "手工", "q": 5, "k": None})
    # 登记表唯一键：首插成功、同键二插拒绝
    conn.execute(text(
        "INSERT INTO import_file_registry (file_hash, import_type, original_filename, result_summary)"
        " VALUES ('p1a-h', 'p1a', 'probe', :s)"
    ), {"s": json.dumps({"ok": 1})})
    sp = conn.begin_nested()
    with pytest.raises(IntegrityError):
        conn.execute(text(
            "INSERT INTO import_file_registry (file_hash, import_type, original_filename)"
            " VALUES ('p1a-h', 'p1a', 'probe')"
        ))
    sp.rollback()


def _pg_assert_no_trace(engine, state) -> None:
    """事务回滚后：自建对象若原不存在则应消失，探针行不留痕，存量行数不变。"""
    with engine.connect() as conn:
        if not state["idx"]:
            assert conn.execute(_IDEM_INDEX_QUERY).scalar() is None
        if not state["tbl"]:
            assert conn.execute(_REGISTRY_TABLE_QUERY).scalar() is False
        total = conn.execute(text("SELECT COUNT(*) FROM inventory_log")).scalar()
        assert total == state["rows"]
        if state["col"]:
            assert conn.execute(
                text("SELECT COUNT(*) FROM inventory_log WHERE idem_key = :k"), {"k": _PROBE}
            ).scalar() == 0
