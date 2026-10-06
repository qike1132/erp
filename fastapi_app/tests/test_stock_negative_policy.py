"""P1-2 负库存策略参数化（ALLOW_NEGATIVE_STOCK）回归测试。

覆盖契约要求：
- 默认（未设 ALLOW_NEGATIVE_STOCK）超量扣减被拒绝，异常类型与文案与改动前一致；
- ALLOW_NEGATIVE_STOCK=true 时同一路径放行；
- stock_concurrency.py / batch_import_service.py / case/commands.py 三处调用点
  全部改为统一入口，且不留内联 current_stock 判断（ast 静态证明）；
- update_stock_with_optimistic_lock 签名与既有行为不变。
"""
import ast
import inspect
import types
from pathlib import Path

import pytest

from fastapi_app.services.batch_import_service import import_case_stockouts_service
from fastapi_app.services.case import commands as case_commands
from fastapi_app.shared.stock_concurrency import (
    allow_negative_stock,
    apply_stock_delta_locked,
    assert_stock_available,
    check_stock_available,
    update_stock_with_optimistic_lock,
)
from fastapi_app.shared_models import CaseMovement

REPO = Path(__file__).resolve().parents[2]
STOCK_CONCURRENCY = REPO / "fastapi_app/shared/stock_concurrency.py"
BATCH_IMPORT = REPO / "fastapi_app/services/batch_import_service.py"
CASE_COMMANDS = REPO / "fastapi_app/services/case/commands.py"
ENV_EXAMPLE = REPO / ".env.example"

HISTORIC_DENY = "库存不足！当前库存: 5，需要: 8"


# --------------------------------------------------------------------------
# 统一入口本身
# --------------------------------------------------------------------------
@pytest.mark.parametrize("raw", ["", " ", "false", "FALSE", "0", "no", "off", "yes-no"])
def test_policy_defaults_to_deny(monkeypatch, raw):
    monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", raw)
    assert allow_negative_stock() is False
    with pytest.raises(ValueError):
        assert_stock_available(1, -2)


def test_policy_unset_denies(monkeypatch):
    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)
    assert allow_negative_stock() is False
    assert check_stock_available(5, -8) == HISTORIC_DENY


@pytest.mark.parametrize("raw", ["true", "TRUE", "True", "1", "yes", "on", " true "])
def test_policy_truthy_allows(monkeypatch, raw):
    monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", raw)
    assert allow_negative_stock() is True
    assert check_stock_available(5, -8) is None
    assert_stock_available(5, -8)  # 不抛异常即为放行


def test_boundary_zero_stock_is_allowed_by_default(monkeypatch):
    """扣减到恰好 0 不算负库存；入库（正 delta）永不被策略拦截。"""
    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)
    assert check_stock_available(5, -5) is None
    assert check_stock_available(0, +10) is None
    assert check_stock_available(0, 0) is None


def test_message_override_keeps_call_site_wording():
    assert check_stock_available(1, -3, message="自定义文案") == "自定义文案"
    with pytest.raises(ValueError) as ei:
        assert_stock_available(1, -3, message="自定义文案")
    assert type(ei.value) is ValueError
    assert str(ei.value) == "自定义文案"


# --------------------------------------------------------------------------
# update_stock_with_optimistic_lock：签名 + 既有行为
# --------------------------------------------------------------------------
class _Result:
    def __init__(self, product=None, rowcount=0):
        self._product = product
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self._product


class _Nested:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class _FakeLockSession:
    """update_stock_with_optimistic_lock 所需的最小 AsyncSession 替身。"""

    def __init__(self, product):
        self.product = product
        self.rows = [product]
        self.statements = []
        self.refreshed = 0
        self.expunged = 0

    def begin_nested(self):
        return _Nested()

    async def execute(self, stmt):
        self.statements.append(stmt)
        if len(self.statements) == 1:
            return _Result(self.product)
        return _Result(rowcount=1)

    async def refresh(self, obj):
        self.refreshed += 1

    def expunge(self, obj):
        self.expunged += 1


def _fake_product(stock=5, version=3):
    return types.SimpleNamespace(id=1, current_stock=stock, version=version)


def test_optimistic_lock_signature_unchanged():
    sig = inspect.signature(update_stock_with_optimistic_lock)
    assert list(sig.parameters) == ["db", "product_id", "delta", "retries"]
    assert sig.parameters["retries"].default == 3


