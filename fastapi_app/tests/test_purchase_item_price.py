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
from fastapi_app.services.purchase_utils import (
    magnified_purchase_qty,
    resolve_item_loss_rate,
)


def _make_item(
    item_id: int,
    order_id: int,
    quantity: str,
    unit_price: str = '0',
    loss_rate: str | None = None,
) -> MagicMock:
    item = MagicMock()
    item.id = item_id
    item.order_id = order_id
    item.material_name = f'物料{item_id}'
    item.quantity = Decimal(quantity)
    item.unit_price = Decimal(unit_price)
    item.loss_rate = Decimal(loss_rate) if loss_rate is not None else None
    item.total_price = Decimal(unit_price) * Decimal(quantity)
    return item


def _make_order(order_id: int = 100, spare_rate: str | None = None) -> MagicMock:
    order = MagicMock()
    order.id = order_id
    order.order_no = 'CG-00100'
    order.status = 'pending'
    order.customer_name = '客户A'
    order.supplier_name = '供应商A'
    order.remark = ''
    order.spare_rate = Decimal(spare_rate) if spare_rate is not None else None
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

    @pytest.mark.asyncio
    async def test_amount_uses_loss_inflated_quantity(self):
        """行金额按「落库数量 × (1 + 损耗率/1000)」计价，不是按落库数量。

        落库的 quantity 是**损耗加放前**的原始用量，真正下单/结算的是加放后的
        数量（前端「数量」列展示的就是它的向上取整值）。金额若按落库数量算，
        采购单总金额会系统性低于实际采购额。
        """
        order = _make_order()
        item1 = _make_item(1, 100, '890', loss_rate='1000')
        db = _make_db([item1])
        db.get = AsyncMock(return_value=order)

        await update_purchase_order(db, 100, {
            'item_prices': [{'id': 1, 'unit_price': 5}],
        })

        # 890 × (1 + 1000‰) = 1780 → 5 × 1780 = 8900
        assert item1.total_price == Decimal('8900')
        assert order.total_amount == Decimal('8900')

    @pytest.mark.asyncio
    async def test_amount_falls_back_to_order_spare_rate(self):
        """逐行 loss_rate 为空时回退订单级 spare_rate（一键生成的明细就是这种情况）。"""
        order = _make_order(spare_rate='1000')
        item1 = _make_item(1, 100, '10', loss_rate=None)
        db = _make_db([item1])
        db.get = AsyncMock(return_value=order)

        await update_purchase_order(db, 100, {
            'item_prices': [{'id': 1, 'unit_price': 5}],
        })

        # 10 × (1 + 1000‰) = 20 → 5 × 20 = 100
        assert item1.total_price == Decimal('100')
        assert order.total_amount == Decimal('100')

    @pytest.mark.asyncio
    async def test_amount_unchanged_when_no_loss_rate(self):
        """损耗率为 0 时金额口径与旧实现一致（零回归）。"""
        order = _make_order()
        item1 = _make_item(1, 100, '10')
        db = _make_db([item1])
        db.get = AsyncMock(return_value=order)

        await update_purchase_order(db, 100, {
            'item_prices': [{'id': 1, 'unit_price': 2.5}],
        })

        assert item1.total_price == Decimal('25.00')
        assert order.total_amount == Decimal('25.00')


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

    def test_rejects_price_above_column_range(self):
        """越界单价在 schema 层拦成 422，而不是等到 flush 才炸成 500。"""
        with pytest.raises(ValidationError):
            PurchaseOrderItemPriceUpdate(id=1, unit_price=99999999999)


class TestPurchaseQtyHelpers:
    """计价数量口径的纯函数（与前端 resolveItemLossRate / magnifyByLossRate 同源）"""

    def test_resolve_item_loss_rate_prefers_item_level(self):
        assert resolve_item_loss_rate(Decimal('15'), Decimal('1000')) == 15.0

    def test_resolve_item_loss_rate_falls_back_to_order_level(self):
        assert resolve_item_loss_rate(None, Decimal('1000')) == 1000.0

    def test_resolve_item_loss_rate_zero_is_valid(self):
        """显式的 0 不再回退订单级（与前端一致）。"""
        assert resolve_item_loss_rate(Decimal('0'), Decimal('1000')) == 0.0

    def test_resolve_item_loss_rate_defaults_to_zero(self):
        assert resolve_item_loss_rate(None, None) == 0.0

    def test_magnified_purchase_qty_no_loss_rate_is_identity(self):
        assert magnified_purchase_qty(Decimal('10'), 0) == Decimal('10')

    def test_magnified_purchase_qty_applies_loss_rate(self):
        # 890 × (1 + 1000‰) = 1780
        assert magnified_purchase_qty(Decimal('890'), 1000) == Decimal('1780')
        # 920 × (1 + 15‰) = 933.8（不取整，取整是展示层的事）
        assert magnified_purchase_qty(Decimal('920'), 15) == Decimal('933.8')

    def test_magnified_purchase_qty_keeps_two_decimals(self):
        assert magnified_purchase_qty(Decimal('10.005'), 100) == Decimal('11.01')
