"""采购中心/来料登记接口的权限对齐回归测试。

背景：导航/权限树里「采购中心」的权限码是 purchase_center_manage、「物料计算器」是
material_calculator、「来料登记」是 material_registration，而接口原先一律只认
product_manage，导致管理员按导航勾选权限后接口仍返回 403。

这里锁定修复后的口径：这些接口接受「任一相关权限」，且未授予相关权限的用户仍被拒绝。
"""
from unittest.mock import AsyncMock, patch

import pytest

from fastapi_app.core.deps import _get_user_with_permissions
from fastapi_app.main import app
from fastapi_app.shared_models import Permission, User

_UNPROCESSED = {'orders': [], 'total': 0, 'pages': 1, 'current_page': 1, 'latest_sync_time': None}
_PRODUCTS = {'products': [], 'total': 0, 'pages': 0, 'current_page': 1}
_REGISTRATIONS = {'success': True, 'registrations': [], 'total': 0, 'pages': 1, 'current_page': 1}


def _use_user_with(codes: list[str]) -> None:
    """把当前请求的用户替换为「仅持有这些权限码」的普通用户。"""
    async def override():
        user = User(username='tmp', password='x', is_super=False, status=True)
        user.permissions = [Permission(name=c, code=c) for c in codes]
        return user
    app.dependency_overrides[_get_user_with_permissions] = override


@pytest.mark.asyncio
async def test_purchase_center_manage_can_read_unprocessed_orders(client):
    """勾选「采购中心」的用户应能读取待审核订单（原先 403）。"""
    _use_user_with(['purchase_center_manage'])
    with patch('fastapi_app.services.purchase_center_service.get_unprocessed_orders', AsyncMock(return_value=_UNPROCESSED)):
        resp = await client.get('/api/v1/purchase-center/unprocessed-orders')
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_material_calculator_can_read_products(client):
    """勾选「物料计算器」的用户应能读取产品列表（原先 403）。"""
    _use_user_with(['material_calculator'])
    with patch('fastapi_app.services.purchase_center_service.get_products', AsyncMock(return_value=_PRODUCTS)):
        resp = await client.get('/api/v1/purchase-center/products?simple=true')
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_material_registration_can_list_registrations(client):
    """勾选「来料登记」的用户应能读取来料登记列表（原先 403）。"""
    _use_user_with(['material_registration'])
    with patch('fastapi_app.api.v1.endpoints.material_registration.mr_service.get_registrations', AsyncMock(return_value=_REGISTRATIONS)):
        resp = await client.get('/api/v1/material-registrations/registrations')
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_product_manage_still_passes_guard(client):
    """原有的「产品清单」权限用户不受影响。"""
    _use_user_with(['product_manage'])
    with patch('fastapi_app.services.purchase_center_service.get_unprocessed_orders', AsyncMock(return_value=_UNPROCESSED)):
        resp = await client.get('/api/v1/purchase-center/unprocessed-orders')
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_unrelated_permission_still_denied(client):
    """不相关权限（如供应商管理）仍须被拒绝，避免放行口径过宽。"""
    _use_user_with(['supplier_manage'])
    resp = await client.get('/api/v1/purchase-center/unprocessed-orders')
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_material_calculator_cannot_read_purchase_center_orders(client):
    """仅持「物料计算器」码的用户不能越权读取采购中心待审核订单。"""
    _use_user_with(['material_calculator'])
    with patch('fastapi_app.services.purchase_center_service.get_unprocessed_orders', AsyncMock(return_value=_UNPROCESSED)):
        resp = await client.get('/api/v1/purchase-center/unprocessed-orders')
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_purchase_center_manage_cannot_read_material_registrations(client):
    """仅持「采购中心」码的用户不能越权读取来料登记列表。"""
    _use_user_with(['purchase_center_manage'])
    with patch('fastapi_app.api.v1.endpoints.material_registration.mr_service.get_registrations', AsyncMock(return_value=_REGISTRATIONS)):
        resp = await client.get('/api/v1/material-registrations/registrations')
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_material_calculator_cannot_save_bom(client):
    """写路径不放宽：仅持「物料计算器」码的用户不能改写产品 BOM。

    「物料计算器」是只读计算页的导航权限，读接口放行不等于写接口放行。
    service 被 patch，确保权限未收紧时不会真的写到数据库。
    """
    _use_user_with(['material_calculator'])
    with patch('fastapi_app.services.purchase_center_service.save_product_bom', AsyncMock(return_value='ok')):
        resp = await client.post('/api/v1/purchase-center/product/1/bom', json={})
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_material_calculator_cannot_copy_bom(client):
    """写路径不放宽：仅持「物料计算器」码的用户不能把 BOM 复制覆盖到目标产品。"""
    _use_user_with(['material_calculator'])
    with patch('fastapi_app.services.purchase_center_service.copy_bom_to_product', AsyncMock(return_value={'message': 'ok'})):
        resp = await client.post('/api/v1/purchase-center/products/1/copy-bom', json={'source_product_id': 2})
    assert resp.status_code == 403, resp.text
