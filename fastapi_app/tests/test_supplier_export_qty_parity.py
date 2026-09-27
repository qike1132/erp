"""供应商汇总导出「与页面口径一致」契约测试。

背景：``/purchase-center/orders/supplier-summary-export`` 原本只按明细原始数量出数，
而页面「供应商采购订单」展示的是**同源派生值**（按损耗率加放、非编辑态向上取整），
两者对不上。修复后契约如下（本文件逐条锁定）：

1. 请求携带 ``supplier_quantities`` 时，导出**严格等于页面行集**：
   行、顺序、数量都取页面展示值，页面不展示的填充物等明细不再导出；
2. 供应商联系信息仍取数据库口径，按供应商名从原分组继承；
3. ``rows`` 为空时保持旧口径（按明细原始数量导出），向后兼容；
4. 数量文本与前端 ``qtyDisplayText`` 同口径：整数不带小数位、非整数最多 2 位。
"""
import io
from unittest.mock import AsyncMock, MagicMock, patch

import openpyxl
import pytest

from fastapi_app.api.v1.endpoints.purchase_center.export_utils import _qty_display_text
from fastapi_app.api.v1.endpoints.purchase_center.print_routes import rebuild_supplier_groups_from_page
from fastapi_app.api.v1.endpoints.purchase_center.schemas import SupplierExportQuantityItem

EXPORT_URL = '/api/v1/purchase-center/orders/supplier-summary-export'
QTY_COL = 14   # 模板「数量」列（N）
NAME_COL = 3   # 模板「物料名称」列（C）
FIRST_DATA_ROW = 10


def _item(name: str, spec: str, unit: str, qty: float) -> dict:
    return {'material_name': name, 'specification': spec, 'unit': unit, 'quantity': qty}


def _group(supplier_name: str, items: list[dict], contact: str = '', phone: str = '', address: str = '') -> dict:
    return {
        'supplier_name': supplier_name, 'items': items,
        'contact_person': contact, 'phone': phone, 'address': address,
    }


def _row(supplier: str, name: str, spec: str, unit: str, qty: float) -> SupplierExportQuantityItem:
    return SupplierExportQuantityItem(
        supplier_name=supplier, material_name=name, specification=spec, unit=unit, quantity=qty,
    )


class TestRebuildSupplierGroupsFromPage:
    def test_row_set_and_order_follow_page(self):
        # DB 分组含页面不展示的填充物 → 重建后必须消失
        db_groups = [_group('供应商1', [
            _item('布料A', 'S1', '米', 20.0),
            _item('填充棉', 'F1', 'kg', 5.5),
        ])]

        rebuilt = rebuild_supplier_groups_from_page(db_groups, [_row('供应商1', '布料A', 'S1', '米', 21)])

        assert [i['material_name'] for i in rebuilt[0]['items']] == ['布料A']
        assert rebuilt[0]['items'][0]['quantity'] == 21

    def test_page_row_order_is_preserved(self):
        db_groups = [_group('供应商1', [_item('布料A', 'S1', '米', 20.0)])]
        rows = [
            _row('供应商1', '布料B', 'S2', '米', 2),
            _row('供应商1', '布料A', 'S1', '米', 1),
        ]

        rebuilt = rebuild_supplier_groups_from_page(db_groups, rows)

        assert [i['material_name'] for i in rebuilt[0]['items']] == ['布料B', '布料A']

    def test_groups_follow_page_supplier_order(self):
        db_groups = [
            _group('供应商1', [_item('布料A', 'S1', '米', 20.0)], contact='张三'),
            _group('供应商2', [_item('布料C', 'S3', '米', 10.0)], contact='李四'),
        ]
        rows = [
            _row('供应商2', '布料C', 'S3', '米', 11),
            _row('供应商1', '布料A', 'S1', '米', 21),
        ]

        rebuilt = rebuild_supplier_groups_from_page(db_groups, rows)

        assert [g['supplier_name'] for g in rebuilt] == ['供应商2', '供应商1']
        assert [g['items'][0]['quantity'] for g in rebuilt] == [11, 21]

    def test_contact_info_inherited_from_db_group(self):
        db_groups = [_group('供应商1', [_item('布料A', 'S1', '米', 20.0)], contact='张三', phone='123', address='地址')]

        rebuilt = rebuild_supplier_groups_from_page(db_groups, [_row('供应商1', '布料A', 'S1', '米', 21)])

        assert rebuilt[0]['contact_person'] == '张三'
        assert rebuilt[0]['phone'] == '123'
        assert rebuilt[0]['address'] == '地址'

    def test_page_row_missing_from_db_groups_still_exported(self):
        # BOM 用量回退等场景：页面有行、明细分组没有 → 仍按页面导出（联系信息留空）
        rebuilt = rebuild_supplier_groups_from_page([], [_row('供应商9', '布料Z', 'S9', '米', 7)])

        assert rebuilt == [{
            'supplier_name': '供应商9',
            'items': [{'material_name': '布料Z', 'specification': 'S9', 'unit': '米', 'quantity': 7}],
            'contact_person': '', 'phone': '', 'address': '',
        }]

    def test_none_spec_unit_normalized_to_blank(self):
        rebuilt = rebuild_supplier_groups_from_page([], [_row('供应商1', '布料A', '', '', 3)])

        assert rebuilt[0]['items'][0]['specification'] == ''
        assert rebuilt[0]['items'][0]['unit'] == ''

    def test_blank_supplier_name_normalized(self):
        db_groups = [_group('', [_item('布料A', 'S1', '米', 20.0)])]

        rebuilt = rebuild_supplier_groups_from_page(db_groups, [_row('', '布料A', 'S1', '米', 21)])

        assert rebuilt[0]['supplier_name'] == '未指定供应商'

    def test_empty_rows_keeps_original_groups(self):
        db_groups = [_group('供应商1', [_item('布料A', 'S1', '米', 20.0)])]

        assert rebuild_supplier_groups_from_page(db_groups, []) is db_groups


