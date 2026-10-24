"""staging/_generic.py 的异步 extra_row_validations 回归测试（P0 止血批 §6.30 强制项 3）

背景（活缺陷）：`_generic_import_staging_from_excel` 曾把 `extra_row_validations`
按同步函数调用：

    if extra_row_validations:
        errors.extend(extra_row_validations(row_data, idx))

而活接线传入的 `_validate_stockin_customer`（fastapi_app/services/staging/stockin.py:43）
与 `_generic_import_staging_from_excel` 自身都是 async def，于是 `errors.extend(<coroutine>)`
抛 `TypeError: 'coroutine' object is not iterable`，被逐行 `except (ValueError, TypeError,
OSError)` 吞掉并改写成「第N行处理失败」——校验器给出的真实错误信息永远到不了调用方，
暂存备货 / 暂存出货的 Excel 导入每一行都失败（修复前本文件全部用例必失败）。

本测试不依赖真实 Excel 文件与真实数据库：
- Excel 解析（read_excel_sheets_async / parse_excel_file_async）与产品映射（_build_product_map）被替身替换；
- db 为 AsyncMock，只记录 add / flush，不建立任何数据库连接。

覆盖三条路径（§6.30 强制项 3 要求）：
1. async 校验器返回错误列表 ⇒ 错误被收集进 errors，且该行不再入库；
2. async 校验器返回空列表 ⇒ 该行继续入库；
3. async 校验器抛 ValueError ⇒ 记为「第N行处理失败: <原因>」。
"""
import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fastapi_app.services.staging import _generic as staging_generic
from fastapi_app.services.staging import stockin as staging_stockin
from fastapi_app.services.staging import stockout as staging_stockout

SESSION_ID = "janitor-extra-validations"
# 端点层只校验前 4 字节魔数，解析器在测试里被替身替换，故内容本身无关
XLSX_MAGIC = b"PK\x03\x04stub"
_GENERIC_PATH = Path(staging_generic.__file__)

# 修复前的写法（用于自证 AST 检测器能区分「未 await」的实现）
_UNAWAITED_SNIPPET = """
async def _generic_import_staging_from_excel(db, rows, extra_row_validations=None):
    errors = []
    for idx, row in enumerate(rows, start=2):
        try:
            if extra_row_validations:
                errors.extend(extra_row_validations(row, idx))
        except (ValueError, TypeError, OSError) as exc:
            errors.append("failed")
"""


def _fake_db():
    """只记录 add / flush 的替身会话，不建立数据库连接"""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    # B1-04 的 _recalc_stock_check_by_balance 会对暂存行做一次 SELECT；
    # 空结果集即可（本文件的用例只关心校验器文案，不涉及结余重算）。
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    return db


async def _noop_clear(_db, _session_id):
    return 0


def _patch_excel(monkeypatch, rows, sheet="备货管理"):
    """替换 Excel 解析与产品映射，使被测函数不触碰真实文件与数据库"""
    monkeypatch.setattr(
        staging_generic, "read_excel_sheets_async", AsyncMock(return_value=(True, [sheet], ""))
    )
    monkeypatch.setattr(
        staging_generic, "parse_excel_file_async", AsyncMock(return_value=(True, rows, ""))
    )
    monkeypatch.setattr(staging_generic, "_build_product_map", AsyncMock(return_value={}))


async def _run_generic(db, monkeypatch, rows, validator, sheet="备货管理"):
    _patch_excel(monkeypatch, rows, sheet)
    return await staging_generic._generic_import_staging_from_excel(
        db, XLSX_MAGIC, SESSION_ID,
        staging_model=staging_stockin.StagingStockIn,
        clear_func=_noop_clear,
        sheet_keyword=sheet,
        entity_label="备货",
        build_entity=lambda *args: object(),
        column_names={"product_name": "产品名称", "quantity": "数量"},
        required_fields=["product_name", "quantity"],
        extra_row_validations=validator,
    )


def _awaits_call(source: str, func_name: str, callee_name: str) -> bool:
    """在 func_name 的函数体内，是否存在对 callee_name 的 await 调用"""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef) or node.name != func_name:
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Await) or not isinstance(sub.value, ast.Call):
                continue
            callee = sub.value.func
            if isinstance(callee, ast.Name) and callee.id == callee_name:
                return True
    return False


