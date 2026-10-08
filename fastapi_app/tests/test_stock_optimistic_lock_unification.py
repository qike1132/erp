"""P1-3 扣减统一乐观锁：写点收敛证明 + 冲突语义 + 批量路径零回归。

覆盖四类断言：
1) 静态证明（ast + 文本）：四个 service 文件内不存在对 current_stock 的 += / -= 直写；
   每个历史写点都改调统一入口 —— 未持锁路径 update_stock_with_optimistic_lock，
   已持锁的批量路径 apply_stock_delta_locked。
2) 未持锁入口 update_stock_with_optimistic_lock：SET/WHERE 均带 version；version 冲突时
   逐轮回滚 savepoint 并重试，耗尽后抛既有 StockConcurrentError（ConflictError 子类），
   且不整体 rollback 外层事务（事务中其他修改保留）。
3) 持锁入口 apply_stock_delta_locked：单次写入、不开 savepoint；version 未命中抛
   StockConcurrentError；成功后 current_stock / version 同步到内存对象。
4) 批量出库 _process_single_stockout 端到端：库存数量语义不变，且仍无嵌套事务。
"""
import ast
import inspect
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import sqlite

from fastapi_app.core.exceptions import ConflictError
from fastapi_app.services import stock_out_service
from fastapi_app.shared.stock_concurrency import (
    MAX_RETRY,
    StockConcurrentError,
    apply_stock_delta_locked,
    update_stock_with_optimistic_lock,
)
from fastapi_app.shared_models import Product

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _default_inventory_balance():
    """库存结余闸门（2026-10-07）默认充足，使本文件聚焦乐观锁语义。"""
    with patch(
        "fastapi_app.services.stock_service.get_inventory_balance",
        new_callable=AsyncMock, return_value=10**9,
    ):
        yield

_SERVICE_FILES = (
    "fastapi_app/services/order/deduction.py",
    "fastapi_app/services/order_deduction_service.py",
    "fastapi_app/services/stock_out_service.py",
    "fastapi_app/services/stock_return_service.py",
)

_UNIFIED_ENTRIES = frozenset({
    "update_stock_with_optimistic_lock",
    "apply_stock_delta_locked",
})

# 每个历史写点所在函数 → 期望调用的统一入口（顺序即源码顺序）
_EXPECTED_CALL_SITES = {
    "fastapi_app/services/order/deduction.py": {
        "_increase_deduction": ["update_stock_with_optimistic_lock"],
        "_decrease_deduction": [
            "update_stock_with_optimistic_lock",
            "update_stock_with_optimistic_lock",
        ],
    },
    "fastapi_app/services/order_deduction_service.py": {
        "process_order_deduction": ["update_stock_with_optimistic_lock"],
    },
    "fastapi_app/services/stock_out_service.py": {
        "create_stockout_core": ["update_stock_with_optimistic_lock"],
        "update_stockout_core": ["update_stock_with_optimistic_lock"],
        "delete_stockout_core": ["update_stock_with_optimistic_lock"],
        # 批量路径：调用方已持行锁，且既有不变式是“自包含、无嵌套事务”
        "_process_single_stockout": ["apply_stock_delta_locked"],
    },
    "fastapi_app/services/stock_return_service.py": {
        "create_stockreturn_core": ["update_stock_with_optimistic_lock"],
        # e14eb4dd 起「删除」由 cancel_stockreturn_core 承担（2026-10-09 起回冲后
        # 直接删除记录），库存写入点同名迁移
        "cancel_stockreturn_core": ["update_stock_with_optimistic_lock"],
    },
}


def _source(rel_path: str) -> str:
    return (_REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _tree(rel_path: str) -> ast.Module:
    return ast.parse(_source(rel_path), filename=rel_path)


def _augassign_current_stock(tree: ast.Module) -> list[int]:
    """返回对 *.current_stock 做 += / -= 的语句行号（AST 版 grep）。"""
    hits: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Attribute)
            and node.target.attr == "current_stock"
        ):
            hits.append(node.lineno)
    return hits


def _unified_calls_by_function(tree: ast.Module) -> dict[str, list[str]]:
    """{函数名: [统一入口函数名, ...]} —— 只收集本模块函数体内的调用。"""
    found: dict[str, list[str]] = {}

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def _visit_func(self, node: ast.AST) -> None:
            name = node.name  # type: ignore[attr-defined]
            self.stack.append(name)
            found.setdefault(name, [])
            self.generic_visit(node)
            self.stack.pop()

        visit_FunctionDef = _visit_func
        visit_AsyncFunctionDef = _visit_func

        def visit_Call(self, node: ast.Call) -> None:
            callee = None
            if isinstance(node.func, ast.Name):
                callee = node.func.id
            elif isinstance(node.func, ast.Attribute):
                callee = node.func.attr
            if callee in _UNIFIED_ENTRIES and self.stack:
                found[self.stack[-1]].append(callee)
            self.generic_visit(node)

    _Visitor().visit(tree)
    return {name: calls for name, calls in found.items() if calls}


