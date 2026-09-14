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
        """空数据列表应返回 count=0 且不产生行级消息"""
        db = AsyncMock()
        count, msgs = await batch_import_service._import_data_generic(
            db, [], row_handler=AsyncMock(), has_debug_messages=True, label="测试",
        )
        assert count == 0
        # debug_messages 现在是纯「行级消息」，完成消息只进日志 ——
        # 调用方会把它整体并进 results.errors，混入完成消息会污染用户看到的错误列表。
        assert msgs == [], f'空输入不应产生行级消息: {msgs}'

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

        count, messages = await batch_import_service.import_products_from_data(db, [])
        assert count == 0
        assert messages == []

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
        count, messages = await batch_import_service.import_products_from_data(db, data)
        assert count == 1
        assert db.add.called
        assert messages == [], f'无重复时不应产生去重消息: {messages}'

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
        count, messages = await batch_import_service.import_products_from_data(db, data)
        assert count == 0
        assert not db.add.called
        # 「产品A」与库中已有的「产品a」仅大小写不同，必须判为重复并**回显**。
        # 这是 ITER-2 决策 1 的核心要求：静默丢行是最容易引入的体验倒退。
        assert any('重复' in m for m in messages), f'重复行未回显: {messages}'
        assert '行2' in messages[0], f'消息缺少行号: {messages[0]}'

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
        count, messages = await batch_import_service.import_products_from_data(db, data)
        assert count == 0
        # 无产品名 → 去重原语拿不到键，按约定「一律保留」并交给 row_handler 处理，
        # 不能被误判成重复行而生成误导性消息。
        assert messages == [], f'无唯一键的行不应产生去重消息: {messages}'


class TestProductDedupeIntegration:
    """去重原语接入产品导入后的行为（ITER-2 决策 1）。

    重点防两件事：批内重复漏判、重复行静默丢弃。
    """

    @staticmethod
    def _db_with_existing(existing_names):
        db = AsyncMock()
        mock = MagicMock()
        mock.all.return_value = [(n,) for n in existing_names]
        db.execute = AsyncMock(return_value=mock)
        db.flush = AsyncMock()
        db.add = MagicMock()
        return db

    @pytest.mark.asyncio
    async def test_in_file_duplicate_keeps_first_and_reports(self):
        """同一文件内出现两次同名产品：保留首次出现，后续行回显跳过"""
        db = self._db_with_existing([])
        data = [
            {"产品名称": "产品A", "69码": "690001"},
            {"产品名称": "产品A", "69码": "690002"},  # 批内重复
            {"产品名称": "产品B", "69码": "690003"},
        ]
        count, messages = await batch_import_service.import_products_from_data(db, data)
        assert count == 2, '批内重复行应被剔除，仅保留 2 条'
        assert any('文件内重复' in m and '行3' in m for m in messages), (
            f'批内重复未回显或行号错误: {messages}'
        )
        # 首次出现者优先：保留的应是行2的「产品A」，而非行3的同名重复行
        added = [c.args[0].name for c in db.add.call_args_list]
        assert added == ['产品A', '产品B'], f'保留行的顺序/内容不符: {added}'

    @pytest.mark.asyncio
    async def test_case_and_whitespace_variants_are_duplicates(self):
        """大小写与首尾空白差异必须判为同一产品（沿用既有 name 匹配口径）"""
        db = self._db_with_existing([])
        data = [
            {"产品名称": "  Acme  "},
            {"产品名称": "acme"},
            {"产品名称": "ACME"},
        ]
        count, _ = await batch_import_service.import_products_from_data(db, data)
        assert count == 1, '三种写法应合并为 1 条'

    @pytest.mark.asyncio
    async def test_no_row_is_silently_dropped(self):
        """每一行输入要么入库、要么在消息里被点名，不允许凭空消失"""
        db = self._db_with_existing(['已有品'])
        data = [
            {"产品名称": "新产品"},       # 入库
            {"产品名称": "已有品"},       # 与库中重复 → 消息
            {"产品名称": "新产品"},       # 批内重复 → 消息
        ]
        count, messages = await batch_import_service.import_products_from_data(db, data)
        assert count + len(messages) == len(data), (
            f'行数不守恒: 入库 {count} + 消息 {len(messages)} != 输入 {len(data)}'
        )
        assert any('行3' in m for m in messages), f'与库中重复未回显: {messages}'
        assert any('行4' in m for m in messages), f'批内重复未回显: {messages}'
