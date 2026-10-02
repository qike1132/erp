"""P1-2b 全仓负库存变更点统一入口回归测试（t31 收敛的 11 处内联判定）。

背景：t14 已把 stock_concurrency.py / batch_import_service.py / case/commands.py 三处
收敛到统一入口；本文件覆盖 t31 收敛的另外 8 个 service 文件内的 11 处历史内联负库存
判定。契约（.agent-teams/erp-p0-hardening/team.json 的 t31）四类断言：

1) 逐站判定：负向路径必须经 check_stock_available / assert_stock_available；
   「不适用」（纯增量）站点保留原行为，并在 DOCUMENTED_WRITES 静态清单里逐个列明；
2) 静态证明：8 个文件内不存在 `*.current_stock` 参与的序关系比较（< <= > >=）；
   等值守卫单列披露（本批文件内为 0 处；全仓仅剩 case/commands.py:228 的
   `case_obj.current_stock != 0`，属 t14 写域且不是扣减判定）；
3) 默认（未设 ALLOW_NEGATIVE_STOCK）行为与改动前逐字一致：异常类型 ValueError、
   文案逐字、返回 dict 语义、以及「先回减累计退货量再判定」这类既有语句顺序不变；
4) ALLOW_NEGATIVE_STOCK=true 时同一批路径放行（覆盖 5 个代表性站点，
   check 分支与 assert 分支各有覆盖）。

静态判定说明：统一入口的调用本身形如
`check_stock_available(product.current_stock, -qty) is not None`，该 Compare 的操作数
文本里同样含 `.current_stock`，所以本文件用「跳过 Call 子树」的判定；若沿用 t14 的宽松
文本判定（ast.unparse 后子串匹配）会把这 11 处新调用点误报为残留内联判定。

5) t42（t26-F-02 修复）补齐两类漏检：① 同一函数内由 .current_stock 派生的局部变量参与序关系
   比较（先 new_current_stock = product.current_stock + delta，再 if new_current_stock < 0）
   ——旧判定只认 ast.Attribute，漏检 ast.Name；② 对 *.current_stock 的普通赋值（ast.Assign），
   旧写检测只收 ast.AugAssign。两类都配 synthetic snippet 灵敏度控制（含则该命中、不含则不
   命中），并用 negative control 证明旧判定确实漏检。
"""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services import product_service, stock_in_service, stock_out_service, stock_return_service
from fastapi_app.shared.stock_concurrency import (
    assert_stock_available,
    check_stock_available,
)

REPO = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# 写域清单（t31 inScope 的 8 个 py 文件）
# ---------------------------------------------------------------------------
IN_SCOPE_FILES = (
    "fastapi_app/services/approval_service.py",
    "fastapi_app/services/batch_import_core.py",
    "fastapi_app/services/ocr/_import.py",
    "fastapi_app/services/order/commands.py",
    "fastapi_app/services/staging/stockout.py",
    "fastapi_app/services/stock_in_service.py",
    "fastapi_app/services/stock_out_service.py",
    "fastapi_app/services/stock_return_service.py",
)

# 每个文件期望的统一入口调用点数量（AST 统计 Call 节点，合计 11 处）
EXPECTED_CALL_SITES = {
    # 删除订单：直写前的净变化量判定
    "fastapi_app/services/approval_service.py": {"assert_stock_available": 1},
    # 出货导入：按行静默跳过（返回 False）
    "fastapi_app/services/batch_import_core.py": {"check_stock_available": 1},
    # OCR 出货导入：只产出暂存行校验结论，不抛异常
    "fastapi_app/services/ocr/_import.py": {"check_stock_available": 1},
    # 删除订单（order 域）：直写前的净变化量判定
    "fastapi_app/services/order/commands.py": {"assert_stock_available": 1},
    # 暂存出货确认：for 循环 + begin_nested 内抛 ValueError
    "fastapi_app/services/staging/stockout.py": {"assert_stock_available": 1},
    # 删除入库（-stockin.quantity）／修改入库数量（quantity - old_quantity）
    "fastapi_app/services/stock_in_service.py": {"assert_stock_available": 2},
    # 创建出库（-quantity）／修改出库（净出货量之差）／批量出库（返回 error dict）
    "fastapi_app/services/stock_out_service.py": {
        "assert_stock_available": 2,
        "check_stock_available": 1,
    },
    # 删除退货（-stockreturn.quantity）
    "fastapi_app/services/stock_return_service.py": {"assert_stock_available": 1},
}