async def test_optimistic_lock_denies_negative_with_historic_error(monkeypatch):
    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)
    product = _fake_product(stock=5)
    db = _FakeLockSession(product)

    with pytest.raises(ValueError) as ei:

        await update_stock_with_optimistic_lock(db, 1, -8)

    assert type(ei.value) is ValueError
    assert str(ei.value) == HISTORIC_DENY
    assert len(db.statements) == 1  # 只发了 SELECT，没有 UPDATE
    assert db.refreshed == 0
    assert product.current_stock == 5
    assert product.version == 3


async def test_optimistic_lock_allows_when_env_true(monkeypatch):
    monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", "true")
    product = _fake_product(stock=5)
    db = _FakeLockSession(product)

    returned = await update_stock_with_optimistic_lock(db, 1, -8)

    assert returned is product
    assert db.refreshed == 1
    assert len(db.statements) == 2
    params = db.statements[-1].compile().params
    assert params["current_stock"] == -3
    assert params["version"] == 4


# --------------------------------------------------------------------------
# 调用点：case/commands.py
# --------------------------------------------------------------------------
class _FakeResult:
    """execute() 的最小返回替身：只支持 scalar_one_or_none()。"""

    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    """case/commands.py 调用点所需的最小 AsyncSession 替身。"""

    def __init__(self, movement=None):
        self.movement = movement
        self.added = []
        self.deleted = []
        self.flushed = 0

    async def get(self, model, pk):
        return self.movement

    async def execute(self, stmt):
        # update_movement / delete_movement 现在用 `SELECT ... FOR UPDATE` 取流水行
        # （先锁再读，避免并发编辑同一条流水时用陈旧快照算增量）
        return _FakeResult(self.movement)

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def flush(self):
        self.flushed += 1

    async def rollback(self):
        self.rolled_back = True

    def begin_nested(self):
        return _Nested()


async def _patch_case(monkeypatch, case_obj, func_name):
    async def _stub(db, key):
        return case_obj

    monkeypatch.setattr(case_commands, func_name, _stub)


async def test_create_case_movement_denies_and_allows(monkeypatch):
    case_obj = types.SimpleNamespace(id=7, current_stock=5, version=0)

    await _patch_case(monkeypatch, case_obj, "_get_case_for_update")

    async def _fake_number(db, direction):
        return "PKOUT-T1"

    monkeypatch.setattr(case_commands, "generate_case_movement_number", _fake_number)
    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)
    db = _FakeSession()
    with pytest.raises(ValueError) as ei:
        await case_commands.create_movement(db, 7, "out", 8, "2026-10-01")
    assert type(ei.value) is ValueError
    assert str(ei.value) == "库存不足，当前库存: 5"
    assert case_obj.current_stock == 5
    assert db.added == []

    monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", "true")
    db2 = _FakeSession()
    result = await case_commands.create_movement(db2, 7, "out", 8, "2026-10-01")
    assert result["success"] is True
    assert case_obj.current_stock == -3
    assert len(db2.added) == 1  # 只写一条流水（不再有单独的 inventory_log）


async def test_delete_case_movement_denies_and_allows(monkeypatch):
    case_obj = types.SimpleNamespace(id=7, current_stock=5, version=0)
    movement = CaseMovement(case_id=7, direction="in", movement_no="PKIN-1", quantity=8)

    await _patch_case(monkeypatch, case_obj, "_get_case_for_update")
    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)
    db = _FakeSession(movement=movement)
    with pytest.raises(ValueError) as ei:
        await case_commands.delete_movement(db, 1)
    assert type(ei.value) is ValueError
    assert str(ei.value) == "删除该记录后库存不足，无法删除"
    assert case_obj.current_stock == 5
    assert db.deleted == []

    monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", "true")
    movement2 = CaseMovement(case_id=7, direction="in", movement_no="PKIN-2", quantity=8)
    db2 = _FakeSession(movement=movement2)
    assert await case_commands.delete_movement(db2, 1) == {"success": True, "message": "删除成功"}
    assert case_obj.current_stock == -3
    assert len(db2.deleted) == 1


