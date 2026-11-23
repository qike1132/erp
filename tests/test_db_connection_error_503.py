"""M-16 族回归：DB 连接类异常不得吞成 success=True 空数据（2026-11-21 全量审计）。

修复前：dashboard 的 activities/todos/mobile/customer 等把 OperationalError/
DisconnectionError 吞成空列表/0 值返回 200——DB 抖动被渲染成「没数据」且无告警；
未吞的端点则裸 500。修复后：service 层停吞连接类异常，main.py 全局处理器统一
转 503（与 /stats 既有口径一致）。

用 monkeypatch 让 service 内部抛 OperationalError，断言端点返回 503：
- activities / customer-out-details：修复前裸 500（无处理器）；
- mobile：修复前 _load_production_data 被卡片级 except 吞掉 → 200 假成功；
- todos：修复前被整体 except 吞掉 → 200 假成功。
"""
import pytest
from sqlalchemy.exc import OperationalError

pytestmark = pytest.mark.asyncio


def _conn_error() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception("connection reset by peer"))


async def test_activities_connection_error_is_503(async_client, auth_headers, monkeypatch):
    import fastapi_app.api.v1.endpoints.dashboard as dash_ep

    async def _boom(db, scope):
        raise _conn_error()

    monkeypatch.setattr(dash_ep, "fetch_dashboard_activities", _boom)
    resp = await async_client.get("/api/v1/dashboard/activities", headers=auth_headers)
    assert resp.status_code == 503, (resp.status_code, resp.text[:200])
    assert resp.json()["success"] is False


async def test_todos_connection_error_is_503(async_client, auth_headers, monkeypatch):
    import fastapi_app.api.v1.endpoints.dashboard as dash_ep

    async def _boom(db, factory_scope):
        raise _conn_error()

    monkeypatch.setattr(dash_ep, "fetch_dashboard_todos", _boom)
    resp = await async_client.get("/api/v1/dashboard/todos", headers=auth_headers)
    assert resp.status_code == 503, (resp.status_code, resp.text[:200])


async def test_customer_out_details_connection_error_is_503(async_client, auth_headers, monkeypatch):
    import fastapi_app.api.v1.endpoints.dashboard as dash_ep

    async def _boom(period, query_date, db, factory=""):
        raise _conn_error()

    monkeypatch.setattr(dash_ep, "fetch_customer_out_details", _boom)
    resp = await async_client.get("/api/v1/dashboard/customer-out-details", headers=auth_headers)
    assert resp.status_code == 503, (resp.status_code, resp.text[:200])


async def test_mobile_card_connection_error_is_503_not_partial_200(async_client, auth_headers, monkeypatch):
    """卡片级 defensive 吞异常不得掩盖 DB 故障：单卡片连接异常 → 整体 503。"""
    import fastapi_app.services.dashboard.mobile as mobile_svc

    async def _boom(*args, **kwargs):
        raise _conn_error()

    monkeypatch.setattr(mobile_svc, "_load_production_data", _boom)
    resp = await async_client.get("/api/v1/dashboard/mobile", headers=auth_headers)
    assert resp.status_code == 503, (resp.status_code, resp.text[:200])


async def test_generic_card_failure_still_degrades_to_partial_200(async_client, auth_headers):
    """防修复误伤：非连接类的单卡片失败仍保持既有「部分降级 200」语义。

    注意：不能 monkeypatch 整个 _load_* 函数——防御 try 在函数体内，整体替换
    会让 RuntimeError 从调用点逃逸成 TaskGroup 500。此处毒化 DB 会话，让真实
    函数体内的 execute 抛 RuntimeError，验证体内 except 仍兜底。
    """
    from fastapi_app.core.database import get_async_read_db
    from fastapi_app.main import app

    class _PoisonedDB:
        async def execute(self, *args, **kwargs):
            raise RuntimeError("某个统计项的计算 bug，非连接问题")

    async def _fake_db():
        yield _PoisonedDB()

    app.dependency_overrides[get_async_read_db] = _fake_db
    try:
        resp = await async_client.get("/api/v1/dashboard/mobile", headers=auth_headers)
    finally:
        app.dependency_overrides.pop(get_async_read_db, None)
    assert resp.status_code == 200, (resp.status_code, resp.text[:200])