# 8 个文件内所有 `*.current_stock += / -=` 直写的静态台账（按文件路径分组）。
# 每一条都标注了它是「纯增量（不适用本任务）」还是「写入侧（负向由统一入口覆盖）」。
DOCUMENTED_WRITES = {
    "fastapi_app/services/approval_service.py": [
        # 写入侧：net_change 可正可负，负向由同函数内 assert_stock_available 覆盖
        "product.current_stock += net_change",
    ],
    "fastapi_app/services/order/commands.py": [
        # 写入侧：total_deducted 可正可负，负向由同函数内 assert_stock_available 覆盖
        "product.current_stock += total_deducted",
    ],
    "fastapi_app/services/batch_import_core.py": [
        # 备货导入：qty 由 _parse_positive_quantity(label=备货) 保证 >0，纯增量
        "locked_product.current_stock += qty",
        # 出货导入写入侧：同一 _row_handler 内已由 check_stock_available 判定覆盖
        "locked_product.current_stock -= qty",
    ],
    # ↑ 2026-10-02 P0 审计修复：原本这里还有一条「订单导入」的 `locked_product.current_stock += qty`，
    #   已删除 —— 订单不该影响物理库存（create_order / order_batch_create /
    #   import_orders_service 三条下单路径都不改），那一行疑为备货模板复制漏删。
    "fastapi_app/services/ocr/_import.py": [],
    "fastapi_app/services/staging/stockout.py": [],
    # ↑ 2026-10-02 P0 审计修复：原有的一处 `product.current_stock -= staging.quantity`
    #   已改走 apply_stock_delta_locked（带 version 守卫并递增 version）。
    "fastapi_app/services/stock_in_service.py": [],
    # ↑ 2026-10-02 P0 审计修复：原有三处直写（create_stockin_core 的 `+= quantity`、
    #   update_stockin_core 的 `+= quantity - old_quantity`、delete_stockin_core 的
    #   `-= stockin.quantity`）已全部改走 `apply_stock_delta_locked`。
    #   原因：直写不递增 `version`（Product 无 version_id_col），与走乐观锁的写入口并发时
    #   对方会以陈旧快照覆盖本处写入 → 丢失更新。列入台账是「已登记」，改走统一入口是「已消除」。
    "fastapi_app/services/stock_out_service.py": [],
    "fastapi_app/services/stock_return_service.py": [],
}

# 台账里「可能把库存写成负数」的写入（负号直写或带符号增量），必须有统一入口前置判定
RISKY_WRITES = frozenset({
    "product.current_stock += net_change",
    "product.current_stock += total_deducted",
    "product.current_stock += quantity - old_quantity",
    "product.current_stock -= staging.quantity",
    "product.current_stock -= stockin.quantity",
    "locked_product.current_stock -= qty",
})

# 2026-10-02 P3 审计：把 fastapi_app/tasks 纳入扫描。
# 原白名单只含 services/shared，导致 tasks/batch_tasks.py 的
# `product.current_stock += quantity`（不递增 version，与乐观锁写路径并发会丢失更新）
# 从未被本门禁覆盖。该处已改走 apply_stock_delta_locked，纳入后无新增残留。
SERVICE_AND_SHARED_ROOTS = ("fastapi_app/services", "fastapi_app/shared", "fastapi_app/tasks")

# t39（janitor）写域：P1-6 原子守卫与 ALLOW_NEGATIVE_STOCK 的互斥由它统一处理，
# 本文件对它内部的序关系比较不作断言。
EXEMPT_FROM_RESIDUAL_SCAN = frozenset({"fastapi_app/shared/stock_concurrency.py"})

# 允许残留（非负库存判定）的序关系比较：文件 -> 说明
ALLOWED_RESIDUAL_ORDERING = {
    "fastapi_app/services/dashboard/stats.py":
        "低库存阈值查询 Product.current_stock <= 10（只是统计阈值，不是负库存判定）",
}

# 普通赋值（ast.Assign）直写 *.current_stock 的静态台账（t42 补齐的漏检类别 ②）。
# 这些写入本身不是「负库存判定」——判定点已收口到统一入口（assert/check_stock_available），
# 写入发生在行锁（product_service）或统一入口自身的原子 UPDATE（stock_concurrency）之内。
DOCUMENTED_PLAIN_ASSIGN_WRITES = {
    "fastapi_app/services/product_service.py": [
        # update_product：:268 get_product_for_update 持 FOR UPDATE 行锁，
        # 负向判定已收口到 assert_stock_available；此处只把差额落到内存对象。
        "product.current_stock = new_current_stock",
    ],
    "fastapi_app/shared/stock_concurrency.py": [
        # apply_stock_delta_locked：原子 UPDATE 成功后同步内存对象（t39 语义未动）
        "product.current_stock = new_stock",
    ],
}