async def test_update_case_movement_quantity_denies_and_allows(monkeypatch):
    case_obj = types.SimpleNamespace(id=7, current_stock=5, version=0)
    movement = CaseMovement(case_id=7, direction="out", movement_no="PKOUT-1", quantity=5)

    await _patch_case(monkeypatch, case_obj, "_get_case_for_update")
    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)
    db = _FakeSession(movement=movement)
    with pytest.raises(ValueError) as ei:
        await case_commands.update_movement(db, 1, {"quantity": 13})
    assert type(ei.value) is ValueError
    assert str(ei.value) == "调整后库存不足，当前库存: -3"
    assert case_obj.current_stock == 5
    assert db.added == []

    monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", "true")
    movement2 = CaseMovement(case_id=7, direction="out", movement_no="PKOUT-2", quantity=5)
    db2 = _FakeSession(movement=movement2)
    await case_commands.update_movement(db2, 1, {"quantity": 13})
    assert case_obj.current_stock == -3
    assert movement2.quantity == 13


# --------------------------------------------------------------------------
# 调用点：batch_import_service.py（错误行进 message，不进异常）
# --------------------------------------------------------------------------
def _patch_batch(monkeypatch, case_obj):
    import fastapi_app.services.batch_import_service as svc
    import fastapi_app.services.batch_service as batch_service

    monkeypatch.setattr(svc, "_validate_xlsx_file", lambda file: None)

    async def _read(file, sheets, msg):
        return ([{"产品名称": "皮套A", "出库数量": 8, "客户名称": "客户甲"}], None)

    monkeypatch.setattr(svc, "_read_excel_sheets", _read)
    monkeypatch.setattr(svc, "parse_date_value", lambda value: None)

    async def _number(db):
        return "PKOUT-B1"

    monkeypatch.setattr(svc, "generate_case_stockout_number", _number)

    async def _find(db, identifier):
        return case_obj, None

    monkeypatch.setattr(batch_service, "find_case_locked", _find)
    return svc


def _fake_upload():
    return types.SimpleNamespace(filename="case_stockouts.xlsx")


async def test_import_case_stockouts_denies_and_allows(monkeypatch):
    case_obj = types.SimpleNamespace(id=7, current_stock=5, version=0)
    _patch_batch(monkeypatch, case_obj)

    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)
    db = _FakeSession()
    blocked = await import_case_stockouts_service(db, _fake_upload())
    assert blocked.success is False
    assert blocked.imported == 0
    # 失败分支（imported == 0）时 _build_batch_result 不回填 skipped（默认 0），
    # 错误文案逐字保留改动前内联判断的写法（"错误: 库存不足，当前库存: 5"）。
    assert blocked.message == "没有成功导入任何皮套出库。错误: 库存不足，当前库存: 5"
    assert case_obj.current_stock == 5
    assert db.added == []

    monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", "true")
    db2 = _FakeSession()
    allowed = await import_case_stockouts_service(db2, _fake_upload())
    assert allowed.success is True
    assert allowed.imported == 1
    assert allowed.skipped == 0
    assert case_obj.current_stock == -3
    assert len(db2.added) == 1  # 只写一条流水


# --------------------------------------------------------------------------
# 静态证明：无残留内联判断 + 统一入口确实被调用
# --------------------------------------------------------------------------
TARGETS = (STOCK_CONCURRENCY, BATCH_IMPORT, CASE_COMMANDS)

# 调用点扫描范围：TARGETS 里除统一入口实现自身之外的文件。
# stock_concurrency.py 是唯一允许比较 .current_stock 的实现文件（P1-6 的 SQL 原子守卫 +
# 竞态兜底判定），故按名从「调用点」扫描中排除；其内部比较由下面的
# test_current_stock_ordering_files_are_exactly_unified_entry_and_threshold 具名豁免，
# 而不是无声跳过。
CALL_SITE_TARGETS = tuple(path for path in TARGETS if path is not STOCK_CONCURRENCY)

# 全仓收敛扫描根（与 t31 的 test_stock_negative_policy_repo_wide.py 同口径）
SERVICE_AND_SHARED_ROOTS = (REPO / "fastapi_app/services", REPO / "fastapi_app/shared")
UNIFIED_ENTRY = STOCK_CONCURRENCY

