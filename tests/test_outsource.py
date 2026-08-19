"""
湖北外发模块 单元测试

覆盖：
- SKU 工序预设 CRUD（重复工序拦截、不存在产品校验）
- 订单外发工序生成（返单自动带出、幂等去重）
- 工序状态流转（开始/完成）
- 进度看板聚合（progress / current_process / status_label）
"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.outsource_service import (
    batch_create_process_types,
    complete_order_process,
    create_process_type,
    delete_order_process,
    delete_process_type,
    generate_order_processes,
    get_kanban,
    list_order_processes,
    list_process_types,
    start_order_process,
    sync_outsource_processes_for_order,
    update_process_type,
)


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
    """构造 mock 订单外发工序对象"""
    p = MagicMock()
    p.id = pid
    p.order_id = order_id
    p.order_item_id = item_id
    p.product_id = product_id
    p.product_name = '测试产品'
    p.process_type = process_type
    p.sort_order = sort_order
    p.status = status
    p.planned_start_time = None
    p.planned_end_time = None
    p.actual_start_time = None
    p.actual_end_time = None
    p.remark = None
    p.created_by = 'admin'
    p.create_time = datetime.now(UTC)
    p.update_time = datetime.now(UTC)
    return p


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
    @patch('fastapi_app.services.outsource_service.sync_outsource_processes_for_order')
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
    """工序状态流转"""

    @pytest.mark.asyncio
    async def test_start_process(self, mock_async_db):
        """开始工序"""
        p = make_order_process(pid=1)
        mock_async_db.get = AsyncMock(return_value=p)

        result = await start_order_process(mock_async_db, 1, 'admin')

        assert result['status'] == 'in_progress'
        assert p.actual_start_time is not None

    @pytest.mark.asyncio
    async def test_start_completed_process(self, mock_async_db):
        """已完成工序无法再开始"""
        p = make_order_process(pid=1, status='completed')
        mock_async_db.get = AsyncMock(return_value=p)

        with pytest.raises(ValueError, match='已完成'):
            await start_order_process(mock_async_db, 1)

    @pytest.mark.asyncio
    async def test_complete_process(self, mock_async_db):
        """完成工序"""
        p = make_order_process(pid=1)
        mock_async_db.get = AsyncMock(return_value=p)

        result = await complete_order_process(mock_async_db, 1, 'admin')

        assert result['status'] == 'completed'
        assert p.actual_end_time is not None
        assert p.actual_start_time is not None  # 未开始直接完成时视为开始即完成

    @pytest.mark.asyncio
    async def test_complete_process_not_found(self, mock_async_db):
        """完成不存在的工序"""
        mock_async_db.get = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match='外发工序不存在'):
            await complete_order_process(mock_async_db, 999)

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
        proc_result = MagicMock()
        proc_result.scalars.return_value.all.return_value = [
            make_order_process(pid=1, order_id=1, process_type='电绣', status='completed'),
            make_order_process(pid=2, order_id=1, process_type='转印', status='completed'),
            make_order_process(pid=3, order_id=1, process_type='配件', status='pending'),
            make_order_process(pid=4, order_id=2, process_type='裁剪', status='completed'),
        ]
        mock_async_db.execute = AsyncMock(return_value=proc_result)

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
        proc_result = MagicMock()
        proc_result.scalars.return_value.all.return_value = []
        mock_async_db.execute = AsyncMock(return_value=proc_result)

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
                {'id': 1, 'record_type': 'order', 'order_no': 'PO-1'},   # 全部 pending → 待开始
                {'id': 2, 'record_type': 'order', 'order_no': 'PO-2'},   # 部分完成 → 进行中
                {'id': 3, 'record_type': 'order', 'order_no': 'PO-3'},   # 全部完成 → 已完成
                {'id': 4, 'record_type': 'order', 'order_no': 'PO-4'},   # 无工序 → 未配置
                {'id': 5, 'record_type': 'stockin', 'stockin_no': 'BH-1'},
            ],
            'total': 5, 'page': 1, 'per_page': 500,
        }
        proc_result = MagicMock()
        proc_result.scalars.return_value.all.return_value = [
            make_order_process(pid=1, order_id=1, process_type='裁剪', status='pending'),
            make_order_process(pid=2, order_id=1, process_type='电绣', status='pending'),
            make_order_process(pid=3, order_id=2, process_type='裁剪', status='completed'),
            make_order_process(pid=4, order_id=2, process_type='电绣', status='pending'),
            make_order_process(pid=5, order_id=3, process_type='裁剪', status='completed'),
            make_order_process(pid=6, order_id=3, process_type='电绣', status='completed'),
        ]
        mock_async_db.execute = AsyncMock(return_value=proc_result)

        pending = await list_outsource_orders(mock_async_db, page=1, per_page=50, process_status='pending')
        in_progress = await list_outsource_orders(mock_async_db, page=1, per_page=50, process_status='in_progress')
        completed = await list_outsource_orders(mock_async_db, page=1, per_page=50, process_status='completed')

        assert [r['id'] for r in pending['items']] == [1]
        assert pending['total'] == 1
        assert pending['items'][0]['status_label'] == '待开始'
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
        proc_result = MagicMock()
        # 全部订单均为待开始（pending）
        proc_result.scalars.return_value.all.return_value = [
            make_order_process(pid=i, order_id=i, process_type='裁剪', status='pending')
            for i in range(1, 5)
        ]
        mock_async_db.execute = AsyncMock(return_value=proc_result)

        page1 = await list_outsource_orders(mock_async_db, page=1, per_page=2, process_status='pending')
        page2 = await list_outsource_orders(mock_async_db, page=2, per_page=2, process_status='pending')

        assert page1['total'] == 4
        assert [r['id'] for r in page1['items']] == [1, 2]
        assert [r['id'] for r in page2['items']] == [3, 4]
        assert page1['page'] == 1 and page2['page'] == 2


class TestKanban:
    """进度看板聚合（兼容保留）"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.outsource_service.list_outsource_orders')
    async def test_kanban_progress(self, mock_list, mock_async_db):
        """看板：进度计算与当前工序"""
        mock_list.return_value = {
            'items': [{
                'id': 1,
                'order_no': 'ORD-001',
                'customer': '客户A',
                'order_date': '2026-08-01 10:00',
                'record_type': 'order',
                'items': [{'product_id': 1, 'product_name': '测试产品', 'quantity': 10}],
            }],
            'total': 1,
            'page': 1,
            'per_page': 20,
        }
        proc_result = MagicMock()
        proc_result.scalars.return_value.all.return_value = [
            make_order_process(pid=1, process_type='电绣', status='completed'),
            make_order_process(pid=2, process_type='转印', status='in_progress'),
            make_order_process(pid=3, process_type='配件', status='pending'),
        ]
        mock_async_db.execute = AsyncMock(return_value=proc_result)

        result = await get_kanban(mock_async_db, page=1, per_page=20)

        assert result['total'] == 1
        order = result['items'][0]
        assert order['total_processes'] == 3
        assert order['completed_processes'] == 1
        assert order['progress'] == 33
        assert order['current_process'] == '转印'
        assert '进行中' in order['status_label']

    @pytest.mark.asyncio
    @patch('fastapi_app.services.outsource_service.list_outsource_orders')
    async def test_kanban_no_processes(self, mock_list, mock_async_db):
        """看板：未配置工序的订单"""
        mock_list.return_value = {
            'items': [{
                'id': 2,
                'order_no': 'ORD-002',
                'customer': '客户B',
                'order_date': '2026-08-02 09:00',
                'record_type': 'order',
                'items': [],
            }],
            'total': 1,
            'page': 1,
            'per_page': 20,
        }
        proc_result = MagicMock()
        proc_result.scalars.return_value.all.return_value = []
        mock_async_db.execute = AsyncMock(return_value=proc_result)

        result = await get_kanban(mock_async_db)

        order = result['items'][0]
        assert order['progress'] == 0
        assert order['status_label'] == '未配置工序'
        assert order['current_process'] is None

    @pytest.mark.asyncio
    @patch('fastapi_app.services.outsource_service.list_outsource_orders')
    async def test_kanban_all_completed(self, mock_list, mock_async_db):
        """看板：全部完成"""
        mock_list.return_value = {
            'items': [{
                'id': 3,
                'order_no': 'ORD-003',
                'customer': '客户C',
                'order_date': '2026-08-03 09:00',
                'record_type': 'order',
                'items': [],
            }],
            'total': 1,
            'page': 1,
            'per_page': 20,
        }
        proc_result = MagicMock()
        proc_result.scalars.return_value.all.return_value = [
            make_order_process(pid=1, order_id=3, process_type='电绣', status='completed'),
            make_order_process(pid=2, order_id=3, process_type='转印', status='completed'),
        ]
        mock_async_db.execute = AsyncMock(return_value=proc_result)

        result = await get_kanban(mock_async_db)

        order = result['items'][0]
        assert order['progress'] == 100
        assert order['status_label'] == '外发完成'
        assert order['current_process'] is None
