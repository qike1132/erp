"""
湖北外发模块 单元测试

覆盖：
- SKU 工序预设 CRUD（重复工序拦截、不存在产品校验）
- 订单外发工序生成（返单自动带出、幂等去重）
- 工序状态流转（开始/完成）
- 进度看板聚合（progress / current_process / status_label）
"""
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.outsource_service import (
    batch_create_process_types,
    create_process_type,
    delete_order_process,
    delete_process_type,
    generate_order_processes,
    list_order_flows,
    list_order_processes,
    list_process_types,
    list_unshipped_processes,
    receive_order_process,
    receive_order_processes_batch,
    search_hubei_products,
    ship_order_process,
    ship_order_processes_batch,
    sync_outsource_processes_for_order,
    update_process_type,
)
from fastapi_app.shared_models import OrderItem, OrderOutsourceProcess


def make_preset(product_id=1, process_type='电绣', sort_order=0, is_active=True, pt_id=1):
    """构造 mock 工序预设对象"""
    pt = MagicMock()
    pt.id = pt_id
    pt.product_id = product_id
    pt.process_type = process_type
    pt.sort_order = sort_order
    pt.is_active = is_active
    pt.remark = None
    pt.created_by = 'admin'
    pt.create_time = datetime.now(UTC)
    pt.update_time = datetime.now(UTC)
    pt.product = MagicMock()
    pt.product.name = '测试产品'
    pt.product.barcode = 'TEST001'
    pt.product.factory = '湖北'
    return pt


def make_order_process(pid=1, order_id=1, item_id=None, product_id=1,
                       process_type='电绣', sort_order=0, status='pending'):
    """构造 mock 订单外发工序对象（数量按状态派生：received=收齐，shipped=已发未收）"""
    p = MagicMock()
    p.id = pid
    p.order_id = order_id
    p.order_item_id = item_id
    p.product_id = product_id
    p.product_name = '测试产品'
    p.process_type = process_type
    p.sort_order = sort_order
    p.status = status
    if status == 'received':
        p.shipped_quantity = 100
        p.received_quantity = 100
    elif status == 'shipped':
        p.shipped_quantity = 100
        p.received_quantity = None
    else:
        p.shipped_quantity = None
        p.received_quantity = None
    p.planned_start_time = None
    p.planned_end_time = None
    p.actual_start_time = None
    p.actual_end_time = None
    p.remark = None
    p.created_by = 'admin'
    p.create_time = datetime.now(UTC)
    p.update_time = datetime.now(UTC)
    return p


def _oracle_process_stats(processes) -> dict:
    """工序进度聚合的参照实现（改造前的 Python 口径）。

    两处使用：
    1) mock 掉数据库时，把聚合结果喂给 _attach_progress_to_orders；
    2) 真实 SQL 测试中与数据库聚合查询的结果逐一对比（改造前后一致）。
    排序与 SQL 保持一致：order_item_id（NULL 在后）、sort_order、id。
    """
    by_order: dict[int, list] = {}
    for p in processes:
        by_order.setdefault(p.order_id, []).append(p)

    stats: dict[int, SimpleNamespace] = {}
    for order_id, rows in by_order.items():
        ordered = sorted(
            rows,
            key=lambda x: (x.order_item_id is None, x.order_item_id or 0, x.sort_order or 0, x.id),
        )
        full = [
            (p.received_quantity or 0) > 0 and (p.received_quantity or 0) >= (p.shipped_quantity or 0)
            for p in ordered
        ]
        current = next((p.process_type for p, f in zip(ordered, full, strict=False) if not f), None)
        stats[order_id] = SimpleNamespace(
            order_id=order_id,
            total_processes=len(ordered),
            completed_processes=sum(1 for f in full if f),
            started_processes=sum(1 for p in ordered if (p.shipped_quantity or 0) > 0),
            current_process=current,
        )
    return stats


def _progress_results(processes) -> list[MagicMock]:
    """一页的两次窄查询结果：[进度聚合行, 有工序的 SKU 行]。"""
    agg_result = MagicMock()
    agg_result.all.return_value = list(_oracle_process_stats(processes).values())
    items_result = MagicMock()
    items_result.all.return_value = [
        (p.order_id, p.order_item_id) for p in processes if p.order_item_id is not None
    ]
    return [agg_result, items_result]


def _mock_progress_queries(mock_db, processes, *, pages: int = 10):
    """让 mock 会话依次返回「进度聚合行」与「有工序的 SKU 行」两组窄查询结果。

    _attach_progress_to_orders 每次调用会执行两次查询（每页一次），
    故按目标页数重复准备 side_effect。
    """
    mock_db.execute = AsyncMock(side_effect=_progress_results(processes) * pages)


class TestProcessTypeCRUD:
    """SKU 工序预设 CRUD"""

    @pytest.mark.asyncio
    async def test_create_success(self, mock_async_db):
        """正常创建工序预设"""
        product = MagicMock()
        product.id = 1
        product.name = '测试产品'
        product.barcode = 'TEST001'
        product.factory = '湖北'
        mock_async_db.get = AsyncMock(return_value=product)

        dup_result = MagicMock()
        dup_result.scalar_one_or_none.return_value = None
        mock_async_db.execute = AsyncMock(return_value=dup_result)

        result = await create_process_type(
            mock_async_db, {'product_id': 1, 'process_type': '电绣', 'sort_order': 0},
            username='admin',
        )

        assert result['product_id'] == 1
        assert result['process_type'] == '电绣'

    @pytest.mark.asyncio
    async def test_create_product_not_found(self, mock_async_db):
        """产品不存在"""
        mock_async_db.get = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match='产品不存在'):
            await create_process_type(
                mock_async_db, {'product_id': 999, 'process_type': '电绣'},
            )

    @pytest.mark.asyncio
    async def test_create_duplicate_process_type(self, mock_async_db):
        """同一产品重复工序类型"""
        product = MagicMock()
        product.id = 1
        mock_async_db.get = AsyncMock(return_value=product)

        dup_result = MagicMock()
        dup_result.scalar_one_or_none.return_value = 1
        mock_async_db.execute = AsyncMock(return_value=dup_result)

        with pytest.raises(ValueError, match='请勿重复添加'):
            await create_process_type(
                mock_async_db, {'product_id': 1, 'process_type': '电绣'},
            )

    @pytest.mark.asyncio
    async def test_batch_create_success(self, mock_async_db):
        """一个 SKU 批量添加多个工序（自由输入名称）"""
        product = MagicMock()
        product.id = 1
        product.name = '测试产品'
        mock_async_db.get = AsyncMock(return_value=product)

        existing_result = MagicMock()
        existing_result.all.return_value = [('电绣', 2)]  # 已有电绣（顺序 2）
        mock_async_db.execute = AsyncMock(return_value=existing_result)

        result = await batch_create_process_types(
            mock_async_db, product_id=1,
            process_types=['裁剪', '电绣', '转印'],  # 电绣重复应跳过
            username='admin',
        )

        assert result['created'] == 2
        assert result['skipped'] == 1
        # 裁剪（顺序 3）、转印（顺序 4）
        added = [c.args[0] for c in mock_async_db.add.call_args_list]
        assert [a.process_type for a in added] == ['裁剪', '转印']
        assert [a.sort_order for a in added] == [3, 4]

    @pytest.mark.asyncio
    async def test_batch_create_empty_names(self, mock_async_db):
        """批量添加：工序名称列表为空/全空白"""
        product = MagicMock()
        product.id = 1
        mock_async_db.get = AsyncMock(return_value=product)
        with pytest.raises(ValueError, match='至少填写一个'):
            await batch_create_process_types(mock_async_db, product_id=1, process_types=['', '  '])

    @pytest.mark.asyncio
    async def test_batch_create_product_not_found(self, mock_async_db):
        """批量添加：产品不存在"""
        mock_async_db.get = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match='产品不存在'):
            await batch_create_process_types(mock_async_db, product_id=999, process_types=['裁剪'])

    @pytest.mark.asyncio
    async def test_update_success(self, mock_async_db):
        """更新工序预设"""
        pt = make_preset(pt_id=5)
        mock_async_db.get = AsyncMock(return_value=pt)

        dup_result = MagicMock()
        dup_result.scalar_one_or_none.return_value = None
        mock_async_db.execute = AsyncMock(return_value=dup_result)

        result = await update_process_type(mock_async_db, 5, {'sort_order': 3})

        assert pt.sort_order == 3
        assert result['id'] == 5

    @pytest.mark.asyncio
    async def test_update_not_found(self, mock_async_db):
        """更新不存在的预设"""
        mock_async_db.get = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match='工序预设不存在'):
            await update_process_type(mock_async_db, 999, {'sort_order': 1})

    @pytest.mark.asyncio
    async def test_delete_success(self, mock_async_db):
        """删除工序预设"""
        pt = make_preset(pt_id=5)
        mock_async_db.get = AsyncMock(return_value=pt)
        await delete_process_type(mock_async_db, 5)
        mock_async_db.delete.assert_called_once_with(pt)

    @pytest.mark.asyncio
    async def test_delete_not_found(self, mock_async_db):
        """删除不存在的预设"""
        mock_async_db.get = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match='工序预设不存在'):
            await delete_process_type(mock_async_db, 999)

    @pytest.mark.asyncio
    async def test_list_process_types(self, mock_async_db):
        """查询工序预设列表"""
        pt = make_preset(pt_id=1)
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        data_result = MagicMock()
        data_result.unique.return_value.scalars.return_value.all.return_value = [pt]
        mock_async_db.execute = AsyncMock(side_effect=[count_result, data_result])

        result = await list_process_types(mock_async_db, product_id=1)

        assert result['total'] == 1
        assert result['items'][0]['process_type'] == '电绣'
        assert result['items'][0]['factory'] == '湖北'


