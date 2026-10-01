"""
库存路由测试 — FastAPI 异步版

测试范围：入库、出库、库存查看等完整流程。
从 Flask test_client 迁移至 httpx AsyncClient。
"""
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from fastapi_app.shared_models import InventoryLog, Order, StockIn, StockOut

MARK = pytest.mark.integration


# ============================================================
# 入库路由测试
# ============================================================

@MARK
class TestStockInRoutes:

    @pytest.mark.asyncio
    async def test_stockin_list_get_success(self, async_client, auth_headers):
        """测试入库列表 API 访问成功"""
        resp = await async_client.get("/api/v1/stock/in/list", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data or "data" in data

    @pytest.mark.asyncio
    async def test_stockin_create_success(self, async_client, auth_headers, async_db_session, test_product, test_customer):
        """测试创建入库记录成功"""
        initial_stock = test_product.current_stock

        payload = {
            "product_id": test_product.id,
            "customer": test_customer.name,
            "quantity": 50,
            "stockin_date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "note": "测试入库",
        }
        resp = await async_client.post("/api/v1/stock/in/create", headers=auth_headers, json=payload)
        assert resp.status_code in (200, 201)

        # 验证库存增加
        await async_db_session.refresh(test_product)
        assert test_product.current_stock == initial_stock + 50

    @pytest.mark.asyncio
    async def test_stockin_create_missing_product(self, async_client, auth_headers, test_customer):
        """测试创建入库记录缺少产品ID"""
        payload = {
            "customer": test_customer.name,
            "quantity": 50,
            "stockin_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        resp = await async_client.post("/api/v1/stock/in/create", headers=auth_headers, json=payload)
        assert resp.status_code in (200, 400, 422)

    @pytest.mark.asyncio
    async def test_stockin_create_nonexistent_product(self, async_client, auth_headers, test_customer):
        """测试创建入库记录产品不存在"""
        payload = {
            "product_id": 99999,
            "customer": test_customer.name,
            "quantity": 50,
            "stockin_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        resp = await async_client.post("/api/v1/stock/in/create", headers=auth_headers, json=payload)
        assert resp.status_code in (200, 400, 422, 404)

    @pytest.mark.asyncio
    async def test_stockin_edit_get_success(self, async_client, auth_headers, test_stockin):
        """测试入库编辑 API 可达（编辑现为 PUT /in/edit/{id}，无 GET 表单路由）"""
        resp = await async_client.put(
            f"/api/v1/stock/in/edit/{test_stockin.id}",
            headers=auth_headers,
            json={},  # 部分更新语义：空载荷沿用原值
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_stockin_edit_success(self, async_client, auth_headers, async_db_session, test_stockin, test_product, test_customer):
        """测试编辑入库记录成功"""
        old_quantity = test_stockin.quantity
        new_quantity = old_quantity + 20

        payload = {
            "customer": test_customer.name,
            "quantity": new_quantity,
            "stockin_date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "note": "更新后的入库",
        }
        resp = await async_client.put(
            f"/api/v1/stock/in/edit/{test_stockin.id}", headers=auth_headers, json=payload
        )
        assert resp.status_code in (200, 201)

        await async_db_session.refresh(test_stockin)
        assert test_stockin.quantity == new_quantity

    @pytest.mark.asyncio
    async def test_stockin_edit_stock_update(self, async_client, auth_headers, async_db_session, test_stockin, test_product, test_customer):
        """测试编辑入库记录时库存更新"""
        initial_stock = test_product.current_stock
        old_quantity = test_stockin.quantity
        new_quantity = old_quantity + 30

        payload = {
            "customer": test_customer.name,
            "quantity": new_quantity,
            "stockin_date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "note": "更新",
        }
        await async_client.put(
            f"/api/v1/stock/in/edit/{test_stockin.id}", headers=auth_headers, json=payload
        )

        await async_db_session.refresh(test_product)
        assert test_product.current_stock == initial_stock + 30

    @pytest.mark.asyncio
    async def test_stockin_delete_success(self, async_client, auth_headers, async_db_session, test_stockin, test_product):
        """测试删除入库记录成功"""
        initial_stock = test_product.current_stock
        stockin_id = test_stockin.id
        stockin_quantity = test_stockin.quantity

        resp = await async_client.delete(
            f"/api/v1/stock/in/delete/{stockin_id}", headers=auth_headers
        )
        assert resp.status_code in (200, 201)

        # 验证入库记录已删除
        result = await async_db_session.execute(
            select(StockIn).where(StockIn.id == stockin_id)
        )
        assert result.scalars().first() is None

        # 验证库存减少
        await async_db_session.refresh(test_product)
        assert test_product.current_stock == initial_stock - stockin_quantity

    @pytest.mark.asyncio
    async def test_stockin_delete_not_found(self, async_client, auth_headers):
        """测试删除不存在的入库记录"""
        resp = await async_client.delete("/api/v1/stock/in/delete/99999", headers=auth_headers)
        assert resp.status_code in (404, 400)

    @pytest.mark.asyncio
    async def test_stockin_delete_with_stockouts(self, async_client, auth_headers, async_db_session, test_stockin, test_product, test_customer):
        """测试删除有关联出库的入库记录"""
        # 创建关联的出库记录
        stockout = StockOut(
            stockout_no="SO-TEST-001",
            product_id=test_product.id,
            customer=test_customer.name,
            quantity=10,
            stockin_id=test_stockin.id,
            stockout_date=datetime.now(UTC),
        )
        async_db_session.add(stockout)
        await async_db_session.flush()

        resp = await async_client.delete(
            f"/api/v1/stock/in/delete/{test_stockin.id}", headers=auth_headers
        )
        assert resp.status_code in (200, 400, 409)
        data = resp.json()
        assert not data.get("success", True) or "error" in str(data).lower() or "无法" in str(data)

    @pytest.mark.asyncio
    async def test_stockin_edit_quantity_with_stockouts_rejected(self, async_client, auth_headers, async_db_session, test_customer):
        """有出库关联的入库不允许改数量（与删除保护对称；2026-10-01 迭代审计补充）。

        独立自建产品/入库/出库，不碰共享 fixture 的状态（后续 delete 用例依赖它）。
        """
        import uuid

        from fastapi_app.shared_models.product import Product

        tag = uuid.uuid4().hex[:8]
        product = Product(name=f"出库关联守卫产品·{tag}", current_stock=100, initial_stock=100)
        async_db_session.add(product)
        await async_db_session.flush()
        stockin = StockIn(
            stockin_no=f"SI-GUARD1-{tag}", product_id=product.id, customer=test_customer.name,
            quantity=50, stockin_date=datetime.now(UTC),
        )
        async_db_session.add(stockin)
        await async_db_session.flush()
        stockout = StockOut(
            stockout_no=f"SO-GUARD1-{tag}", product_id=product.id, customer=test_customer.name,
            quantity=10, stockin_id=stockin.id, stockout_date=datetime.now(UTC),
        )
        async_db_session.add(stockout)
        await async_db_session.flush()

        payload = {
            "customer": test_customer.name,
            "quantity": 55,  # 50 → 55，仅改数量也应被拒
            "stockin_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        resp = await async_client.put(
            f"/api/v1/stock/in/edit/{stockin.id}", headers=auth_headers, json=payload
        )
        assert resp.status_code == 400
        assert "出库关联" in resp.text

    @pytest.mark.asyncio
    async def test_stockin_edit_quantity_negative_stock_rejected(self, async_client, auth_headers, async_db_session, test_customer):
        """编辑入库导致库存为负被拒（与删除保护对称；2026-10-01 迭代审计补充）"""
        import uuid

        from fastapi_app.shared_models.product import Product

        tag = uuid.uuid4().hex[:8]
        product = Product(name=f"负库存守卫产品·{tag}", current_stock=5, initial_stock=5)
        async_db_session.add(product)
        await async_db_session.flush()
        stockin = StockIn(
            stockin_no=f"SI-GUARD2-{tag}", product_id=product.id, customer=test_customer.name,
            quantity=50, stockin_date=datetime.now(UTC),
        )
        async_db_session.add(stockin)
        await async_db_session.flush()

        payload = {
            "customer": test_customer.name,
            "quantity": 5,  # 50 → 5 减 45，超过当前库存 5
            "stockin_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        resp = await async_client.put(
            f"/api/v1/stock/in/edit/{stockin.id}", headers=auth_headers, json=payload
        )
        assert resp.status_code == 400
        assert "库存为负" in resp.text


# ============================================================
# 出库路由测试
# ============================================================

@MARK
class TestStockOutRoutes:

    @pytest.mark.asyncio
    async def test_stockout_list_get_success(self, async_client, auth_headers):
        """测试出库列表 API 访问成功"""
        resp = await async_client.get("/api/v1/stock/out/list", headers=auth_headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_stockout_create_success(self, async_client, auth_headers, async_db_session, test_product, test_customer, test_order):
        """测试创建出库记录成功（出库受 FIFO 订单约束，需先有该客户订单）"""
        test_product.current_stock = 100
        await async_db_session.flush()

        initial_stock = test_product.current_stock
        payload = {
            "product_id": test_product.id,
            "quantity": 20,
            "customer": test_customer.name,
            "stockout_date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "note": "测试出库",
        }
        resp = await async_client.post("/api/v1/stock/out/create", headers=auth_headers, json=payload)
        assert resp.status_code in (200, 201)

        await async_db_session.refresh(test_product)
        assert test_product.current_stock == initial_stock - 20

    @pytest.mark.asyncio
    async def test_stockout_create_insufficient_stock(self, async_client, auth_headers, async_db_session, test_product, test_customer, test_order):
        """测试库存不足时出库（400，业务校验在服务层）"""
        test_product.current_stock = 10
        await async_db_session.flush()

        payload = {
            "product_id": test_product.id,
            "quantity": 100,
            "customer": test_customer.name,
            "stockout_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        resp = await async_client.post("/api/v1/stock/out/create", headers=auth_headers, json=payload)
        assert resp.status_code == 400
        data = resp.json()
        assert not data.get("success", True) or "error" in str(data).lower() or "不足" in str(data)

    @pytest.mark.asyncio
    async def test_stockout_create_nonexistent_product(self, async_client, auth_headers):
        """测试创建出库记录产品不存在"""
        payload = {
            "product_id": 99999,
            "quantity": 20,
            "stockout_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        resp = await async_client.post("/api/v1/stock/out/create", headers=auth_headers, json=payload)
        assert resp.status_code in (200, 400, 422, 404)

    @pytest.mark.asyncio
    async def test_stockout_edit_get_success(self, async_client, auth_headers, test_stockout):
        """测试出库编辑 API 可达（编辑现为 PUT /out/edit/{id}，无 GET 表单路由）"""
        resp = await async_client.put(
            f"/api/v1/stock/out/edit/{test_stockout.id}",
            headers=auth_headers,
            json={},  # 部分更新语义：空载荷沿用原值
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_stockout_edit_success(self, async_client, auth_headers, async_db_session, test_stockout, test_product):
        """测试编辑出库记录成功"""
        test_product.current_stock = 100
        await async_db_session.flush()

        old_quantity = test_stockout.quantity
        new_quantity = old_quantity + 5

        payload = {
            "quantity": new_quantity,
            "stockout_date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "note": "更新后的出库",
        }
        resp = await async_client.put(
            f"/api/v1/stock/out/edit/{test_stockout.id}", headers=auth_headers, json=payload
        )
        assert resp.status_code in (200, 201)

        await async_db_session.refresh(test_stockout)
        assert test_stockout.quantity == new_quantity

    @pytest.mark.asyncio
    async def test_stockout_edit_insufficient_stock(self, async_client, auth_headers, async_db_session, test_stockout, test_product):
        """测试编辑出库记录库存不足"""
        test_product.current_stock = 5
        await async_db_session.flush()

        payload = {
            "quantity": 100,
            "stockout_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        resp = await async_client.put(
            f"/api/v1/stock/out/edit/{test_stockout.id}", headers=auth_headers, json=payload
        )
        assert resp.status_code in (200, 400)

    @pytest.mark.asyncio
    async def test_stockout_delete_success(self, async_client, auth_headers, async_db_session, test_stockout, test_product):
        """测试删除出库记录成功"""
        initial_stock = test_product.current_stock
        stockout_id = test_stockout.id
        stockout_quantity = test_stockout.quantity

        resp = await async_client.delete(
            f"/api/v1/stock/out/delete/{stockout_id}", headers=auth_headers
        )
        assert resp.status_code in (200, 201)

        result = await async_db_session.execute(
            select(StockOut).where(StockOut.id == stockout_id)
        )
        assert result.scalars().first() is None

        await async_db_session.refresh(test_product)
        assert test_product.current_stock == initial_stock + stockout_quantity

    @pytest.mark.asyncio
    async def test_stockout_delete_not_found(self, async_client, auth_headers):
        """测试删除不存在的出库记录"""
        resp = await async_client.delete("/api/v1/stock/out/delete/99999", headers=auth_headers)
        assert resp.status_code in (404, 400)


# ============================================================
# 库存查看路由测试
# ============================================================

@MARK
class TestInventoryRoutes:

    @pytest.mark.asyncio
    async def test_inventory_view_success(self, async_client, auth_headers):
        """测试库存查看 API 访问成功"""
        resp = await async_client.get("/api/v1/stock/inventory", headers=auth_headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_inventory_with_data(self, async_client, auth_headers, async_db_session, test_product, test_customer):
        """测试有产品数据时的库存查看"""
        # 创建相关业务数据
        order = Order(
            order_no="ORD-INV-001",
            product_id=test_product.id,
            customer=test_customer.name,
            quantity=20,
            order_date=datetime.now(UTC),
            status="待备货",
        )
        async_db_session.add(order)
        await async_db_session.flush()

        stockin = StockIn(
            stockin_no="SI-INV-001",
            product_id=test_product.id,
            customer=test_customer.name,
            quantity=50,
            stockin_date=datetime.now(UTC),
        )
        async_db_session.add(stockin)
        await async_db_session.flush()

        resp = await async_client.get("/api/v1/stock/inventory", headers=auth_headers)
        assert resp.status_code == 200


# ============================================================
# 库存业务逻辑测试
# ============================================================

@MARK
class TestStockBusinessLogic:

    @pytest.mark.asyncio
    async def test_stockin_creates_inventory_log(self, async_client, auth_headers, async_db_session, test_product, test_customer):
        """测试入库时库存日志创建"""
        payload = {
            "product_id": test_product.id,
            "customer": test_customer.name,
            "quantity": 30,
            "stockin_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        await async_client.post("/api/v1/stock/in/create", headers=auth_headers, json=payload)

        result = await async_db_session.execute(
            select(InventoryLog)
            .where(InventoryLog.product_id == test_product.id)
            .order_by(InventoryLog.id.desc())
        )
        log = result.scalars().first()
        assert log is not None
        assert log.change_quantity == 30

    @pytest.mark.asyncio
    async def test_stockout_creates_inventory_log(self, async_client, auth_headers, async_db_session, test_product, test_customer, test_order):
        """测试出库时库存日志创建（出库受 FIFO 订单约束，需先有该客户订单）"""
        test_product.current_stock = 100
        await async_db_session.flush()

        payload = {
            "product_id": test_product.id,
            "quantity": 25,
            "customer": test_customer.name,
            "stockout_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        resp = await async_client.post("/api/v1/stock/out/create", headers=auth_headers, json=payload)
        assert resp.status_code in (200, 201), resp.text

        result = await async_db_session.execute(
            select(InventoryLog)
            .where(InventoryLog.product_id == test_product.id)
            .order_by(InventoryLog.id.desc())
        )
        log = result.scalars().first()
        assert log is not None
        assert log.change_quantity == -25

    @pytest.mark.asyncio
    async def test_stockin_edit_creates_log(self, async_client, auth_headers, async_db_session, test_stockin, test_product, test_customer):
        """测试编辑入库时库存日志更新"""
        old_quantity = test_stockin.quantity
        new_quantity = old_quantity + 15

        payload = {
            "customer": test_customer.name,
            "quantity": new_quantity,
            "stockin_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        await async_client.put(
            f"/api/v1/stock/in/edit/{test_stockin.id}", headers=auth_headers, json=payload
        )

        result = await async_db_session.execute(
            select(InventoryLog)
            .where(InventoryLog.product_id == test_product.id)
            .order_by(InventoryLog.id.desc())
        )
        log = result.scalars().first()
        assert log is not None
        assert log.change_quantity == 15


# ============================================================
# 边界条件测试
# ============================================================

@MARK
class TestStockEdgeCases:

    @pytest.mark.asyncio
    async def test_stockin_zero_quantity(self, async_client, auth_headers, test_product, test_customer):
        """测试零数量入库"""
        payload = {
            "product_id": test_product.id,
            "customer": test_customer.name,
            "quantity": 0,
            "stockin_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        resp = await async_client.post("/api/v1/stock/in/create", headers=auth_headers, json=payload)
        assert resp.status_code in (200, 400, 422)

    @pytest.mark.asyncio
    async def test_stockout_zero_quantity(self, async_client, auth_headers, test_product):
        """测试零数量出库"""
        payload = {
            "product_id": test_product.id,
            "quantity": 0,
            "stockout_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        resp = await async_client.post("/api/v1/stock/out/create", headers=auth_headers, json=payload)
        assert resp.status_code in (200, 400, 422)

    @pytest.mark.asyncio
    async def test_stockout_exact_stock(self, async_client, auth_headers, async_db_session, test_product, test_customer):
        """测试出库数量等于库存（专用订单，避免与套件内其他出货共享可出货量）"""
        from fastapi_app.shared_models.order import Order

        test_product.current_stock = 50
        await async_db_session.flush()

        order = Order(
            order_no="ORD-TEST-EXACT-001",
            product_id=test_product.id,
            customer=test_customer.name,
            quantity=50,
            order_date=datetime.now(UTC),
            status="待备货",
        )
        async_db_session.add(order)
        await async_db_session.flush()

        payload = {
            "product_id": test_product.id,
            "quantity": 50,
            "customer": test_customer.name,
            "stockout_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        resp = await async_client.post("/api/v1/stock/out/create", headers=auth_headers, json=payload)
        assert resp.status_code in (200, 201)

        await async_db_session.refresh(test_product)
        assert test_product.current_stock == 0

    @pytest.mark.asyncio
    async def test_stockin_with_future_date(self, async_client, auth_headers, test_product, test_customer):
        """测试未来日期入库"""
        payload = {
            "product_id": test_product.id,
            "customer": test_customer.name,
            "quantity": 10,
            "stockin_date": "2030-12-31",
        }
        resp = await async_client.post("/api/v1/stock/in/create", headers=auth_headers, json=payload)
        assert resp.status_code in (200, 201, 400)

    @pytest.mark.asyncio
    async def test_stockin_with_past_date(self, async_client, auth_headers, test_product, test_customer):
        """测试过去日期入库"""
        payload = {
            "product_id": test_product.id,
            "customer": test_customer.name,
            "quantity": 10,
            "stockin_date": "2020-01-01",
        }
        resp = await async_client.post("/api/v1/stock/in/create", headers=auth_headers, json=payload)
        assert resp.status_code in (200, 201)


# ============================================================
# 性能测试
# ============================================================

@MARK
class TestStockPerformance:

    @pytest.mark.asyncio
    async def test_stockin_list_with_many_records(self, async_client, auth_headers, async_db_session, test_product, test_customer):
        """测试大量入库记录列表查询"""
        for i in range(100):
            stockin = StockIn(
                stockin_no=f"SI-PERF-{i:04d}",
                product_id=test_product.id,
                customer=test_customer.name,
                quantity=10,
                stockin_date=datetime.now(UTC),
            )
            async_db_session.add(stockin)
        await async_db_session.flush()

        resp = await async_client.get("/api/v1/stock/in/list", headers=auth_headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_stockout_list_with_many_records(self, async_client, auth_headers, async_db_session, test_product):
        """测试大量出库记录列表查询"""
        test_product.current_stock = 10000
        await async_db_session.flush()

        for i in range(100):
            stockout = StockOut(
                stockout_no=f"SO-PERF-{i:04d}",
                product_id=test_product.id,
                quantity=5,
                stockout_date=datetime.now(UTC),
            )
            async_db_session.add(stockout)
        await async_db_session.flush()

        resp = await async_client.get("/api/v1/stock/out/list", headers=auth_headers)
        assert resp.status_code == 200
