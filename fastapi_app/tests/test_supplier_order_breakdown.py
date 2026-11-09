"""供应商采购订单「来源订单」逐单明细回归（2026-11-09 需求）。

背景：一次选中 N 张采购单汇总下单后，「供应商采购订单」页签按
(供应商, 物料, 规格, 单位) 合并成一行，页面只显示合计数量，无法回溯
这行来自哪几张采购单。修复后：

1. `/orders/supplier-summary` 的每个物料行带 ``orders``：逐单
   ``{order_no, quantity}``（原始口径，跨单累加）；
2. 导出/打印共用的 ``build_supplier_export_groups`` 同样带
   ``order_breakdown``，并在页面行重建、打印、Excel 备注列中传递；
3. 同一张采购单内同物料拆成多条明细时，逐单数量必须合并为一条，
   不能出现两个相同单号。
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from fastapi_app.api.v1.endpoints.purchase_center.export_utils import (
    create_supplier_workbook,
    generate_supplier_summary_print,
)
from fastapi_app.api.v1.endpoints.purchase_center.print_routes import rebuild_supplier_groups_from_page
from fastapi_app.api.v1.endpoints.purchase_center.schemas import (
    SupplierExportOrderQuantity,
    SupplierExportQuantityItem,
)
from fastapi_app.services.purchase._supplier import _build_supplier_mat_map
from fastapi_app.services.purchase_order_query import build_supplier_export_groups


def _po(po_id: int, order_no: str, supplier_name: str = '供应商1', qty: float = 100.0):
    return SimpleNamespace(
        id=po_id, order_no=order_no, supplier_name=supplier_name,
        product_quantity=qty, source_order_id=None, source_order_ids=None,
    )


def _bom_row(supplier='供应商1', material='布料A', spec='S1', unit='米', qty=1.0):
    return {
        'supplier_name': supplier, 'material_name': material,
        'specification': spec, 'unit': unit, 'quantity': qty,
        'category': '主料',
    }


def _export_item(name, spec='', unit='', qty=0.0, supplier=None):
    it = SimpleNamespace()
    it.material_name = name
    it.specification = spec
    it.unit = unit
    it.quantity = qty
    it.supplier_name = supplier
    return it


def _export_order(order_no, items, supplier_name=None,
                  contact='', phone='', address=''):
    return SimpleNamespace(
        order_no=order_no, items=items, supplier_name=supplier_name,
        supplier_contact_person=contact, supplier_phone=phone,
        supplier_address=address,
    )


def _empty_db():
    """Supplier 主数据查询返回空（走订单冗余字段回退）。"""
    result = SimpleNamespace()
    result.scalars = lambda: SimpleNamespace(all=lambda: [])
    db = SimpleNamespace()
    db.execute = _async_return(result)
    return db


def _async_return(value):
    async def _inner(*_args, **_kwargs):
        return value
    return _inner


class TestSupplierMatMapOrderBreakdown:
    def test_two_orders_merge_quantity_and_record_each_order(self):
        orders = [_po(1, 'PO-001'), _po(2, 'PO-002')]
        bom_data = {11: [_bom_row(qty=1.0)], 12: [_bom_row(qty=1.0)]}
        items_map = {
            (1, '布料A', 'S1', '米'): [SimpleNamespace(quantity=Decimal('10'))],
            (2, '布料A', 'S1', '米'): [SimpleNamespace(quantity=Decimal('5'))],
        }

        mat_map = _build_supplier_mat_map(
            orders, bom_data, items_map, {}, {},
            po_pids_map={1: [11], 2: [12]},
        )

        row = mat_map[('供应商1', '布料A', 'S1', '米')]
        assert row['total_quantity'] == 15.0
        assert row['orders'] == [
            {'order_no': 'PO-001', 'quantity': 10.0},
            {'order_no': 'PO-002', 'quantity': 5.0},
        ]

    def test_same_material_in_one_order_records_single_line(self):
        """同一张单的物料拆成多条明细 → 逐单数量合并成一条。"""
        orders = [_po(1, 'PO-001')]
        bom_data = {11: [_bom_row(qty=1.0)]}
        items_map = {
            (1, '布料A', 'S1', '米'): [
                SimpleNamespace(quantity=Decimal('6')),
                SimpleNamespace(quantity=Decimal('4')),
            ],
        }

        row = _build_supplier_mat_map(
            orders, bom_data, items_map, {}, {},
            po_pids_map={1: [11]},
        )[('供应商1', '布料A', 'S1', '米')]

        assert row['total_quantity'] == 10.0
        assert row['orders'] == [{'order_no': 'PO-001', 'quantity': 10.0}]

    def test_multisku_same_material_not_double_counted_per_order(self):
        """多 SKU 采购单共享物料：同一单只能贡献一次。"""
        orders = [_po(1, 'PO-001')]
        bom_data = {
            11: [_bom_row(qty=1.0)],
            12: [_bom_row(qty=1.0)],
        }
        items_map = {
            (1, '布料A', 'S1', '米'): [SimpleNamespace(quantity=Decimal('60'))],
        }

        row = _build_supplier_mat_map(
            orders, bom_data, items_map, {}, {},
            po_pids_map={1: [11, 12]},
        )[('供应商1', '布料A', 'S1', '米')]

        assert row['total_quantity'] == 60.0
        assert row['orders'] == [{'order_no': 'PO-001', 'quantity': 60.0}]


class TestExportGroupsOrderBreakdown:
    @pytest.mark.asyncio
    async def test_item_breakdown_merges_same_material_across_orders(self):
        orders = [
            _export_order('PO-001', [_export_item('布料A', 'S1', '米', 10.0)]),
            _export_order('PO-002', [_export_item('布料A', 'S1', '米', 5.0)]),
        ]

        group = (await build_supplier_export_groups(_empty_db(), orders))[0]

        assert group['items'][0]['order_breakdown'] == [
            {'order_no': 'PO-001', 'quantity': 10.0},
            {'order_no': 'PO-002', 'quantity': 5.0},
        ]

    @pytest.mark.asyncio
    async def test_same_order_multiple_rows_summed_into_one_breakdown_line(self):
        orders = [_export_order('PO-001', [
            _export_item('布料A', 'S1', '米', 6.0),
            _export_item('布料A', 'S1', '米', 4.0),
        ])]

        group = (await build_supplier_export_groups(_empty_db(), orders))[0]

        assert group['items'][0]['order_breakdown'] == [
            {'order_no': 'PO-001', 'quantity': 10.0},
        ]


class TestRebuildFromPageKeepsBreakdown:
    def test_page_rows_inherit_breakdown_from_db_group(self):
        db_groups = [{
            'supplier_name': '供应商1',
            'items': [{
                'material_name': '布料A', 'specification': 'S1', 'unit': '米',
                'quantity': 15.0,
                'order_breakdown': [
                    {'order_no': 'PO-001', 'quantity': 10.0},
                    {'order_no': 'PO-002', 'quantity': 5.0},
                ],
            }],
            'contact_person': '张三', 'phone': '123', 'address': '地址',
        }]
        page_row = SimpleNamespace(
            supplier_name='供应商1', material_name='布料A',
            specification='S1', unit='米', quantity=15.4,
        )

        rebuilt = rebuild_supplier_groups_from_page(db_groups, [page_row])

        item = rebuilt[0]['items'][0]
        assert item['quantity'] == 15.4
        assert item['order_breakdown'] == [
            {'order_no': 'PO-001', 'quantity': 10.0},
            {'order_no': 'PO-002', 'quantity': 5.0},
        ]

    def test_page_breakdown_takes_precedence_over_raw_db_breakdown(self):
        """页面已把合计分配成整数：导出必须用页面值，不能回退数据库原始小数。"""
        db_groups = [{
            'supplier_name': '供应商1',
            'items': [{
                'material_name': '布料A', 'specification': 'S1', 'unit': '米',
                'quantity': 15.0,
                'order_breakdown': [
                    {'order_no': 'PO-001', 'quantity': 10.0},
                    {'order_no': 'PO-002', 'quantity': 5.0},
                ],
            }],
            'contact_person': '', 'phone': '', 'address': '',
        }]
        page_row = SupplierExportQuantityItem(
            supplier_name='供应商1', material_name='布料A', specification='S1', unit='米',
            quantity=15.0,
            order_breakdown=[
                SupplierExportOrderQuantity(order_no='PO-001', quantity=8),
                SupplierExportOrderQuantity(order_no='PO-002', quantity=7),
            ],
        )

        item = rebuild_supplier_groups_from_page(db_groups, [page_row])[0]['items'][0]

        assert item['order_breakdown'] == [
            {'order_no': 'PO-001', 'quantity': 8.0},
            {'order_no': 'PO-002', 'quantity': 7.0},
        ]


class TestSupplierPrintAndExcelShowBreakdown:
    def _groups(self):
        return [{
            'supplier_name': '供应商1',
            'orders': ['PO-001', 'PO-002'],
            'order_count': 2,
            'items': [{
                'material_name': '布料A', 'specification': 'S1', 'unit': '米',
                'quantity': 15.0, 'material_category': '主料', 'order_count': 2,
                'order_breakdown': [
                    {'order_no': 'PO-001', 'quantity': 10.0},
                    {'order_no': 'PO-002', 'quantity': 5.0},
                ],
            }],
        }]

    def test_print_shows_each_order_and_quantity(self):
        page = generate_supplier_summary_print(self._groups(), [])

        assert 'PO-001×10' in page
        assert 'PO-002×5' in page

    def test_excel_note_column_contains_breakdown(self):
        wb = create_supplier_workbook(self._groups()[0])

        ws = wb.active
        note = ws.cell(row=10, column=37).value  # AK 列 = 模板「备注」
        assert note == 'PO-001×10；PO-002×5'
        wb.close()
