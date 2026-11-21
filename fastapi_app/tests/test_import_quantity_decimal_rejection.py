"""H-1（2026-11-21 全量审计）回归：导入数量小数一律拒绝，不得静默截断。

四条出货/入库导入路径（综合导入出库、单 Sheet 出货、皮套出库、皮套入库）此前用
裸 ``int(quantity)``：Excel 数值单元格 10.5 被截成 10 按错误数量扣库存/建流水，
而订单/备货路径早已「小数一律拒绝」——同一输入因 Sheet 不同结果不同。
修复后全部走 :func:`batch_import_core._parse_positive_quantity` 唯一实现；
末尾一条静态证明防回归（batch_import_parser.py 的 int() 前有显式 is_integer
守卫，不在本证明范围）。
"""
import types
from pathlib import Path

import pytest

from fastapi_app.services import batch_import_core as bic
from fastapi_app.services import batch_import_service as bis

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "fastapi_app/services/batch_import_core.py"
SERVICE = REPO / "fastapi_app/services/batch_import_service.py"
DECIMAL_MSG = "小数一律拒绝"


# --------------------------------------------------------------------------
# 唯一实现本身
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad", [10.5, 0, -3, "abc", "10.5", None],
)
def test_parse_positive_quantity_rejects_non_positive_and_decimal(bad):
    assert bic._parse_positive_quantity(
        bad, 1, label="测试", product_name="P", customer="C") is None


@pytest.mark.parametrize("good", [10, 10.0, "10"])
def test_parse_positive_quantity_accepts_positive_integer_forms(good):
    assert bic._parse_positive_quantity(
        good, 1, label="测试", product_name="P", customer="C") == 10


# --------------------------------------------------------------------------
# 综合导入出库路径（batch_import_core._resolve_stockout_inputs）
# --------------------------------------------------------------------------
class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return None


class _FakeSession:
    """导入路径所需的最小 AsyncSession 替身（与 test_stock_negative_policy 同形）。

    ``result_rows`` 非空时所有 execute 返回这些行（core 路径的 Product 查询用）；
    默认空结果（service 闭包路径的 movement-exists 幂等查询用）。
    """

    def __init__(self, result_rows=None):
        self._result_rows = result_rows or []
        self.added = []

    async def execute(self, stmt):
        return _FakeResult(self._result_rows)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def rollback(self):
        return None

    def begin_nested(self):
        return _NestedCtx()


class _NestedCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _product():
    return types.SimpleNamespace(
        id=1, name="P1", factory=None, current_stock=100, version=0,
    )


async def test_core_stockout_row_rejects_decimal_quantity(monkeypatch):
    """综合导入出库 Sheet：10.5 不得被截成 10 通过校验。"""
    import fastapi_app.services.stock_out_service as sos

    async def _no_balance(db, *a, **k):
        return None

    monkeypatch.setattr(sos, "_assert_inventory_balance", _no_balance)

    async def _pass_product(db, pid):
        return _product()

    async def _avail(db, pid, customer):
        return {"available_quantity": 50}

    deps = bic.ImportDeps(
        get_product_for_update=_pass_product,
        calculate_available_shipment_quantity=_avail,
    )
    debug: list[str] = []
    resolved = await bic._resolve_stockout_inputs(
        _FakeSession(result_rows=[_product()]), deps,
        {"产品名称": "P1", "数量": 10.5, "客户名称": "客户甲"},
        2, debug, None,
    )
    assert resolved is None
    assert any(DECIMAL_MSG in m for m in debug), debug


async def test_core_stockout_row_accepts_integer_quantity(monkeypatch):
    """同路径整数 10 仍正常通过（防修复误伤）。"""
    import fastapi_app.services.stock_out_service as sos

    async def _no_balance(db, *a, **k):
        return None

    monkeypatch.setattr(sos, "_assert_inventory_balance", _no_balance)

    async def _pass_product(db, pid):
        return _product()

    async def _avail(db, pid, customer):
        return {"available_quantity": 50}

    deps = bic.ImportDeps(
        get_product_for_update=_pass_product,
        calculate_available_shipment_quantity=_avail,
    )
    resolved = await bic._resolve_stockout_inputs(
        _FakeSession(result_rows=[_product()]), deps,
        {"产品名称": "P1", "数量": 10, "客户名称": "客户甲"},
        2, [], None,
    )
    assert resolved is not None
    assert resolved[2] == 10