class TestSyncOrderProcesses:
    """订单外发工序生成（返单自动带出）"""

    def _make_reload_result(self, order):
        """构造 eager-load 订单查询结果（sync 首先重新加载订单）"""
        reload_result = MagicMock()
        reload_result.unique.return_value.scalar_one_or_none.return_value = order
        return reload_result

    @pytest.mark.asyncio
    async def test_sync_creates_from_presets(self, mock_async_db):
        """根据 SKU 预设生成订单工序"""
        order = MagicMock()
        order.id = 1
        order.order_no = 'ORD-001'
        item = MagicMock()
        item.id = 11
        item.product_id = 1
        item.product_name = '测试产品'
        order.items = [item]

        reload_result = self._make_reload_result(order)
        presets_result = MagicMock()
        presets_result.scalars.return_value.all.return_value = [
            make_preset(pt_id=1, process_type='电绣', sort_order=0),
            make_preset(pt_id=2, process_type='转印', sort_order=1),
        ]
        existing_result = MagicMock()
        existing_result.all.return_value = []

        # 1) sync 重载订单(eager-load) 2) get_presets_for_products 3) existing 查询
        mock_async_db.execute = AsyncMock(side_effect=[reload_result, presets_result, existing_result])

        created, skipped = await sync_outsource_processes_for_order(mock_async_db, order, 'admin')

        assert created == 2
        assert skipped == 0
        # 生成了 2 道工序
        assert mock_async_db.add.call_count == 2

    @pytest.mark.asyncio
    async def test_sync_reloads_items_when_unloaded(self, mock_async_db):
        """回归：创建路径中 order.items 未填充时，从 DB 重新加载后仍按全量 SKU 生成"""
        # 传入的 order 对象 items 集合为空（模拟创建时 items 单独 flush）
        stale_order = MagicMock()
        stale_order.id = 1
        stale_order.items = []

        # DB 中订单有两个 SKU 明细
        fresh_order = MagicMock()
        fresh_order.id = 1
        fresh_order.order_no = 'ORD-001'
        item_a = MagicMock()
        item_a.id = 11
        item_a.product_id = 1
        item_a.product_name = '产品A'
        item_b = MagicMock()
        item_b.id = 12
        item_b.product_id = 2
        item_b.product_name = '产品B'
        fresh_order.items = [item_a, item_b]

        reload_result = self._make_reload_result(fresh_order)
        presets_result = MagicMock()
        presets_result.scalars.return_value.all.return_value = [
            make_preset(pt_id=1, product_id=1, process_type='电绣', sort_order=0),
            make_preset(pt_id=2, product_id=2, process_type='转印', sort_order=0),
        ]
        existing_result = MagicMock()
        existing_result.all.return_value = []
        mock_async_db.execute = AsyncMock(side_effect=[reload_result, presets_result, existing_result])

        created, skipped = await sync_outsource_processes_for_order(mock_async_db, stale_order, 'admin')

        assert created == 2  # 两个 SKU 各一道，而非回退到 order.product_id 只生成 1 道
        assert skipped == 0

    @pytest.mark.asyncio
    async def test_sync_skips_existing(self, mock_async_db):
        """已存在的工序跳过（幂等）"""
        order = MagicMock()
        order.id = 1
        order.order_no = 'ORD-001'
        item = MagicMock()
        item.id = 11
        item.product_id = 1
        item.product_name = '测试产品'
        order.items = [item]

        reload_result = self._make_reload_result(order)
        presets_result = MagicMock()
        presets_result.scalars.return_value.all.return_value = [
            make_preset(pt_id=1, process_type='电绣', sort_order=0),
        ]
        existing_result = MagicMock()
        existing_result.all.return_value = [
            (11, 1, '电绣'),  # (order_item_id, product_id, process_type)
        ]
        mock_async_db.execute = AsyncMock(side_effect=[reload_result, presets_result, existing_result])

        created, skipped = await sync_outsource_processes_for_order(mock_async_db, order)

        assert created == 0
        assert skipped == 1
        mock_async_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_no_presets(self, mock_async_db):
        """无预设时不生成工序"""
        order = MagicMock()
        order.id = 1
        order.items = []
        order.product_id = 1
        order.product = MagicMock()
        order.product.name = '测试产品'

        reload_result = self._make_reload_result(order)
        presets_result = MagicMock()
        presets_result.scalars.return_value.all.return_value = []
        mock_async_db.execute = AsyncMock(side_effect=[reload_result, presets_result])

        created, skipped = await sync_outsource_processes_for_order(mock_async_db, order)

        assert created == 0
        assert skipped == 0

    @pytest.mark.asyncio
    async def test_generate_order_not_found(self, mock_async_db):
        """生成工序 - 订单不存在（含备货记录 id：其 id 是 StockIn.id 而非 Order.id）"""
        reload_result = MagicMock()
        reload_result.unique.return_value.scalar_one_or_none.return_value = None
        mock_async_db.execute = AsyncMock(return_value=reload_result)
        with pytest.raises(ValueError, match='订单不存在'):
            await generate_order_processes(mock_async_db, 999)

    @pytest.mark.asyncio
    # patch 目标必须是真实定义模块：generate_order_processes 在 _order_processes 命名空间内
    # 调用 sync_outsource_processes_for_order，patch 兼容层 outsource_service 不会生效。
    @patch('fastapi_app.services.outsource._order_processes.sync_outsource_processes_for_order')
    async def test_generate_order_success(self, mock_sync, mock_async_db):
        """生成工序 - 正常"""
        order = MagicMock()
        order.id = 1
        order.is_deleted = False
        reload_result = self._make_reload_result(order)
        mock_async_db.execute = AsyncMock(return_value=reload_result)
        mock_sync.return_value = (2, 1)

        result = await generate_order_processes(mock_async_db, 1, 'admin')

        assert result['created'] == 2
        assert result['skipped'] == 1

    @pytest.mark.asyncio
    async def test_generate_deleted_order_rejected(self, mock_async_db):
        """生成工序 - 已删除订单拒绝"""
        order = MagicMock()
        order.id = 1
        order.is_deleted = True
        reload_result = self._make_reload_result(order)
        mock_async_db.execute = AsyncMock(return_value=reload_result)
        with pytest.raises(ValueError, match='订单不存在'):
            await generate_order_processes(mock_async_db, 1)