ORDERING_OPS = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)


def _source(rel_path: str) -> str:
    return (REPO / rel_path).read_text(encoding="utf-8")


def _tree(rel_path: str) -> ast.Module:
    return ast.parse(_source(rel_path), filename=rel_path)


def _direct_current_stock(node: ast.AST) -> bool:
    """操作数是否直接读取 .current_stock（且不位于函数调用实参里）。

    跳过 Call 子树：`check_stock_available(product.current_stock, -qty) is not None`
    这类统一入口调用不是内联判定。
    """
    if isinstance(node, ast.Call):
        return False
    if isinstance(node, ast.Attribute) and node.attr == "current_stock":
        return True
    return any(_direct_current_stock(child) for child in ast.iter_child_nodes(node))


def _references_current_stock(node: ast.AST) -> bool:
    """子树里是否读取了 .current_stock（含作为统一入口实参的情形，仅用于「派生」判定）。"""
    return any(
        isinstance(child, ast.Attribute) and child.attr == "current_stock"
        for child in ast.walk(node)
    )


def _derived_current_stock_names(func: ast.AST | None) -> set[str]:
    """函数作用域内由 .current_stock 派生的局部变量名（t42 补齐的漏检类别 ①）。

    旧式写法把判定拆成两步，比较的操作数是 ast.Name 而不是 ast.Attribute：
        new_current_stock = product.current_stock + stock_change
        if new_current_stock < 0: ...
    只认 Attribute 的 _direct_current_stock 对这类写法静默漏检。
    """
    if func is None:
        return set()
    names: set[str] = set()
    for node in ast.walk(func):
        value: ast.AST | None = None
        targets: list[ast.AST] = []
        if isinstance(node, ast.Assign):
            value, targets = node.value, list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            value, targets = node.value, [node.target]
        if value is None or not _references_current_stock(value):
            continue
        for target in targets:
            names.update(child.id for child in ast.walk(target) if isinstance(child, ast.Name))
    return names


def _compare_hits(tree: ast.Module, ops=ORDERING_OPS) -> list[tuple[int, str]]:
    """[(lineno, 源码)]：.current_stock 或其派生局部变量参与该组比较的位置。"""
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    derived_cache: dict[int, set[str]] = {}

    def enclosing_function(node: ast.AST) -> ast.AST | None:
        cursor = parents.get(node)
        while cursor is not None:
            if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return cursor
            cursor = parents.get(cursor)
        return None

    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Compare) and any(isinstance(op, ops) for op in node.ops)):
            continue
        func = enclosing_function(node)
        key = id(func)
        if key not in derived_cache:
            derived_cache[key] = _derived_current_stock_names(func)
        derived = derived_cache[key]
        operands = [node.left, *node.comparators]
        if any(_direct_current_stock(operand) for operand in operands) or any(
            isinstance(operand, ast.Name) and operand.id in derived for operand in operands
        ):
            hits.append((node.lineno, ast.unparse(node)))
    return hits


def _ordering_hits(source: str, filename: str, ops=ORDERING_OPS) -> list[str]:
    """源码文本内仍在做「.current_stock 或其派生局部变量参与该组比较」的位置。

    同时供真实仓库扫描与 synthetic snippet 灵敏度控制复用。
    """
    return [
        f"{filename}:{lineno}: {text}"
        for lineno, text in _compare_hits(ast.parse(source, filename=filename), ops)
    ]


def _inline_stock_comparisons(path: Path, ops=ORDERING_OPS) -> list[str]:
    """文件内仍在做「.current_stock 参与该组比较运算」的位置（rel:line: 源码）。"""
    rel = path.relative_to(REPO).as_posix() if path.is_absolute() else path.as_posix()
    return _ordering_hits(path.read_text(encoding="utf-8"), rel, ops)


