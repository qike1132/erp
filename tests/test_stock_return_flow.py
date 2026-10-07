"""退货管理全流程 E2E 测试（按产品退货，模拟数据走完整业务链）。

P1 录入变更：退货 = 选产品 + 数量（不关联出货单/订单），库存 +N、流水留痕；
取消（软删除）对称扣回并保留记录；request_id 幂等防重复提交。
全程经真实服务层与 ASGI HTTP，事务由 savepoint 统一回滚。
另覆盖历史关联行（stockout_id 非空）取消时的 returned_quantity 回减分支。
"""
import uuid

import pytest
from sqlalchemy import select
from test_stock_return_api import sr_api as _flow_api_fixture
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.services import stock_service

# pytest 按模块属性名注册导入的夹具：赋值回 sr_api，供本文件用例以 sr_api 参数取用
sr_api = _flow_api_fixture

from fastapi_app.shared_models import InventoryLog, Order, Product, StockIn, StockOut, StockReturn



async def _fresh_product(db, suffix, stock):
    from fastapi_app.shared_models import Product
    product = Product(name=f"流程产品-{suffix}", current_stock=stock)
    db.add(product)
    await db.flush()
    # 库存结余闸门（2026-10-07）：出货要求「包装部入库 − 已出货」≥ 出货量，
    # 故补一条足量包装部入库记录。
    from datetime import UTC, datetime

    from fastapi_app.shared_models import DailyProductionRecord
    db.add(DailyProductionRecord(
        department='packaging', product_id=product.id,
        product_name=product.name, barcode='', quantity=100000,
        production_date=datetime.now(UTC).date(),
    ))
    await db.flush()
    return product


async def _fresh_order(db, product, suffix, quantity):
    from fastapi_app.shared_models import Order
    order = Order(order_no=f"ORD-FLOW-{suffix}", product_id=product.id,
                  customer=f"流程客户-{suffix}", quantity=quantity, status="待备货")
    db.add(order)
    await db.flush()
    return order