class TestProcessStatusFlow:
    """工序状态流转（发货 → 确认收货）"""

    @pytest.mark.asyncio
    async def test_ship_process(self, mock_async_db):
        """发货工序：记录发货数量，状态 → shipped"""
        # 第八轮落地：_process_target_quantity 改为 fail-closed（无明细拒绝发货），
        # 发货用例统一用 item_id + fake_get 提供 SKU 数量。
        p = make_order_process(pid=1, item_id=1)
        item = MagicMock()
        item.quantity = 100
        async def fake_get(model, pk, **_kwargs):
            return item if model is OrderItem else p
        mock_async_db.get = AsyncMock(side_effect=fake_get)

        result = await ship_order_process(mock_async_db, 1, 50, 'admin')

        assert result['status'] == 'shipped'
        assert p.shipped_quantity == 50
        assert p.actual_start_time is not None

    @pytest.mark.asyncio
    async def test_ship_partially_received_process(self, mock_async_db):
        """回归：已部分收货但未发满的工序，仍可继续发下一批（收货只闭环本批）。"""
        p = make_order_process(pid=1, item_id=1)
        p.shipped_quantity = 40
        p.received_quantity = 40
        item = MagicMock()
        item.quantity = 100
        # db.get：工序返回 p，OrderItem 返回带目标数量的 item
        async def fake_get(model, pk, **_kwargs):
            return item if model is OrderItem else p
        mock_async_db.get = AsyncMock(side_effect=fake_get)

        result = await ship_order_process(mock_async_db, 1, 60, 'admin')

        assert p.shipped_quantity == 100
        assert result['status'] == 'shipped'

    @pytest.mark.asyncio
    async def test_ship_fully_shipped_process(self, mock_async_db):
        """已发满目标数量的工序无法再发货"""
        p = make_order_process(pid=1, item_id=1)
        p.shipped_quantity = 100
        p.received_quantity = 100
        item = MagicMock()
        item.quantity = 100
        async def fake_get(model, pk, **_kwargs):
            return item if model is OrderItem else p
        mock_async_db.get = AsyncMock(side_effect=fake_get)

        with pytest.raises(ValueError, match='已全部发货'):
            await ship_order_process(mock_async_db, 1, 50)

    @pytest.mark.asyncio
    async def test_receive_process(self, mock_async_db):
        """确认收货：状态 → received，收货数量默认等于发货数量"""
        p = make_order_process(pid=1, status='shipped')
        p.shipped_quantity = 50
        mock_async_db.get = AsyncMock(return_value=p)

        result = await receive_order_process(mock_async_db, 1, 'admin')

        assert result['status'] == 'received'
        assert p.received_quantity == 50
        assert p.actual_end_time is not None

    @pytest.mark.asyncio
    async def test_receive_process_custom_quantity(self, mock_async_db):
        """确认收货：传入 received_quantity 时按自定义收货数量记录（部分收货状态仍为 shipped）"""
        p = make_order_process(pid=1, status='shipped')
        p.shipped_quantity = 50
        mock_async_db.get = AsyncMock(return_value=p)

        result = await receive_order_process(mock_async_db, 1, 'admin', received_quantity=30)

        assert result['status'] == 'shipped'
        assert p.received_quantity == 30

    @pytest.mark.asyncio
    async def test_ship_batch_accumulate(self, mock_async_db):
        """分批发货：多次发货数量累加，且每次追加流水"""
        p = make_order_process(pid=1, item_id=1)
        item = MagicMock()
        item.quantity = 100
        async def fake_get(model, pk, **_kwargs):
            return item if model is OrderItem else p
        mock_async_db.get = AsyncMock(side_effect=fake_get)

        await ship_order_process(mock_async_db, 1, 50, 'admin')
        result = await ship_order_process(mock_async_db, 1, 30, 'admin')

        assert p.shipped_quantity == 80
        assert result['status'] == 'shipped'
        # 两次发货各追加一条 ship 流水
        flows = [c.args[0] for c in mock_async_db.add.call_args_list]
        ship_flows = [f for f in flows if getattr(f, 'action', None) == 'ship']
        assert len(ship_flows) == 2
        assert ship_flows[0].quantity == 50
        assert ship_flows[1].quantity == 30

    @pytest.mark.asyncio
    async def test_ship_exceed_remaining(self, mock_async_db):
        """分批发货：超过剩余目标数量被拒绝"""
        p = make_order_process(pid=1, item_id=1)
        p.shipped_quantity = 80
        item = MagicMock()
        item.quantity = 100
        # db.get：进程返回 p，OrderItem 返回带数量的 item
        # （**_kwargs 兼容 with_for_update 等关键字参数）
        async def fake_get(model, pk, **_kwargs):
            return item if model is OrderItem else p
        mock_async_db.get = AsyncMock(side_effect=fake_get)

        with pytest.raises(ValueError, match='超过剩余数量'):
            await ship_order_process(mock_async_db, 1, 30)

    @pytest.mark.asyncio
    async def test_receive_batch_accumulate(self, mock_async_db):
        """分批收货：多次收货数量累加，未收齐前状态仍为 shipped"""
        p = make_order_process(pid=1, status='shipped')
        p.shipped_quantity = 100
        p.received_quantity = None
        mock_async_db.get = AsyncMock(return_value=p)

        first = await receive_order_process(mock_async_db, 1, '贝乐', received_quantity=30)
        assert first['status'] == 'shipped'
        assert p.received_quantity == 30

        second = await receive_order_process(mock_async_db, 1, '贝乐', received_quantity=70)
        assert second['status'] == 'received'
        assert p.received_quantity == 100

    @pytest.mark.asyncio
    async def test_receive_exceed_shipped(self, mock_async_db):
        """分批收货：超过已发货数量被拒绝"""
        p = make_order_process(pid=1, status='shipped')
        p.shipped_quantity = 50
        p.received_quantity = None
        mock_async_db.get = AsyncMock(return_value=p)

        with pytest.raises(ValueError, match='收货数量需在'):
            await receive_order_process(mock_async_db, 1, '贝乐', received_quantity=60)

    @pytest.mark.asyncio
    async def test_list_order_flows(self, mock_async_db):
        """流水列表：返回工序名/动作/数量/操作人/时间"""
        flow = MagicMock()
        flow.id = 1
        flow.process_id = 1
        flow.action = 'ship'
        flow.quantity = 50
        flow.operator = 'admin'
        flow.create_time = datetime.now(UTC)
        proc_result = MagicMock()
        proc_result.all.return_value = [(flow, '电绣')]
        mock_async_db.execute = AsyncMock(return_value=proc_result)

        result = await list_order_flows(mock_async_db, 1)

        assert result[0]['process_type'] == '电绣'
        assert result[0]['action'] == 'ship'
        assert result[0]['quantity'] == 50
        assert result[0]['operator'] == 'admin'

    @pytest.mark.asyncio
    async def test_receive_not_shipped_process(self, mock_async_db):
        """未发货工序无法确认收货"""
        p = make_order_process(pid=1, status='pending')
        mock_async_db.get = AsyncMock(return_value=p)

        with pytest.raises(ValueError, match='尚未发货'):
            await receive_order_process(mock_async_db, 1)

    @pytest.mark.asyncio
    async def test_receive_process_not_found(self, mock_async_db):
        """收货不存在的工序"""
        mock_async_db.get = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match='外发工序不存在'):
            await receive_order_process(mock_async_db, 999)

    @pytest.mark.asyncio
    async def test_delete_process(self, mock_async_db):
        """删除工序"""
        p = make_order_process(pid=1)
        mock_async_db.get = AsyncMock(return_value=p)
        await delete_order_process(mock_async_db, 1)
        mock_async_db.delete.assert_called_once_with(p)

    @pytest.mark.asyncio
    async def test_list_order_processes(self, mock_async_db):
        """查询订单工序列表"""
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = [
            make_order_process(pid=1, process_type='电绣'),
            make_order_process(pid=2, process_type='转印'),
        ]
        mock_async_db.execute = AsyncMock(return_value=data_result)

        result = await list_order_processes(mock_async_db, 1)

        assert len(result) == 2
        assert result[0]['process_type'] == '电绣'


