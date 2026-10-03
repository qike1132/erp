"""P1-6：product.current_stock 的 DB 级非负兜底（CHECK）+ 迁移自适应行为。

四层覆盖：
1) 模型声明：product 表带 ck_product_current_stock_nonneg CHECK (current_stock >= 0)。
2) DB 行为（SQLite 内存库，直接用 ORM 编译出的 CREATE TABLE DDL）：插入 / 更新
   负库存被数据库拒绝（IntegrityError 且报错含约束名），0 与正值放行，不留负值行。
3) 迁移：revision 链 + 单 head、upgrade 自适应（存在存量负值 ⇒ NOT VALID + WARNING）、
   幂等分支、空表分支、offline 分支、downgrade DROP IF EXISTS。
4) 真实 PostgreSQL 单事务证明（captain 裁定 (b)）：事务内执行迁移 DDL + 负值写入
   断言 IntegrityError + 整事务 ROLLBACK —— 零持久变更（约束、探针行、存量库存三项复核）。
"""
import ast
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

import migrations.versions.pg_standalone_061_add_product_stock_check as mig
from fastapi_app.shared_models import Product

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VERSIONS_DIR = _REPO_ROOT / "migrations" / "versions"
_MIGRATION_FILENAME = "pg_standalone_061_add_product_stock_check.py"
_CONSTRAINT = "ck_product_current_stock_nonneg"
_CHECK_SQL = "current_stock >= 0"
_PREVIOUS_REVISION = "pg_standalone_060_fix_updated_at_varchar_columns"
# 探针名：仅存在于被回滚的事务里
_PROBE_NAME = "__p1_6_probe_ck__"


# ---------------------------------------------------------------------------
# 1) 模型声明
# ---------------------------------------------------------------------------
def test_model_declares_non_negative_check():
    checks = {
        c.name: str(c.sqltext)
        for c in Product.__table__.constraints
        if isinstance(c, CheckConstraint)
    }
    assert checks.get(_CONSTRAINT) == _CHECK_SQL


def test_compiled_create_table_carries_named_check():
    engine = create_engine("sqlite://")
    ddl = str(CreateTable(Product.__table__).compile(engine))
    assert _CONSTRAINT in ddl
    assert "CHECK (current_stock >= 0)" in ddl
    engine.dispose()


# ---------------------------------------------------------------------------
# 2) DB 行为：真实 SQLite 引擎用同一份 ORM DDL
# ---------------------------------------------------------------------------
@pytest.fixture()
def product_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'p16_stock_check.db'}")
    ddl = str(CreateTable(Product.__table__).compile(engine))
    with engine.begin() as conn:
        conn.execute(text(ddl))
    yield engine
    engine.dispose()


def _insert(conn, name: str, stock: int):
    return conn.execute(
        Product.__table__.insert().values(name=name, current_stock=stock)
    )


def test_insert_negative_stock_is_rejected_by_db(product_db):
    with product_db.begin() as conn:
        _insert(conn, "P-ZERO", 0)
        _insert(conn, "P-POS", 7)

    with pytest.raises(IntegrityError) as ei:
        with product_db.begin() as conn:
            _insert(conn, "P-NEG", -1)

    assert _CONSTRAINT in str(ei.value)
    with product_db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM product")).scalar() == 2
        assert conn.execute(
            text("SELECT COUNT(*) FROM product WHERE name = 'P-NEG'")
        ).scalar() == 0


def test_update_to_negative_stock_is_rejected_by_db(product_db):
    with product_db.begin() as conn:
        _insert(conn, "P-UPD", 5)

    with pytest.raises(IntegrityError) as ei:
        with product_db.begin() as conn:
            conn.execute(text("UPDATE product SET current_stock = -1 WHERE name = 'P-UPD'"))

    assert _CONSTRAINT in str(ei.value)
    with product_db.connect() as conn:
        assert conn.execute(
            text("SELECT current_stock FROM product WHERE name = 'P-UPD'")
        ).scalar() == 5


def test_zero_and_positive_stock_are_allowed(product_db):
    with product_db.begin() as conn:
        _insert(conn, "P-MIN", 0)
        _insert(conn, "P-MAX", 10 ** 6)
    with product_db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM product")).scalar() == 2


# ---------------------------------------------------------------------------
# 3) 迁移：revision 图 + 自适应分支
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
    except Exception:  # pragma: no cover - 非法字面量时视为 None
        return None