# 具名豁免：低库存计数用的只读阈值查询（无任何写入路径，不是负库存判定）。
# fastapi_app/services/dashboard/stats.py:208 的 .where(Product.current_stock <= 10)
# 属统计阈值语义，与 t31 的 ALLOWED_RESIDUAL_ORDERING 逐字一致；在本任务写域之外，未改。
DASHBOARD_STATS = REPO / "fastapi_app/services/dashboard/stats.py"
DASHBOARD_STATS_HITS = ["stats.py:208: Product.current_stock <= 10"]
# 2026-10-06 出货校准：可出货量 = min(订单余量, 产品净存量)，此比较为只读阈值（不写库存）
INVENTORY_SERVICE = REPO / "fastapi_app/services/inventory_service.py"

ORDERING_OPS = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)


def _inline_stock_comparisons(path: Path, ops=ORDERING_OPS) -> list:
    """返回文件内仍用「属性 .current_stock 参与序关系比较」的位置。

    只统计 < / <= / > / >=：这类比较即内联负库存判定。等值比较
    （case/commands.py:228 的 current_stock != 0「只能删除库存为0的皮套」）
    不是扣减判定，不属于本任务收敛范围。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and any(isinstance(op, ops) for op in node.ops):
            operands = [node.left, *node.comparators]
            if any(".current_stock" in ast.unparse(op) for op in operands):
                hits.append(f"{path.name}:{node.lineno}: {ast.unparse(node)}")
    return hits


def _iter_service_and_shared() -> list:
    """fastapi_app/services/** 与 fastapi_app/shared/** 下全部非测试 .py 文件。"""
    files = []
    for root in SERVICE_AND_SHARED_ROOTS:
        files.extend(sorted(p for p in root.rglob("*.py") if "tests" not in p.parts))
    return files


def _ordering_hits_by_file() -> dict:
    """{仓库相对路径: [命中源码, ...]}，只列出确有序关系比较的文件。"""
    hits: dict = {}
    for path in _iter_service_and_shared():
        found = _inline_stock_comparisons(path)
        if found:
            hits[path.relative_to(REPO).as_posix()] = found
    return hits


def test_no_inline_current_stock_comparison_left():
    """调用点（batch_import_service / case/commands）不得再有内联序关系判定。"""
    leftovers = [
        hit for path in CALL_SITE_TARGETS for hit in _inline_stock_comparisons(path)
    ]
    assert leftovers == []


def test_current_stock_ordering_files_are_exactly_unified_entry_and_threshold():
    """全仓（services/** + shared/**）只剩统一入口 + 具名豁免的只读阈值会比较 .current_stock。

    豁免项内命中逐字固化，统一入口内的 3 处
    命中（1 处竞态兜底判定 + 2 处 SQL 原子守卫）也逐项固定 —— 任何新增文件、新增比较或
    守卫被悄悄删掉都会让本断言失败。
    2026-10-06 新增豁免：inventory_service 的可出货量实物封顶
    （min(订单余量, 产品净存量)，只读阈值，不写库存），按内容而非行号断言。
    """
    hits = _ordering_hits_by_file()
    assert set(hits) == {
        UNIFIED_ENTRY.relative_to(REPO).as_posix(),
        DASHBOARD_STATS.relative_to(REPO).as_posix(),
        INVENTORY_SERVICE.relative_to(REPO).as_posix(),
    }, hits
    assert hits[DASHBOARD_STATS.relative_to(REPO).as_posix()] == DASHBOARD_STATS_HITS
    unified = hits[UNIFIED_ENTRY.relative_to(REPO).as_posix()]
    assert len(unified) == 3, unified
    assert sum("current_stock + delta >= 0" in hit for hit in unified) == 2, unified
    inv = hits[INVENTORY_SERVICE.relative_to(REPO).as_posix()]
    assert len(inv) == 1 and 'available_quantity' in inv[0] and 'product.current_stock' in inv[0], inv


def test_only_unified_entry_may_compare_current_stock():
    """去掉具名豁免（dashboard 只读阈值 + inventory 出货封顶阈值）后，
    全仓唯一会比较 .current_stock 的文件就是统一入口。"""
    hits = _ordering_hits_by_file()
    residual = set(hits) - {
        DASHBOARD_STATS.relative_to(REPO).as_posix(),
        INVENTORY_SERVICE.relative_to(REPO).as_posix(),
    }
    assert residual == {UNIFIED_ENTRY.relative_to(REPO).as_posix()}, hits


def test_no_remaining_equality_guard_on_current_stock():
    """披露：重写后 case/commands.py 不再有任何 .current_stock 等值比较
    （旧的「只能删除库存为0的皮套」守卫已随删除逻辑一并移除）。"""
    equality = [
        hit
        for path in TARGETS
        for hit in _inline_stock_comparisons(path, ops=(ast.Eq, ast.NotEq))
    ]
    assert equality == []


def test_call_sites_use_unified_entry():
    sc = STOCK_CONCURRENCY.read_text(encoding="utf-8")
    assert "assert_stock_available(product.current_stock, delta)" in sc

    bi = BATCH_IMPORT.read_text(encoding="utf-8")
    assert bi.count("check_stock_available(") == 2  # 两处调用点（import 行无括号）

    cc = CASE_COMMANDS.read_text(encoding="utf-8")
    assert cc.count("assert_stock_available(") == 3  # 三处调用点


def test_targets_import_unified_entry():
    for path in TARGETS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "fastapi_app.shared.stock_concurrency":
                imported.update(alias.name for alias in node.names)
        assert path is STOCK_CONCURRENCY or (
            imported & {"check_stock_available", "assert_stock_available"}
        ), path.name


def test_env_example_declares_policy_key():
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    assert "ALLOW_NEGATIVE_STOCK=false" in [line.strip() for line in lines]


# --------------------------------------------------------------------------
# P1-6 原子守卫随策略（t39）：守卫只在 ALLOW_NEGATIVE_STOCK 为假时附加
# --------------------------------------------------------------------------
class _UpdateCaptureSession:
    """只捕获 UPDATE 语句、报告给定 rowcount 的最小会话替身（持锁写入口用）。"""

    def __init__(self, rowcount=1):
        self.rowcount = rowcount
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _Result(rowcount=self.rowcount)


def _where_clause(stmt) -> str:
    """编译后的 UPDATE ... WHERE 之后的片段（SET current_stock=... 不参与判定）。"""
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert " WHERE " in sql, sql
    return sql.split(" WHERE ", 1)[1]


def _has_atomic_guard(stmt) -> bool:
    """WHERE 里是否带 P1-6 原子非负守卫（current_stock + delta >= 0）。"""
    where = _where_clause(stmt)
    return "current_stock + " in where and ">= 0" in where


async def test_locked_update_guard_is_policy_dependent(monkeypatch):
    """apply_stock_delta_locked：默认（拒绝负库存）带守卫；策略放行时不带。"""
    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)
    product = types.SimpleNamespace(id=1, current_stock=5, version=3)
    db = _UpdateCaptureSession()
    await apply_stock_delta_locked(db, product, -5)
    assert _has_atomic_guard(db.statements[-1]) is True

    monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", "true")
    product2 = types.SimpleNamespace(id=1, current_stock=5, version=3)
    db2 = _UpdateCaptureSession()
    await apply_stock_delta_locked(db2, product2, -5)
    assert _has_atomic_guard(db2.statements[-1]) is False
    assert "current_stock" not in _where_clause(db2.statements[-1])


@pytest.mark.parametrize("raw", ["false", "FALSE", "0", "no", "off", "yes-no"])
async def test_locked_update_guard_present_for_every_falsy_value(monkeypatch, raw):
    monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", raw)
    product = types.SimpleNamespace(id=1, current_stock=5, version=3)
    db = _UpdateCaptureSession()
    await apply_stock_delta_locked(db, product, -5)
    assert _has_atomic_guard(db.statements[-1]) is True


async def test_optimistic_lock_update_guard_is_policy_dependent(monkeypatch):
    """update_stock_with_optimistic_lock（savepoint + 重试路径）同口径。"""
    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)
    db = _FakeLockSession(_fake_product(stock=5, version=3))
    await update_stock_with_optimistic_lock(db, 1, -5)
    assert _has_atomic_guard(db.statements[-1]) is True

    monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", "true")
    db2 = _FakeLockSession(_fake_product(stock=5, version=3))
    await update_stock_with_optimistic_lock(db2, 1, -5)
    assert _has_atomic_guard(db2.statements[-1]) is False
    assert "current_stock" not in _where_clause(db2.statements[-1])