class TestOrderListProgress:
    """订单列表附加外发工序进度（看板合并进订单列表）"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order_crud.get_beile_orders_with_stockins')
    async def test_orders_attach_progress(self, mock_beile, mock_async_db):
        """订单列表条目附带 progress/status_label，备货记录标记未配置"""
        from fastapi_app.services.outsource_service import list_outsource_orders
        mock_beile.return_value = {
            'items': [
                {'id': 1, 'record_type': 'order', 'order_no': 'PO-1'},
                {'id': 2, 'record_type': 'order', 'order_no': 'PO-2'},
                {'id': 99, 'record_type': 'stockin', 'stockin_no': 'BH-1'},
            ],
            'total': 3, 'page': 1, 'per_page': 50,
        }
        _mock_progress_queries(mock_async_db, [
            make_order_process(pid=1, order_id=1, process_type='电绣', status='received'),
            make_order_process(pid=2, order_id=1, process_type='转印', status='received'),
            make_order_process(pid=3, order_id=1, process_type='配件', status='pending'),
            make_order_process(pid=4, order_id=2, process_type='裁剪', status='received'),
        ])

        result = await list_outsource_orders(mock_async_db, page=1, per_page=50)

        items = result['items']
        order1 = next(i for i in items if i['id'] == 1)
        order2 = next(i for i in items if i['id'] == 2)
        stockin = next(i for i in items if i['id'] == 99)
        assert order1['total_processes'] == 3
        assert order1['completed_processes'] == 2
        assert order1['progress'] == 67
        assert order1['current_process'] == '配件'
        assert '进行中' in order1['status_label']
        assert order2['progress'] == 100
        assert order2['status_label'] == '外发完成'
        assert stockin['progress'] == 0
        assert stockin['status_label'] == '未配置工序'

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order_crud.get_beile_orders_with_stockins')
    async def test_orders_attach_progress_no_processes(self, mock_beile, mock_async_db):
        """无任何工序时列表项标记未配置"""
        from fastapi_app.services.outsource_service import list_outsource_orders
        mock_beile.return_value = {
            'items': [{'id': 1, 'record_type': 'order', 'order_no': 'PO-1'}],
            'total': 1, 'page': 1, 'per_page': 50,
        }
        _mock_progress_queries(mock_async_db, [])

        result = await list_outsource_orders(mock_async_db)

        item = result['items'][0]
        assert item['progress'] == 0
        assert item['status_label'] == '未配置工序'
        assert item['current_process'] is None

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order_crud.get_beile_orders_with_stockins')
    async def test_orders_filter_by_process_status(self, mock_beile, mock_async_db):
        """按工序整体状态过滤：待开始/进行中/已完成，未配置订单不属于任何状态"""
        from fastapi_app.services.outsource_service import list_outsource_orders
        mock_beile.return_value = {
            'items': [
                {'id': 1, 'record_type': 'order', 'order_no': 'PO-1'},   # 全部 pending → 待发货
                {'id': 2, 'record_type': 'order', 'order_no': 'PO-2'},   # 部分收货 → 进行中
                {'id': 3, 'record_type': 'order', 'order_no': 'PO-3'},   # 全部收货 → 已完成
                {'id': 4, 'record_type': 'order', 'order_no': 'PO-4'},   # 无工序 → 未配置
                {'id': 5, 'record_type': 'stockin', 'stockin_no': 'BH-1'},
            ],
            'total': 5, 'page': 1, 'per_page': 500,
        }
        _mock_progress_queries(mock_async_db, [
            make_order_process(pid=1, order_id=1, process_type='裁剪', status='pending'),
            make_order_process(pid=2, order_id=1, process_type='电绣', status='pending'),
            make_order_process(pid=3, order_id=2, process_type='裁剪', status='received'),
            make_order_process(pid=4, order_id=2, process_type='电绣', status='pending'),
            make_order_process(pid=5, order_id=3, process_type='裁剪', status='received'),
            make_order_process(pid=6, order_id=3, process_type='电绣', status='received'),
        ], pages=30)

        pending = await list_outsource_orders(mock_async_db, page=1, per_page=50, process_status='pending')
        in_progress = await list_outsource_orders(mock_async_db, page=1, per_page=50, process_status='in_progress')
        completed = await list_outsource_orders(mock_async_db, page=1, per_page=50, process_status='completed')

        assert [r['id'] for r in pending['items']] == [1]
        assert pending['total'] == 1
        assert pending['items'][0]['status_label'] == '待发货'
        assert [r['id'] for r in in_progress['items']] == [2]
        assert in_progress['total'] == 1
        assert in_progress['items'][0]['status_label'] == '进行中（电绣）'
        assert [r['id'] for r in completed['items']] == [3]
        assert completed['total'] == 1
        assert completed['items'][0]['status_label'] == '外发完成'

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order_crud.get_beile_orders_with_stockins')
    async def test_orders_filter_by_process_status_pagination(self, mock_beile, mock_async_db):
        """状态过滤后再分页：page/per_page 作用于过滤结果"""
        from fastapi_app.services.outsource_service import list_outsource_orders
        mock_beile.return_value = {
            'items': [
                {'id': i, 'record_type': 'order', 'order_no': f'PO-{i}'}
                for i in range(1, 5)
            ],
            'total': 4, 'page': 1, 'per_page': 500,
        }
        _mock_progress_queries(mock_async_db, [
            make_order_process(pid=i, order_id=i, process_type='裁剪', status='pending')
            for i in range(1, 5)
        ], pages=20)

        page1 = await list_outsource_orders(mock_async_db, page=1, per_page=2, process_status='pending')
        page2 = await list_outsource_orders(mock_async_db, page=2, per_page=2, process_status='pending')

        assert page1['total'] == 4
        assert [r['id'] for r in page1['items']] == [1, 2]
        assert [r['id'] for r in page2['items']] == [3, 4]
        assert page1['page'] == 1 and page2['page'] == 2


class TestOutsourceRegressions:
    """回归测试：对应本轮修复的缺陷（修复前失败，修复后通过）"""

    @pytest.mark.asyncio
    async def test_ship_locks_process_row(self, mock_async_db):
        """并发保护：发货读取工序行时必须加行锁（FOR UPDATE）

        数量是「读-改-写」，不加锁时并发发货会相互覆盖（丢失更新）。
        """
        p = make_order_process(pid=1, item_id=1)
        item = MagicMock()
        item.quantity = 100
        async def fake_get(model, pk, **_kwargs):
            return item if model is OrderItem else p
        mock_async_db.get = AsyncMock(side_effect=fake_get)

        await ship_order_process(mock_async_db, 1, 10, 'admin')

        first_call = mock_async_db.get.await_args_list[0]
        assert first_call.args[0] is OrderOutsourceProcess
        assert first_call.kwargs.get('with_for_update') is True

    @pytest.mark.asyncio
    async def test_receive_locks_process_row(self, mock_async_db):
        """并发保护：收货同样需要行锁（同一工序可分批收货）"""
        p = make_order_process(pid=1, status='shipped')
        p.shipped_quantity = 50
        mock_async_db.get = AsyncMock(return_value=p)

        await receive_order_process(mock_async_db, 1, '贝乐')

        first_call = mock_async_db.get.await_args_list[0]
        assert first_call.args[0] is OrderOutsourceProcess
        assert first_call.kwargs.get('with_for_update') is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order_crud.get_beile_orders_with_stockins')
    async def test_process_status_filter_scans_all_pages(self, mock_beile, mock_async_db):
        """回归：状态筛选必须遍历全部页，不能只取首页 500 条

        修复前固定 page=1&per_page=500，第 501 条起的命中订单被静默丢弃。
        """
        from fastapi_app.services.outsource_service import list_outsource_orders
        mock_beile.side_effect = [
            {
                'items': [{'id': i, 'record_type': 'order', 'order_no': f'PO-{i}'} for i in range(1, 501)],
                'total': 501, 'page': 1, 'per_page': 500,
            },
            {
                'items': [{'id': 501, 'record_type': 'order', 'order_no': 'PO-501'}],
                'total': 501, 'page': 2, 'per_page': 500,
            },
        ]
        # 唯一一道「待发货」工序挂在第 501 条订单上（首页取不到）
        page2_processes = [
            make_order_process(pid=1, order_id=501, process_type='裁剪', status='pending'),
        ]
        mock_async_db.execute = AsyncMock(
            side_effect=_progress_results([]) + _progress_results(page2_processes)
        )

        result = await list_outsource_orders(
            mock_async_db, page=1, per_page=50, process_status='pending',
        )

        assert mock_beile.call_count == 2, '状态筛选必须继续取第 2 页'
        assert result['total'] == 1
        assert [r['id'] for r in result['items']] == [501]

    @pytest.mark.asyncio
    @patch('fastapi_app.services.outsource._common._load_process_item_ids', new_callable=AsyncMock)
    @patch('fastapi_app.services.outsource._common._load_process_stats', new_callable=AsyncMock)
    async def test_progress_query_excludes_stockin_ids(self, mock_stats, mock_item_ids, mock_async_db):
        """备货记录 id 与订单 id 不同域：进度查询只能带订单 id（防止串号挂错工序）

        备货记录（record_type='stockin'）的 id 与订单 id 是两套编号，
        若一起放进 order_id IN (...) 会把无关订单的工序挂到备货行上。
        """
        from fastapi_app.services.outsource._common import _attach_progress_to_orders

        mock_stats.return_value = {}
        mock_item_ids.return_value = {}
        items = [
            {'id': 7, 'record_type': 'order', 'items': [{'id': 11}]},
            {'id': 3, 'record_type': 'stockin', 'stockin_no': 'BH-1'},
        ]

        await _attach_progress_to_orders(mock_async_db, items)

        assert mock_stats.await_args.args[1] == [7], '备货 id 不得进入工序进度查询'
        assert items[1]['status_label'] == '未配置工序'
        assert items[1]['total_processes'] == 0


class TestProcessProgressSqlAggregation:
    """进度统计下推数据库：SQL 聚合结果与改造前的 Python 口径逐一对比"""

    # (id, order_id, order_item_id, process_type, sort_order, status, shipped, received)
    SPECS: ClassVar[list[tuple]] = [
        # 订单 1：3 道工序，2 已收齐 + 1 未发货 → 进行中（配件）
        (1, 1, 11, '电绣', 0, 'received', 10, 10),
        (2, 1, 11, '转印', 1, 'received', 10, 10),
        (3, 1, 11, '配件', 2, 'pending', None, None),
        # 订单 2：全部收齐 → 外发完成
        (4, 2, 21, '裁剪', 0, 'received', 5, 5),
        # 订单 3：已发未收 → 进行中
        (5, 3, 31, '电绣', 0, 'shipped', 8, None),
        (6, 3, 31, '裁剪', 1, 'shipped', 8, 3),
        # 订单 4：全部未发货 → 待发货
        (7, 4, 41, '电绣', 0, 'pending', 0, None),
    ]

    @staticmethod
    def _specs_as_objects():
        return [
            SimpleNamespace(
                id=r[0], order_id=r[1], order_item_id=r[2], process_type=r[3],
                sort_order=r[4], status=r[5], shipped_quantity=r[6], received_quantity=r[7],
            )
            for r in TestProcessProgressSqlAggregation.SPECS
        ]

    @staticmethod
    async def _session(tmp_path):
        """真实 SQLite 库（仅建外发工序相关表），用于验证聚合 SQL 语义"""
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "oosp.db"}')
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: OrderOutsourceProcess.__table__.create(c, checkfirst=True)
            )
        return engine, async_sessionmaker(engine, expire_on_commit=False)

    @pytest.mark.asyncio
    async def test_sql_aggregation_matches_python_oracle(self, tmp_path):
        """改造前后结果一致：数据库聚合 == 旧 Python 汇总（含 current_process）"""
        from fastapi_app.services.outsource._common import (
            _format_process_progress,
            _load_process_stats,
        )

        engine, session_factory = await self._session(tmp_path)
        try:
            async with session_factory() as session:
                for r in self.SPECS:
                    session.add(OrderOutsourceProcess(
                        id=r[0], order_id=r[1], order_item_id=r[2], product_id=1,
                        product_name='测试产品', process_type=r[3], sort_order=r[4],
                        status=r[5], shipped_quantity=r[6], received_quantity=r[7],
                    ))
                await session.commit()

            async with session_factory() as session:
                stats = await _load_process_stats(session, [1, 2, 3, 4, 999])

            expected: dict[int, dict] = {}
            for order_id, row in _oracle_process_stats(self._specs_as_objects()).items():
                expected[order_id] = _format_process_progress(
                    total=row.total_processes,
                    completed=row.completed_processes,
                    started=row.started_processes,
                    current_process=row.current_process,
                )

            assert stats == expected
            # 抽查关键口径，避免“两边都错成一样”时用例失去意义
            assert stats[1]['progress'] == 67
            assert stats[1]['current_process'] == '配件'
            assert stats[3]['status_label'] == '进行中（电绣）'
            assert stats[4]['status_label'] == '待发货'
            assert stats[2]['status_label'] == '外发完成'
            assert 999 not in stats
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order_crud.get_beile_orders_with_stockins')
    async def test_progress_query_count_is_constant_per_page(self, mock_beile, mock_async_db):
        """进度查询次数与订单数/工序数无关：每页固定 2 条窄查询（聚合 + 有工序的 SKU）"""
        from fastapi_app.services.outsource._common import _attach_progress_to_orders

        processes = [
            make_order_process(pid=o * 10 + k, order_id=o, item_id=o, process_type=f'工序{k}')
            for o in range(1, 41) for k in range(3)
        ]
        _mock_progress_queries(mock_async_db, processes)
        items = [{'id': o, 'record_type': 'order', 'items': [{'id': o}]} for o in range(1, 41)]

        await _attach_progress_to_orders(mock_async_db, items)

        # 改造前：按订单拉取全部工序行（此处必然是 1 次大查询 + Python 循环），
        # 改造后：固定 2 次（聚合行 + SKU 标记），不随订单/工序数量增长
        assert mock_async_db.execute.await_count == 2
        assert all(item['total_processes'] == 3 for item in items)
        assert all(sku['has_processes'] for item in items for sku in item['items'])


class TestBatchShipReceive:
    """批量发货/收货：单事务内逐条复用单条发货/收货逻辑，失败即抛错回滚整批"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.outsource._order_processes.ship_order_process')
    async def test_batch_ship_reuses_single_path_and_does_not_commit(self, mock_ship, mock_async_db):
        """批量发货逐条复用带行锁的单条发货；服务层不得自行 commit（事务边界归端点）"""
        mock_ship.side_effect = [{'id': 1, 'order_id': 7}, {'id': 2, 'order_id': 7}]

        items = await ship_order_processes_batch(mock_async_db, 7, [(1, 5), (2, 3)], 'admin')

        assert [i['id'] for i in items] == [1, 2]
        assert [c.args[1:] for c in mock_ship.await_args_list] == [(1, 5, 'admin'), (2, 3, 'admin')]
        mock_async_db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch('fastapi_app.services.outsource._order_processes.ship_order_process')
    async def test_batch_ship_failure_names_process_and_aborts(self, mock_ship, mock_async_db):
        """任一条失败：抛错并指明工序，由外层事务整批回滚（不留下部分成功）"""
        mock_ship.side_effect = [
            {'id': 1, 'order_id': 7},
            ValueError('发货数量超过剩余数量（剩余 3）'),
        ]

        with pytest.raises(ValueError, match='外发工序 2：发货数量超过剩余数量'):
            await ship_order_processes_batch(mock_async_db, 7, [(1, 5), (2, 9)], 'admin')
        assert mock_ship.await_count == 2

    @pytest.mark.asyncio
    @patch('fastapi_app.services.outsource._order_processes.ship_order_process')
    async def test_batch_ship_rejects_process_from_other_order(self, mock_ship, mock_async_db):
        """防越权：批量接口只允许操作路径上的订单自己的工序"""
        mock_ship.return_value = {'id': 1, 'order_id': 999}

        with pytest.raises(ValueError, match='不属于订单 7'):
            await ship_order_processes_batch(mock_async_db, 7, [(1, 5)], 'admin')

    @pytest.mark.asyncio
    @patch('fastapi_app.services.outsource._order_processes.receive_order_process')
    async def test_batch_receive_passes_quantity_and_operator(self, mock_receive, mock_async_db):
        """批量收货把本批数量与操作人透传给单条收货（None 表示按剩余待收）"""
        mock_receive.side_effect = [
            {'id': 1, 'order_id': 7}, {'id': 2, 'order_id': 7},
        ]

        await receive_order_processes_batch(mock_async_db, 7, [(1, 4), (2, None)], '收货员')

        assert [c.args[1:] for c in mock_receive.await_args_list] == [(1, '收货员'), (2, '收货员')]
        assert [c.kwargs['received_quantity'] for c in mock_receive.await_args_list] == [4, None]