def _unified_calls(rel_path: str) -> dict[str, int]:
    """{统一入口函数名: Call 节点数}。"""
    found: dict[str, int] = {}
    for node in ast.walk(_tree(rel_path)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("check_stock_available", "assert_stock_available"):
                found[node.func.id] = found.get(node.func.id, 0) + 1
    return found


def _current_stock_writes_from_source(source: str) -> list[tuple[str, str]]:
    """[(kind, 源码)]，kind 取 augassign / assign：对 *.current_stock 的直写。

    t42 补齐的漏检类别 ②：普通赋值（ast.Assign）此前完全没进检测（只收 ast.AugAssign）。
    """
    hits: list[tuple[str, str]] = []
    for node in ast.walk(ast.parse(source)):
        target: ast.AST | None = None
        kind = ""
        if isinstance(node, ast.AugAssign):
            target, kind = node.target, "augassign"
        elif isinstance(node, ast.Assign):
            target = next(
                (
                    candidate
                    for candidate in node.targets
                    if isinstance(candidate, ast.Attribute) and candidate.attr == "current_stock"
                ),
                None,
            )
            kind = "assign"
        if isinstance(target, ast.Attribute) and target.attr == "current_stock":
            hits.append((kind, ast.unparse(node)))
    return hits


def _current_stock_writes(rel_path: str) -> list[str]:
    """AugAssign + 普通 Assign 两类直写的并集（用于逐条台账比对）。"""
    return sorted(text for _, text in _current_stock_writes_from_source(_source(rel_path)))


def _plain_assign_writes(rel_path: str) -> list[str]:
    """只含普通赋值（ast.Assign）的 *.current_stock 直写（t42 漏检类别 ②）。"""
    return sorted(
        text
        for kind, text in _current_stock_writes_from_source(_source(rel_path))
        if kind == "assign"
    )


def _iter_py(roots) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        files.extend(sorted(p for p in (REPO / root).rglob("*.py") if "tests" not in p.parts))
    return files


# ---------------------------------------------------------------------------
# 2) 静态证明：无残留内联序关系判定
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rel_path", IN_SCOPE_FILES)
def test_no_inline_current_stock_ordering_comparison_left(rel_path):
    """11 处站点全部改走统一入口后，8 个文件内不应再有 < <= > >= 内联判定。"""
    assert _inline_stock_comparisons(REPO / rel_path) == []


@pytest.mark.parametrize("rel_path", IN_SCOPE_FILES)
def test_no_equality_guard_in_scope_files(rel_path):
    """等值守卫单列披露：本批 8 个文件内 0 处（全仓仅剩 case/commands.py:228）。"""
    assert _inline_stock_comparisons(REPO / rel_path, ops=(ast.Eq, ast.NotEq)) == []


def test_services_and_shared_residual_ordering_is_only_the_documented_threshold():
    """services/** 与 shared/** 内除 stock_concurrency.py 外，序关系比较只剩统计阈值。"""
    residuals: dict[str, list[str]] = {}
    for path in _iter_py(SERVICE_AND_SHARED_ROOTS):
        rel = path.relative_to(REPO).as_posix()
        if rel in EXEMPT_FROM_RESIDUAL_SCAN:
            continue
        hits = _inline_stock_comparisons(path)
        if hits:
            residuals[rel] = hits
    assert set(residuals) == set(ALLOWED_RESIDUAL_ORDERING), residuals
    for rel, why in ALLOWED_RESIDUAL_ORDERING.items():
        assert rel in residuals, why


def test_plain_assignment_current_stock_writes_are_documented():
    """t42 漏检类别 ②：普通赋值（ast.Assign）直写也必须逐条进台账，不得静默新增。"""
    residuals: dict[str, list[str]] = {}
    for path in _iter_py(SERVICE_AND_SHARED_ROOTS):
        rel = path.relative_to(REPO).as_posix()
        hits = _plain_assign_writes(rel)
        if hits:
            residuals[rel] = hits
    assert set(residuals) == set(DOCUMENTED_PLAIN_ASSIGN_WRITES), residuals
    for rel, expected in DOCUMENTED_PLAIN_ASSIGN_WRITES.items():
        assert residuals[rel] == sorted(expected), rel


# ---------------------------------------------------------------------------
# 3) 灵敏度控制（t42）：synthetic snippet 反证 —— 含该写法必命中、不含必不命中
# ---------------------------------------------------------------------------
SYNTH_DERIVED_LOCAL_COMPARISON = """def adjust(product, stock_change):
    new_current_stock = product.current_stock + stock_change
    if new_current_stock < 0:
        return new_current_stock
"""

SYNTH_DIRECT_ATTRIBUTE_COMPARISON = """def low(product):
    return product.current_stock <= 10
"""

SYNTH_CLEAN_UNIFIED_ENTRY = """def adjust(product, stock_change):
    assert_stock_available(product.current_stock, stock_change)
    new_current_stock = product.current_stock + stock_change
    product.current_stock = new_current_stock
"""

SYNTH_EQUALITY_IS_NOT_ORDERING = """def guard(case_obj):
    return case_obj.current_stock != 0
"""

SYNTH_PLAIN_ASSIGN_WRITE = """def adjust(product, new_stock):
    product.current_stock = new_stock
"""

SYNTH_AUGASSIGN_WRITE = """def adjust(product, qty):
    product.current_stock -= qty
"""

SYNTH_NO_WRITE = """def read(product):
    return product.current_stock
"""


def test_sensitivity_derived_local_comparison_is_detected():
    assert _ordering_hits(SYNTH_DERIVED_LOCAL_COMPARISON, "synth.py") == [
        "synth.py:3: new_current_stock < 0"
    ]


def test_sensitivity_direct_attribute_comparison_is_detected():
    assert _ordering_hits(SYNTH_DIRECT_ATTRIBUTE_COMPARISON, "synth.py") == [
        "synth.py:2: product.current_stock <= 10"
    ]


def test_sensitivity_clean_unified_entry_snippet_is_not_flagged():
    """negative control：不含该写法必须不命中（统一入口调用与纯派生局部变量都不算）。"""
    assert _ordering_hits(SYNTH_CLEAN_UNIFIED_ENTRY, "synth.py") == []


def test_sensitivity_equality_guard_is_not_an_ordering_hit():
    assert _ordering_hits(SYNTH_EQUALITY_IS_NOT_ORDERING, "synth.py") == []


def test_sensitivity_write_detection_covers_both_forms():
    assert _current_stock_writes_from_source(SYNTH_PLAIN_ASSIGN_WRITE) == [
        ("assign", "product.current_stock = new_stock")
    ]
    assert _current_stock_writes_from_source(SYNTH_AUGASSIGN_WRITE) == [
        ("augassign", "product.current_stock -= qty")
    ]
    assert _current_stock_writes_from_source(SYNTH_NO_WRITE) == []


def test_sensitivity_control_proves_the_legacy_gap():
    """negative control：旧判定对这两类写法必然漏检，新判定命中（证明补的是真漏检）。"""
    tree = ast.parse(SYNTH_DERIVED_LOCAL_COMPARISON)
    compare = next(node for node in ast.walk(tree) if isinstance(node, ast.Compare))
    assert _direct_current_stock(compare.left) is False
    assert _ordering_hits(SYNTH_DERIVED_LOCAL_COMPARISON, "synth.py")
    assert [
        node
        for node in ast.walk(ast.parse(SYNTH_PLAIN_ASSIGN_WRITE))
        if isinstance(node, ast.AugAssign)
    ] == []
    assert _current_stock_writes_from_source(SYNTH_PLAIN_ASSIGN_WRITE)


# ---------------------------------------------------------------------------
# 1) 逐站判定：调用点数量 + 写点台账
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rel_path", IN_SCOPE_FILES)
def test_call_sites_use_unified_entry(rel_path):
    assert _unified_calls(rel_path) == EXPECTED_CALL_SITES[rel_path]


def test_total_call_sites_is_eleven():
    total = sum(count for site in EXPECTED_CALL_SITES.values() for count in site.values())
    assert total == 11
    assert sum(sum(_unified_calls(rel).values()) for rel in IN_SCOPE_FILES) == 11


@pytest.mark.parametrize("rel_path", IN_SCOPE_FILES)
def test_in_scope_files_import_unified_entry(rel_path):
    imported: set[str] = set()
    for node in ast.walk(_tree(rel_path)):
        if (isinstance(node, ast.ImportFrom)
                and node.module == "fastapi_app.shared.stock_concurrency"):
            imported.update(alias.name for alias in node.names)
    assert imported & {"check_stock_available", "assert_stock_available"}, rel_path


@pytest.mark.parametrize("rel_path", IN_SCOPE_FILES)
def test_remaining_current_stock_writes_are_documented(rel_path):
    """剩下的直写必须逐条进台账（纯增量「不适用」或写入侧「负向已被覆盖」）。"""
    assert _current_stock_writes(rel_path) == sorted(DOCUMENTED_WRITES[rel_path])


def test_risky_writes_all_sit_behind_unified_entry():
    for rel_path in IN_SCOPE_FILES:
        writes = set(_current_stock_writes(rel_path))
        if writes & RISKY_WRITES:
            assert sum(_unified_calls(rel_path).values()) >= 1, rel_path


def test_update_stockin_core_is_only_called_by_the_wrapper():
    """update_stockin_core 的写入侧之所以由包装层守卫覆盖，前提是唯一调用方即包装层。"""
    callers: list[tuple[str, str]] = []
    for path in _iter_py(("fastapi_app",)):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "update_stockin_core"):
                for parent in ast.walk(tree):
                    if (isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and any(child is node for child in ast.walk(parent))):
                        callers.append((path.relative_to(REPO).as_posix(), parent.name))
                        break
    assert callers == [("fastapi_app/services/stock_in_service.py", "update_stockin")]


