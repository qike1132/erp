"""本地 mock 数据测试 /api/v2/dashboard 已迁移端点

用法（在仓库根目录执行）：
    python scripts/mock_dashboard_v2_test.py

说明：
- 仅在本地开发数据库插入少量测试数据，测试结束后自动清理。
- 依赖 .env 中的数据库配置，若 SECRET_KEY 加载失败请先显式设置。
- 需要本地能正常导入 fastapi_app.main。
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import async_engine, get_async_read_db
from fastapi_app.core.deps import get_current_user_id
from fastapi_app.main import app
from fastapi_app.shared_models import Order, Product, StockIn, StockOut

TS = datetime.now(UTC).strftime("%Y%m%d%H%M%S")


async def _seed(session: AsyncSession) -> dict[str, int]:
    """插入最小 mock 数据并返回主键，供测试后清理。"""
    now = datetime.now(UTC)

    product = Product(
        name=f"测试产品-{TS}",
        price=10.0,
        current_stock=100,
    )
    session.add(product)
    await session.flush()

    order = Order(
        order_no=f"MOCK-{TS}",
        customer="测试客户A",
        product_id=product.id,
        quantity=5,
        order_date=now,
        status="pending",
    )
    session.add(order)
    await session.flush()

    stockin = StockIn(
        stockin_no=f"SI-{TS}",
        customer="测试客户A",
        product_id=product.id,
        quantity=3,
        stockin_date=now,
    )
    session.add(stockin)
    await session.flush()

    stockout = StockOut(
        stockout_no=f"SO-{TS}",
        customer="测试客户A",
        product_id=product.id,
        quantity=2,
        stockout_date=now,
        order_id=order.id,
    )
    session.add(stockout)
    await session.commit()

    return {
        "product_id": product.id,
        "order_id": order.id,
        "stockin_id": stockin.id,
        "stockout_id": stockout.id,
    }


async def _cleanup(session: AsyncSession, ids: dict[str, int]) -> None:
    """按依赖顺序删除 mock 数据。"""
    await session.execute(delete(StockOut).where(StockOut.id == ids["stockout_id"]))
    await session.execute(delete(StockIn).where(StockIn.id == ids["stockin_id"]))
    await session.execute(delete(Order).where(Order.id == ids["order_id"]))
    await session.execute(delete(Product).where(Product.id == ids["product_id"]))
    await session.commit()


async def main() -> None:
    session = AsyncSession(bind=async_engine, expire_on_commit=False)
    ids = await _seed(session)

    # 覆盖依赖：固定当前用户、固定只读会话
    app.dependency_overrides[get_current_user_id] = lambda: 1
    app.dependency_overrides[get_async_read_db] = lambda: session

    endpoints = [
        "/api/v2/dashboard/stats",
        "/api/v2/dashboard/activities",
        "/api/v2/dashboard/todos",
        "/api/v2/dashboard/system-status",
        "/api/v2/dashboard/mobile",
        "/api/v2/dashboard/nav-sections",
        "/api/v2/dashboard/customer-out-details",
        "/api/v2/dashboard/customer-order-details",
    ]

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for ep in endpoints:
                print(f"\n>>> GET {ep}")
                try:
                    resp = await client.get(ep)
                    print(f"status: {resp.status_code}")
                    print(resp.json())
                    assert resp.status_code == 200, f"{ep} 返回 {resp.status_code}"
                    assert resp.headers.get("API-Version") == "2.0.0", "缺少 API-Version 头"
                except Exception as exc:
                    print(f"请求失败: {exc}")
        print("\n所有 /api/v2/dashboard 端点 mock 测试通过")
    finally:
        await _cleanup(session, ids)
        await session.close()
        app.dependency_overrides.clear()


if __name__ == "__main__":
    asyncio.run(main())
