"""
采购中心：BOM 复制 / 批量删除端点，与 update_purchase_order 跨订单篡改回归。

从 test_purchase_center.py 拆出（file_size_gate 阈值 1600 行）；测试逻辑与断言未改动。
"""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ============================================================
# BOM 复制与批量删除功能测试 (从 material.py 迁移)
# ============================================================

class TestBomCopyAndBatchDelete:
    """BOM复制和批量删除功能的端点测试"""

    # ---- GET /api/products/search ----

    @pytest.mark.asyncio
    async def test_search_products_empty_keyword(self, client):
        """空关键词返回422（FastAPI参数校验）"""
        resp = await client.get("/api/v1/purchase-center/products/search?keyword=")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_search_products_success(self, client, mock_db):
        """搜索产品用于BOM复制"""
        with patch('fastapi_app.services.purchase_center_service.search_products_for_bom_copy') as mock_svc:
            mock_svc.return_value = [
                {'id': 1, 'name': '测试产品', 'barcode': '123456', 'has_bom': False, 'material_count': 0}
            ]
            resp = await client.get("/api/v1/purchase-center/products/search?keyword=测试")
            assert resp.status_code == 200
            data = resp.json()
            assert data['success'] is True
            assert len(data['products']) == 1
            assert data['products'][0]['name'] == '测试产品'

    # ---- GET /api/products/{id}/bom-preview ----

    @pytest.mark.asyncio
    async def test_bom_preview_not_found(self, client, mock_db):
        """产品不存在时返回400"""
        with patch('fastapi_app.services.purchase_center_service.get_bom_preview') as mock_svc:
            mock_svc.side_effect = ValueError('产品ID 999 不存在')
            resp = await client.get("/api/v1/purchase-center/products/999/bom-preview")
            assert resp.status_code == 400
            assert '不存在' in resp.json()['detail']

    @pytest.mark.asyncio
    async def test_bom_preview_no_bom(self, client, mock_db):
        """产品无BOM时返回400"""
        with patch('fastapi_app.services.purchase_center_service.get_bom_preview') as mock_svc:
            mock_svc.side_effect = ValueError('该产品没有配置BOM表，无法复制')
            resp = await client.get("/api/v1/purchase-center/products/1/bom-preview")
            assert resp.status_code == 400
            assert '没有配置BOM' in resp.json()['detail']

    @pytest.mark.asyncio
    async def test_bom_preview_success(self, client, mock_db):
        """成功获取BOM预览"""
        preview_data = {
            'product': {'id': 1, 'name': '源产品', 'barcode': 'BAR001', 'create_time': '2026-01-01 00:00:00'},
            'bom': {
                'filling': {'cotton_usage': 100},
                'fabric': [{'fabric_name': '面料A'}],
                'accessory': [],
            },
            'material_count': 2,
        }
        with patch('fastapi_app.services.purchase_center_service.get_bom_preview') as mock_svc:
            mock_svc.return_value = preview_data
            resp = await client.get("/api/v1/purchase-center/products/1/bom-preview")
            assert resp.status_code == 200
            data = resp.json()
            assert data['success'] is True
            assert data['product']['name'] == '源产品'
            assert data['material_count'] == 2
            assert data['bom']['filling'] is not None
            assert len(data['bom']['fabric']) == 1

    # ---- POST /api/products/{id}/copy-bom ----

    @pytest.mark.asyncio
    async def test_copy_bom_same_product(self, client, mock_db):
        """复制到同一产品返回400"""
        with patch('fastapi_app.services.purchase_center_service.copy_bom_to_product') as mock_svc:
            mock_svc.side_effect = ValueError('不能复制到同一产品')
            resp = await client.post("/api/v1/purchase-center/products/1/copy-bom", json={'source_product_id': 1})
            assert resp.status_code == 400
            assert '不能复制到同一产品' in resp.json()['detail']

    @pytest.mark.asyncio
    async def test_copy_bom_no_source(self, client, mock_db):
        """未选择源产品返回400/422"""
        with patch('fastapi_app.services.purchase_center_service.copy_bom_to_product') as mock_svc:
            mock_svc.side_effect = ValueError('请选择源产品')
            resp = await client.post("/api/v1/purchase-center/products/2/copy-bom", json={})
            assert resp.status_code == 422, f"缺 source_product_id 应由请求模型拒绝 422，实测 {resp.status_code}: {resp.text}"
            mock_svc.assert_not_called()

    @pytest.mark.asyncio
    async def test_copy_bom_target_has_existing_bom(self, client, mock_db):
        """目标产品已有BOM且未覆盖时返回409"""
        with patch('fastapi_app.services.purchase_center_service.copy_bom_to_product') as mock_svc:
            mock_svc.side_effect = ValueError('目标产品已有BOM表，请确认是否覆盖')
            resp = await client.post("/api/v1/purchase-center/products/2/copy-bom", json={'source_product_id': 1, 'overwrite': False})
            assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_copy_bom_source_no_bom(self, client, mock_db):
        """源产品无BOM返回400"""
        with patch('fastapi_app.services.purchase_center_service.copy_bom_to_product') as mock_svc:
            mock_svc.side_effect = ValueError('源产品没有配置BOM表')
            resp = await client.post("/api/v1/purchase-center/products/2/copy-bom", json={'source_product_id': 1, 'overwrite': True})
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_copy_bom_success(self, client, mock_db):
        """成功复制BOM"""
        copy_result = {
            'message': 'BOM复制成功，共复制 3 项物料',
            'copied_count': 3,
            'source_product': {'id': 1, 'name': '源产品'},
            'target_product': {'id': 2, 'name': '目标产品'},
        }
        with patch('fastapi_app.services.purchase_center_service.copy_bom_to_product') as mock_svc:
            mock_svc.return_value = copy_result
            resp = await client.post("/api/v1/purchase-center/products/2/copy-bom", json={
                'source_product_id': 1,
                'overwrite': True,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data['success'] is True
            assert data['copied_count'] == 3
            assert data['source_product']['name'] == '源产品'
            assert data['target_product']['name'] == '目标产品'

    # ---- POST /api/orders/batch-delete ----

    @pytest.mark.asyncio
    async def test_batch_delete_empty_ids(self, client, mock_db):
        """空订单列表返回400/422"""
        with patch('fastapi_app.services.purchase_center_service.batch_delete_purchase_orders') as mock_svc:
            mock_svc.side_effect = ValueError('请选择要删除的订单')
            resp = await client.post("/api/v1/purchase-center/orders/batch-delete", json={'order_ids': []})
            assert resp.status_code == 422, f"order_ids 空列表应由请求模型拒绝 422，实测 {resp.status_code}: {resp.text}"
            mock_svc.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_delete_orders_not_found(self, client, mock_db):
        """未找到订单返回400"""
        with patch('fastapi_app.services.purchase_center_service.batch_delete_purchase_orders') as mock_svc:
            mock_svc.side_effect = ValueError('未找到要删除的订单')
            resp = await client.post("/api/v1/purchase-center/orders/batch-delete", json={'order_ids': [999, 1000]})
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_delete_success(self, client, mock_db):
        """批量删除成功"""
        delete_result = {
            'message': '成功删除 2 个订单',
            'deleted_count': 2,
        }
        with patch('fastapi_app.services.purchase_center_service.batch_delete_purchase_orders') as mock_svc:
            mock_svc.return_value = delete_result
            resp = await client.post("/api/v1/purchase-center/orders/batch-delete", json={'order_ids': [1, 2]})
            assert resp.status_code == 200
            data = resp.json()
            assert data['success'] is True
            assert data['deleted_count'] == 2


class TestBomCopyService:
    """BOM复制服务层单元测试"""

    def test_product_has_bom_true_with_filling(self):
        """有填充类物料时返回True"""
        from unittest.mock import MagicMock

        from fastapi_app.services.purchase_center_service import product_has_bom
        product = MagicMock()
        mock_material = MagicMock()
        mock_material.cotton_usage = Decimal('100')
        product.material = mock_material
        product.fabrics = []
        product.accessories = []
        assert product_has_bom(product) is True

    def test_product_has_bom_true_with_fabric(self):
        """有面料类物料时返回True"""
        from unittest.mock import MagicMock

        from fastapi_app.services.purchase_center_service import product_has_bom
        product = MagicMock()
        product.material = None
        product.fabrics = [MagicMock()]
        product.accessories = []
        assert product_has_bom(product) is True

    def test_product_has_bom_false_all_empty(self):
        """所有物料为空时返回False"""
        from unittest.mock import MagicMock

        from fastapi_app.services.purchase_center_service import product_has_bom
        product = MagicMock()
        product.material = None
        product.fabrics = []
        product.accessories = []
        assert product_has_bom(product) is False

    def test_product_has_bom_false_zero_cotton(self):
        """填充类cotton_usage为0时返回False"""
        from unittest.mock import MagicMock

        from fastapi_app.services.purchase_center_service import product_has_bom
        product = MagicMock()
        mock_material = MagicMock()
        mock_material.cotton_usage = Decimal('0')
        product.material = mock_material
        product.fabrics = []
        product.accessories = []
        assert product_has_bom(product) is False


# ============================================================
# update_purchase_order 防跨订单数据篡改回归测试
# ============================================================

class TestUpdatePurchaseOrderCrossOrderTampering:
    """
    提交后正确性检查回归：
    Bug：_upsert_order_items 在 item_id 属于其他订单时，item 变量仍指向
    其他订单的明细对象，后续 _apply_item_fields 会篡改跨订单数据。
    """

    @pytest.mark.asyncio
    async def test_cross_order_item_not_modified(self):
        """
        触发场景：
        - Order 100 (order_id=100) 有 Item 1
        - Order 200 (order_id=200) 有 Item 2（其他订单）
        - 更新 Order 100 时提交 items=[{id:2, ...}, {id:1, ...}]
        期望：
        - Item 2 (Order 200) 的字段完全不被修改
        - Item 1 (Order 100) 的字段正确更新
        - Order 100.total_amount 仅包含 Item 1 的金额（不含 Item 2）
        - Item 1 不被误删除（即 updated_ids 包含它）
        """
        from fastapi_app.services.purchase_order_crud import update_purchase_order

        # ---- 构造 Order 100 + Item 1 ----
        order_100 = MagicMock()
        order_100.id = 100
        order_100.order_no = 'CG-00100'
        order_100.status = 'pending'
        order_100.customer_name = '原客户A'
        order_100.supplier_name = '原供应商A'
        order_100.remark = '原备注'
        # 订单级损耗率为 NULL：行金额按落库数量计价。
        # ⚠️ 必须显式置 None：MagicMock 会自动生成任意属性，
        # float(MagicMock()) == 1.0 → 会被当成 1‰ 损耗率，把行金额算成 200.2000。
        order_100.spare_rate = None

        item_1 = MagicMock()
        item_1.id = 1
        item_1.order_id = 100
        item_1.material_name = '原物料1'
        item_1.material_code = 'CODE001'
        item_1.specification = '规格1'
        item_1.unit = '件'
        item_1.unit_price = Decimal('10.00')
        item_1.quantity = Decimal('5')
        item_1.total_price = Decimal('50.00')
        item_1.material_category = '面料'
        item_1.remark = '明细1备注'
        item_1.supplier_name = '原供应商A'
        item_1.customer_name = '原客户A'
        # 逐行损耗率为 NULL（落库真实形态）：行金额按落库数量计价，见 order_100.spare_rate 注释
        item_1.loss_rate = None

        # ---- 构造 Order 200 + Item 2（其他订单，不应被触碰） ----
        item_2 = MagicMock()
        item_2.id = 2
        item_2.order_id = 200  # ⚠️ 属于其他订单
        item_2.material_name = '其他订单物料'
        item_2.material_code = 'OTHER002'
        item_2.specification = '其他规格'
        item_2.unit = '米'
        item_2.unit_price = Decimal('999.00')
        item_2.quantity = Decimal('3')
        item_2.total_price = Decimal('2997.00')
        item_2.material_category = '配件'
        item_2.remark = '其他订单备注'
        item_2.supplier_name = '其他供应商'
        item_2.customer_name = '其他客户'
        item_2.loss_rate = None

        # ---- 快照 item_2 原始值用于后续断言 ----
        item_2_orig = {
            'material_name': item_2.material_name,
            'material_code': item_2.material_code,
            'specification': item_2.specification,
            'unit': item_2.unit,
            'unit_price': item_2.unit_price,
            'quantity': item_2.quantity,
            'total_price': item_2.total_price,
            'material_category': item_2.material_category,
            'remark': item_2.remark,
            'supplier_name': item_2.supplier_name,
            'customer_name': item_2.customer_name,
        }

        db = MagicMock()
        # db.get(PurchaseOrder, 100) -> order_100
        # db.get(PurchaseOrderItem, 2)  -> item_2（fallback 回退路径）
        get_results = {
            ('PurchaseOrder', 100): order_100,
            ('PurchaseOrderItem', 2): item_2,
        }

        async def fake_get(model_cls, oid):
            key = (model_cls.__name__ if hasattr(model_cls, '__name__') else str(model_cls), oid)
            return get_results.get(('PurchaseOrder', oid)) if key[0] not in ('PurchaseOrder',) \
                else get_results.get(key)

        # 简化版：分两次不同的 get 返回
        async def fake_get_po(_cls, oid):
            if oid == 100:
                return order_100
            return None

        async def fake_get_poi(_cls, oid):
            if oid == 2:
                return item_2
            return None

        call_count = {'n': 0}

        async def fake_get_mux(_cls, oid, **kwargs):  # **kwargs：with_for_update 行锁参数
            call_count['n'] += 1
            # 第一次调用：update_purchase_order 开头获取 PO
            if call_count['n'] == 1:
                return order_100 if oid == 100 else None
            # 后续调用：获取 POI
            if oid == 2:
                return item_2
            return None

        db.get = fake_get_mux

        # ---- db.execute 返回 ----
        # 1) _upsert_order_items 第一次 execute：Order 100 的现有明细
        existing_items_result = MagicMock()
        existing_items_result.scalars.return_value.all.return_value = [item_1]

        # 2) 第二次 execute：批量预取 items_data 中带 id 的明细 (1, 2)
        fetched_result = MagicMock()
        # fetched_items_map = {1: item_1, 2: item_2}
        fetched_result.scalars.return_value.all.return_value = [item_1, item_2]

        # 3) delete execute（仅测试被调用即可，无需检查值）
        delete_result = MagicMock()

        execute_count = {'n': 0}

        async def fake_execute(stmt):
            execute_count['n'] += 1
            # 第1次：select existing items (where order_id == 100)
            # 第2次：select IN批量预取
            # 第3次：delete（如有 to_delete_ids）
            if execute_count['n'] == 1:
                return existing_items_result
            elif execute_count['n'] == 2:
                return fetched_result
            else:
                return delete_result

        db.execute = fake_execute
        db.add = MagicMock()
        db.flush = AsyncMock()

        # ---- 调用 update_purchase_order ----
        result = await update_purchase_order(
            db,
            order_id=100,
            data={
                'supplier_name': '新供应商A',
                'items': [
                    # 恶意/误传：引用其他订单的明细
                    {
                        'id': 2,
                        'material_name': '篡改物料!!!',
                        'material_code': 'HACKED',
                        'unit_price': '999999.99',
                        'quantity': '999',
                    },
                    # 正常：本订单的明细
                    {
                        'id': 1,
                        'material_name': '新物料1',
                        'material_code': 'NEW001',
                        'unit_price': '20.00',
                        'quantity': '10',
                    },
                ],
            },
            username='tester',
        )

        # ====== 断言 ======

        # 1. 其他订单明细 Item 2 的所有字段都未变化
        assert item_2.material_name == item_2_orig['material_name'], \
            '跨订单明细 material_name 不应被修改'
        assert item_2.material_code == item_2_orig['material_code'], \
            '跨订单明细 material_code 不应被修改'
        assert item_2.specification == item_2_orig['specification'], \
            '跨订单明细 specification 不应被修改'
        assert item_2.unit == item_2_orig['unit'], \
            '跨订单明细 unit 不应被修改'
        assert item_2.unit_price == item_2_orig['unit_price'], \
            '跨订单明细 unit_price 不应被修改'
        assert item_2.quantity == item_2_orig['quantity'], \
            '跨订单明细 quantity 不应被修改'
        assert item_2.total_price == item_2_orig['total_price'], \
            '跨订单明细 total_price 不应被修改'
        assert item_2.material_category == item_2_orig['material_category'], \
            '跨订单明细 material_category 不应被修改'
        assert item_2.remark == item_2_orig['remark'], \
            '跨订单明细 remark 不应被修改'
        assert item_2.supplier_name == item_2_orig['supplier_name'], \
            '跨订单明细 supplier_name 不应被修改（最关键：不应覆盖为目标订单的供应商）'
        assert item_2.customer_name == item_2_orig['customer_name'], \
            '跨订单明细 customer_name 不应被修改（最关键：不应覆盖为目标订单的客户）'

        # 2. 本订单明细 Item 1 被正确更新
        assert item_1.material_name == '新物料1'
        assert item_1.material_code == 'NEW001'
        assert item_1.unit_price == Decimal('20.00')
        assert item_1.quantity == Decimal('10')
        assert item_1.total_price == Decimal('20.00') * Decimal('10')  # 200.00

        # 3. Order 100 的 total_amount 仅包含 Item 1 (200.00)，不含 Item 2 的金额
        assert order_100.total_amount == Decimal('200.00'), \
            'total_amount 不应包含跨订单明细的金额'

        # 4. 返回结果正常
        assert result['id'] == 100
        assert result['order_no'] == 'CG-00100'
        assert result['status'] == 'pending'

        # 5. db.execute.delete 未以 Item 1 为目标（即 Item 1 在 updated_ids 中，未被误删）
        # 这里用 execute_count 间接验证：若有删除则会有第 3 次 execute
        # 如果 items_data 中包含了所有 existing_items 且都有效，则不应触发 delete
        # (Item 2 无效被跳过, Item 1 有效被更新；existing={1}, updated_ids={1} => to_delete_ids=空)
        # 因此第 3 次 execute 不应发生
        assert execute_count['n'] == 2, \
            f'不应触发删除执行（期望 execute_count=2，实际={execute_count["n"]}）'

    @pytest.mark.asyncio
    async def test_nonexistent_item_id_skipped_no_crash(self):
        """提交完全不存在的 item_id 时应安全跳过，不抛异常也不写入。"""
        from fastapi_app.services.purchase_order_crud import update_purchase_order

        order = MagicMock()
        order.id = 500
        order.order_no = 'CG-00500'
        order.status = 'pending'
        order.customer_name = '客户X'
        order.supplier_name = '供应商X'
        order.remark = ''

        item_existing = MagicMock()
        item_existing.id = 50
        item_existing.order_id = 500
        item_existing.material_name = '现有物料'
        item_existing.material_code = 'EX050'
        item_existing.specification = ''
        item_existing.unit = '件'
        item_existing.unit_price = Decimal('5.00')
        item_existing.quantity = Decimal('2')
        item_existing.total_price = Decimal('10.00')
        item_existing.material_category = ''
        item_existing.remark = ''
        item_existing.supplier_name = '供应商X'
        item_existing.customer_name = '客户X'

        db = MagicMock()
        call_count = {'n': 0}

        async def fake_get_mux(_cls, oid, **kwargs):  # **kwargs：with_for_update 行锁参数
            call_count['n'] += 1
            if call_count['n'] == 1:
                return order if oid == 500 else None
            # 对不存在的 item_id=99999 回退查询也返回 None
            return None

        db.get = fake_get_mux

        existing_result = MagicMock()
        existing_result.scalars.return_value.all.return_value = [item_existing]

        fetched_result = MagicMock()
        # 批量预取中 id=99999 不存在，id=50 返回 item_existing
        fetched_result.scalars.return_value.all.return_value = [item_existing]

        execute_count = {'n': 0}

        async def fake_execute(_stmt):
            execute_count['n'] += 1
            if execute_count['n'] == 1:
                return existing_result
            elif execute_count['n'] == 2:
                return fetched_result
            return MagicMock()

        db.execute = fake_execute
        db.add = MagicMock()
        db.flush = AsyncMock()

        # 不应抛出任何异常
        result = await update_purchase_order(
            db,
            order_id=500,
            data={
                'items': [
                    {'id': 99999, 'material_name': '不存在的id', 'unit_price': '1', 'quantity': '1'},
                    {'id': 50, 'material_name': '更新后的物料', 'unit_price': '8.00', 'quantity': '3'},
                ],
            },
            username='tester',
        )

        assert result['id'] == 500
        # Item 50 被正确更新
        assert item_existing.material_name == '更新后的物料'
        assert item_existing.quantity == Decimal('3')
        # 总金额仅包含 Item 50：8 * 3 = 24
        assert order.total_amount == Decimal('24.00')