# ---------------------------------------------------------------------------
# 最小替身：只实现负库存判定路径触及的 AsyncSession 成员
# ---------------------------------------------------------------------------
class _FakeResult:
    def __init__(self, scalar=None, rowcount: int = 1):
        self._scalar = scalar
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self._scalar


class _FakeSession:
    def __init__(self, *scalars):
        self.info: dict = {}
        self.refreshed = False
        self._scalars = list(scalars)
        self.added: list = []
        self.deleted: list = []
        self.flushes = 0

    async def execute(self, *args, **kwargs):
        return _FakeResult(self._scalars.pop(0) if self._scalars else None)

    async def get(self, *args, **kwargs):
        return None

    def add(self, obj) -> None:
        self.added.append(obj)

    async def delete(self, obj) -> None:
        self.deleted.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def refresh(self, obj) -> None:
        self.refreshed = True

    class _Nested:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc_info):
            return False

    def begin_nested(self):
        return _FakeSession._Nested()


def _deny_env(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)


# ---------------------------------------------------------------------------
# 3) + 4) 五个代表性站点的双分支运行时证据
# ---------------------------------------------------------------------------
async def test_create_stockout_core_denies_then_policy_releases(monkeypatch):
    """站点 8：assert 分支 + 抛 ValueError（文案逐字）。"""
    _deny_env(monkeypatch)
    product = SimpleNamespace(current_stock=5)
    db = _FakeSession()
    info = {"available_quantity": 0, "order_quantity": 0, "shipped_quantity": 0, "orders": []}
    with patch("fastapi_app.services.stock_service.get_product_for_update",
               new_callable=AsyncMock, return_value=product), patch(
        "fastapi_app.services.stock_service.calculate_available_shipment_quantity",
        new_callable=AsyncMock, return_value=info,
    ) as calc:
        with pytest.raises(ValueError) as ei:
            await stock_out_service.create_stockout_core(db, 1, 8, "客户A", None, "")
        assert str(ei.value) == "库存不足！"
        calc.assert_not_awaited()  # 守卫先于任何后续校验/写入
        assert db.added == []

        monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", "true")
        with pytest.raises(ValueError) as ei2:
            await stock_out_service.create_stockout_core(db, 1, 8, "客户A", None, "")
        # 策略放行后越过库存守卫，落到下一道业务校验（可用订单量）——
        # 即守卫确实不再拦截，且后续错误文案与改动前一致
        assert str(ei2.value) == "该客户没有可用的订单支持出货！请先创建订单。"
        calc.assert_awaited()