@pytest.mark.parametrize("rel_path", _SERVICE_FILES)
def test_no_direct_current_stock_augmented_assignment(rel_path):
    """四个文件内不存在 current_stock += / -= 直写（AST + 文本双重证明）。"""
    assert _augassign_current_stock(_tree(rel_path)) == []
    assert not re.search(r"current_stock\s*[+-]=", _source(rel_path))


@pytest.mark.parametrize("rel_path", sorted(_EXPECTED_CALL_SITES))
def test_every_write_point_calls_unified_entry(rel_path):
    """每个历史直写点都改调统一写入口，且没有额外遗留写点。"""
    assert _unified_calls_by_function(_tree(rel_path)) == _EXPECTED_CALL_SITES[rel_path]


# ---------------------------------------------------------------------------
# 最小 AsyncSession 替身
# ---------------------------------------------------------------------------
class _Result:
    def __init__(self, product=None, rowcount: int = 0):
        self._product = product
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self._product


class _Savepoint:
    def __init__(self, events: list[str]):
        self.events = events

    async def __aenter__(self):
        self.events.append("enter")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.events.append("rollback" if exc_type is not None else "commit")
        return False


def _is_update(stmt) -> bool:
    return getattr(stmt, "__visit_name__", "") == "update"


class _FakeSession:
    """SELECT 返回固定产品；UPDATE 的 rowcount 按序列编排（最后一个值重复使用）。"""

    def __init__(self, product=None, update_rowcounts=(1,)):
        self.product = product
        self._rowcounts = list(update_rowcounts)
        self.selects: list = []
        self.updates: list = []
        self.savepoint_events: list[str] = []
        self.refreshed: list = []
        self.expunged: list = []
        self.rollback_calls = 0

    def begin_nested(self):
        return _Savepoint(self.savepoint_events)

    async def execute(self, stmt):
        if _is_update(stmt):
            self.updates.append(stmt)
            index = min(len(self.updates) - 1, len(self._rowcounts) - 1)
            return _Result(rowcount=self._rowcounts[index])
        self.selects.append(stmt)
        return _Result(self.product)

    async def refresh(self, obj):
        self.refreshed.append(obj)

    def expunge(self, obj):
        self.expunged.append(obj)

    async def rollback(self):
        self.rollback_calls += 1


def _fake_product(stock: int = 10, version: int = 3, pid: int = 7):
    return SimpleNamespace(id=pid, current_stock=stock, version=version)


def _update_params(stmt) -> set:
    return set(stmt.compile(dialect=sqlite.dialect()).params.values())


# ---------------------------------------------------------------------------
# 未持锁入口：update_stock_with_optimistic_lock
# ---------------------------------------------------------------------------
async def test_optimistic_lock_success_carries_version_guard(monkeypatch):
    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)
    product = _fake_product(stock=10, version=3)
    db = _FakeSession(product, update_rowcounts=(1,))

    out = await update_stock_with_optimistic_lock(db, 7, -4)

    assert out is product
    assert len(db.updates) == 1
    assert db.refreshed == [product]
    assert db.savepoint_events == ["enter", "commit"]
    sql = str(db.updates[0].compile(dialect=sqlite.dialect()))
    assert f"UPDATE {Product.__tablename__}" in sql
    assert "WHERE" in sql
    # SET current_stock=6 / version=4，WHERE id=7 AND version=3
    assert _update_params(db.updates[0]) >= {6, 4, 7, 3}


async def test_version_conflict_rolls_back_savepoint_and_raises_existing_error(monkeypatch):
    """version 冲突：逐轮回滚 savepoint，耗尽后抛既有冲突异常，且不整体回滚事务。"""
    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)
    product = _fake_product(stock=10, version=3)
    db = _FakeSession(product, update_rowcounts=(0,))

    with pytest.raises(StockConcurrentError) as ei:
        await update_stock_with_optimistic_lock(db, 7, -4)

    assert isinstance(ei.value, ConflictError)  # 既有冲突异常类型（HTTP 409）
    assert db.savepoint_events.count("enter") == MAX_RETRY == 3
    assert db.savepoint_events.count("rollback") == MAX_RETRY
    assert "commit" not in db.savepoint_events
    assert db.rollback_calls == 0  # 只回滚 savepoint：事务中其他有效修改保留
    assert db.refreshed == []
    assert product.current_stock == 10 and product.version == 3


async def test_conflict_then_success_on_retry(monkeypatch):
    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)
    product = _fake_product(stock=10, version=3)
    db = _FakeSession(product, update_rowcounts=(0, 1))

    out = await update_stock_with_optimistic_lock(db, 7, 5)

    assert out is product
    assert db.savepoint_events == ["enter", "rollback", "enter", "commit"]
    assert db.expunged == [product]  # 重试前先 expunge 上一轮对象


async def test_retries_parameter_is_honoured(monkeypatch):
    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)
    db = _FakeSession(_fake_product(), update_rowcounts=(0,))

    with pytest.raises(StockConcurrentError):
        await update_stock_with_optimistic_lock(db, 7, -4, retries=1)

    assert db.savepoint_events.count("enter") == 1


