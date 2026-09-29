"""批量创建订单（多 SKU 聚合）- 单元测试

覆盖 fastapi_app.services.order_batch_create.batch_create_orders 的：
- 同客户多 SKU 聚合为 1 主订单 + N OrderItem
- 多客户分组
- 单 SKU 等价旧逻辑
- 按 OrderItem 粒度的库存抵扣
- 分组级校验失败隔离
- _SavepointRollbackSignalError 触发 savepoint 回滚并继续下一组
"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.order_batch_create import (
    batch_create_orders,
)
from fastapi_app.shared_models import Order


def _make_product(pid, name=None, barcode=None):
    p = MagicMock()
    p.id = pid
    p.name = name or f"产品{pid}"
    p.barcode = barcode or f"BC{pid}"
    return p


def _make_order_data(product_id, customer="客户A", quantity=5, deduct_stock=False,
                     deduct_quantity=0, order_type="regular", note=""):
    return {
        "product_id": product_id,
        "customer": customer,
        "quantity": quantity,
        "deduct_stock": deduct_stock,
        "deduct_quantity": deduct_quantity,
        "order_type": order_type,
        "note": note,
    }


class _NestedCM:
    """模拟 db.begin_nested() 返回的 savepoint 上下文，记录是否回滚。"""

    def __init__(self):
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc is not None:
            self.rolled_back = True
        return False  # 不吞异常，让 _SavepointRollbackSignalError 向外传播


def _make_db(products):
    """构造带 id 自增 flush 与 savepoint 记录的 mock AsyncSession。"""
    db = AsyncMock()
    db.add = MagicMock()

    counter = {"n": 0}

    async def _flush(*args, **kwargs):
        # 给最近一次 db.add 且尚未赋 id 的对象分配自增 id，
        # 模拟 DB 在 flush 时为 Order/OrderItem 主键赋值。
        for call in reversed(db.add.call_args_list):
            obj = call.args[0]
            if getattr(obj, "id", None) is None:
                counter["n"] += 1
                obj.id = counter["n"]
                return

    db.flush = AsyncMock(side_effect=_flush)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = list(products)
    db.execute = AsyncMock(return_value=mock_result)

    nested_cms = []

    def _make_nested():
        cm = _NestedCM()
        nested_cms.append(cm)
        return cm

    db.begin_nested = MagicMock(side_effect=_make_nested)
    db._nested_cms = nested_cms
    return db


class TestBatchCreateOrdersAggregation:
    @pytest.mark.asyncio
    async def test_same_customer_multiple_skus_one_order(self):
        products = [_make_product(1), _make_product(2), _make_product(3)]
        db = _make_db(products)
        orders_data = [
            _make_order_data(1, customer="客户A", quantity=5),
            _make_order_data(2, customer="客户A", quantity=5),
            _make_order_data(3, customer="客户A", quantity=5),
        ]
        with patch("fastapi_app.services.numbering.generate_order_number",
                   new_callable=AsyncMock, return_value="PO-TEST-0001"), \
             patch("fastapi_app.services.order_batch_create.process_order_deduction",
                   new_callable=AsyncMock):
            result = await batch_create_orders(db, orders_data)

        assert result["results"][0]["success"] is True
        assert result["created_count"] == 1
        assert len(result["results"][0]["items"]) == 3

    @pytest.mark.asyncio
    async def test_multiple_customers_multiple_orders(self):
        products = [_make_product(1), _make_product(2), _make_product(3), _make_product(4)]
        db = _make_db(products)
        orders_data = [
            _make_order_data(1, customer="客户A", quantity=5),
            _make_order_data(2, customer="客户A", quantity=5),
            _make_order_data(3, customer="客户B", quantity=5),
            _make_order_data(4, customer="客户B", quantity=5),
        ]
        with patch("fastapi_app.services.numbering.generate_order_number",
                   new_callable=AsyncMock, side_effect=["PO-A-0001", "PO-B-0002"]), \
             patch("fastapi_app.services.order_batch_create.process_order_deduction",
                   new_callable=AsyncMock):
            result = await batch_create_orders(db, orders_data)

        assert result["created_count"] == 2
        assert len(result["results"]) == 2
        assert len(result["results"][0]["items"]) == 2
        assert len(result["results"][1]["items"]) == 2

    @pytest.mark.asyncio
    async def test_single_sku_one_order_one_item(self):
        products = [_make_product(1)]
        db = _make_db(products)
        orders_data = [_make_order_data(1, customer="客户A", quantity=5)]
        with patch("fastapi_app.services.numbering.generate_order_number",
                   new_callable=AsyncMock, return_value="PO-TEST-0001"), \
             patch("fastapi_app.services.order_batch_create.process_order_deduction",
                   new_callable=AsyncMock):
            result = await batch_create_orders(db, orders_data)

        assert result["created_count"] == 1
        assert len(result["results"]) == 1
        assert len(result["results"][0]["items"]) == 1

    @pytest.mark.asyncio
    async def test_multi_deduction_calls_process_per_deducted_item(self):
        products = [_make_product(1), _make_product(2), _make_product(3)]
        db = _make_db(products)
        orders_data = [
            _make_order_data(1, customer="客户A", quantity=5, deduct_stock=True, deduct_quantity=5),
            _make_order_data(2, customer="客户A", quantity=5, deduct_stock=True, deduct_quantity=5),
            _make_order_data(3, customer="客户A", quantity=5, deduct_stock=True, deduct_quantity=0),
        ]
        with patch("fastapi_app.services.numbering.generate_order_number",
                   new_callable=AsyncMock, return_value="PO-TEST-0001"), \
             patch("fastapi_app.services.order_batch_create.process_order_deduction",
                   new_callable=AsyncMock) as mock_deduct:
            result = await batch_create_orders(db, orders_data)

        assert mock_deduct.call_count == 2
        called_product_ids = [call.args[2] for call in mock_deduct.call_args_list]
        assert called_product_ids == [1, 2]
        # 未抵扣项（deduct_quantity=0）仍应出现在结果中
        assert len(result["results"][0]["items"]) == 3

    @pytest.mark.asyncio
    async def test_validation_failure_in_one_group_does_not_affect_others(self):
        products = [_make_product(1), _make_product(2), _make_product(3)]
        db = _make_db(products)
        orders_data = [
            _make_order_data(1, customer="客户A", quantity=0),  # 无效
            _make_order_data(2, customer="客户B", quantity=5),
            _make_order_data(3, customer="客户B", quantity=5),
        ]
        with patch("fastapi_app.services.numbering.generate_order_number",
                   new_callable=AsyncMock, return_value="PO-B-0001"), \
             patch("fastapi_app.services.order_batch_create.process_order_deduction",
                   new_callable=AsyncMock):
            result = await batch_create_orders(db, orders_data)

        assert result["results"][0]["success"] is False
        assert result["results"][0]["customer"] == "客户A"
        assert result["results"][1]["success"] is True
        assert result["results"][1]["customer"] == "客户B"
        assert result["created_count"] == 1

    @pytest.mark.asyncio
    async def test_savepoint_rollback_signal_rolls_back_and_continues(self):
        # product 999 不在 map → 触发 _SavepointRollbackSignalError
        products = [_make_product(2)]
        db = _make_db(products)
        orders_data = [
            _make_order_data(999, customer="客户A", quantity=5),
            _make_order_data(2, customer="客户B", quantity=5),
        ]
        with patch("fastapi_app.services.numbering.generate_order_number",
                   new_callable=AsyncMock, return_value="PO-B-0001"), \
             patch("fastapi_app.services.order_batch_create.process_order_deduction",
                   new_callable=AsyncMock):
            result = await batch_create_orders(db, orders_data)

        # 第一组触发 savepoint 回滚
        assert db._nested_cms[0].rolled_back is True
        assert result["results"][0]["success"] is False
        assert result["results"][0]["customer"] == "客户A"
        # 第二组继续执行并成功
        assert result["results"][1]["success"] is True
        assert result["created_count"] == 1


class TestUserSelectedOrderDate:
    """回归：下单页选择的自定义日期必须落库，不能被 now() 覆盖。"""

    def _added_order(self, db) -> Order:
        return next(
            call.args[0] for call in db.add.call_args_list
            if isinstance(call.args[0], Order)
        )

    @pytest.mark.asyncio
    async def test_custom_order_date_is_written_to_order(self):
        products = [_make_product(1)]
        db = _make_db(products)
        order_data = _make_order_data(1, customer="客户A", quantity=5)
        order_data["order_date"] = "2026-09-25"
        with patch("fastapi_app.services.numbering.generate_order_number",
                   new_callable=AsyncMock, return_value="PO-TEST-0001"), \
             patch("fastapi_app.services.order_batch_create.process_order_deduction",
                   new_callable=AsyncMock):
            result = await batch_create_orders(db, [order_data])

        assert result["created_count"] == 1
        order = self._added_order(db)
        assert order.order_date == datetime(2026, 9, 25, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_missing_order_date_falls_back_to_now(self):
        products = [_make_product(1)]
        db = _make_db(products)
        order_data = _make_order_data(1, customer="客户A", quantity=5)
        order_data["order_date"] = ""
        with patch("fastapi_app.services.numbering.generate_order_number",
                   new_callable=AsyncMock, return_value="PO-TEST-0001"), \
             patch("fastapi_app.services.order_batch_create.process_order_deduction",
                   new_callable=AsyncMock):
            result = await batch_create_orders(db, [order_data])

        assert result["created_count"] == 1
        order = self._added_order(db)
        assert order.order_date is not None
        assert order.order_date.tzinfo is not None