async def test_batch_stockout_item_denies_with_historic_message_then_releases(monkeypatch):
    """站点 10：check 分支 + 返回 success/error 字典（拒绝文案逐字）。"""
    _deny_env(monkeypatch)
    deny_product = MagicMock()
    deny_product.id = 1
    deny_product.current_stock = 5
    deny_product.version = 1
    with patch("fastapi_app.services.stock_service.get_product_for_update",
               new_callable=AsyncMock, return_value=deny_product):
        denied = await stock_out_service._process_single_stockout(
            _FakeSession(), {"product_id": 1, "customer": "客户A", "quantity": 10, "id": "t-2"},
        )
    assert denied == {"success": False, "error": "库存不足，当前库存: 5", "id": "t-2"}
    assert deny_product.current_stock == 5

    monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", "true")
    allow_product = MagicMock()
    allow_product.id = 1
    allow_product.current_stock = 5
    allow_product.version = 1
    info = {"available_quantity": 10, "order_quantity": 10, "shipped_quantity": 0, "orders": []}
    db = _FakeSession()
    with patch("fastapi_app.services.stock_service.get_product_for_update",
               new_callable=AsyncMock, return_value=allow_product), patch(
        "fastapi_app.services.stock_service.calculate_available_shipment_quantity",
        new_callable=AsyncMock, return_value=info,
    ), patch("fastapi_app.services.stock_service.log_inventory_change"):
        released = await stock_out_service._process_single_stockout(
            db, {"product_id": 1, "customer": "客户A", "quantity": 10, "id": "t-2"},
        )
    assert released["success"] is True
    assert released["id"] == "t-2"
    assert allow_product.current_stock == -5  # 策略打开时允许扣成负数（P1-6 SQL 守卫归 t39）


