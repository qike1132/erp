"""
采购中心模块测试
"""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ============================================================
# Schema 测试
# ============================================================

class TestPurchaseCenterSchemas:
    def test_product_list_item(self):
        from fastapi_app.schemas.purchase_center import ProductBomInfo, ProductListItem
        item = ProductListItem(id=1, name="测试产品", barcode="6901234567890", has_bom=True, bom_info=ProductBomInfo(filling_count=1))
        assert item.id == 1
        assert item.has_bom is True
        assert item.bom_info.filling_count == 1

    def test_supplier_create(self):
        from fastapi_app.schemas.purchase_center import SupplierCreate
        s = SupplierCreate(name="测试供应商", contact_person="张三")
        assert s.name == "测试供应商"
        assert s.contact_person == "张三"

    def test_purchase_order_create(self):
        from fastapi_app.schemas.purchase_center import PurchaseOrderCreate
        po = PurchaseOrderCreate(materials=[{'material_name': '棉花'}], customer_name="客户A")
        assert len(po.materials) == 1
        assert po.customer_name == "客户A"

    def test_bom_save_request(self):
        # DTO 收口后 canonical 为强类型版：filling 为 FillingItem（非 dict）
        from fastapi_app.schemas.purchase_center import BomSaveRequest
        bom = BomSaveRequest(filling={'cotton_usage': 100}, fabrics=[], accessories=[])
        assert bom.filling.cotton_usage == 100

    def test_supplier_summary_response(self):
        from fastapi_app.schemas.purchase_center import SupplierSummary, SupplierSummaryItem, SupplierSummaryResponse
        resp = SupplierSummaryResponse(
            success=True,
            suppliers=[SupplierSummary(
                supplier_name="供应商A",
                items=[SupplierSummaryItem(material_name="棉花", quantity=100.0, order_count=2)],
                orders=["BF001"],
                order_count=1,
            )],
            supplier_count=1,
            order_count=1,
        )
        assert resp.success is True
        assert resp.supplier_count == 1
        assert len(resp.suppliers) == 1

    def test_calculate_material_request_bounds(self):
        """物料计算请求边界：quantity ≤ 100 万、orders ≤ 200 条，越界须拒绝。"""
        from pydantic import ValidationError

        from fastapi_app.api.v1.endpoints.purchase_center.schemas import CalculateMaterialRequest

        # 正常与边界值应通过
        ok = CalculateMaterialRequest(orders=[{"product_id": 1, "quantity": 10}])
        assert ok.orders[0].quantity == 10
        edge = CalculateMaterialRequest(
            orders=[{"product_id": 1, "quantity": 1_000_000}] * 200
        )
        assert len(edge.orders) == 200

        # quantity 超上限应拒绝（防止超大数值渗入聚合运算产生 Infinity/NaN）
        with pytest.raises(ValidationError):
            CalculateMaterialRequest(orders=[{"product_id": 1, "quantity": 1_000_000.1}])

        # orders 超长应拒绝（防止无界列表撑爆 SQL IN 子句与 selectinload）
        with pytest.raises(ValidationError):
            CalculateMaterialRequest(orders=[{"product_id": 1, "quantity": 1}] * 201)


# ============================================================
# Service 测试
# ============================================================

