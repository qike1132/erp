"""供应商汇总归并结构回归（2026-10-30 审计 A-M2）。

背景：`/purchase-center/orders/supplier-summary` 与 `summary-print?format=supplier`
原先调用 `query_supplier_groups`（只有金额聚合）并塞进 `SupplierSummaryResponse`，
字段与响应模型不匹配 → 校验 500；打印路径还会因 `group['items']` KeyError 500。

修复后两个端点统一走 `build_supplier_export_groups`（明细级归并）。本文件锁定：

1. 每项 item 带 ``order_count``（该物料出现在几张采购单）；
2. 每组带 ``orders``（去重订单号，升序）与 ``order_count``；
3. 输出能直接通过 ``SupplierSummary`` 校验（这是 500 的直接判据）；
4. 同一物料跨单合并数量，但 ``order_count`` 反映真实来源单数。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.schemas.purchase_center import SupplierSummary
from fastapi_app.services.purchase_order_query import build_supplier_export_groups


def _item(name, spec='', unit='', qty=0.0, supplier=None):
    it = MagicMock()
    it.material_name = name
    it.specification = spec
    it.unit = unit
    it.quantity = qty
    it.supplier_name = supplier
    return it


def _order(order_no, items, supplier_name=None, contact='', phone='', address=''):
    o = MagicMock()
    o.order_no = order_no
    o.items = items
    o.supplier_name = supplier_name
    o.supplier_contact_person = contact
    o.supplier_phone = phone
    o.supplier_address = address
    return o


def _db(supplier_rows=None):
    """Supplier 主数据查询返回空（走订单冗余字段回退）。"""
    result = MagicMock()
    result.scalars.return_value.all.return_value = supplier_rows or []
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_same_material_across_orders_is_merged_with_order_count():
    orders = [
        _order('PO-001', [_item('布料A', 'S1', '米', 10.0)]),
        _order('PO-002', [_item('布料A', 'S1', '米', 5.0)]),
    ]

    groups = await build_supplier_export_groups(_db(), orders)

    assert len(groups) == 1
    group = groups[0]
    assert group['supplier_name'] == '未指定供应商'
    # 跨订单合并数量，但 item 的 order_count 记录来源单数
    assert len(group['items']) == 1
    assert group['items'][0]['quantity'] == 15.0
    assert group['items'][0]['order_count'] == 2
    assert group['orders'] == ['PO-001', 'PO-002']
    assert group['order_count'] == 2


@pytest.mark.asyncio
async def test_item_order_count_is_per_material_not_per_group():
    """同一张单里两个物料：各自 order_count=1，组 order_count=1。"""
    orders = [
        _order('PO-001', [
            _item('布料A', 'S1', '米', 10.0),
            _item('填充棉', 'F1', 'kg', 2.0),
        ]),
        _order('PO-002', [_item('布料A', 'S1', '米', 5.0)]),
    ]

    group = (await build_supplier_export_groups(_db(), orders))[0]
    by_name = {i['material_name']: i for i in group['items']}

    assert by_name['布料A']['order_count'] == 2
    assert by_name['填充棉']['order_count'] == 1
    assert group['order_count'] == 2


@pytest.mark.asyncio
async def test_output_passes_supplier_summary_model():
    """输出必须能被响应模型接受（A-M2: 旧结构在此处 500）。"""
    orders = [_order('PO-001', [_item('布料A', 'S1', '米', 10.0)], supplier_name='供应商1')]

    groups = await build_supplier_export_groups(_db(), orders)

    validated = [SupplierSummary(**g) for g in groups]
    assert validated[0].supplier_name == '供应商1'
    assert validated[0].order_count == 1
    assert validated[0].items[0].order_count == 1
    assert validated[0].items[0].quantity == 10.0


@pytest.mark.asyncio
async def test_contact_falls_back_to_order_columns_when_master_missing():
    orders = [
        _order('PO-001', [_item('布料A', 'S1', '米', 1.0)], supplier_name='供应商1',
               contact='张三', phone='13800000000', address='东莞'),
    ]

    group = (await build_supplier_export_groups(_db(), orders))[0]

    assert (group['contact_person'], group['phone'], group['address']) == ('张三', '13800000000', '东莞')


@pytest.mark.asyncio
async def test_item_level_supplier_wins_over_order_level():
    """明细级供应商优先；不同供应商各自成组。"""
    orders = [
        _order('PO-001', [
            _item('布料A', 'S1', '米', 10.0, supplier='供应商1'),
            _item('布料B', 'S2', '米', 3.0, supplier='供应商2'),
        ], supplier_name='订单级供应商'),
    ]

    groups = await build_supplier_export_groups(_db(), orders)

    assert {g['supplier_name'] for g in groups} == {'供应商1', '供应商2'}
