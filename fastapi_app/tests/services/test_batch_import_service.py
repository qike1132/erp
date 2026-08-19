"""batch_import_service.py - 单元测试

覆盖 P1-3 从 batch_service.py endpoint 下沉的批量导入业务逻辑：
- parse_excel_file_async / read_excel_sheets_async（Excel 解析）
- _pre_load_product_map（产品字典预加载）
- _import_data_generic（通用导入框架）
- import_products_from_data（产品导入）
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services import batch_import_service


class _MockNested:
    """模拟 savepoint 异步上下文管理器"""
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass


def _make_db_with_savepoint():
    """创建带 begin_nested 支持的 mock DB"""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.begin_nested = MagicMock(return_value=_MockNested())
    return db


# ============================================================================
# parse_date_value
# ============================================================================
class TestParseDateValue:
    def test_parse_none_returns_none(self):
        assert batch_import_service.parse_date_value(None) is None

    def test_parse_empty_string_returns_none(self):
        assert batch_import_service.parse_date_value("") is None

    def test_parse_valid_date_string(self):
        result = batch_import_service.parse_date_value("2026-01-15")
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 15

    def test_parse_invalid_string_returns_none(self):
        assert batch_import_service.parse_date_value("not-a-date") is None


# ============================================================================
# parse_excel_file_async
# ============================================================================
class TestParseExcelFileAsync:
    @pytest.mark.asyncio
    async def test_parse_nonexistent_file_returns_error(self, tmp_path):
        """不存在的文件应返回 (False, [], error_msg)"""
        path = str(tmp_path / "no_such_file.xlsx")
        ok, data, msg = await batch_import_service.parse_excel_file_async(path)
        assert ok is False
        assert data == []
        assert msg != ""

    @pytest.mark.asyncio
    async def test_parse_valid_excel_returns_data(self, tmp_path):
        """有效 Excel 文件应返回 (True, data_list, "")"""
        # 使用 openpyxl 创建测试文件
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["产品名称", "数量"])
        ws.append(["产品A", 100])
        path = tmp_path / "test.xlsx"
        wb.save(path)

        ok, data, msg = await batch_import_service.parse_excel_file_async(str(path))
        assert ok is True
        assert len(data) == 1  # 1 数据行（首行表头）
        assert msg == ""
        assert data[0]['产品名称'] == '产品A'


# ============================================================================
# read_excel_sheets_async
# ============================================================================
class TestReadExcelSheetsAsync:
    @pytest.mark.asyncio
    async def test_read_sheets_nonexistent_file(self, tmp_path):
        """不存在的文件应返回 (False, [], error_msg)"""
        path = str(tmp_path / "no_such_file.xlsx")
        ok, sheets, _msg = await batch_import_service.read_excel_sheets_async(path)
        assert ok is False
        assert sheets == []

    @pytest.mark.asyncio
    async def test_read_sheets_valid_file(self, tmp_path):
        """有效 Excel 文件应返回 sheet 名称列表"""
        from openpyxl import Workbook
        wb = Workbook()
        wb.active.title = "Sheet1"
        path = tmp_path / "test.xlsx"
        wb.save(path)

        ok, sheets, msg = await batch_import_service.read_excel_sheets_async(str(path))
        assert ok is True
        assert "Sheet1" in sheets
        assert msg == ""


# ============================================================================
# _pre_load_product_map
# ============================================================================
class TestPreLoadProductMap:
    @pytest.mark.asyncio
    async def test_builds_name_and_barcode_index(self):
        """应构建名称小写与条码双重索引"""
        p1 = MagicMock()
        p1.name = "产品A"
        p1.barcode = "690001"
        p2 = MagicMock()
        p2.name = "产品B"
        p2.barcode = "690002"

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [p1, p2]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        result = await batch_import_service._pre_load_product_map(db)
        product_map = result['product_map']
        assert product_map['产品a'.lower()] is p1 or product_map['产品a'] is p1
        assert product_map['690001'] is p1
        assert product_map['690002'] is p2

    @pytest.mark.asyncio
    async def test_empty_products_returns_empty_map(self):
        """无产品时应返回空字典"""
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        result = await batch_import_service._pre_load_product_map(db)
        assert result['product_map'] == {}


# ============================================================================
# _import_data_generic
# ============================================================================
class TestImportDataGeneric:
    @pytest.mark.asyncio
    async def test_empty_data_list_returns_zero(self):
        """空数据列表应返回 count=0"""
        db = AsyncMock()
        count, msgs = await batch_import_service._import_data_generic(
            db, [], row_handler=AsyncMock(), has_debug_messages=True, label="测试",
        )
        assert count == 0
        assert any("测试完成" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_row_handler_returns_true_increments_count(self):
        """row_handler 返回 True 时应计入 count"""
        db = _make_db_with_savepoint()

        async def handler(db, row, idx, ctx, msgs):
            return True

        count, _msgs = await batch_import_service._import_data_generic(
            db, [{"a": 1}, {"b": 2}], row_handler=handler,
            has_debug_messages=True, label="测试",
        )
        assert count == 2

    @pytest.mark.asyncio
    async def test_row_handler_returns_false_skips_count(self):
        """row_handler 返回 False 时不应计入 count"""
        db = _make_db_with_savepoint()

        async def handler(db, row, idx, ctx, msgs):
            return False

        count, _ = await batch_import_service._import_data_generic(
            db, [{"a": 1}], row_handler=handler,
            has_debug_messages=True, label="测试",
        )
        assert count == 0

    @pytest.mark.asyncio
    async def test_row_handler_exception_continues(self):
        """row_handler 抛异常时应跳过该行并继续处理"""
        db = _make_db_with_savepoint()
        call_count = 0

        async def handler(db, row, idx, ctx, msgs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("bad row")
            return True

        count, msgs = await batch_import_service._import_data_generic(
            db, [{"a": 1}, {"b": 2}], row_handler=handler,
            has_debug_messages=True, label="测试",
        )
        assert count == 1
        assert any("异常" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_pre_load_called_before_rows(self):
        """pre_load 回调应在处理行之前执行"""
        db = _make_db_with_savepoint()
        pre_load_called = []

        async def pre_load(db):
            pre_load_called.append(True)
            return {"loaded": True}

        async def handler(db, row, idx, ctx, msgs):
            assert ctx.get("loaded") is True
            return True

        await batch_import_service._import_data_generic(
            db, [{"a": 1}], row_handler=handler, pre_load=pre_load,
            has_debug_messages=False, label="测试",
        )
        assert pre_load_called == [True]

    @pytest.mark.asyncio
    async def test_no_debug_messages_returns_count_only(self):
        """has_debug_messages=False 时应仅返回 count（int）"""
        db = _make_db_with_savepoint()

        async def handler(db, row, idx, ctx, msgs):
            return True

        result = await batch_import_service._import_data_generic(
            db, [{"a": 1}], row_handler=handler,
            has_debug_messages=False, label="测试",
        )
        assert isinstance(result, int)
        assert result == 1


# ============================================================================
# import_products_from_data
# ============================================================================
class TestImportProductsFromData:
    @pytest.mark.asyncio
    async def test_empty_data_returns_zero(self):
        """空数据列表应返回 0"""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)
        db.flush = AsyncMock()

        count = await batch_import_service.import_products_from_data(db, [])
        assert count == 0

    @pytest.mark.asyncio
    async def test_imports_new_product(self):
        """应导入新产品并返回 count=1"""
        db = AsyncMock()
        # _pre_load 返回空 existing_names
        existing_mock = MagicMock()
        existing_mock.all.return_value = []
        db.execute = AsyncMock(return_value=existing_mock)
        db.flush = AsyncMock()
        db.add = MagicMock()

        data = [{"产品名称": "新产品A", "69码": "690123", "价格": 99.9, "初始库存": 50}]
        count = await batch_import_service.import_products_from_data(db, data)
        assert count == 1
        assert db.add.called

    @pytest.mark.asyncio
    async def test_skips_existing_product(self):
        """已存在的产品名称应跳过"""
        db = AsyncMock()
        existing_mock = MagicMock()
        existing_mock.all.return_value = [("产品a",)]
        db.execute = AsyncMock(return_value=existing_mock)
        db.flush = AsyncMock()
        db.add = MagicMock()

        data = [{"产品名称": "产品A", "69码": "690123"}]
        count = await batch_import_service.import_products_from_data(db, data)
        assert count == 0
        assert not db.add.called

    @pytest.mark.asyncio
    async def test_skips_row_without_name(self):
        """无产品名称的行应跳过"""
        db = AsyncMock()
        existing_mock = MagicMock()
        existing_mock.all.return_value = []
        db.execute = AsyncMock(return_value=existing_mock)
        db.flush = AsyncMock()
        db.add = MagicMock()

        data = [{"69码": "690123", "价格": 10}]
        count = await batch_import_service.import_products_from_data(db, data)
        assert count == 0