class TestPurchaseCenterService:
    @pytest.mark.asyncio
    async def test_get_search_suggestions_empty(self):
        from fastapi_app.services.purchase_center_service import get_search_suggestions
        db = MagicMock()
        result = await get_search_suggestions(db, '')
        assert result == []

    @pytest.mark.asyncio
    async def test_get_search_suggestions_with_keyword(self):
        from fastapi_app.services.purchase_product_service import get_search_suggestions
        db = MagicMock()
        mock_product = MagicMock()
        mock_product.id = 1
        mock_product.name = "测试产品"
        mock_product.barcode = "690"
        mock_product.price = 0
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_product]
        db.execute = AsyncMock(return_value=mock_result)

        with patch('fastapi_app.services.purchase_product_service._batch_check_bom_exists', new_callable=AsyncMock, return_value=set()):
            result = await get_search_suggestions(db, '测试')
            assert len(result) == 1
            assert result[0]['name'] == '测试产品'

    @pytest.mark.asyncio
    async def test_create_supplier_success(self):
        from fastapi_app.services.purchase_center_service import create_supplier
        db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        db.add = MagicMock(side_effect=lambda x: setattr(x, 'id', 1))
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        result = await create_supplier(db, {'name': '新供应商', 'contact_person': '张三'})
        assert result['name'] == '新供应商'

    @pytest.mark.asyncio
    async def test_create_supplier_duplicate(self):
        from fastapi_app.services.purchase_center_service import create_supplier
        db = MagicMock()
        existing = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match='供应商已存在'):
            await create_supplier(db, {'name': '已存在供应商'})

    @pytest.mark.asyncio
    async def test_get_saved_queries(self):
        from fastapi_app.services.purchase_center_service import get_saved_queries
        db = MagicMock()
        mock_sq = MagicMock()
        mock_sq.to_dict.return_value = {'id': 1, 'name': '测试查询'}
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_sq]
        db.execute = AsyncMock(return_value=mock_result)

        result = await get_saved_queries(db, user_id=1)
        assert len(result) == 1
        assert result[0]['name'] == '测试查询'

    @pytest.mark.asyncio
    async def test_get_completed_order_quick_filters(self):
        from fastapi_app.services.purchase_center_service import get_completed_order_quick_filters
        db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        db.execute = AsyncMock(return_value=mock_result)
        result = await get_completed_order_quick_filters(db)
        assert 'today' in result
        assert 'week' in result
        assert 'month' in result

    @pytest.mark.asyncio
    async def test_get_completed_order_suggestions_empty(self):
        from fastapi_app.services.purchase_center_service import get_completed_order_suggestions
        result = await get_completed_order_suggestions(MagicMock(), '')
        assert result == []

    @pytest.mark.asyncio
    async def test_export_completed_orders_field_mapping(self):
        """P-5 集成测试：验证列查询的 Row 属性访问与 dict 字段映射正确"""
        from datetime import datetime
        from types import SimpleNamespace

        from fastapi_app.services.purchase_center_service import export_completed_orders

        # 模拟订单列查询返回的 Row（属性访问）
        # spare_rate 必须给出：导出的「数量」按有效损耗率加放后取值
        order_row = SimpleNamespace(
            id=1, order_no='CG-20260723-0001', supplier_name='供应商A',
            customer_name='客户B', completed_at=datetime(2026, 7, 23, 10, 0, 0),
            spare_rate=None,
        )
        # 模拟明细列查询返回的 Row
        item_row = SimpleNamespace(
            order_id=1, material_name='面料X', material_code='M001',
            specification='规格1', unit='米', quantity=10.5,
            unit_price=20.0, total_price=210.0,
            loss_rate=None,
        )
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[
            MagicMock(all=MagicMock(return_value=[order_row])),  # 订单查询
            MagicMock(all=MagicMock(return_value=[item_row])),  # 明细查询
        ])
        # 2026-10-18 OCR 评审：导出门禁改为先 COUNT 订单总数（建在未截断的订单集上），
        # 桩必须提供 db.scalar；否则真实实现一 await 就 TypeError。
        db.scalar = AsyncMock(return_value=1)

        rows = await export_completed_orders(db)

        assert len(rows) == 1
        row = rows[0]
        # 验证所有字段映射正确（P-5 列查询改造的关键风险点）
        assert row['order_no'] == 'CG-20260723-0001'
        assert row['supplier_name'] == '供应商A'
        assert row['customer_name'] == '客户B'
        assert row['material_name'] == '面料X'
        assert row['material_code'] == 'M001'
        assert row['specification'] == '规格1'
        assert row['unit'] == '米'
        assert row['quantity'] == 10.5
        assert row['unit_price'] == 20.0
        assert row['amount'] == 210.0
        assert row['completed_at'] == '2026-07-23'

    @pytest.mark.asyncio
    async def test_export_completed_orders_empty(self):
        """P-5：无订单时返回空列表"""
        from fastapi_app.services.purchase_center_service import export_completed_orders
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        db.scalar = AsyncMock(return_value=0)

        rows = await export_completed_orders(db)
        assert rows == []

    async def test_export_accepts_all_request_schema_fields(self):
        """契约回归：导出服务必须接受 ExportCompletedRequest 的全部字段。

        历史缺陷：路由层用 **data.model_dump() 传参，而服务层只声明了
        supplier_id/date_from/date_to。因导出链路此前无前端调用方，该 TypeError
        一直未被触发，直到下单查询 TAB 恢复导出入口才暴露。
        """
        import inspect

        from fastapi_app.api.v1.endpoints.purchase_center.schemas import ExportCompletedRequest
        from fastapi_app.services.purchase_center_service import export_completed_orders

        # 全字段填充，确保模型 dump 出所有 key
        body = ExportCompletedRequest(
            order_no='PO-001', customer_name='客户A', product_name='产品X',
            start_date='2026-09-01', end_date='2026-09-14',
        )
        sent = set(body.model_dump(exclude_none=True).keys())
        accepted = set(inspect.signature(export_completed_orders).parameters.keys()) - {'db'}

        unsupported = sorted(sent - accepted)
        assert not unsupported, (
            f'路由层会传入这些字段但服务层不接受：{unsupported}，'
            f'调用将抛 TypeError。服务层需同步签名。'
        )

    @pytest.mark.asyncio
    async def test_export_applies_text_filters(self):
        """导出应把 order_no/customer_name/product_name 转成 ilike 条件（与列表口径一致）"""
        from fastapi_app.services.purchase_center_service import export_completed_orders
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        db.scalar = AsyncMock(return_value=0)

        await export_completed_orders(
            db, order_no='PO-001', customer_name='晨光', product_name='保温杯',
        )

        stmt = db.execute.call_args_list[0].args[0]
        compiled = str(stmt)
        # 三个文本字段都应生成 ilike 条件，值以绑定参数形式传入
        assert compiled.count('LIKE') == 3
        assert 'order_no' in compiled and 'customer_name' in compiled and 'product_name' in compiled
        assert set(stmt.compile().params.values()) >= {'%PO-001%', '%晨光%', '%保温杯%'}

    @pytest.mark.asyncio
    async def test_export_date_aliases_backward_compatible(self):
        """date_from/date_to 作为 start_date/end_date 的兼容别名仍生效"""
        from fastapi_app.services.purchase_center_service import export_completed_orders
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        db.scalar = AsyncMock(return_value=0)

        await export_completed_orders(db, date_from='2026-09-01', date_to='2026-09-14')
        params = db.execute.call_args_list[0].args[0].compile().params
        # 日期以绑定参数传入（非字符串拼接），结束日补齐到当日 23:59:59
        assert '2026-09-01' in params.values()
        assert '2026-09-14 23:59:59' in params.values()

    @pytest.mark.asyncio
    async def test_export_start_date_takes_precedence_over_alias(self):
        """同时传 start_date 与 date_from 时，以 start_date 为准"""
        from fastapi_app.services.purchase_center_service import export_completed_orders
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        db.scalar = AsyncMock(return_value=0)

        await export_completed_orders(db, start_date='2026-09-10', date_from='2026-01-01')
        values = db.execute.call_args_list[0].args[0].compile().params.values()
        assert '2026-09-10' in values
        assert '2026-01-01' not in values

    @pytest.mark.asyncio
    async def test_export_rejects_when_order_count_exceeds_limit(self):
        """2026-10-18 OCR 评审：门禁必须建在**未截断**的订单集上。

        旧实现先 `limit(EXPORT_MAX_ROWS + 1)` 截断订单再统计明细行 —— 订单被裁后
        明细行数永远不可能超限，`if len(rows) > EXPORT_MAX_ROWS` 形同虚设。
        现在先 COUNT 订单总数，超限即抛 ValueError（端点转 413）。
        """
        import pytest as _pytest

        from fastapi_app.services.export_limits import EXPORT_MAX_ROWS
        from fastapi_app.services.purchase_center_service import export_completed_orders

        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        db.scalar = AsyncMock(return_value=EXPORT_MAX_ROWS + 1)

        with _pytest.raises(ValueError, match='导出数据量过大'):
            await export_completed_orders(db)
        # 超限时必须**拒绝**，不得再拉明细（否则等于把超量的活干完才报错）
        assert db.execute.await_count == 0

    @pytest.mark.asyncio
    async def test_export_rejects_when_detail_rows_exceed_limit(self):
        """订单数未超限、但展开后明细行数爆上限 → 同样拒绝（不再静默截断）。"""
        from datetime import datetime
        from types import SimpleNamespace

        import pytest as _pytest

        from fastapi_app.services.export_limits import EXPORT_MAX_ROWS
        from fastapi_app.services.purchase_center_service import export_completed_orders

        # 1 个订单带 EXPORT_MAX_ROWS+1 行明细：订单数远未超限，行数超限
        order_row = SimpleNamespace(
            id=1, order_no='CG-1', supplier_name='S',
            customer_name='C', completed_at=datetime(2026, 1, 1),
            spare_rate=None,
        )
        item_rows = [
            SimpleNamespace(
                order_id=1, material_name='m', material_code='c', specification='',
                unit='米', quantity=1.0, unit_price=1.0, total_price=1.0,
                loss_rate=None,
            )
            for _ in range(EXPORT_MAX_ROWS + 1)
        ]
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[
            MagicMock(all=MagicMock(return_value=[order_row])),
            MagicMock(all=MagicMock(return_value=item_rows)),
        ])
        db.scalar = AsyncMock(return_value=1)

        with _pytest.raises(ValueError, match='导出明细超过上限'):
            await export_completed_orders(db)

    @pytest.mark.asyncio
    async def test_get_customers_statistics(self):
        from fastapi_app.services.purchase_center_service import get_customers_statistics
        db = MagicMock()
        r1 = MagicMock()
        r1.scalar.return_value = 100
        r2 = MagicMock()
        r2.scalar.return_value = 80
        r3 = MagicMock()
        r3.scalar.return_value = 10
        db.execute = AsyncMock(side_effect=[r1, r2, r3])

        result = await get_customers_statistics(db)
        assert result['total'] == 100
        assert result['active'] == 80

    @pytest.mark.asyncio
    async def test_get_unprocessed_orders_empty(self):
        """P-1：UNION ALL 返回 0 行时返回空列表"""
        from fastapi_app.core.cache import _cache_local
        from fastapi_app.services.purchase_order_query import get_unprocessed_orders

        # 清除所有缓存层（L1 + fallback），避免其他测试干扰
        _cache_local.clear()
        from utils.redis_cache import redis_cache
        redis_cache._fallback_cache.clear()

        db = MagicMock()
        # P-6: NOT EXISTS 子查询嵌入 COUNT SQL，无需预查询
        # COUNT 查询返回 0
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        db.execute = AsyncMock(return_value=count_result)

        result = await get_unprocessed_orders(db, page=1, per_page=20)

        assert result['orders'] == []
        assert result['total'] == 0
        assert result['current_page'] == 1

    @pytest.mark.asyncio
    async def test_get_unprocessed_orders_mixed_page(self):
        """P-1：验证 UNION ALL 混合页（order + stockin）的字段映射与排序"""
        from datetime import datetime
        from types import SimpleNamespace

        from fastapi_app.core.cache import _cache_local

        _cache_local.clear()
        from utils.redis_cache import redis_cache
        redis_cache._fallback_cache.clear()

        # 模拟 UNION ALL 分页查询返回的 Row（按 sort_date 降序）
        order_row = SimpleNamespace(
            record_type='order', source_id=1, order_no='DD-20260723-0001',
            customer='客户A', sort_date=datetime(2026, 7, 23, 14, 0, 0),
        )
        stockin_row = SimpleNamespace(
            record_type='stockin', source_id=2, order_no='BH-20260723-0001',
            customer='客户B', sort_date=datetime(2026, 7, 23, 10, 0, 0),
        )

        # 模拟 Order ORM 实例（含 items）
        mock_order_item = SimpleNamespace(
            id=10, product_id=100, product_name='产品X', product_barcode='690',
            quantity=50, order_type='regular', country='', deduct_quantity=0, note='',
        )
        mock_order = SimpleNamespace(
            id=1, order_no='DD-20260723-0001', customer='客户A',
            order_date=datetime(2026, 7, 23, 14, 0, 0), items=[mock_order_item],
        )

        # 模拟 StockIn ORM 实例
        mock_stockin = SimpleNamespace(
            id=2, stockin_no='BH-20260723-0001', customer='客户B',
            stockin_date=datetime(2026, 7, 23, 10, 0, 0),
            product_id=200, quantity=30, order_type='regular', country='', note='',
        )

        db = MagicMock()

        # db.execute 调用顺序：
        # 1. COUNT → 2
        # 2. 分页查询 → [order_row, stockin_row]
        # 3. Order 查询（selectinload items）→ [mock_order]
        # 4. StockIn 查询 → [mock_stockin]
        # 5. Product 查询 → [(100, '产品X', '690'), (200, '产品Y', '691')]
        count_result = MagicMock()
        count_result.scalar.return_value = 2

        page_result_mock = MagicMock()
        page_result_mock.all.return_value = [order_row, stockin_row]

        order_result_mock = MagicMock()
        # 函数直接迭代 .scalars().unique()（不调 .all()），故返回值需可迭代
        order_result_mock.scalars.return_value.unique.return_value = [mock_order]

        stockin_result_mock = MagicMock()
        # 函数直接迭代 .scalars()（不调 .all()），故返回值需可迭代
        stockin_result_mock.scalars.return_value = [mock_stockin]

        prod_result_mock = MagicMock()
        prod_result_mock.all.return_value = [
            (100, '产品X', '690'),
            (200, '产品Y', '691'),
        ]

        db.execute = AsyncMock(side_effect=[
            count_result,           # 1. COUNT
            page_result_mock,       # 2. 分页查询
            order_result_mock,      # 3. Order + items
            stockin_result_mock,    # 4. StockIn
            prod_result_mock,       # 5. Product 名称
        ])

        with patch(
            'fastapi_app.services.purchase_order_query._fetch_bom_product_ids',
            new_callable=AsyncMock, return_value={100},
        ):
            # 直接调用原始函数（绕过 cache_result 装饰器）
            # P-6: NOT EXISTS 子查询嵌入 SQL，无需 patch _fetch_processed_order_ids
            from fastapi_app.services.purchase_order_query import get_unprocessed_orders as _orig
            result = await _orig.__wrapped__(db, page=1, per_page=20)

        # 验证总数与分页
        assert result['total'] == 2
        assert result['current_page'] == 1
        assert len(result['orders']) == 2

        # 验证排序：order（14:00）在 stockin（10:00）之前
        first, second = result['orders']
        assert first['record_type'] == 'order'
        assert first['order_no'] == 'DD-20260723-0001'
        assert first['customer'] == '客户A'
        assert first['order_date'] == '2026-07-23'

        # 验证 order 的 items 字段映射
        assert first['sku_count'] == 1
        assert len(first['items']) == 1
        item = first['items'][0]
        assert item['product_id'] == 100
        assert item['product_name'] == '产品X'
        assert item['product_barcode'] == '690'
        assert item['has_bom'] is True  # 100 in bom_product_ids

        # 验证 stockin 记录
        assert second['record_type'] == 'stockin'
        assert second['order_no'] == 'BH-20260723-0001'
        assert second['customer'] == '客户B'
        assert second['product_id'] == 200
        assert second['product_name'] == '产品Y'  # 由 pid_name_map 填充
        # stockin 的 item has_bom=False（200 不在 bom_product_ids）
        assert second['items'][0]['has_bom'] is False

    @pytest.mark.asyncio
    async def test_get_unprocessed_orders_pagination_offset(self):
        """P-1：验证第 2 页的 offset 计算与空页处理"""
        from fastapi_app.core.cache import _cache_local
        from fastapi_app.services.purchase_order_query import get_unprocessed_orders

        _cache_local.clear()
        from utils.redis_cache import redis_cache
        redis_cache._fallback_cache.clear()

        db = MagicMock()
        # COUNT 返回 5，但第 2 页（per_page=20）无数据
        count_result = MagicMock()
        count_result.scalar.return_value = 5
        page_result = MagicMock()
        page_result.all.return_value = []  # 第 2 页为空

        db.execute = AsyncMock(side_effect=[count_result, page_result])

        # P-6: NOT EXISTS 子查询嵌入 SQL，无需 patch _fetch_processed_order_ids
        result = await get_unprocessed_orders(db, page=2, per_page=20)

        assert result['total'] == 5
        assert result['current_page'] == 2
        assert result['orders'] == []

    @pytest.mark.asyncio
    async def test_get_unprocessed_orders_not_processed_filter(self):
        """P-6：验证 NOT EXISTS 子查询嵌入后函数正常工作

        P-6 后排除逻辑由 NOT EXISTS JSONB 子查询在数据库层完成，
        无需预查询 processed_order_ids。此处验证函数路径不崩溃。
        """
        from datetime import datetime
        from types import SimpleNamespace

        from fastapi_app.core.cache import _cache_local

        _cache_local.clear()
        from utils.redis_cache import redis_cache
        redis_cache._fallback_cache.clear()

        # 模拟一条 order（NOT EXISTS 过滤由数据库完成，mock 无法验证其逻辑）
        order_row = SimpleNamespace(
            record_type='order', source_id=10, order_no='DD-001',
            customer='客户A', sort_date=datetime(2026, 7, 23, 14, 0, 0),
        )
        mock_order = SimpleNamespace(
            id=10, order_no='DD-001', customer='客户A',
            order_date=datetime(2026, 7, 23, 14, 0, 0),
            items=[SimpleNamespace(
                id=100, product_id=200, product_name='产品A', product_barcode='690',
                quantity=10, order_type='regular', country='', deduct_quantity=0, note='',
            )],
        )

        count_result = MagicMock()
        count_result.scalar.return_value = 1

        page_result_mock = MagicMock()
        page_result_mock.all.return_value = [order_row]

        order_result_mock = MagicMock()
        order_result_mock.scalars.return_value.unique.return_value = [mock_order]

        prod_result_mock = MagicMock()
        prod_result_mock.all.return_value = [(200, '产品A', '690')]

        db = MagicMock()
        db.execute = AsyncMock(side_effect=[
            count_result,       # 1. COUNT
            page_result_mock,   # 2. 分页查询
            order_result_mock,  # 3. Order + items（无 stockin 查询）
            prod_result_mock,   # 4. Product 名称
        ])

        # P-6: NOT EXISTS 子查询嵌入 SQL，无需 patch _fetch_processed_order_ids
        with patch(
            'fastapi_app.services.purchase_order_query._fetch_bom_product_ids',
            new_callable=AsyncMock, return_value=set(),
        ):
            from fastapi_app.services.purchase_order_query import get_unprocessed_orders as _orig
            result = await _orig.__wrapped__(db, page=1, per_page=20)

        # 验证函数正常执行，记录正确返回
        assert result['total'] == 1
        assert len(result['orders']) == 1
        assert result['orders'][0]['order_no'] == 'DD-001'