class TestShipReceivePermissions:
    """发货/收货改为权限点：outsource_ship / outsource_receive（不再按用户名 == 贝乐 硬编码）"""

    @staticmethod
    def _route_permission(suffix: str, method: str = 'POST') -> str | None:
        """取出该路由声明的权限点名称（require_permission 挂的 __permission_codes__）"""
        from fastapi_app.api.v1.endpoints.outsource import router

        for route in router.routes:
            if not getattr(route, 'path', '').endswith(suffix) or method not in route.methods:
                continue
            for dep in route.dependant.dependencies:
                codes = getattr(dep.call, '__permission_codes__', None)
                if codes:
                    # 只认单码声明（require_permission）：多码的 require_any_permission 返回
                    # None，这样路由一旦从单码放宽成「任一码」，下面的断言就会失败。
                    return codes[0] if len(codes) == 1 else None
        return None

    def test_ship_and_receive_routes_use_permission_points(self):
        assert self._route_permission('/processes/{process_id}/ship') == 'outsource_ship'
        assert self._route_permission('/processes/{process_id}/receive') == 'outsource_receive'
        assert self._route_permission('/orders/{order_id}/processes/ship-batch') == 'outsource_ship'
        assert self._route_permission('/orders/{order_id}/processes/receive-batch') == 'outsource_receive'

    def test_ship_and_receive_are_independent_permissions(self):
        """发货与收货是两个独立权限点：同一账号可分别授予（原实现两者互斥）"""
        assert self._route_permission('/processes/{process_id}/ship') != self._route_permission(
            '/processes/{process_id}/receive'
        )


