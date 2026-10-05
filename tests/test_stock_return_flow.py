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

# pytest 按模块属性名注册导入的夹具：赋值回 sr_api，供本文件用例以 sr_api 参数取用
sr_api = _flow_api_fixture

from fastapi_app.shared_models import InventoryLog, Order, Product, StockIn, StockOut, StockReturn


@pytest.mark.integration
class TestStockReturnFullFlow:
    """按产品退货 · 全流程（模拟数据 + 真实服务层/HTTP）"""

    async def test_product_return_and_cancel_cycle(self, sr_api):
        """创建（库存+流水+列表）→ 幂等重复提交被拒 → 取消（对称扣回、记录保留）"""
        client, db, _ = sr_api
        suffix = uuid.uuid4().hex[:8]
        customer = f"流程客户-{suffix}"
        product = Product(name=f"退货流程产品-{suffix}", current_stock=100)
        db.add(product)
        await db.flush()

        # ---- 1) 列表为空 → 按产品创建退货 10：库存回补 + 流水 ----
        resp = await client.get("/api/v1/stock-returns/list", params={"customer": customer})
        assert resp.status_code == 200 and resp.json()["total"] == 0

        resp = await client.post("/api/v1/stock-returns/create", json={
            "product_id": product.id, "quantity": 10, "customer": customer,
            "reason": "质量问题", "note": "E2E", "request_id": "flow-e2e-req-0001",
        })
        assert resp.status_code == 200, resp.text
        assert "SR-" in resp.json()["message"]

        await db.refresh(product)
        assert product.current_stock == 110, "退货 10 后库存应回补至 110"

        log_rows = (await db.execute(
            select(InventoryLog).where(
                InventoryLog.change_type == "退货",
                InventoryLog.product_id == product.id,
            )
        )).scalars().all()
        assert any(r.change_quantity == 10 for r in log_rows), "应存在 change_type=退货、+10 的库存流水"

        resp = await client.get("/api/v1/stock-returns/list", params={"customer": customer})
        body = resp.json()
        assert body["total"] == 1
        row = body["data"][0]
        return_id = row["id"]
        assert row["product"]["name"] == product.name
        assert row["stockout_no"] == "", "按产品退货无出货关联"
        assert row["status"] == "active"

        # ---- 2) P1-③ 幂等：同 request_id 重复提交 → 400，不二次累计 ----
        resp = await client.post("/api/v1/stock-returns/create", json={
            "product_id": product.id, "quantity": 10, "customer": customer,
            "reason": "质量问题", "request_id": "flow-e2e-req-0001",
        })
        assert resp.status_code == 400
        assert "请勿重复提交" in resp.json()["detail"]
        await db.refresh(product)
        assert product.current_stock == 110, "重复请求不得二次累计库存"

        # ---- 3) 第二笔退货（新弹窗新令牌，无上限概念）----
        resp = await client.post("/api/v1/stock-returns/create", json={
            "product_id": product.id, "quantity": 5, "customer": customer,
            "reason": "错发",
        })
        assert resp.status_code == 200, resp.text
        await db.refresh(product)
        assert product.current_stock == 115

        # ---- 4) 取消第一笔：库存对称扣回、记录保留、重复取消 400 ----
        resp = await client.delete(f"/api/v1/stock-returns/{return_id}")
        assert resp.status_code == 200, resp.text
        assert "取消" in resp.json()["message"]
        await db.refresh(product)
        assert product.current_stock == 105, "取消 10 件应扣回至 105"

        resp = await client.delete(f"/api/v1/stock-returns/{return_id}")
        assert resp.status_code == 400
        assert "已取消" in resp.json()["detail"]

        resp = await client.get("/api/v1/stock-returns/list", params={"customer": customer})
        body = resp.json()
        assert body["total"] == 2, "软取消不清列表"
        statuses = {r["id"]: r["status"] for r in body["data"]}
        assert statuses[return_id] == "cancelled"
        assert sum(1 for s in statuses.values() if s == "active") == 1

        # ---- 5) 取消第二笔：库存回到初始 100 ----
        remaining_id = next(rid for rid, s in statuses.items() if s == "active")
        resp = await client.delete(f"/api/v1/stock-returns/{remaining_id}")
        assert resp.status_code == 200, resp.text
        await db.refresh(product)
        assert product.current_stock == 100, "全部取消后回到初始库存"

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