# ============================================================
# Endpoint 测试
# ============================================================

class TestPurchaseCenterEndpoints:
    """测试采购中心主要端点"""

    @pytest.mark.asyncio
    async def test_get_products_statistics(self, client):
        with patch('fastapi_app.services.purchase_center_service.get_products_statistics') as mock_svc:
            mock_svc.return_value = {'total': 50, 'has_bom': 30, 'no_bom': 20}
            resp = await client.get("/api/v1/purchase-center/products/statistics")
            assert resp.status_code == 200
            data = resp.json()
            assert data['success'] is True
            assert data['statistics']['total'] == 50

    @pytest.mark.asyncio
    async def test_get_categories(self, client):
        resp = await client.get("/api/v1/purchase-center/categories")
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert 'fabric' in data['categories']

    @pytest.mark.asyncio
    async def test_cache_clear_removed(self, client):
        resp = await client.post("/api/v1/purchase-center/cache/clear")
        assert resp.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_get_search_suggestions_empty(self, client):
        resp = await client.get("/api/v1/purchase-center/products/search-suggestions?q=")
        assert resp.status_code == 200
        data = resp.json()
        assert data['suggestions'] == []

    @pytest.mark.asyncio
    async def test_get_quick_filters(self, client):
        with patch('fastapi_app.services.purchase_center_service.get_completed_order_quick_filters', new_callable=AsyncMock, return_value={'today': 0, 'week': 0, 'month': 0}):
            resp = await client.get("/api/v1/purchase-center/orders/completed/quick-filters")
            assert resp.status_code == 200
            data = resp.json()
            assert data['success'] is True
            assert 'today' in data['quick_filters']
            assert 'week' in data['quick_filters']
            assert 'month' in data['quick_filters']

    @pytest.mark.asyncio
    async def test_get_modification_logs(self, client):
        with patch('fastapi_app.services.purchase_center_service.get_modification_logs') as mock_svc:
            mock_svc.return_value = {'logs': [{'id': 1, 'field_name': 'status'}], 'total': 1}
            resp = await client.get("/api/v1/purchase-center/modification-logs")
            assert resp.status_code == 200
            data = resp.json()
            assert data['success'] is True

    @pytest.mark.asyncio
    async def test_get_saved_queries(self, client):
        with patch('fastapi_app.services.purchase_center_service.get_saved_queries') as mock_svc:
            mock_svc.return_value = [{'id': 1, 'name': '测试'}]
            resp = await client.get("/api/v1/purchase-center/saved-queries")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data['queries']) == 1

    @pytest.mark.asyncio
    async def test_get_status_logs(self, client):
        with patch('fastapi_app.services.purchase_center_service.get_status_logs') as mock_svc:
            mock_svc.return_value = {'logs': [{'id': 1}], 'total': 1}
            resp = await client.get("/api/v1/purchase-center/status-logs")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_unprocessed_orders(self, client):
        with patch('fastapi_app.services.purchase_center_service.get_unprocessed_orders') as mock_svc:
            mock_svc.return_value = {'orders': [], 'total': 0, 'pages': 1, 'current_page': 1, 'latest_sync_time': None}
            resp = await client.get("/api/v1/purchase-center/unprocessed-orders")
            assert resp.status_code == 200
            data = resp.json()
            assert data['success'] is True
            assert data['total'] == 0
            assert data['pages'] == 1
            assert data['current_page'] == 1

    @pytest.mark.asyncio
    async def test_get_unprocessed_orders_pagination(self, client):
        with patch('fastapi_app.services.purchase_center_service.get_unprocessed_orders') as mock_svc:
            mock_svc.return_value = {
                'orders': [{'id': i} for i in range(15)],
                'total': 102,
                'pages': 7,
                'current_page': 1,
                'latest_sync_time': None,
            }
            resp = await client.get("/api/v1/purchase-center/unprocessed-orders?page=1&per_page=15")
            assert resp.status_code == 200
            data = resp.json()
            assert data['success'] is True
            assert data['total'] == 102
            assert data['pages'] == 7
            assert data['current_page'] == 1

    @pytest.mark.asyncio
    async def test_get_completed_suggestions_empty(self, client):
        resp = await client.get("/api/v1/purchase-center/orders/completed/suggestions?field=&q=")
        assert resp.status_code == 200
        data = resp.json()
        assert data['suggestions'] == []

    @pytest.mark.asyncio
    async def test_save_saved_query_missing_name(self, client):
        resp = await client.post("/api/v1/purchase-center/saved-queries", json={})
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_delete_saved_query(self, client):
        with patch('fastapi_app.services.purchase_center_service.delete_saved_query') as mock_svc:
            mock_svc.return_value = '已删除'
            resp = await client.delete("/api/v1/purchase-center/saved-queries/1")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_saved_query_not_found(self, client):
        with patch('fastapi_app.services.purchase_center_service.delete_saved_query') as mock_svc:
            mock_svc.return_value = None
            resp = await client.delete("/api/v1/purchase-center/saved-queries/999")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_use_saved_query(self, client):
        with patch('fastapi_app.services.purchase_center_service.use_saved_query') as mock_svc:
            mock_svc.return_value = {'id': 1, 'use_count': 1}
            resp = await client.post("/api/v1/purchase-center/saved-queries/1/use")
            assert resp.status_code == 200
            data = resp.json()
            assert data['success'] is True

    @pytest.mark.asyncio
    async def test_create_purchase_order_no_data(self, client):
        resp = await client.post("/api/v1/purchase-center/orders", json=None)
        assert resp.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_one_click_generate_empty(self, client):
        resp = await client.post("/api/v1/purchase-center/orders/one-click-generate", json={})
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_one_click_generate_works_normally(self, client):
        """一键生成端点应正常调用 service 并返回结果。"""
        expected = {
            'success': True,
            'message': '成功生成 1 个采购订单',
            'created_count': 1,
            'orders': [{'id': 20, 'order_no': 'CG-20'}],
        }
        async def _fake_svc(db, composite_ids, idempotency_key=''):
            return expected
        with patch(
            'fastapi_app.services.purchase_center_service.generate_purchase_orders_from_customer_orders',
            new=_fake_svc,
        ):
            resp = await client.post(
                "/api/v1/purchase-center/orders/one-click-generate",
                json={'composite_ids': ['order:5']},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data['success'] is True
            assert data['created_count'] == 1

    @pytest.mark.asyncio
    async def test_cleanup_orphan_includes_stockin(self):
        """cleanup_orphan_pending_purchase_orders 应同时处理 stockin_ids。"""
        from fastapi_app.services.purchase_order_crud import cleanup_orphan_pending_purchase_orders

        # 模拟一个 pending 采购单，其 source_order_ids 包含 stockin ID 3
        mock_po = MagicMock()
        mock_po.id = 100
        mock_po.status = 'pending'

        # row 是个具名 tuple (id, source_order_ids)
        row = MagicMock()
        row.source_order_ids = '[3, 4]'
        row.id = 100

        result2 = MagicMock()
        result2.all.return_value = [row]

        result = MagicMock()
        result.scalars.return_value.all.return_value = [mock_po]

        db = MagicMock()
        db.execute = AsyncMock(side_effect=[result2, result])
        db.delete = AsyncMock()

        deleted = await cleanup_orphan_pending_purchase_orders(
            db, order_ids=None, stockin_ids=[3],
        )
        assert deleted == 1
        # db.delete 必须被调用一次（删除该 pending 采购单）
        db.delete.assert_awaited_once_with(mock_po)

    @pytest.mark.asyncio
    async def test_cleanup_orphan_with_order_ids_still_works(self):
        """cleanup_orphan_pending_purchase_orders 接受 order_ids（向后兼容）。"""
        from fastapi_app.services.purchase_order_crud import cleanup_orphan_pending_purchase_orders

        mock_po = MagicMock()
        mock_po.id = 200
        mock_po.status = 'pending'

        result2 = MagicMock()
        result2.all.return_value = []

        result = MagicMock()
        result.scalars.return_value.all.return_value = [mock_po]

        db = MagicMock()
        db.execute = AsyncMock(side_effect=[result2, result])
        db.delete = AsyncMock()

        deleted = await cleanup_orphan_pending_purchase_orders(
            db, order_ids=[5, 6], stockin_ids=None,
        )
        assert deleted == 1
        db.delete.assert_awaited_once_with(mock_po)

    @pytest.mark.asyncio
    async def test_complete_order_missing_id(self, client):
        resp = await client.post("/api/v1/purchase-center/orders/complete", json={})
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_batch_complete_empty(self, client):
        resp = await client.post("/api/v1/purchase-center/orders/batch-complete", json={})
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_batch_print_empty(self, client):
        resp = await client.post("/api/v1/purchase-center/orders/batch-print", json={})
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_factory_summary_empty(self, client):
        resp = await client.post("/api/v1/purchase-center/orders/factory-summary", json={})
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_factory_summary_save_empty(self, client):
        resp = await client.post("/api/v1/purchase-center/orders/factory-summary/save", json={})
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_factory_summary_save_empty_edits_with_spare_rate_ok(self, client):
        """契约配对：`edits` 放宽为可空后，「仅改损耗率」必须仍可保存。

        与上一条 `test_factory_summary_save_empty` 共同锁定放宽后的边界：
        - 完全空 `{}`  → 422（无可保存内容，护栏拒绝）；
        - `edits=[] + spare_rate + order_ids` → 200（新需求合法路径，不得被护栏误伤）。
        """
        with patch(
            'fastapi_app.services.purchase_center_service.save_factory_summary_edits',
            new_callable=AsyncMock,
            return_value={'updated_count': 0, 'spare_updated_count': 1},
        ) as mock_svc:
            resp = await client.post(
                "/api/v1/purchase-center/orders/factory-summary/save",
                json={'edits': [], 'spare_rate': 50, 'order_ids': [1]},
            )
        assert resp.status_code == 200
        assert resp.json().get('success') is True
        mock_svc.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_factory_summary_save_no_content_payloads_422(self, client):
        """FIX-5 收紧：无任何可落库内容的 payload 必须 422（不得静默 200）。

        - `{order_ids:[...]}`（有目标无内容）：无 edit 也无 rate → 422；
        - `{spare_rate:...}`（无目标订单）：后端无从定位采购单 → 422；
        - `{edits:[...]}`（仅布料改动）：正常内容 → 200。
        与 `test_factory_summary_save_empty_edits_with_spare_rate_ok` 共同锁定收紧后的边界。
        """
        with patch(
            'fastapi_app.services.purchase_center_service.save_factory_summary_edits',
            new_callable=AsyncMock,
            return_value={'updated_count': 1, 'spare_updated_count': 0},
        ) as mock_svc:
            # 有目标无内容 → 422
            r1 = await client.post(
                "/api/v1/purchase-center/orders/factory-summary/save",
                json={'order_ids': [1]},
            )
            # 无目标订单 → 422
            r2 = await client.post(
                "/api/v1/purchase-center/orders/factory-summary/save",
                json={'spare_rate': 50},
            )
            # 仅布料改动（正常内容）→ 200
            r3 = await client.post(
                "/api/v1/purchase-center/orders/factory-summary/save",
                json={'edits': [{'item_ids': [1], 'quantity': 12}]},
            )
        assert r1.status_code == 422, f'有目标无内容应 422，实测 {r1.status_code}'
        assert r2.status_code == 422, f'无目标订单应 422，实测 {r2.status_code}'
        assert r3.status_code == 200, f'仅布料改动应 200，实测 {r3.status_code}'
        # 两个被拒请求不得触达 service；仅正常内容那一次调用
        mock_svc.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_supplier_summary_empty(self, client):
        resp = await client.post("/api/v1/purchase-center/orders/supplier-summary", json={})
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_supplier_summary_by_vendor_empty(self, client):
        resp = await client.post("/api/v1/purchase-center/orders/supplier-summary-by-vendor", json={})
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_summary_print_empty(self, client):
        resp = await client.post("/api/v1/purchase-center/orders/summary-print", json={})
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_get_purchase_orders_default(self, client):
        with patch('fastapi_app.services.purchase_center_service.get_purchase_orders') as mock_svc:
            mock_svc.return_value = {'orders': [], 'total': 0, 'pages': 0, 'current_page': 1}
            resp = await client.get("/api/v1/purchase-center/orders")
            assert resp.status_code == 200
            data = resp.json()
            assert data['success'] is True

    @pytest.mark.asyncio
    async def test_get_completed_orders(self, client):
        with patch('fastapi_app.services.purchase_center_service.get_completed_purchase_orders') as mock_svc:
            mock_svc.return_value = {'orders': [], 'total': 0, 'page': 1, 'per_page': 20, 'total_pages': 0}
            resp = await client.get("/api/v1/purchase-center/orders/completed")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_export_completed_orders(self, client):
        with patch('fastapi_app.services.purchase_center_service.export_completed_orders') as mock_svc:
            mock_svc.return_value = '<html></html>'
            resp = await client.post("/api/v1/purchase-center/orders/completed/export", json={})
            assert resp.status_code == 200
            data = resp.json()
            assert data['success'] is True

    @pytest.mark.asyncio
    async def test_get_order_not_found(self, client):
        with patch('fastapi_app.services.purchase_center_service.get_purchase_order') as mock_svc:
            mock_svc.return_value = None
            resp = await client.get("/api/v1/purchase-center/orders/999")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_order_not_found(self, client):
        with patch('fastapi_app.services.purchase_center_service.delete_purchase_order') as mock_svc:
            mock_svc.return_value = None
            resp = await client.delete("/api/v1/purchase-center/orders/999")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_order_print_not_found(self, client):
        with patch('fastapi_app.services.purchase_center_service.get_purchase_order') as mock_svc:
            mock_svc.return_value = None
            resp = await client.get("/api/v1/purchase-center/orders/999/print")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_customer_detail_not_found(self, client):
        with patch('fastapi_app.services.purchase_center_service.get_customer_detail') as mock_svc:
            mock_svc.return_value = None
            resp = await client.get("/api/v1/purchase-center/customers/999")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_customers_statistics(self, client):
        with patch('fastapi_app.services.purchase_center_service.get_customers_statistics') as mock_svc:
            mock_svc.return_value = {'total': 50, 'active': 40, 'inactive': 10, 'recent_updated': 5}
            resp = await client.get("/api/v1/purchase-center/customers/statistics")
            assert resp.status_code == 200
            data = resp.json()
            assert data['statistics']['total'] == 50


# ============================================================
# 模型测试
# ============================================================

class TestPurchaseCenterModels:
    def test_supplier_model(self):
        from fastapi_app.shared_models.supplier import Supplier
        assert Supplier.__tablename__ == 'supplier'

    def test_product_material_model(self):
        from fastapi_app.shared_models.product_material import (
            ProductAccessory,
            ProductFabric,
            ProductMaterial,
        )
        assert ProductMaterial.__tablename__ == 'product_material'
        assert ProductFabric.__tablename__ == 'product_fabric'
        assert ProductAccessory.__tablename__ == 'product_accessory'

    def test_modification_log_model(self):
        from fastapi_app.shared_models.purchase_center import ModificationLog
        assert ModificationLog.__tablename__ == 'modification_log'

    def test_saved_query_model(self):
        from fastapi_app.shared_models.purchase_center import SavedQuery
        assert SavedQuery.__tablename__ == 'saved_query'

    def test_order_status_log_model(self):
        from fastapi_app.shared_models.order_status_log import OrderStatusLog
        assert OrderStatusLog.__tablename__ == 'order_status_log'

    def test_material_categories(self):
        from fastapi_app.shared_models.product_material import MATERIAL_CATEGORIES
        assert 'fabric' in MATERIAL_CATEGORIES
        assert 'filling' in MATERIAL_CATEGORIES
        assert 'accessory' in MATERIAL_CATEGORIES
        assert 'packaging' in MATERIAL_CATEGORIES
        assert MATERIAL_CATEGORIES['fabric']['name'] == '面料类'

    def test_modification_log_to_dict(self):
        from fastapi_app.shared_models.purchase_center import ModificationLog
        log = ModificationLog(
            target_type='purchase_order', target_id=1,
            field_name='status', old_value='pending', new_value='completed',
            modifier_name='admin',
        )
        d = log.to_dict()
        assert d['target_type'] == 'purchase_order'
        assert d['field_name'] == 'status'

    def test_saved_query_to_dict(self):
        from fastapi_app.shared_models.purchase_center import SavedQuery
        sq = SavedQuery(name='测试', query_type='purchase_order', conditions='{}')
        d = sq.to_dict()
        assert d['name'] == '测试'
        assert d['query_type'] == 'purchase_order'

    def test_order_status_log_to_dict(self):
        from fastapi_app.shared_models.order_status_log import OrderStatusLog
        log = OrderStatusLog(target_type='purchase_order', target_id=1, to_status='completed', action='complete')
        d = log.to_dict()
        assert d['to_status'] == 'completed'
        assert d['action'] == 'complete'


# ============================================================
# 一键生成采购订单分组逻辑测试
# ============================================================

class TestOneClickGenerateGrouping:
    @pytest.mark.asyncio
    async def test_single_po_with_supplier_details(self):
        """1 个客户订单 = 1 个采购订单：所有供应商的物料作为该订单的明细"""
        from fastapi_app.services.purchase_order_generate import one_click_generate_order

        db = MagicMock()
        created = []

        async def fake_create(_db, data, **kwargs):
            created.append(data)
            return {'order_no': f'CG-20260624-{len(created):04d}', 'id': len(created), 'total_amount': 0}

        with patch('fastapi_app.services.purchase_order_generate.create_purchase_order', fake_create):
            items = [
                {'supplier_id': None, 'supplier_name': '供应商A', 'customer_name': '客户1', 'material_name': '棉花', 'quantity': 10},
                {'supplier_id': None, 'supplier_name': '供应商B', 'customer_name': '客户1', 'material_name': '面料', 'quantity': 5},
                {'supplier_id': 2, 'supplier_name': '供应商C', 'customer_name': '客户1', 'material_name': '配件', 'quantity': 3},
            ]
            result = await one_click_generate_order(
                db, items, customer_name='客户1', source_order_ids=[1]
            )

        assert result['count'] == 1
        assert len(created) == 1
        # 供应商信息保留在明细级：3 条明细（含 supplier_id 为 None 的项）全部在同一 PO 内
        po_items = created[0]['items']
        assert len(po_items) == 3
        assert sum(1 for it in po_items if it['supplier_id'] is None) == 2


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
            assert resp.status_code in (400, 422)

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
            assert resp.status_code in (400, 422)

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

        async def fake_get_mux(_cls, oid):
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

        async def fake_get_mux(_cls, oid):
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