class TestConcurrencyAndLegacyData:
    """并发与异常路径：并发发货不丢量、旧数据 status 与数量不一致、缓存命中时进度新鲜度"""

    @staticmethod
    async def _session(tmp_path):
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from fastapi_app.shared_models import OrderOutsourceProcessFlow

        engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "oosp.db"}')
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: OrderOutsourceProcess.__table__.create(c, checkfirst=True)
            )
            await conn.run_sync(
                lambda c: OrderOutsourceProcessFlow.__table__.create(c, checkfirst=True)
            )
        return engine, async_sessionmaker(engine, expire_on_commit=False)

    @pytest.mark.asyncio
    async def test_two_ship_calls_accumulate_without_losing_quantity(self, tmp_path):
        """两次发货不丢量：按「锁内读到的累计值 + 本次数量」累加，流水逐次留痕

        注：SQLite 不支持 SELECT ... FOR UPDATE（无法在本用例中重现真正的并发竞争），
        「读-改-写 必须拿行锁」由 test_ship_locks_process_row / test_receive_locks_process_row
        直接断言；本用例验证累加语义与流水条数在真实库上成立。
        """
        from sqlalchemy import func, select

        from fastapi_app.services.outsource import _order_processes as mod
        from fastapi_app.shared_models import OrderOutsourceProcessFlow

        engine, session_factory = await self._session(tmp_path)
        try:
            async with session_factory() as session:
                session.add(OrderOutsourceProcess(
                    id=1, order_id=1, order_item_id=None, product_id=1, product_name='测试产品',
                    process_type='电绣', sort_order=0, status='pending',
                    shipped_quantity=None, received_quantity=None,
                ))
                await session.commit()

            async with session_factory() as session:
                with patch.object(mod, '_process_target_quantity', AsyncMock(return_value=100)):
                    await mod.ship_order_process(session, 1, 5, '甲')
                    await mod.ship_order_process(session, 1, 3, '乙')
                await session.commit()

            async with session_factory() as session:
                p = await session.get(OrderOutsourceProcess, 1)
                flow_count = await session.scalar(
                    select(func.count()).select_from(OrderOutsourceProcessFlow)
                )

            assert p.shipped_quantity == 8, '第二次发货必须基于第一次的累计值，不能覆盖'
            assert p.status == 'shipped'
            assert flow_count == 2, '每次发货各留一条流水'
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_legacy_row_with_stale_status_is_derived_from_quantities(self, tmp_path):
        """旧数据 status 与数量不一致（status='received' 但没收到货）：以数量为准，写回时自愈

        - 进度聚合不信任 status 列，按数量派生 → 不会误报「外发完成」
        - 发货/收货的准入判定同样按数量（_is_fully_received）→ 旧行仍可正常发/收货
        - 写回时用数量重算 status，把不一致的旧值纠正过来
        """
        from fastapi_app.services.outsource import _order_processes as mod
        from fastapi_app.services.outsource._common import _load_process_stats

        engine, session_factory = await self._session(tmp_path)
        try:
            async with session_factory() as session:
                session.add(OrderOutsourceProcess(
                    id=1, order_id=1, order_item_id=None, product_id=1, product_name='测试产品',
                    process_type='电绣', sort_order=0,
                    status='received',          # 旧数据：status 声称已收货
                    shipped_quantity=10, received_quantity=0,   # 但数量根本没收
                ))
                await session.commit()

            async with session_factory() as session:
                stats = await _load_process_stats(session, [1])

            assert stats[1]['completed_processes'] == 0, '进度按数量派生，不被 status 列误导'
            assert stats[1]['progress'] == 0
            assert stats[1]['status_label'] == '进行中（电绣）'

            async with session_factory() as session:
                item = await mod.receive_order_process(session, 1, '收货员')
                await session.commit()

            assert item['status'] == 'received'
            async with session_factory() as session:
                p = await session.get(OrderOutsourceProcess, 1)
            assert p.received_quantity == 10
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    @patch('fastapi_app.services.order_crud.get_beile_orders_with_stockins')
    async def test_cached_order_list_still_gets_fresh_progress(self, mock_beile, mock_async_db):
        """订单列表命中缓存（同一 list 对象）时：进度必须按本次数据库结果重算

        get_beile_orders_with_stockins 带 @cache_result(ttl=60)，进度不在其缓存键内，
        因此每次请求都要重新聚合；同时进度不能就地写回缓存对象。
        """
        from fastapi_app.services.outsource_service import list_outsource_orders

        cached_items = [{'id': 1, 'record_type': 'order', 'order_no': 'PO-1'}]
        mock_beile.return_value = {
            'items': cached_items, 'total': 1, 'page': 1, 'per_page': 50,
        }
        pending = [make_order_process(pid=1, order_id=1, process_type='电绣', status='pending')]
        received = [make_order_process(pid=1, order_id=1, process_type='电绣', status='received')]
        mock_async_db.execute = AsyncMock(
            side_effect=_progress_results(pending) + _progress_results(received)
        )

        first = await list_outsource_orders(mock_async_db, page=1, per_page=50)
        second = await list_outsource_orders(mock_async_db, page=1, per_page=50)

        assert first['items'][0]['status_label'] == '待发货'
        assert second['items'][0]['status_label'] == '外发完成'
        assert second['items'][0]['progress'] == 100
        # 缓存对象不得被就地写入进度字段（否则会污染 beile-order 页面的缓存响应）
        assert 'progress' not in cached_items[0]
        assert 'status_label' not in cached_items[0]
        assert 'has_processes' not in cached_items[0]


class TestHubeiProductSearch:
    """湖北 SKU 搜索（工序预设页搜索框数据源）"""

    @pytest.mark.asyncio
    async def test_search_returns_hubei_products(self, mock_async_db):
        """返回工厂=湖北 的 SKU（含名称/条码/工厂字段）"""
        row = SimpleNamespace(id=1, name='测试产品', barcode='TEST001', factory='湖北')
        result = MagicMock()
        result.all.return_value = [row]
        mock_async_db.execute = AsyncMock(return_value=result)

        items = await search_hubei_products(mock_async_db, '测试')

        assert items == [{'id': 1, 'name': '测试产品', 'barcode': 'TEST001', 'factory': '湖北'}]

    @pytest.mark.asyncio
    async def test_search_empty_keyword_still_scoped(self, mock_async_db):
        """空关键词时返回空结果（仍只查湖北 SKU）"""
        result = MagicMock()
        result.all.return_value = []
        mock_async_db.execute = AsyncMock(return_value=result)

        items = await search_hubei_products(mock_async_db, '')

        assert items == []