class TestAsyncExtraRowValidationsCollected:
    """_generic_import_staging_from_excel 必须 await 异步校验器"""

    async def test_async_validator_errors_are_collected(self, monkeypatch):
        """校验器返回的错误进入 errors，且该行不再入库（修复前退化成 coroutine TypeError）"""
        seen = []

        async def _validator(row_data, idx):
            seen.append((dict(row_data), idx))
            return [f"第{idx}行：自定义校验失败"]

        db = _fake_db()
        imported, message, errors = await _run_generic(
            db, monkeypatch, [{"产品名称": "产品A", "数量": 3}], _validator
        )

        # 校验器确实被 await 调用（拿到协程结果），且收到的是原始行数据与 Excel 行号
        assert seen == [({"产品名称": "产品A", "数量": 3}, 2)]
        assert errors == ["第2行：自定义校验失败"]
        assert imported == 0
        db.add.assert_not_called()
        assert "自定义校验失败" in message
        assert "coroutine" not in message

    async def test_empty_validation_keeps_row(self, monkeypatch):
        """校验器返回空列表 ⇒ 该行继续入库"""

        async def _validator(row_data, idx):
            return []

        db = _fake_db()
        imported, message, errors = await _run_generic(
            db, monkeypatch, [{"产品名称": "产品A", "数量": 3}], _validator
        )

        assert errors == []
        assert imported == 1
        assert db.add.call_count == 1
        assert message.startswith("成功导入 1 个备货到暂存区")

    async def test_validator_value_error_is_row_failure(self, monkeypatch):
        """校验器抛 ValueError ⇒ 记为「第N行处理失败: <原因>」，不吞成 coroutine 错误"""

        async def _validator(row_data, idx):
            raise ValueError("客户名称包含非法字符")

        db = _fake_db()
        imported, message, errors = await _run_generic(
            db, monkeypatch, [{"产品名称": "产品A", "数量": 3}], _validator
        )

        assert errors == ["第2行处理失败: 客户名称包含非法字符"]
        assert imported == 0
        db.add.assert_not_called()
        assert "coroutine" not in message

    def test_generic_source_awaits_validator(self):
        """静态回归锁：源码里存在 await extra_row_validations(...)（AST，非文本匹配）"""
        source = _GENERIC_PATH.read_text(encoding="utf-8")
        assert _awaits_call(source, "_generic_import_staging_from_excel", "extra_row_validations")
        # 自证检测器有效：修复前的写法必须被判为「未 await」
        assert not _awaits_call(
            _UNAWAITED_SNIPPET, "_generic_import_staging_from_excel", "extra_row_validations"
        )


class TestLiveStagingWiring:
    """活接线（stockin / stockout 的 Excel 导入入口）必须把校验器文案带回调用方"""

    async def test_stockin_import_surfaces_validator_message(self, monkeypatch):
        rows = [{"客户名称": "客户@非法", "产品名称": "产品A", "备货数量": 3, "时间": "2026-01-05", "备注": ""}]
        _patch_excel(monkeypatch, rows)
        monkeypatch.setattr(staging_stockin, "clear_staging_stockins_by_session", AsyncMock(return_value=0))
        db = _fake_db()

        imported, message, errors = await staging_stockin.import_staging_stockins_from_excel(
            db, XLSX_MAGIC, SESSION_ID
        )

        assert errors == ["第2行：客户名称包含非法字符"]
        assert imported == 0
        db.add.assert_not_called()
        assert "客户名称包含非法字符" in message

    async def test_stockout_import_surfaces_validator_message(self, monkeypatch):
        rows = [{"客户名称": "客户@非法", "产品名称": "产品A", "出货数量": 3, "时间": "2026-01-05", "备注": ""}]
        _patch_excel(monkeypatch, rows, sheet="出货管理")
        monkeypatch.setattr(staging_stockout, "clear_staging_stockouts_by_session", AsyncMock(return_value=0))
        db = _fake_db()

        imported, _message, errors = await staging_stockout.import_staging_stockouts_from_excel(
            db, XLSX_MAGIC, SESSION_ID
        )

        assert errors == ["第2行：客户名称包含非法字符"]
        assert imported == 0
        db.add.assert_not_called()

    async def test_valid_row_still_imported(self, monkeypatch):
        """镜像正例：合规客户名 + 校验器返回空列表 ⇒ 行照常入库（修复未误伤主流程）"""
        rows = [{"客户名称": "华东客户", "产品名称": "产品A", "备货数量": 3, "时间": "2026-01-05", "备注": "ok"}]
        _patch_excel(monkeypatch, rows)
        monkeypatch.setattr(staging_stockin, "clear_staging_stockins_by_session", AsyncMock(return_value=0))
        db = _fake_db()

        imported, _message, errors = await staging_stockin.import_staging_stockins_from_excel(
            db, XLSX_MAGIC, SESSION_ID
        )

        assert errors == []
        assert imported == 1
        assert db.add.call_count == 1
        entity = db.add.call_args[0][0]
        assert entity.customer == "华东客户"
        assert entity.quantity == 3
        assert entity.is_validated is False  # 产品映射为空 ⇒ 未匹配产品（既有行为）