@pytest.mark.integration
class TestStockReturnFullFlow:
    """按产品退货 · 全流程（模拟数据 + 真实服务层/HTTP）"""

    async def test_stockout_return_and_cancel_cycle(self, sr_api):
        """出货 -> 搜索明细 -> 退货(幂等) -> 超退拒绝 -> 取消(软删/对称回冲)"""
        client, db, _ = sr_api
        suffix = uuid.uuid4().hex[:8]
        customer = f"流程客户-{suffix}"
        product = await _fresh_product(db, suffix, stock=100)
        order = await _fresh_order(db, product, suffix, quantity=30)

        async with db_transaction(db):
            await stock_service.create_stockout(
                db, product_id=product.id, quantity=30, customer=customer,
                stockout_date_str="2026-10-05", note="流程测试",
            )
        await db.refresh(product)
        assert product.current_stock == 70
        stockout = (await db.execute(
            select(StockOut).where(StockOut.customer == customer)
        )).scalars().one()
        await db.refresh(order)
        assert order.status == "已出货"

        # 搜索明细：按产品名可搜到，可退 30
        resp = await client.get("/api/v1/stock-returns/shipment-options",
                                params={"q": "流程产品"})
        assert resp.status_code == 200, resp.text
        rows = [r for r in resp.json() if r["stockout_no"] == stockout.stockout_no]
        assert rows and rows[0]["available"] == 30

        # 退货 10（幂等令牌）：库存 80、明细已退 10、订单待出货
        resp = await client.post("/api/v1/stock-returns/create", json={
            "stockout_id": stockout.id, "quantity": 10, "reason": "质量问题",
            "request_id": "flow-e2e-req-0001",
        })
        assert resp.status_code == 200, resp.text
        await db.refresh(product); await db.refresh(stockout); await db.refresh(order)
        assert product.current_stock == 80
        assert stockout.returned_quantity == 10
        assert order.status == "待出货"

        # 同令牌重复提交 -> 400，不二次累计
        resp = await client.post("/api/v1/stock-returns/create", json={
            "stockout_id": stockout.id, "quantity": 10, "reason": "质量问题",
            "request_id": "flow-e2e-req-0001",
        })
        assert resp.status_code == 400 and "请勿重复提交" in resp.json()["detail"]
        await db.refresh(stockout)
        assert stockout.returned_quantity == 10

        # 超退：可退 20，退 21 -> 400
        resp = await client.post("/api/v1/stock-returns/create", json={
            "stockout_id": stockout.id, "quantity": 21, "reason": "错发",
        })
        assert resp.status_code == 400 and "可退：20" in resp.json()["detail"]

        # 恰好退满：可退 0，明细从搜索结果消失
        resp = await client.post("/api/v1/stock-returns/create", json={
            "stockout_id": stockout.id, "quantity": 20, "reason": "换货",
        })
        assert resp.status_code == 200, resp.text
        await db.refresh(product)
        assert product.current_stock == 100
        resp = await client.get("/api/v1/stock-returns/shipment-options",
                                params={"q": "流程产品"})
        assert resp.json() == []

        # 取消第一张：库存 90、明细已退 20、订单待出货；重复取消 400
        resp = await client.get("/api/v1/stock-returns/list", params={"customer": customer})
        body = resp.json()
        ids = {r["id"]: r for r in body["data"]}
        first_id = next(rid for rid, r in ids.items() if r["quantity"] == 10)
        resp = await client.delete(f"/api/v1/stock-returns/{first_id}")
        assert resp.status_code == 200 and "取消" in resp.json()["message"]
        await db.refresh(product); await db.refresh(stockout); await db.refresh(order)
        assert product.current_stock == 90
        assert stockout.returned_quantity == 20
        assert order.status == "待出货"
        resp = await client.delete(f"/api/v1/stock-returns/{first_id}")
        assert resp.status_code == 400 and "已取消" in resp.json()["detail"]

        # 取消第二张：全部回冲到出货后原点，记录保留
        resp = await client.get("/api/v1/stock-returns/list", params={"customer": customer})
        remaining = next(r for r in resp.json()["data"] if r["status"] == "active")
        resp = await client.delete(f"/api/v1/stock-returns/{remaining['id']}")
        assert resp.status_code == 200, resp.text
        await db.refresh(product); await db.refresh(stockout); await db.refresh(order)
        assert product.current_stock == 70
        assert stockout.returned_quantity == 0
        assert order.status == "已出货"
        resp = await client.get("/api/v1/stock-returns/list", params={"customer": customer})
        assert all(r["status"] == "cancelled" for r in resp.json()["data"])

    async def test_cancel_legacy_stockout_linked_return(self, sr_api):
        """历史关联行（stockout_id 非空）取消：回减出货单 returned_quantity 并重算订单"""
        client, db, _ = sr_api
        suffix = uuid.uuid4().hex[:8]
        customer = f"历史客户-{suffix}"
        product = Product(name=f"历史关联产品-{suffix}", current_stock=50)
        db.add(product)
        await db.flush()
        order = Order(
            order_no=f"ORD-LEGACY-{suffix}", product_id=product.id,
            customer=customer, quantity=10, status="待出货",
        )
        db.add(order)
        await db.flush()
        stockout = StockOut(
            stockout_no=f"SO-LEG-{suffix}", product_id=product.id,
            quantity=10, customer=customer, returned_quantity=5,
            order_id=order.id,
        )
        db.add(stockout)
        await db.flush()
        legacy_return = StockReturn(
            return_no=f"SR-LEG-{suffix}", product_id=product.id, quantity=5,
            customer=customer, stockout_id=stockout.id, order_id=order.id,
            reason="错发",
        )
        db.add(legacy_return)
        await db.flush()

        # 取消历史关联退货：returned_quantity 回减 + 订单净出货 10/10 → 已出货
        resp = await client.delete(f"/api/v1/stock-returns/{legacy_return.id}")
        assert resp.status_code == 200, resp.text
        await db.refresh(product)
        assert product.current_stock == 45, "取消 5 件应扣回至 45"
        await db.refresh(stockout)
        assert stockout.returned_quantity == 0, "历史关联行的 returned_quantity 应回减"
        await db.refresh(order)
        assert order.status == "已出货", "净出货回到 10/10，订单恢复已出货"

        resp = await client.get("/api/v1/stock-returns/list", params={"customer": customer})
        assert resp.json()["data"][0]["status"] == "cancelled"