class TestListUnshippedProcesses:
    """未到货（未发完）工序明细聚合"""

    @pytest.mark.asyncio
    async def test_remaining_is_target_minus_shipped(self, mock_async_db):
        """未到数量 = 订单数量 - 已发数量"""
        row = SimpleNamespace(
            order_id=1, order_no='HB001', customer='客户A',
            order_date=datetime(2026, 1, 2, 2, 30, tzinfo=UTC),  # UTC 02:30
            product_name='测试产品', product_barcode='TEST001',
            process_type='电绣', target_qty=100, shipped_qty=30,
        )
        result = MagicMock()
        result.all.return_value = [row]
        mock_async_db.execute = AsyncMock(return_value=result)

        items = await list_unshipped_processes(mock_async_db)

        assert len(items) == 1
        assert items[0]['order_no'] == 'HB001'
        assert items[0]['target_qty'] == 100
        assert items[0]['shipped_qty'] == 30
        assert items[0]['remaining'] == 70
        # 下单时间按北京时间展示（与 beile-list 同口径）：UTC 02:30 → 北京 10:30
        assert items[0]['order_date'] == '2026-01-02 10:30'

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_async_db):
        """无未发完工序时返回空列表"""
        result = MagicMock()
        result.all.return_value = []
        mock_async_db.execute = AsyncMock(return_value=result)

        items = await list_unshipped_processes(mock_async_db)

        assert items == []

    @pytest.mark.asyncio
    async def test_processes_source_is_presets_not_instances(self, tmp_path):
        """工序以 SKU 预设为准（回归）：实例多出的工序不导出、预设缺失的工序仍导出。

        修复前导出读 order_outsource_process（下单时的工序实例快照，与预设脱节）；
        修复后以 outsource_process_type（当前预设，is_active）为准，已发数量左连接实例。
        """
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from fastapi_app.shared_models import (
            Order as OrderModel,
        )
        from fastapi_app.shared_models import (
            OrderItem as OrderItemModel,
        )
        from fastapi_app.shared_models import (
            OutsourceProcessType,
        )
        from fastapi_app.shared_models import (
            Product as ProductModel,
        )

        engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "unshipped.db"}')
        try:
            async with engine.begin() as conn:
                for table in (
                    ProductModel.__table__, OrderModel.__table__, OrderItemModel.__table__,
                    OutsourceProcessType.__table__, OrderOutsourceProcess.__table__,
                ):
                    await conn.run_sync(lambda c, t=table: t.create(c, checkfirst=True))

            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            async with session_factory() as session:
                session.add(ProductModel(id=1, name='测试SKU', barcode='6978946330588', factory='湖北'))
                session.add(OrderModel(
                    id=1, order_no='PO-1', customer='客户A',
                    order_date=datetime(2026, 1, 2, 2, 30, tzinfo=UTC), product_id=1, quantity=100,
                ))
                session.add(OrderItemModel(id=1, order_id=1, product_id=1, quantity=100))
                # 预设只有「电绣」「转印」
                session.add(OutsourceProcessType(id=1, product_id=1, process_type='电绣', sort_order=1, is_active=True))
                session.add(OutsourceProcessType(id=2, product_id=1, process_type='转印', sort_order=2, is_active=True))
                # 订单实例与预设不一致：裁剪/电绣(已全发)/缝制
                session.add(OrderOutsourceProcess(
                    id=1, order_id=1, order_item_id=1, product_id=1, product_name='测试SKU',
                    process_type='裁剪', sort_order=0, status='pending',
                ))
                session.add(OrderOutsourceProcess(
                    id=2, order_id=1, order_item_id=1, product_id=1, product_name='测试SKU',
                    process_type='电绣', sort_order=0, status='received',
                    shipped_quantity=100, received_quantity=100,
                ))
                session.add(OrderOutsourceProcess(
                    id=3, order_id=1, order_item_id=1, product_id=1, product_name='测试SKU',
                    process_type='缝制', sort_order=0, status='pending',
                ))
                await session.commit()

            async with session_factory() as session:
                rows = await list_unshipped_processes(session)

            procs = [r['process_type'] for r in rows]
            # 预设「电绣」全发（100/100）→ 排除；预设「转印」无实例 → 保留且已发 0
            assert procs == ['转印']
            assert rows[0]['shipped_qty'] == 0
            assert rows[0]['remaining'] == 100
            # 实例特有工序（裁剪/缝制）不属于预设，不得出现在导出中
            assert '裁剪' not in procs
            assert '缝制' not in procs
        finally:
            await engine.dispose()


class TestSyncOrdersForProduct:
    """预设变更后自动同步订单实例：新增补齐、仅删未发货、已发货保留"""

    @staticmethod
    async def _session(tmp_path):
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from fastapi_app.shared_models import (
            Order as OrderModel,
        )
        from fastapi_app.shared_models import (
            OrderItem as OrderItemModel,
        )
        from fastapi_app.shared_models import (
            OutsourceProcessType,
        )
        from fastapi_app.shared_models import (
            Product as ProductModel,
        )
        engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "sync.db"}')
        async with engine.begin() as conn:
            for table in (
                ProductModel.__table__, OrderModel.__table__, OrderItemModel.__table__,
                OutsourceProcessType.__table__, OrderOutsourceProcess.__table__,
            ):
                await conn.run_sync(lambda c, t=table: t.create(c, checkfirst=True))
        return engine, async_sessionmaker(engine, expire_on_commit=False)

    @staticmethod
    def _seed(session):
        """预设=电绣/转印；实例=电绣(已发100) + 裁剪(未发，不在预设)。"""
        from fastapi_app.shared_models import (
            Order as OrderModel,
        )
        from fastapi_app.shared_models import (
            OrderItem as OrderItemModel,
        )
        from fastapi_app.shared_models import (
            OutsourceProcessType,
        )
        from fastapi_app.shared_models import (
            Product as ProductModel,
        )
        session.add(ProductModel(id=1, name='SKU1', factory='湖北'))
        session.add(OrderModel(id=1, order_no='PO-1', customer='C', product_id=1, quantity=100))
        session.add(OrderItemModel(id=10, order_id=1, product_id=1, quantity=100))
        session.add(OutsourceProcessType(id=1, product_id=1, process_type='电绣', sort_order=1, is_active=True))
        session.add(OutsourceProcessType(id=2, product_id=1, process_type='转印', sort_order=2, is_active=True))
        session.add(OrderOutsourceProcess(
            id=1, order_id=1, order_item_id=10, product_id=1, product_name='SKU1',
            process_type='电绣', sort_order=1, status='shipped', shipped_quantity=100,
        ))
        session.add(OrderOutsourceProcess(
            id=2, order_id=1, order_item_id=10, product_id=1, product_name='SKU1',
            process_type='裁剪', sort_order=0, status='pending',
        ))

    @pytest.mark.asyncio
    async def test_add_missing_and_remove_unshipped(self, tmp_path):
        """同步：补预设缺失工序、删未发货的非预设工序、保留已发货的非预设工序"""
        from sqlalchemy import select

        from fastapi_app.services.outsource_service import sync_orders_for_product
        from fastapi_app.shared_models import OutsourceProcessType

        engine, session_factory = await self._session(tmp_path)
        try:
            async with session_factory() as session:
                self._seed(session)
                await session.commit()

            async with session_factory() as session:
                stats = await sync_orders_for_product(session, 1)
                await session.commit()
                # 新增「转印」；移除未发货的「裁剪」；「电绣」在预设中不动
                assert stats == {'created': 1, 'removed': 1, 'kept': 0}
                procs = (await session.execute(
                    select(OrderOutsourceProcess.process_type)
                )).scalars().all()
                assert sorted(procs) == ['电绣', '转印']

            # 删除预设「电绣」后同步：该实例已发货 → 必须保留，不丢发货流水
            async with session_factory() as session:
                pt = (await session.execute(
                    select(OutsourceProcessType).where(OutsourceProcessType.process_type == '电绣')
                )).scalar_one()
                await session.delete(pt)
                await session.commit()

            async with session_factory() as session:
                stats2 = await sync_orders_for_product(session, 1)
                await session.commit()
                assert stats2 == {'created': 0, 'removed': 0, 'kept': 1}
                procs2 = (await session.execute(
                    select(OrderOutsourceProcess.process_type)
                )).scalars().all()
                assert sorted(procs2) == ['电绣', '转印']
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_remove_unshipped_when_preset_deleted(self, tmp_path):
        """预设删除某工序且实例未发货 → 同步删除该实例。"""
        from sqlalchemy import select

        from fastapi_app.services.outsource_service import sync_orders_for_product
        from fastapi_app.shared_models import OutsourceProcessType

        engine, session_factory = await self._session(tmp_path)
        try:
            async with session_factory() as session:
                self._seed(session)
                await session.commit()

            # 先同步（补齐「转印」实例），再删除预设「转印」
            async with session_factory() as session:
                await sync_orders_for_product(session, 1)
                await session.commit()
            async with session_factory() as session:
                pt = (await session.execute(
                    select(OutsourceProcessType).where(OutsourceProcessType.process_type == '转印')
                )).scalar_one()
                await session.delete(pt)
                await session.commit()

            async with session_factory() as session:
                stats = await sync_orders_for_product(session, 1)
                await session.commit()
                assert stats['removed'] == 1
                procs = (await session.execute(
                    select(OrderOutsourceProcess.process_type)
                )).scalars().all()
                assert '转印' not in procs
        finally:
            await engine.dispose()


