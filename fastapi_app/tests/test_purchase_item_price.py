"""采购单单价补录（item_prices）回归测试。

2026-10-17 审计（待核实 #1）：一键生成路径把 ``unit_price`` 写死 0（BOM 没有
价格来源），而更新请求原本不带 items 字段 → 采购单价生成后**没有任何入口**可改，
采购单金额恒为 0，供应商金额汇总（``SUM(purchase_order.total_amount)``）恒为 0。

本文件锁住补录入口的三条要求：
1. 只改单价：行金额（total_price）与订单总金额（total_amount）跟着重算，
   数量/物料/其它行**不受影响**（尤其不删行）；
2. 明细 id 必须属于本订单，重复 id 一律拒绝（不静默跳过、不半改）；
3. schema 层挡住负数单价。
"""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from fastapi_app.api.v1.endpoints.purchase_center.schemas import (
    PurchaseOrderItemPriceUpdate,
    PurchaseOrderUpdateRequest,
)
from fastapi_app.services.purchase_order_crud import update_purchase_order


def _make_item(item_id: int, order_id: int, quantity: str, unit_price: str = '0') -> MagicMock:
    item = MagicMock()
    item.id = item_id
    item.order_id = order_id
    item.material_name = f'物料{item_id}'
    item.quantity = Decimal(quantity)
    item.unit_price = Decimal(unit_price)
    item.total_price = Decimal(unit_price) * Decimal(quantity)
    return item


def _make_order(order_id: int = 100) -> MagicMock:
    order = MagicMock()
    order.id = order_id
    order.order_no = 'CG-00100'
    order.status = 'pending'
    order.customer_name = '客户A'
    order.supplier_name = '供应商A'
    order.remark = ''
    order.total_amount = Decimal('0')
    return order


def _make_db(items: list) -> MagicMock:
    db = MagicMock()
    db.get = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    db.execute = AsyncMock(return_value=result)
    return db


class TestItemPricesBackfill:
    """单价补录：落库 + 金额重算"""

    @pytest.mark.asyncio
    async def test_updates_price_and_recomputes_totals(self):
        order = _make_order()
        item1 = _make_item(1, 100, '5')
        item2 = _make_item(2, 100, '3')
        db = _make_db([item1, item2])
        db.get = AsyncMock(return_value=order)

        await update_purchase_order(db, 100, {
            'item_prices': [{'id': 1, 'unit_price': 12.5}],
        })

        assert item1.unit_price == Decimal('12.50')
        assert item1.total_price == Decimal('62.50')  # 12.5 × 5
        # 另一行不受影响
        assert item2.unit_price == Decimal('0')
        assert item2.total_price == Decimal('0')
        # 订单总金额 = 全部行之和（含未补录的行）
        assert order.total_amount == Decimal('62.50')

    @pytest.mark.asyncio
    async def test_quantizes_to_two_decimals(self):
        order = _make_order()
        item1 = _make_item(1, 100, '2')
        db = _make_db([item1])
        db.get = AsyncMock(return_value=order)

        await update_purchase_order(db, 100, {
            'item_prices': [{'id': 1, 'unit_price': 3.456}],
        })

        assert item1.unit_price == Decimal('3.46')
        assert item1.total_price == Decimal('6.92')

    @pytest.mark.asyncio
    async def test_does_not_delete_other_items(self):
        """只补录单价不得触发「未提交明细即删除」的 upsert 语义"""
        order = _make_order()
        item1 = _make_item(1, 100, '5')
        item2 = _make_item(2, 100, '3')
        db = _make_db([item1, item2])
        db.get = AsyncMock(return_value=order)

        await update_purchase_order(db, 100, {
            'item_prices': [{'id': 1, 'unit_price': 2}],
        })

        statements = [str(call.args[0]) for call in db.execute.call_args_list]
        assert not any('DELETE' in s.upper() for s in statements), statements
        assert item2.quantity == Decimal('3')

    @pytest.mark.asyncio
    async def test_rejects_item_of_other_order(self):
        """明细 id 不属于本订单（查询按 order_id 过滤，别的订单的行根本查不到）→ 拒绝"""
        order = _make_order()
        db = _make_db([])  # 本订单没有这条明细
        db.get = AsyncMock(return_value=order)

        with pytest.raises(ValueError, match='不属于该采购单'):
            await update_purchase_order(db, 100, {
                'item_prices': [{'id': 9, 'unit_price': 5}],
            })

    @pytest.mark.asyncio
    async def test_rejects_duplicate_item_id(self):
        order = _make_order()
        item1 = _make_item(1, 100, '5')
        db = _make_db([item1])
        db.get = AsyncMock(return_value=order)

        with pytest.raises(ValueError, match='重复提交单价'):
            await update_purchase_order(db, 100, {
                'item_prices': [
                    {'id': 1, 'unit_price': 5},
                    {'id': 1, 'unit_price': 9},
                ],
            })

    @pytest.mark.asyncio
    async def test_no_price_entries_keeps_totals_untouched(self):
        order = _make_order()
        order.total_amount = Decimal('88.00')
        item1 = _make_item(1, 100, '5')
        db = _make_db([item1])
        db.get = AsyncMock(return_value=order)

        await update_purchase_order(db, 100, {})

        assert item1.unit_price == Decimal('0')
        assert order.total_amount == Decimal('88.00')


class TestItemPricesSchema:
    """schema 层：负数单价挡住、dump 后是普通 dict"""

    def test_rejects_negative_price(self):
        with pytest.raises(ValidationError):
            PurchaseOrderUpdateRequest(item_prices=[{'id': 1, 'unit_price': -1}])

    def test_rejects_non_positive_id(self):
        with pytest.raises(ValidationError):
            PurchaseOrderItemPriceUpdate(id=0, unit_price=1)

    def test_dump_yields_plain_dicts(self):
        payload = PurchaseOrderUpdateRequest(
            item_prices=[{'id': 3, 'unit_price': 4.5}],
        ).model_dump(exclude_unset=True)

        assert payload == {'item_prices': [{'id': 3, 'unit_price': 4.5}]}