async def test_delete_stockin_core_message_verbatim_then_releases(monkeypatch):
    """站点 6：assert 分支 + 含产品名的长文案逐字保留。"""
    _deny_env(monkeypatch)
    stockin = SimpleNamespace(stockin_stockouts=[], quantity=5, product_id=1, id=7)
    # id/version 是 2026-10-02 起必需的：该路径的写入已改走 apply_stock_delta_locked，
    # 它以 `WHERE id = ? AND version = 旧值` 更新并递增 version（原先直写两者都不需要）。
    product = SimpleNamespace(current_stock=3, name="测试产品", id=1, version=1)
    db = _FakeSession()
    with patch("fastapi_app.services.stock_service.get_product_for_update",
               new_callable=AsyncMock, return_value=product), patch(
        "fastapi_app.services.stock_service.log_inventory_change"):
        with pytest.raises(ValueError) as ei:
            await stock_in_service.delete_stockin_core(db, stockin)
        assert str(ei.value) == (
            "删除入库记录将导致库存为负数（产品：测试产品，当前库存：3，入库数量：5）"
        )
        assert product.current_stock == 3
        assert db.deleted == []

        monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", "true")
        await stock_in_service.delete_stockin_core(db, stockin)
    assert product.current_stock == -2
    assert db.deleted == [stockin]


async def test_update_stockin_wrapper_delta_guard_then_releases(monkeypatch):
    """站点 7：assert 分支（增量 quantity - old_quantity）在包装层拦截写入。"""
    _deny_env(monkeypatch)
    stockin_obj = SimpleNamespace(
        id=7, product_id=1, quantity=5, stockin_no="SI-2026-0001",
        stockin_date=None, stockin_stockouts=[],
    )
    product = SimpleNamespace(current_stock=1, name="测试产品")
    with patch("fastapi_app.services.stock_service.get_product_for_update",
               new_callable=AsyncMock, return_value=product), patch(
        "fastapi_app.services.stock_in_service.update_stockin_core",
        new_callable=AsyncMock,
    ) as core, patch("fastapi_app.services.stock_in_service.cache_mgr",
                     MagicMock(invalidate_stock_and_order=AsyncMock())), patch(
        "fastapi_app.services.stock_in_service.schedule_post_commit_invalidation",
    ):
        with pytest.raises(ValueError) as ei:
            await stock_in_service.update_stockin(
                # 第一个标量是「无锁读 product_id」的结果，第二个才是 WITH FOR UPDATE
                # 取到的入库行（顺序即 SQL 执行顺序）
                _FakeSession(stockin_obj.product_id, stockin_obj), 7, quantity=2,
                customer="客户A", stockin_date_str="2026-10-01", note="",
            )
        assert str(ei.value) == (
            "修改入库数量将导致库存为负数（产品：测试产品，当前库存：1，变更量：-3）"
        )
        core.assert_not_awaited()  # 守卫拦住 => 真实写点未被调用
        assert product.current_stock == 1

        monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", "true")
        await stock_in_service.update_stockin(
            _FakeSession(stockin_obj.product_id, stockin_obj), 7, quantity=2,
            customer="客户A", stockin_date_str="2026-10-01", note="",
        )
        core.assert_awaited_once()