class TestListShippableProcesses:
    """待发货工序聚合（批量发货面板数据源）"""

    @staticmethod
    async def _session(tmp_path):
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from fastapi_app.shared_models import (
            Order as OrderModel,
        )
        from fastapi_app.shared_models import (
            OrderItem as OrderItemModel,
        )
        from fastapi_app.shared_models import (
            Product as ProductModel,
        )
        engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "shippable.db"}')
        async with engine.begin() as conn:
            for table in (
                ProductModel.__table__, OrderModel.__table__, OrderItemModel.__table__,
                OrderOutsourceProcess.__table__,
            ):
                await conn.run_sync(lambda c, t=table: t.create(c, checkfirst=True))
        return engine, async_sessionmaker(engine, expire_on_commit=False)

    @pytest.mark.asyncio
    async def test_only_unshipped_processes_listed(self, tmp_path):
        """待发货 = 已发 < 目标；已发满/已收齐的不出现。"""
        from fastapi_app.services.outsource_service import list_shippable_processes
        from fastapi_app.shared_models import (
            Order as OrderModel,
        )
        from fastapi_app.shared_models import (
            OrderItem as OrderItemModel,
        )
        from fastapi_app.shared_models import (
            Product as ProductModel,
        )

        engine, session_factory = await self._session(tmp_path)
        try:
            async with session_factory() as session:
                session.add(ProductModel(id=1, name='SKU1', factory='湖北'))
                session.add(OrderModel(id=1, order_no='PO-1', customer='C', product_id=1, quantity=100))
                session.add(OrderItemModel(id=10, order_id=1, product_id=1, quantity=100))
                session.add(OrderOutsourceProcess(id=1, order_id=1, order_item_id=10, product_id=1, product_name='SKU1', process_type='电绣', sort_order=1, status='pending'))
                session.add(OrderOutsourceProcess(id=2, order_id=1, order_item_id=10, product_id=1, product_name='SKU1', process_type='转印', sort_order=2, status='shipped', shipped_quantity=30))
                session.add(OrderOutsourceProcess(id=3, order_id=1, order_item_id=10, product_id=1, product_name='SKU1', process_type='缝制', sort_order=3, status='received', shipped_quantity=100, received_quantity=100))
                session.add(OrderOutsourceProcess(id=4, order_id=1, order_item_id=10, product_id=1, product_name='SKU1', process_type='配件', sort_order=4, status='shipped', shipped_quantity=100))
                await session.commit()

            async with session_factory() as session:
                rows = await list_shippable_processes(session)

            procs = [(r['process_type'], r['remaining']) for r in rows]
            assert procs == [('电绣', 100), ('转印', 70)]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_partially_shipped_then_received_still_listed(self, tmp_path):
        """回归：部分发货并已收货、但未发满的工序，仍须留在待发货列表（可继续发下一批）。

        收货只闭环「本批」而非关闭整单；此前以 received_quantity > 0 过滤，
        导致「王者荣耀」这类分批场景在首次收货后从批量发货面板消失，剩余数量再也发不出去。
        """
        from fastapi_app.services.outsource_service import list_shippable_processes
        from fastapi_app.shared_models import (
            Order as OrderModel,
        )
        from fastapi_app.shared_models import (
            OrderItem as OrderItemModel,
        )
        from fastapi_app.shared_models import (
            Product as ProductModel,
        )

        engine, session_factory = await self._session(tmp_path)
        try:
            async with session_factory() as session:
                session.add(ProductModel(id=1, name='王者荣耀', factory='湖北'))
                session.add(OrderModel(id=1, order_no='PO-1', customer='C', product_id=1, quantity=100))
                session.add(OrderItemModel(id=10, order_id=1, product_id=1, quantity=100))
                # 发 40 收 40，目标 100 → 剩余 60，仍应可发
                session.add(OrderOutsourceProcess(
                    id=1, order_id=1, order_item_id=10, product_id=1, product_name='王者荣耀',
                    process_type='电绣', sort_order=1, status='shipped',
                    shipped_quantity=40, received_quantity=40,
                ))
                await session.commit()

            async with session_factory() as session:
                rows = await list_shippable_processes(session)

            assert [(r['process_type'], r['target_qty'], r['shipped_qty'], r['remaining']) for r in rows] == [
                ('电绣', 100, 40, 60),
            ]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_fully_received_not_listed(self, tmp_path):
        """已收齐（收货累计 >= 目标）的工序不再出现在待发货列表。"""
        from fastapi_app.services.outsource_service import list_shippable_processes
        from fastapi_app.shared_models import (
            Order as OrderModel,
        )
        from fastapi_app.shared_models import (
            OrderItem as OrderItemModel,
        )
        from fastapi_app.shared_models import (
            Product as ProductModel,
        )

        engine, session_factory = await self._session(tmp_path)
        try:
            async with session_factory() as session:
                session.add(ProductModel(id=1, name='王者荣耀', factory='湖北'))
                session.add(OrderModel(id=1, order_no='PO-1', customer='C', product_id=1, quantity=100))
                session.add(OrderItemModel(id=10, order_id=1, product_id=1, quantity=100))
                session.add(OrderOutsourceProcess(
                    id=1, order_id=1, order_item_id=10, product_id=1, product_name='王者荣耀',
                    process_type='电绣', sort_order=1, status='received',
                    shipped_quantity=100, received_quantity=100,
                ))
                await session.commit()

            async with session_factory() as session:
                rows = await list_shippable_processes(session)

            assert rows == []
        finally:
            await engine.dispose()


class TestShipProcessesMulti:
    """跨订单批量发货：逐条复用 ship_order_process，失败包装错误"""

    @pytest.mark.asyncio
    async def test_ship_cross_orders(self, mock_async_db):
        from fastapi_app.services import outsource_service
        from fastapi_app.services.outsource import _order_processes as mod

        mock_ship = AsyncMock(side_effect=[
            {'id': 1, 'order_id': 100},
            {'id': 2, 'order_id': 200},
        ])
        with patch.object(mod, 'ship_order_process', new=mock_ship):
            items = await outsource_service.ship_processes_multi(
                mock_async_db, [(1, 10), (2, 20)], username='admin',
            )

        assert len(items) == 2
        assert items[0]['order_id'] == 100
        assert items[1]['order_id'] == 200
        assert mock_ship.await_count == 2

    @pytest.mark.asyncio
    async def test_ship_failure_wraps_error(self, mock_async_db):
        from fastapi_app.services import outsource_service
        from fastapi_app.services.outsource import _order_processes as mod

        with patch.object(mod, 'ship_order_process', new=AsyncMock(
            side_effect=ValueError('发货数量超过剩余数量（剩余 5）'),
        )):
            with pytest.raises(ValueError, match='外发工序 1：发货数量超过剩余数量'):
                await outsource_service.ship_processes_multi(
                    mock_async_db, [(1, 100)], username='admin',
                )
