"""API v2 版本化端点测试

P2-15: 验证 /api/v2 路由的版本响应头与已迁移业务端点 (仪表盘统计、最近活动、待办事项、系统状态、移动端看板、导航菜单、客户出库/订单详情)。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_app.api.v2.endpoints import dashboard as dashboard_endpoint
from fastapi_app.api.v2.router import router as v2_router
from fastapi_app.core.database import get_async_read_db
from fastapi_app.core.deps import get_current_user_id
from fastapi_app.services.dashboard_service import (
    Activity,
    CustomerOutDetailResponse,
    MobileDashboardResponse,
    NavSection,
    TodoItem,
)


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(v2_router, prefix="/api")

    async def _fake_user():
        return 1

    async def _fake_db():
        return None

    app.dependency_overrides[get_current_user_id] = _fake_user
    app.dependency_overrides[get_async_read_db] = _fake_db

    async def _fake_fetch(_db):
        return {
            "order_today": 5,
            "stockin_today": 3,
            "stockout_today": 2,
            "pending_approvals": 1,
        }

    async def _fake_activities(_db):
        return [
            Activity(type="order", time="2026-06-22", status="pending", title="订单 PO-1", desc="订单 PO-1"),
        ]

    async def _fake_todos(_db):
        return [
            TodoItem(id=1, type="order", description="订单 PO-1 待处理", urgency="urgent", related_module="order_query", related_business_id=1),
        ]

    def _fake_system_status():
        from fastapi_app.services.dashboard_service import SystemStatus, SystemStatusResponse
        return SystemStatusResponse(
            success=True,
            data=SystemStatus(is_running=True, last_sync_time="2026-06-22", data_status="up_to_date"),
        )

    def _fake_mobile_dashboard(_query_date, _db):
        return MobileDashboardResponse(
            success=True,
            data={
                "stock": {"today_quantity": 1, "today_amount": 1.0, "month_quantity": 2, "month_amount": 2.0, "total_quantity": 3, "total_amount": 3.0},
                "production": {"total_value": 0.0, "departments": []},
                "shipping": {"daily_qty": 0, "total_amount": 0.0},
                "orders": {"daily_qty": 0, "daily_amount": 0.0, "total_amount": 0.0, "total_qty": 0, "total_inventory": 0, "total_inventory_amount": 0.0},
                "warehouse": {"in_qty": 0, "in_amount": 0.0, "out_qty": 0, "out_amount": 0.0},
            },
        )

    async def _fake_nav_sections():
        return {"main": NavSection(name="主菜单", items=[])}

    async def _fake_customer_out_details(_period, _query_date, _db):
        return CustomerOutDetailResponse(success=True, data=[{"customer_name": "客户A", "total_quantity": 10, "total_amount": 100.0}])

    async def _fake_customer_order_details(_period, _date_param, _db):
        return CustomerOutDetailResponse(success=True, data=[{"customer_name": "客户B", "total_quantity": 5, "total_amount": 50.0}])

    monkeypatch.setattr(dashboard_endpoint, "fetch_dashboard_stats", _fake_fetch)
    monkeypatch.setattr(dashboard_endpoint, "fetch_dashboard_activities", _fake_activities)
    monkeypatch.setattr(dashboard_endpoint, "fetch_dashboard_todos", _fake_todos)
    monkeypatch.setattr(dashboard_endpoint, "fetch_system_status", _fake_system_status)
    monkeypatch.setattr(dashboard_endpoint, "fetch_mobile_dashboard", _fake_mobile_dashboard)
    monkeypatch.setattr(dashboard_endpoint, "fetch_nav_sections", _fake_nav_sections)
    monkeypatch.setattr(dashboard_endpoint, "fetch_customer_out_details", _fake_customer_out_details)
    monkeypatch.setattr(dashboard_endpoint, "fetch_customer_order_details", _fake_customer_order_details)
    return TestClient(app)


def test_health_v2_returns_version_headers(client):
    resp = client.get("/api/v2/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": "2.0.0"}
    assert resp.headers["API-Version"] == "2.0.0"
    assert resp.headers["Deprecation"] == "false"
    assert "Sunset" in resp.headers


def test_dashboard_stats_v2_returns_data_and_headers(client):
    resp = client.get("/api/v2/dashboard/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["order_today"] == 5
    assert data["data"]["stockin_today"] == 3
    assert data["data"]["stockout_today"] == 2
    assert data["data"]["pending_approvals"] == 1
    assert resp.headers["API-Version"] == "2.0.0"
    assert resp.headers["Deprecation"] == "false"
    assert "Sunset" in resp.headers


def test_dashboard_activities_v2_returns_data_and_headers(client):
    resp = client.get("/api/v2/dashboard/activities")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["type"] == "order"
    assert data[0]["title"] == "订单 PO-1"
    assert resp.headers["API-Version"] == "2.0.0"
    assert resp.headers["Deprecation"] == "false"
    assert "Sunset" in resp.headers


def test_dashboard_todos_v2_returns_data_and_headers(client):
    resp = client.get("/api/v2/dashboard/todos")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]) == 1
    assert data["data"][0]["type"] == "order"
    assert data["data"][0]["urgency"] == "urgent"
    assert resp.headers["API-Version"] == "2.0.0"
    assert resp.headers["Deprecation"] == "false"
    assert "Sunset" in resp.headers


def test_system_status_v2_returns_data_and_headers(client):
    resp = client.get("/api/v2/dashboard/system-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["is_running"] is True
    assert data["data"]["last_sync_time"] == "2026-06-22"
    assert data["data"]["data_status"] == "up_to_date"
    assert resp.headers["API-Version"] == "2.0.0"
    assert resp.headers["Deprecation"] == "false"
    assert "Sunset" in resp.headers


def test_mobile_dashboard_v2_returns_data_and_headers(client):
    resp = client.get("/api/v2/dashboard/mobile")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["stock"]["today_quantity"] == 1
    assert data["data"]["production"]["total_value"] == 0.0
    assert resp.headers["API-Version"] == "2.0.0"
    assert resp.headers["Deprecation"] == "false"
    assert "Sunset" in resp.headers


def test_nav_sections_v2_returns_data_and_headers(client):
    resp = client.get("/api/v2/dashboard/nav-sections")
    assert resp.status_code == 200
    data = resp.json()
    assert "main" in data
    assert data["main"]["name"] == "主菜单"
    assert resp.headers["API-Version"] == "2.0.0"
    assert resp.headers["Deprecation"] == "false"
    assert "Sunset" in resp.headers


def test_customer_out_details_v2_returns_data_and_headers(client):
    resp = client.get("/api/v2/dashboard/customer-out-details")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]) == 1
    assert data["data"][0]["customer_name"] == "客户A"
    assert resp.headers["API-Version"] == "2.0.0"
    assert resp.headers["Deprecation"] == "false"
    assert "Sunset" in resp.headers


def test_customer_order_details_v2_returns_data_and_headers(client):
    resp = client.get("/api/v2/dashboard/customer-order-details")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]) == 1
    assert data["data"][0]["customer_name"] == "客户B"
    assert resp.headers["API-Version"] == "2.0.0"
    assert resp.headers["Deprecation"] == "false"
    assert "Sunset" in resp.headers
