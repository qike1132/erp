"""stock / customer / aux 读接口的「导航码 ↔ 接口权限码」对齐回归测试。

背景：导航/权限树里「订单列表」的权限码是 ``stock_view``、「客户管理」是
``customer_manage``，而接口原先一律只认 ``stockin_manage`` / ``product_view``，
导致管理员按导航勾选权限后接口仍返回 403（``has_permission`` 只有
``xxx_manage → xxx_view`` 单向继承，不存在 ``stock_view → stockin_manage``）。

这里锁定修复后的口径：
- ``/stock/inventory``、``/stock/export-inventory`` 接受「备货管理(全部)」或「订单列表」；
- ``/aux/product-search`` 接受产品只读码或调用它的三个页面码；
- ``/customers/active-names`` 是全局客户名字典，登录即可读（不再要求客户管理）；
- 未授予相关权限的用户仍被拒绝，避免放行口径过宽。
"""
from unittest.mock import AsyncMock, patch

import pytest

from fastapi_app.core.deps import _get_user_with_permissions
from fastapi_app.main import app
from fastapi_app.shared_models import Permission, User

_INVENTORY = {
    'inventory_data': [],
    'total_order_qty': 0,
    'total_stockin_qty': 0,
    'total_stock': 0,
    'total_available_stock': 0,
    'all_customers': [],
    'total_items': 0,
    'page': 1,
    'per_page': 15,
}

_INVENTORY_SVC = 'fastapi_app.api.v1.endpoints.stock.stock_service.get_inventory_paginated'
_EXCEL_BUILDER = 'fastapi_app.api.v1.endpoints.stock._build_inventory_excel'
_PRODUCT_SEARCH = (
    'fastapi_app.services.product_search_service'
    '.product_search_service.search_async_with_cache'
)
_ACTIVE_NAMES = 'fastapi_app.api.v1.endpoints.customer.customer_service.get_active_customer_names'


def _use_user_with(codes: list[str]) -> None:
    """把当前请求的用户替换为「仅持有这些权限码」的普通用户。"""
    async def override():
        user = User(username='tmp', password='x', is_super=False, status=True)
        user.permissions = [Permission(name=c, code=c) for c in codes]
        return user
    app.dependency_overrides[_get_user_with_permissions] = override


# ==================== /stock/inventory ====================

@pytest.mark.asyncio
async def test_stock_view_can_read_inventory(client):
    """勾选「订单列表」的用户应能读取库存（原先 403）。"""
    _use_user_with(['stock_view'])
    with patch(_INVENTORY_SVC, AsyncMock(return_value=_INVENTORY)):
        resp = await client.get('/api/v1/stock/inventory?page=1&per_page=15')
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_stockin_manage_still_reads_inventory(client):
    """原有的「备货管理(全部)」权限用户不受影响。"""
    _use_user_with(['stockin_manage'])
    with patch(_INVENTORY_SVC, AsyncMock(return_value=_INVENTORY)):
        resp = await client.get('/api/v1/stock/inventory?page=1&per_page=15')
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_unrelated_permission_denied_inventory(client):
    """不相关权限（如供应商管理）仍须被拒绝，避免放行口径过宽。"""
    _use_user_with(['supplier_manage'])
    with patch(_INVENTORY_SVC, AsyncMock(return_value=_INVENTORY)):
        resp = await client.get('/api/v1/stock/inventory?page=1&per_page=15')
    assert resp.status_code == 403


# ==================== /stock/export-inventory ====================

@pytest.mark.asyncio
async def test_stock_view_can_export_inventory(client):
    """「订单列表」页的导出按钮走同一份库存数据，也应放行（原先 403）。"""
    _use_user_with(['stock_view'])
    with patch(_INVENTORY_SVC, AsyncMock(return_value=_INVENTORY)), \
            patch(_EXCEL_BUILDER, return_value=(b'xlsx', 'inventory.xlsx')):
        resp = await client.get('/api/v1/stock/export-inventory')
    assert resp.status_code == 200, resp.text


# ==================== /aux/product-search ====================

@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['order_manage', 'stockout_manage', 'production_plan_view'])
async def test_page_codes_can_search_products(client, code):
    """调用产品搜索的三个页面（客户订单/出库管理/出货计划）都应放行（原先 403）。"""
    _use_user_with([code])
    with patch(_PRODUCT_SEARCH, AsyncMock(return_value=[])):
        resp = await client.get('/api/v1/aux/product-search?q=test')
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_product_manage_still_searches_products(client):
    """原有的「产品清单」权限用户不受影响。"""
    _use_user_with(['product_manage'])
    with patch(_PRODUCT_SEARCH, AsyncMock(return_value=[])):
        resp = await client.get('/api/v1/aux/product-search?q=test')
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_unrelated_permission_denied_product_search(client):
    """不相关权限（如供应商管理）仍须被拒绝。"""
    _use_user_with(['supplier_manage'])
    with patch(_PRODUCT_SEARCH, AsyncMock(return_value=[])):
        resp = await client.get('/api/v1/aux/product-search?q=test')
    assert resp.status_code == 403


# ==================== /customers/active-names ====================

@pytest.mark.asyncio
async def test_active_names_readable_without_any_permission(client):
    """全局客户下拉字典：登录即可读，零权限用户不应 403（10+ 页面共用）。"""
    _use_user_with([])
    with patch(_ACTIVE_NAMES, AsyncMock(return_value=[])):
        resp = await client.get('/api/v1/customers/active-names')
    assert resp.status_code == 200, resp.text
