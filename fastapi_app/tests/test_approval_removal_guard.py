"""审批系统下线守卫（2026-11-28）。

审批控制台、审批服务、订单审批分支与订单锁列已整体移除。本文件锁死
「不复活」不变量：任何把审批路由、模型导出、schema 字段或订单锁列加回
来的改动都必须在这里显式失败。
"""
import pytest

from fastapi_app.core import state_machine
from fastapi_app.main import app
from fastapi_app.schemas.dashboard import DashboardStats
from fastapi_app.shared_models import Order


def test_openapi_has_no_approval_paths():
    paths = app.openapi()['paths']
    forbidden = [p for p in paths if 'approv' in p.lower()]
    assert forbidden == [], f'审批相关路由复活: {forbidden}'


@pytest.mark.asyncio
async def test_approvals_endpoint_returns_404(client):
    """路由未挂载：Starlette 在依赖解析前即返回 404，无需认证。

    /orders/my-approvals 会先撞上 GET /orders/{order_id} 的 int 校验 → 422，
    同样证明该端点不存在（非 200/401/403 即可）。
    """
    resp = await client.get('/api/v1/approvals/list')
    assert resp.status_code == 404
    resp = await client.post('/api/v1/approvals/approve/1')
    assert resp.status_code == 404
    resp = await client.get('/api/v1/orders/my-approvals')
    assert resp.status_code in (404, 422)
    resp = await client.post('/api/v1/orders/cancel-approval/1')
    assert resp.status_code in (404, 422)


def test_shared_models_no_approval_exports():
    import fastapi_app.shared_models as sm

    assert 'ApprovalRequest' not in sm.__all__
    assert 'ApprovalLog' not in sm.__all__
    assert not hasattr(sm, 'ApprovalRequest')
    assert not hasattr(sm, 'ApprovalLog')


def test_order_model_has_no_lock_columns():
    assert 'is_locked' not in Order.__table__.columns
    assert 'locked_by_id' not in Order.__table__.columns
    assert 'lock_time' not in Order.__table__.columns
    assert not hasattr(Order, 'locked_by')


def test_dashboard_stats_has_no_pending_approvals():
    assert 'pending_approvals' not in DashboardStats.model_fields


def test_state_machine_has_no_approval_domain():
    assert not hasattr(state_machine, 'ApprovalState')
    assert not hasattr(state_machine, 'ApprovalAction')
    assert not hasattr(state_machine, 'ApprovalOperation')
    # 模块级审批转移函数也已移除（staging 走 StateMachine 实例方法）
    assert not hasattr(state_machine, 'can_transition')
    assert not hasattr(state_machine, 'transition')