def _migration_graph() -> dict[str, tuple]:
    graph: dict[str, tuple] = {}
    for path in sorted(_VERSIONS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision = None
        down = None
        for node in tree.body:
            # 兼容 `revision = ...` 与 `revision: str = ...` 两种写法
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
    assert mig.revision == _MIGRATION_FILENAME[:-3]
    assert mig.down_revision == _PREVIOUS_REVISION
    assert mig.branch_labels is None and mig.depends_on is None

    graph = _migration_graph()
    assert mig.revision in graph
    assert graph[mig.revision] == (_PREVIOUS_REVISION,)

    heads = [rev for rev in graph if rev not in {p for ps in graph.values() for p in ps}]
    assert len(heads) == 1, f"迁移图必须单 head，实际: {heads}"

    chain: set[str] = set()
    stack = list(_parents(heads[0]))
    while stack:
        cur = stack.pop()
        if cur in chain or cur not in graph:
            continue
        chain.add(cur)
        stack.extend(graph[cur])
    assert mig.revision in chain, "本迁移必须位于唯一 head 的祖先链上"


@pytest.fixture()
def captured_ddl(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(mig.op, "execute", lambda stmt: calls.append(str(stmt)))
    return calls


def _arm(monkeypatch, *, offline: bool, table: bool, exists: bool, negatives: list[int]):
    monkeypatch.setattr(mig.context, "is_offline_mode", lambda: offline)
    monkeypatch.setattr(mig, "table_exists", lambda _t: table)
    monkeypatch.setattr(mig, "_constraint_exists", lambda: exists)
    monkeypatch.setattr(mig, "_negative_stock_ids", lambda: negatives)


def test_upgrade_adds_valid_check_when_no_negative_rows(monkeypatch, captured_ddl):
    _arm(monkeypatch, offline=False, table=True, exists=False, negatives=[])
    mig.upgrade()
    assert captured_ddl == [mig._ADD_VALID]
    assert captured_ddl[0] == (
        'ALTER TABLE "product" ADD CONSTRAINT ck_product_current_stock_nonneg '
        "CHECK (current_stock >= 0)"
    )


def test_upgrade_uses_not_valid_when_negative_rows_exist(monkeypatch, captured_ddl):
    _arm(monkeypatch, offline=False, table=True, exists=False, negatives=[3, 9])
    mig.upgrade()
    assert captured_ddl == [mig._ADD_NOT_VALID]
    assert captured_ddl[0].endswith("NOT VALID")


def test_upgrade_is_idempotent_when_constraint_exists(monkeypatch, captured_ddl):
    _arm(monkeypatch, offline=False, table=True, exists=True, negatives=[])
    mig.upgrade()
    assert captured_ddl == []


def test_upgrade_skips_when_product_table_absent(monkeypatch, captured_ddl):
    """空库重放：product 表不存在时跳过，且不触碰任何探测以外的 SQL。"""
    _arm(monkeypatch, offline=False, table=False, exists=False, negatives=[])

    def _forbidden():
        raise AssertionError("表不存在时不得扫描存量负值")

    monkeypatch.setattr(mig, "_negative_stock_ids", _forbidden)
    mig.upgrade()
    assert captured_ddl == []


def test_upgrade_offline_renders_valid_without_probing(monkeypatch, captured_ddl):
    """--sql 模式无 DB 可探测：按「存量负值 0 条」的已验证假设输出 VALID DDL。"""
    monkeypatch.setattr(mig.context, "is_offline_mode", lambda: True)

    def _forbidden():
        raise AssertionError("offline 模式不得扫描存量")

    monkeypatch.setattr(mig, "_negative_stock_ids", _forbidden)
    mig.upgrade()
    assert captured_ddl == [mig._ADD_VALID]


def test_downgrade_drops_constraint_if_exists(monkeypatch, captured_ddl):
    monkeypatch.setattr(mig, "table_exists", lambda _t: True)
    mig.downgrade()
    assert captured_ddl == [mig._DROP]
    assert "DROP CONSTRAINT IF EXISTS" in captured_ddl[0]


def test_downgrade_skips_when_table_absent(monkeypatch, captured_ddl):
    monkeypatch.setattr(mig, "table_exists", lambda _t: False)
    mig.downgrade()
    assert captured_ddl == []


# ---------------------------------------------------------------------------
# 4) 真实 PostgreSQL 单事务证明（零持久变更）
# ---------------------------------------------------------------------------
def _real_pg_engine():
    from fastapi_app.core.database import get_sync_engine

    engine = get_sync_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return engine


_CONSTRAINT_QUERY = text(
    "SELECT conname FROM pg_constraint "
    "WHERE conname = :n AND conrelid = to_regclass('product')"
)
_SNAPSHOT_QUERY = text("SELECT id, current_stock FROM product ORDER BY id")


def _probe_negative_write(engine, sql: str, params: dict) -> bool:
    """独立事务内：加约束 → 执行一次负值写（断言 IntegrityError）→ 整事务 ROLLBACK。

    PG 事务一旦报错即进入 aborted 状态，故每次探测都必须单独开事务。
    返回约束在探测前是否已存在。
    """
    with engine.connect() as conn:
        trans = conn.begin()
        pre_existed = False
        try:
            existing = conn.execute(_CONSTRAINT_QUERY, {"n": _CONSTRAINT}).scalar()
            pre_existed = existing is not None
            if not pre_existed:
                conn.execute(text(mig._ADD_VALID))
            with pytest.raises(IntegrityError) as ei:
                conn.execute(text(sql), params)
            assert _CONSTRAINT in str(ei.value)
        finally:
            trans.rollback()
    return pre_existed


def test_real_pg_transaction_scoped_proof():
    """事务内加约束 → 负值 INSERT/UPDATE 被 DB 拒绝 → 整事务回滚；库内零痕迹。"""
    try:
        engine = _real_pg_engine()
    except Exception as exc:  # pragma: no cover - 无库环境跳过
        pytest.skip(f"真实 PostgreSQL 不可用，跳过单事务证明: {exc!r}")

    with engine.connect() as conn:
        before_rows = conn.execute(_SNAPSHOT_QUERY).fetchall()

    pre_existed = _probe_negative_write(
        engine,
        "INSERT INTO product (name, current_stock, initial_stock) VALUES (:n, -1, 0)",
        {"n": _PROBE_NAME},
    )
    if before_rows:
        _probe_negative_write(
            engine,
            "UPDATE product SET current_stock = -1 WHERE id = :n",
            {"n": before_rows[0][0]},
        )

    with engine.connect() as conn:
        # 约束、探针行、存量库存/版本三项都不因本次证明发生变化
        if not pre_existed:
            assert conn.execute(_CONSTRAINT_QUERY, {"n": _CONSTRAINT}).scalar() is None
        assert conn.execute(
            text("SELECT COUNT(*) FROM product WHERE name = :n"), {"n": _PROBE_NAME}
        ).scalar() == 0
        assert conn.execute(_SNAPSHOT_QUERY).fetchall() == before_rows