async def test_insufficient_stock_keeps_historic_error_and_sends_no_update(monkeypatch):
    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)
    product = _fake_product(stock=5, version=1)
    db = _FakeSession(product, update_rowcounts=(1,))

    with pytest.raises(ValueError) as ei:
        await update_stock_with_optimistic_lock(db, 7, -8)

    assert str(ei.value) == "库存不足！当前库存: 5，需要: 8"
    assert db.updates == []
    assert product.current_stock == 5


# ---------------------------------------------------------------------------
# 持锁入口：apply_stock_delta_locked
# ---------------------------------------------------------------------------
def test_locked_entry_signature():
    assert list(inspect.signature(apply_stock_delta_locked).parameters) == [
        "db",
        "product",
        "delta",
    ]


async def test_locked_entry_single_shot_without_savepoint(monkeypatch):
    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)
    product = _fake_product(stock=10, version=3)
    db = _FakeSession(product, update_rowcounts=(1,))

    out = await apply_stock_delta_locked(db, product, -4)

    assert out is product
    assert db.savepoint_events == []  # 持锁路径不开 savepoint
    assert db.selects == []  # 调用方已持行锁，不需要再次 SELECT
    assert len(db.updates) == 1
    assert _update_params(db.updates[0]) >= {6, 4, 7, 3}
    # 内存对象同步，调用方后续读到一致值
    assert product.current_stock == 6 and product.version == 4


async def test_locked_entry_raises_on_version_miss(monkeypatch):
    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)
    product = _fake_product(stock=10, version=3)
    db = _FakeSession(product, update_rowcounts=(0,))

    with pytest.raises(StockConcurrentError) as ei:
        await apply_stock_delta_locked(db, product, -4)

    assert isinstance(ei.value, ConflictError)
    assert product.current_stock == 10 and product.version == 3  # 不污染内存对象
    assert db.savepoint_events == []


async def test_locked_entry_rejects_negative_stock_and_allows_positive(monkeypatch):
    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)
    product = _fake_product(stock=2, version=1)
    db = _FakeSession(product, update_rowcounts=(1,))

    with pytest.raises(ValueError) as ei:
        await apply_stock_delta_locked(db, product, -3)

    assert str(ei.value) == "库存不足！当前库存: 2，需要: 3"
    assert db.updates == []

    # 入库（正 delta）在 0 库存时也必须放行
    zero = _fake_product(stock=0, version=1)
    await apply_stock_delta_locked(db, zero, 5)
    assert zero.current_stock == 5 and zero.version == 2


# ---------------------------------------------------------------------------
# 批量出库端到端：走持锁入口，且仍无嵌套事务
# ---------------------------------------------------------------------------
async def test_batch_stockout_writes_via_locked_entry_without_nested_transaction(mock_db):
    product = MagicMock()
    product.id = 1
    product.current_stock = 100
    product.version = 3
    shipment_info = {
        "available_quantity": 50,
        "order_quantity": 100,
        "shipped_quantity": 50,
        "orders": [{"order_id": 1, "available": 50, "quantity": 100}],
    }

    with patch(
        "fastapi_app.services.stock_service.get_product_for_update",
        new_callable=AsyncMock,
        return_value=product,
    ), patch(
        "fastapi_app.services.stock_service.calculate_available_shipment_quantity",
        new_callable=AsyncMock,
        return_value=shipment_info,
    ), patch(
        "fastapi_app.services.stock_service.generate_stockout_number",
        new_callable=AsyncMock,
        return_value="SO-2026-0001",
    ):
        result = await stock_out_service.batch_create_stockouts(
            mock_db,
            [{"product_id": 1, "customer": "客户A", "quantity": 10, "note": "", "id": "t-1"}],
        )

    assert result["success"] is True
    assert result["results"][0]["success"] is True
    assert product.current_stock == 90  # 数量语义与改动前一致
    mock_db.begin_nested.assert_not_called()  # 批量路径仍无嵌套事务


async def test_batch_stockout_insufficient_stock_denied_at_write_guard(mock_db):
    """2026-10-06 校准：准入按客户+产品订单口径；产品级负库存由写入原子守卫兜底拒绝"""
    product = MagicMock()
    product.id = 1
    product.current_stock = 5
    product.version = 1
    admit = {"available_quantity": 10, "order_quantity": 10, "shipped_quantity": 0, "orders": []}

    with patch(
        "fastapi_app.services.stock_service.get_product_for_update",
        new_callable=AsyncMock,
        return_value=product,
    ), patch(
        "fastapi_app.services.stock_service.calculate_available_shipment_quantity",
        new_callable=AsyncMock,
        return_value=admit,
    ), patch(
        "fastapi_app.services.stock_out_service.apply_stock_delta_locked",
        side_effect=ValueError("库存不足！当前库存: 5，需要: 10"),
    ):
        result = await stock_out_service.batch_create_stockouts(
            mock_db,
            [{"product_id": 1, "customer": "客户A", "quantity": 10, "note": "", "id": "t-2"}],
        )

    assert result["results"][0]["success"] is False
    assert result["results"][0]["error"] == "库存不足！当前库存: 5，需要: 10"
    assert product.current_stock == 5