# --------------------------------------------------------------------------
# 单 Sheet 路径（batch_import_service，monkeypatch 行数据直喂）
# --------------------------------------------------------------------------
def _fake_upload():
    return types.SimpleNamespace(filename="stockouts.xlsx")


def _patch_common(monkeypatch, rows):
    monkeypatch.setattr(bis, "_validate_xlsx_file", lambda file: None)

    async def _read(file, sheets, msg):
        return (rows, None)

    monkeypatch.setattr(bis, "_read_excel_sheets", _read)
    monkeypatch.setattr(bis, "parse_date_value", lambda value: None)


async def test_sheet_stockout_import_rejects_decimal_quantity(monkeypatch):
    import fastapi_app.services.batch_service as bsv
    import fastapi_app.services.stock_out_service as sos

    product = _product()

    async def _get_prod(db, ident):
        return product

    async def _lock(db, pid):
        return product

    async def _no_balance(db, *a, **k):
        return None

    async def _avail(db, pid, customer):
        return {"available_quantity": 50}

    async def _no_alloc(db, *a, **k):
        return None

    async def _no_delta(db, product_obj, delta):
        return None

    monkeypatch.setattr(bsv, "get_product_by_identifier", _get_prod)
    monkeypatch.setattr(bis, "get_product_for_update", _lock)
    monkeypatch.setattr(bis, "calculate_available_shipment_quantity", _avail)
    monkeypatch.setattr(bis, "_allocate_stockout_to_orders", _no_alloc)
    monkeypatch.setattr(bis, "apply_stock_delta_locked", _no_delta)
    monkeypatch.setattr(sos, "_assert_inventory_balance", _no_balance)
    _patch_common(
        monkeypatch,
        [{"产品名称": "P1", "出货数量": 10.5, "客户名称": "客户甲"}],
    )

    result = await bis.import_stockouts_service(_FakeSession(), _fake_upload())
    assert result.imported == 0
    assert DECIMAL_MSG in (result.message or ""), result.message
    assert product.current_stock == 100  # 未被按截断后的 10 扣减


async def test_case_stockout_import_rejects_decimal_quantity(monkeypatch):
    import fastapi_app.services.batch_service as batch_service

    case_obj = types.SimpleNamespace(id=7, current_stock=100, version=0)

    async def _number(db):
        return "PKOUT-B1"

    async def _find(db, identifier):
        return case_obj, None

    monkeypatch.setattr(bis, "generate_case_stockout_number", _number)
    monkeypatch.setattr(batch_service, "find_case_locked", _find)
    _patch_common(
        monkeypatch,
        [{"产品名称": "皮套A", "出库数量": 10.5, "客户名称": "客户甲"}],
    )

    result = await bis.import_case_stockouts_service(_FakeSession(), _fake_upload())
    assert result.imported == 0
    assert DECIMAL_MSG in (result.message or ""), result.message
    assert case_obj.current_stock == 100  # 未被按截断后的 10 出库


async def test_case_stockin_import_rejects_decimal_quantity(monkeypatch):
    import fastapi_app.services.batch_service as batch_service

    case_obj = types.SimpleNamespace(id=7, current_stock=100, version=0)

    async def _number(db):
        return "PKIN-B1"

    async def _find(db, identifier):
        return case_obj, None

    monkeypatch.setattr(bis, "generate_case_stockin_number", _number)
    monkeypatch.setattr(batch_service, "find_case_locked", _find)
    _patch_common(
        monkeypatch,
        [{"产品名称": "皮套A", "入库数量": 10.5, "客户名称": "客户甲"}],
    )

    result = await bis.import_case_stockins_service(_FakeSession(), _fake_upload())
    assert result.imported == 0
    assert DECIMAL_MSG in (result.message or ""), result.message
    assert case_obj.current_stock == 100  # 未被按截断后的 10 入库


# --------------------------------------------------------------------------
# 静态证明：裸 int(quantity) 只允许存在于 canonical helper 内部
# --------------------------------------------------------------------------
def test_no_bare_int_quantity_parse_left_in_import_modules():
    core_src = CORE.read_text(encoding="utf-8")
    assert core_src.count("qty = int(quantity)") == 1, "batch_import_core 只允许 _parse_positive_quantity 内部出现一次"
    service_src = SERVICE.read_text(encoding="utf-8")
    assert "int(quantity)" not in service_src, "batch_import_service 不允许任何裸 int(quantity)"
