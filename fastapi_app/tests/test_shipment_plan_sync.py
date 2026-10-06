"""订单 → 采购计划（出货计划）分批同步 - 单元测试

覆盖 fastapi_app.services.shipment_plan_sync 的同步与删除联动，以及
order_batch_create 的接线（2026-10-06 v2 分批版设计稿）：

- 无计划条目零开销短路（不查客户、不写库）
- 客户名不在客户档案 → ValueError 整组回滚语义
- 分批落库：每批一条明细（日期/数量/批次备注正确）
- 排满口径：分批总和 ≠ 订单数量 → 前置校验拦截
- 跨月分批 → 按月分组 find-or-create
- batch_create_orders 接线：created_by 透传、同步失败触发 savepoint 回滚并裁剪回调
- 删除联动：purge 按订单号清理明细、删空主单、按月失效缓存
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.order_batch_create import batch_create_orders
from fastapi_app.services.shipment_plan_sync import (
    purge_shipment_plan_details_for_order,
    sync_order_items_to_plans,
)


def _make_product(pid, name=None, barcode=None):
    p = MagicMock()
    p.id = pid
    p.name = name or f"产品{pid}"
    p.barcode = barcode or f"BC{pid}"
    return p


def _split(plan_date, quantity, note=""):
    return {"plan_date": plan_date, "quantity": quantity, "note": note}


def _plan_item(product_id, quantity=5, plans=None, **extra):
    """带分批出货计划的 validated item（模拟 _validate_one_item 的输出形状）。

    plans 未显式给出时默认单批排满订单量（等效 v1 单日期场景）。
    """
    if plans is None:
        plans = [_split("2026-10-15", quantity)]
    item = {
        "product_id": product_id,
        "quantity": quantity,
        "product": _make_product(product_id),
        "deduct_stock": False,
        "deduct_quantity": 0,
        "note": "",
        "order_date": "",
        "shipment_plans": plans,
    }
    item.update(extra)
    return item


def _no_plan_item(product_id, quantity=5):
    return _plan_item(product_id, quantity=quantity, plans=[])


def _make_customer(cid=11, name="客户A"):
    c = MagicMock()
    c.id = cid
    c.name = name
    return c


def _make_existing_plan(plan_id=99, plan_month="2026-10"):
    plan = MagicMock()
    plan.id = plan_id
    plan.plan_month = plan_month
    plan.plan_no = f"PP-TEST-{plan_id}"
    return plan


def _make_sync_db(customer=None, existing_plans=None):
    """同步服务专用的 mock AsyncSession：按查询目标分发 execute 结果。

    - select(Customer) → scalar_one_or_none() 返回 customer（可为 None）
    - select(PurchasePlan)（IN 批量）→ scalars().all() 返回 existing_plans 列表
    """
    db = AsyncMock()
    db.add = MagicMock()

    async def _execute(stmt, *args, **kwargs):
        sql = str(stmt)
        result = MagicMock()
        if "purchase_plans" in sql:
            result.scalars.return_value.all.return_value = list(existing_plans or [])
        else:  # Customer 查询
            result.scalar_one_or_none = MagicMock(return_value=customer)
        return result

    db.execute = AsyncMock(side_effect=_execute)
    db.flush = AsyncMock()
    return db


class TestSyncOrderItemsToPlans:
    @pytest.mark.asyncio
    async def test_no_plan_items_short_circuit(self):
        """全部条目无计划 → 返回 0，不触发任何查询与写入"""
        db = _make_sync_db()
        count = await sync_order_items_to_plans(
            db, customer_name="客户A", order_no="PO-1",
            validated_items=[_no_plan_item(1), _no_plan_item(2)], created_by="tester",
        )
        assert count == 0
        db.execute.assert_not_awaited()
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_customer_not_found_raises(self):
        """客户名不在客户档案 → ValueError，文案含「客户档案中不存在客户」"""
        db = _make_sync_db(customer=None)
        with pytest.raises(ValueError, match="客户档案中不存在客户"):
            await sync_order_items_to_plans(
                db, customer_name="幽灵客户", order_no="PO-1",
                validated_items=[_plan_item(1)], created_by="tester",
            )

    @pytest.mark.asyncio
    async def test_single_batch_create_plan_path(self):
        """单批排满 → create_plan 新建主单，明细字段完整"""
        db = _make_sync_db(customer=_make_customer(), existing_plans=[])
        with patch("fastapi_app.services.shipment_plan_sync.create_plan", new_callable=AsyncMock) as mock_create, \
             patch("fastapi_app.services.shipment_plan_sync.add_details", new_callable=AsyncMock) as mock_add:
            count = await sync_order_items_to_plans(
                db, customer_name="客户A", order_no="PO-100",
                validated_items=[_plan_item(1, quantity=7, plans=[_split("2026-10-15", 7)])],
                created_by="张三",
            )
        assert count == 1
        mock_add.assert_not_awaited()
        mock_create.assert_awaited_once()
        kwargs = mock_create.await_args.kwargs
        assert kwargs["customer_id"] == 11
        assert kwargs["plan_month"] == "2026-10"
        assert kwargs["created_by"] == "张三"
        assert "PO-100" in kwargs["remark"]
        detail = kwargs["details"][0]
        assert detail["plan_date"] == "2026-10-15"
        assert detail["quantity"] == 7
        assert detail["remark"] == "来源订单:PO-100"
        assert detail["barcode"] == "BC1"

    @pytest.mark.asyncio
    async def test_multi_batch_two_details_with_notes(self):
        """500 拆 200+300 两批 → 两条明细，数量/日期/批次备注各自正确"""
        db = _make_sync_db(customer=_make_customer(), existing_plans=[])
        with patch("fastapi_app.services.shipment_plan_sync.create_plan", new_callable=AsyncMock) as mock_create:
            count = await sync_order_items_to_plans(
                db, customer_name="客户A", order_no="PO-500",
                validated_items=[_plan_item(1, quantity=500, plans=[
                    _split("2026-10-10", 200, note="首批急发"),
                    _split("2026-10-20", 300, note=""),
                ])],
                created_by="tester",
            )
        assert count == 2
        details = mock_create.await_args.kwargs["details"]
        assert details[0]["quantity"] == 200
        assert details[0]["plan_date"] == "2026-10-10"
        assert details[0]["remark"] == "来源订单:PO-500；首批急发"
        assert details[1]["quantity"] == 300
        assert details[1]["plan_date"] == "2026-10-20"
        assert details[1]["remark"] == "来源订单:PO-500"

    @pytest.mark.asyncio
    async def test_existing_plan_appends_details(self):
        """同客户同月已有计划 → 走 add_details 追加，不新建主单"""
        db = _make_sync_db(customer=_make_customer(), existing_plans=[_make_existing_plan(plan_id=99)])
        with patch("fastapi_app.services.shipment_plan_sync.create_plan", new_callable=AsyncMock) as mock_create, \
             patch("fastapi_app.services.shipment_plan_sync.add_details", new_callable=AsyncMock) as mock_add:
            count = await sync_order_items_to_plans(
                db, customer_name="客户A", order_no="PO-200",
                validated_items=[_plan_item(2, quantity=3, plans=[_split("2026-10-20", 3)])],
                created_by="tester",
            )
        assert count == 1
        mock_create.assert_not_awaited()
        mock_add.assert_awaited_once()
        args = mock_add.await_args.args
        assert args[1] == 99  # 既有主单 id（args[0] 是 db）
        assert args[2][0]["remark"] == "来源订单:PO-200"

    @pytest.mark.asyncio
    async def test_cross_month_batches_grouped_by_month(self):
        """跨月分批 → 按月分组，两个月各自 find-or-create"""
        db = _make_sync_db(customer=_make_customer(), existing_plans=[])
        with patch("fastapi_app.services.shipment_plan_sync.create_plan", new_callable=AsyncMock) as mock_create:
            count = await sync_order_items_to_plans(
                db, customer_name="客户A", order_no="PO-300",
                validated_items=[_plan_item(1, quantity=10, plans=[
                    _split("2026-10-15", 6),
                    _split("2026-11-05", 4),
                ])],
                created_by="tester",
            )
        assert count == 2
        months = {call.kwargs["plan_month"] for call in mock_create.await_args_list}
        assert months == {"2026-10", "2026-11"}


class _NestedCM:
    """模拟 db.begin_nested() 的 savepoint 上下文，记录是否回滚。"""

    def __init__(self):
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc is not None:
            self.rolled_back = True
        return False


def _make_batch_db(products):
    """batch_create_orders 集成测试用的 mock AsyncSession（参照 test_order_batch_create）。"""
    db = AsyncMock()
    db.add = MagicMock()
    db.info = {}  # post_commit_callbacks 挂载点，必须为真实 dict
    counter = {"n": 0}

    async def _flush(*args, **kwargs):
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


def _make_order_data(product_id, customer="客户A", quantity=5, **extra):
    data = {
        "product_id": product_id,
        "customer": customer,
        "quantity": quantity,
        "deduct_stock": False,
        "deduct_quantity": 0,
        "note": "",
    }
    data.update(extra)
    return data


class TestBatchCreateOrdersSyncWiring:
    @pytest.mark.asyncio
    async def test_sync_called_with_created_by(self):
        """带分批计划条目 → 同步函数被调用且 created_by 正确透传"""
        db = _make_batch_db([_make_product(1)])
        orders_data = [_make_order_data(1, quantity=10,
                                        shipment_plans=[_split("2026-10-15", 10)])]
        with patch("fastapi_app.services.numbering.generate_order_number",
                   new_callable=AsyncMock, return_value="PO-TEST-0001"), \
             patch("fastapi_app.services.order_batch_create.process_order_deduction", new_callable=AsyncMock), \
             patch("fastapi_app.services.shipment_plan_sync.sync_order_items_to_plans",
                   new_callable=AsyncMock, return_value=1) as mock_sync:
            result = await batch_create_orders(db, orders_data, created_by="录单员")
        assert result["results"][0]["success"] is True
        mock_sync.assert_awaited_once()
        kwargs = mock_sync.await_args.kwargs
        assert kwargs["created_by"] == "录单员"
        assert kwargs["customer_name"] == "客户A"

    @pytest.mark.asyncio
    async def test_sync_not_called_without_plan(self):
        """无计划条目 → 同步函数被调用但条目无计划标记（真实短路在 sync 函数内部，已有单测覆盖）"""
        db = _make_batch_db([_make_product(1)])
        orders_data = [_make_order_data(1)]
        with patch("fastapi_app.services.numbering.generate_order_number",
                   new_callable=AsyncMock, return_value="PO-TEST-0001"), \
             patch("fastapi_app.services.order_batch_create.process_order_deduction", new_callable=AsyncMock), \
             patch("fastapi_app.services.shipment_plan_sync.sync_order_items_to_plans",
                   new_callable=AsyncMock) as mock_sync:
            result = await batch_create_orders(db, orders_data)
        assert result["results"][0]["success"] is True
        mock_sync.assert_awaited_once()
        assert all(not it["shipment_plans"] for it in mock_sync.await_args.kwargs["validated_items"])

    @pytest.mark.asyncio
    async def test_sync_failure_rolls_back_group(self):
        """同步失败 → 该客户组失败、savepoint 回滚（订单与计划同生共死）"""
        db = _make_batch_db([_make_product(1)])
        orders_data = [_make_order_data(1, quantity=10,
                                        shipment_plans=[_split("2026-10-15", 10)])]
        with patch("fastapi_app.services.numbering.generate_order_number",
                   new_callable=AsyncMock, return_value="PO-TEST-0001"), \
             patch("fastapi_app.services.order_batch_create.process_order_deduction", new_callable=AsyncMock), \
             patch("fastapi_app.services.shipment_plan_sync.sync_order_items_to_plans",
                   new_callable=AsyncMock, side_effect=ValueError("客户档案中不存在客户")):
            result = await batch_create_orders(db, orders_data)
        assert result["results"][0]["success"] is False
        assert "出货计划同步失败" in result["results"][0]["error"]
        assert result["created_count"] == 0
        assert db._nested_cms[0].rolled_back is True

    @pytest.mark.asyncio
    async def test_unfilled_split_total_fails_validation(self):
        """排满口径：200+200=400 ≠ 500 → 前置校验拦截"""
        db = _make_batch_db([_make_product(1)])
        orders_data = [_make_order_data(1, quantity=500,
                                        shipment_plans=[_split("2026-10-10", 200),
                                                        _split("2026-10-20", 200)])]
        with patch("fastapi_app.services.numbering.generate_order_number",
                   new_callable=AsyncMock, return_value="PO-TEST-0001"), \
             patch("fastapi_app.services.order_batch_create.process_order_deduction", new_callable=AsyncMock):
            result = await batch_create_orders(db, orders_data)
        assert result["results"][0]["success"] is False
        assert "必须等于订单数量(500)" in result["results"][0]["error"]

    @pytest.mark.asyncio
    async def test_filled_multi_batch_passes_and_carries_notes(self):
        """排满的两批通过校验，note 原样进入 validated item"""
        db = _make_batch_db([_make_product(1)])
        orders_data = [_make_order_data(1, quantity=500,
                                        shipment_plans=[_split("2026-10-10", 200, note="首批急发"),
                                                        _split("2026-10-20", 300)])]
        with patch("fastapi_app.services.numbering.generate_order_number",
                   new_callable=AsyncMock, return_value="PO-TEST-0001"), \
             patch("fastapi_app.services.order_batch_create.process_order_deduction", new_callable=AsyncMock), \
             patch("fastapi_app.services.shipment_plan_sync.sync_order_items_to_plans",
                   new_callable=AsyncMock, return_value=2) as mock_sync:
            result = await batch_create_orders(db, orders_data)
        assert result["results"][0]["success"] is True
        plans = mock_sync.await_args.kwargs["validated_items"][0]["shipment_plans"]
        assert plans[0]["note"] == "首批急发"
        assert plans[1]["note"] == ""

    @pytest.mark.asyncio
    async def test_bad_plan_date_format_fails_validation(self):
        """日期格式非法（绕过前端手改请求）→ 前置校验拦截"""
        db = _make_batch_db([_make_product(1)])
        orders_data = [_make_order_data(1, quantity=10,
                                        shipment_plans=[_split("2026/10/15", 10)])]
        with patch("fastapi_app.services.numbering.generate_order_number",
                   new_callable=AsyncMock, return_value="PO-TEST-0001"), \
             patch("fastapi_app.services.order_batch_create.process_order_deduction", new_callable=AsyncMock):
            result = await batch_create_orders(db, orders_data)
        assert result["results"][0]["success"] is False
        assert "出货日期格式错误" in result["results"][0]["error"]

    @pytest.mark.asyncio
    async def test_non_positive_split_qty_fails_validation(self):
        """分批数量 0/负数 → 前置校验拦截"""
        db = _make_batch_db([_make_product(1)])
        orders_data = [_make_order_data(1, quantity=10,
                                        shipment_plans=[_split("2026-10-15", 0)])]
        with patch("fastapi_app.services.numbering.generate_order_number",
                   new_callable=AsyncMock, return_value="PO-TEST-0001"), \
             patch("fastapi_app.services.order_batch_create.process_order_deduction", new_callable=AsyncMock):
            result = await batch_create_orders(db, orders_data)
        assert result["results"][0]["success"] is False
        assert "分批数量必须为正整数" in result["results"][0]["error"]

    @pytest.mark.asyncio
    async def test_sync_failure_trims_own_post_commit_callbacks(self):
        """同步失败回滚后，本组注册的 post-commit 回调被裁剪（评审 P2：幽灵 plan_id 事件）"""
        db = _make_batch_db([_make_product(1)])
        db.info["post_commit_callbacks"] = ["前一组遗留回调"]

        async def _register_then_fail(*args, **kwargs):
            # 模拟 sync 过程中 create_plan 注册了回调，随后整组失败
            db.info["post_commit_callbacks"].append("本组幽灵回调")
            raise ValueError("客户档案中不存在客户")

        with patch("fastapi_app.services.numbering.generate_order_number",
                   new_callable=AsyncMock, return_value="PO-TEST-0001"), \
             patch("fastapi_app.services.order_batch_create.process_order_deduction", new_callable=AsyncMock), \
             patch("fastapi_app.services.shipment_plan_sync.sync_order_items_to_plans",
                   new_callable=AsyncMock, side_effect=_register_then_fail):
            result = await batch_create_orders(
                db, orders_data=[_make_order_data(1, quantity=10,
                                                  shipment_plans=[_split("2026-10-15", 10)])])

        assert result["results"][0]["success"] is False
        # 幽灵回调被裁剪，先前组/编排层的回调保留
        assert db.info["post_commit_callbacks"] == ["前一组遗留回调"]


def _detail_row(detail_id, plan_id):
    return SimpleNamespace(id=detail_id, plan_id=plan_id)


def _make_purge_db(*, hit_rows, affected_months, remaining_plan_ids, detail_rowcount=None, plan_rowcount=None):
    """purge 助手专用的 mock AsyncSession：按语句形态分发 execute 结果。"""
    db = AsyncMock()
    db.info = {}

    async def _execute(stmt, *args, **kwargs):
        sql = str(stmt)
        result = MagicMock()
        if sql.startswith('DELETE FROM purchase_plan_details'):
            result.rowcount = detail_rowcount if detail_rowcount is not None else len(hit_rows)
        elif sql.startswith('DELETE FROM purchase_plans'):
            result.rowcount = plan_rowcount if plan_rowcount is not None else (
                len(hit_rows and {r.plan_id for r in hit_rows} - set(remaining_plan_ids or [])) or 0)
        elif 'purchase_plan_details' in sql and 'GROUP BY' in sql:
            result.scalars.return_value.all.return_value = list(remaining_plan_ids or [])
        elif 'purchase_plans' in sql and 'plan_month' in sql:
            result.scalars.return_value.all.return_value = list(affected_months or [])
        elif 'purchase_plan_details' in sql:
            result.all.return_value = list(hit_rows)
        else:  # pragma: no cover
            raise AssertionError(f'未预期的语句: {sql[:120]}')
        return result

    db.execute = AsyncMock(side_effect=_execute)
    return db


class TestPurgeShipmentPlanDetailsForOrder:
    @pytest.mark.asyncio
    async def test_no_hits_short_circuit(self):
        """订单无同步明细 → 0/0，不产生任何删除"""
        db = _make_purge_db(hit_rows=[], affected_months=[], remaining_plan_ids=[])
        with patch('fastapi_app.services.purchase_plan_common._schedule_post_commit') as mock_sched:
            result = await purge_shipment_plan_details_for_order(db, 'PO-1')
        assert result == {'detail_deleted': 0, 'plan_deleted': 0}
        mock_sched.assert_not_called()

    @pytest.mark.asyncio
    async def test_purge_details_keeps_non_empty_plan(self):
        """计划还有其他订单的明细 → 只删本单明细，主单保留，按月失效缓存"""
        db = _make_purge_db(
            hit_rows=[_detail_row(1, 99), _detail_row(2, 99)],
            affected_months=['2026-10'],
            remaining_plan_ids=[99],  # 删除后仍有别的明细
        )
        with patch('fastapi_app.services.purchase_plan_common._schedule_post_commit') as mock_sched:
            result = await purge_shipment_plan_details_for_order(db, 'PO-100')
        assert result == {'detail_deleted': 2, 'plan_deleted': 0}
        mock_sched.assert_called_once()
        # 注册的是带月份参数的回调工厂
        cb = mock_sched.call_args.args[1]
        assert cb.__defaults__ and cb.__defaults__[0] == '2026-10'

    @pytest.mark.asyncio
    async def test_purge_removes_emptied_plan(self):
        """计划被删空 → 主单一并移除"""
        db = _make_purge_db(
            hit_rows=[_detail_row(1, 99), _detail_row(2, 99)],
            affected_months=['2026-10'],
            remaining_plan_ids=[],  # 删除后无剩余明细
        )
        with patch('fastapi_app.services.purchase_plan_common._schedule_post_commit'):
            result = await purge_shipment_plan_details_for_order(db, 'PO-100')
        assert result == {'detail_deleted': 2, 'plan_deleted': 1}

    @pytest.mark.asyncio
    async def test_purge_cross_month_invalidates_each_month(self):
        """明细跨两个月 → 每个月各注册一次缓存失效"""
        db = _make_purge_db(
            hit_rows=[_detail_row(1, 99), _detail_row(2, 100)],
            affected_months=['2026-10', '2026-11'],
            remaining_plan_ids=[],
        )
        with patch('fastapi_app.services.purchase_plan_common._schedule_post_commit') as mock_sched:
            result = await purge_shipment_plan_details_for_order(db, 'PO-300')
        assert result == {'detail_deleted': 2, 'plan_deleted': 2}
        months = {call.args[1].__defaults__[0] for call in mock_sched.call_args_list}
        assert months == {'2026-10', '2026-11'}