async def test_delete_stockreturn_core_message_verbatim_then_releases(monkeypatch):
    """站点 11：assert 分支；并固化「先回减累计退货量、后判定」的既有语句顺序。"""
    _deny_env(monkeypatch)
    stockreturn = SimpleNamespace(
        stockout_id=1, quantity=2, product_id=1, id=9, order_id=None, customer="客户A")
    stockout = SimpleNamespace(id=1, returned_quantity=2)
    product = SimpleNamespace(current_stock=1, name="测试产品")
    stockreturn_release = SimpleNamespace(
        stockout_id=1, quantity=2, product_id=1, id=10, order_id=None, customer="客户A")
    stockout_release = SimpleNamespace(id=1, returned_quantity=2)
    with patch("fastapi_app.services.stock_service.get_product_for_update",
               new_callable=AsyncMock, return_value=product), patch(
        "fastapi_app.services.stock_service.log_inventory_change"), patch(
        "fastapi_app.services.stock_return_service.update_stock_with_optimistic_lock",
        new_callable=AsyncMock,
    ) as upd:
        with pytest.raises(ValueError) as ei:
            await stock_return_service.delete_stockreturn_core(
                _FakeSession(stockout), stockreturn,
            )
        assert str(ei.value) == "删除退货将导致库存为负数（当前库存：1，退货数量：2）"
        upd.assert_not_awaited()
        assert product.current_stock == 1
        # 与改动前逐字一致：回减发生在守卫之前（异常后不提交，故无副作用）
        assert stockout.returned_quantity == 0

        monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", "true")
        await stock_return_service.delete_stockreturn_core(
            _FakeSession(stockout_release), stockreturn_release,
        )
        upd.assert_awaited_once()
        assert product.current_stock == 1  # 真实写入口已被替换为替身，库存不变


# ---------------------------------------------------------------------------
# 统一入口本身的默认语义（本批站点全部依赖它，故在文件内复核一次）
# ---------------------------------------------------------------------------
def test_unified_entry_defaults_to_deny_and_message_is_verbatim(monkeypatch):
    _deny_env(monkeypatch)
    assert check_stock_available(3, -5) == "库存不足！当前库存: 3，需要: 5"
    assert check_stock_available(3, -3) is None
    assert check_stock_available(0, 10) is None
    with pytest.raises(ValueError):
        assert_stock_available(3, -5)
    assert check_stock_available(3, -5, message="自定义文案") == "自定义文案"


def test_unified_entry_releases_when_policy_truthy(monkeypatch):
    monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", "true")
    assert check_stock_available(3, -5) is None
    assert_stock_available(3, -5)  # 不抛异常即为放行

# ---------------------------------------------------------------------------
# 5) t42 修复站点：product_service.update_product 的判定收口到统一入口
# ---------------------------------------------------------------------------
class _T42Product:
    """update_product 触及的最小产品替身（含 to_dict）。"""

    def __init__(self, *, current_stock: int, initial_stock: int):
        self.id = 7
        self.name = "T42-测试产品"
        self.barcode = None
        self.price = None
        self.image = None
        self.factory = None
        self.version = 0
        self.current_stock = current_stock
        self.initial_stock = initial_stock

    def to_dict(self) -> dict:
        return {"id": self.id, "current_stock": self.current_stock}


async def _t42_update_product(product, new_initial_stock: int):
    """调用 update_product；行锁、缓存失效、post-commit 回调一律以替身替代。"""
    with patch("fastapi_app.services.product_service.get_product_for_update",
               new_callable=AsyncMock, return_value=product), patch(
        "fastapi_app.services.product_service.cache_mgr",
        MagicMock(invalidate=AsyncMock()),
    ), patch("fastapi_app.services.product_service._schedule_post_commit"):
        return await product_service.update_product(
            _FakeSession(), product.id, None, None, None, new_initial_stock,
        )


async def test_update_product_negative_stock_is_denied_by_unified_entry(monkeypatch):
    """缺省策略：仍抛 ValueError，且文案与改动前逐字一致（初始库存 10 改 3 ⇒ 调整量 -7）。"""
    _deny_env(monkeypatch)
    product = _T42Product(current_stock=5, initial_stock=10)
    with pytest.raises(ValueError) as ei:
        await _t42_update_product(product, 3)
    assert str(ei.value) == "初始库存调整将导致当前库存为负数（当前库存：5，调整量：-7）"
    assert product.current_stock == 5
    assert product.initial_stock == 10


@pytest.mark.parametrize("truthy", ["true", "1", "yes", "on"])
async def test_update_product_negative_stock_released_when_policy_truthy(monkeypatch, truthy):
    """策略为真值时不再硬拒（替身级证据：真实库受 CHECK 约束，无法持久化负值）。"""
    monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", truthy)
    product = _T42Product(current_stock=5, initial_stock=10)
    result = await _t42_update_product(product, 3)
    assert product.current_stock == -2
    assert product.initial_stock == 3
    assert result == {"id": 7, "current_stock": -2}