class TestQtyDisplayText:
    def test_integral_drops_decimal_part(self):
        assert _qty_display_text(22.0) == '22'
        assert _qty_display_text(22) == '22'
        assert _qty_display_text('22') == '22'
        assert _qty_display_text(0) == '0'

    def test_fraction_keeps_at_most_two_digits(self):
        assert _qty_display_text(20.1) == '20.1'
        assert _qty_display_text(20.10) == '20.1'
        assert _qty_display_text(10.05) == '10.05'

    def test_none_and_blank_are_zero(self):
        assert _qty_display_text(None) == '0'
        assert _qty_display_text('') == '0'


class TestSupplierSummaryExportRoute:
    @pytest.fixture
    def patched_service(self):
        """DB 分组含填充物（页面不展示）：未带页面行时导出会包含它，带页面行时必须消失。"""
        groups = [_group('供应商1', [
            _item('布料A', 'S1', '米', 20.0),
            _item('填充棉', 'F1', 'kg', 5.5),
        ])]
        with patch(
            'fastapi_app.services.purchase_center_service.get_purchase_orders_with_items',
            new=AsyncMock(return_value=[MagicMock()]),
        ), patch(
            'fastapi_app.services.purchase_center_service.build_supplier_export_groups',
            new=AsyncMock(return_value=groups),
        ):
            yield groups

    @pytest.mark.asyncio
    async def test_export_matches_page_rows_and_quantities(self, client, patched_service):
        resp = await client.post(EXPORT_URL, json={
            'ids': [1],
            'supplier_quantities': [
                {'supplier_name': '供应商1', 'material_name': '布料A',
                 'specification': 'S1', 'unit': '米', 'quantity': 21},
            ],
        })

        assert resp.status_code == 200
        assert 'spreadsheetml' in resp.headers['content-type']
        ws = openpyxl.load_workbook(io.BytesIO(resp.content)).active
        # 页面展示的整数不带小数位
        assert ws.cell(row=FIRST_DATA_ROW, column=QTY_COL).value == '21'
        assert ws.cell(row=FIRST_DATA_ROW, column=NAME_COL).value == '布料A（S1）'
        # 填充物（页面不展示）不再出现在导出中
        assert ws.cell(row=FIRST_DATA_ROW + 1, column=NAME_COL).value is None
        assert ws.cell(row=FIRST_DATA_ROW + 1, column=QTY_COL).value is None

    @pytest.mark.asyncio
    async def test_export_without_page_rows_keeps_legacy_output(self, client, patched_service):
        resp = await client.post(EXPORT_URL, json={'ids': [1]})

        assert resp.status_code == 200
        ws = openpyxl.load_workbook(io.BytesIO(resp.content)).active
        # 旧口径：明细原始数量、含填充物
        assert ws.cell(row=FIRST_DATA_ROW, column=QTY_COL).value == '20'
        assert ws.cell(row=FIRST_DATA_ROW + 1, column=NAME_COL).value == '填充棉（F1）'
        assert ws.cell(row=FIRST_DATA_ROW + 1, column=QTY_COL).value == '5.5'
