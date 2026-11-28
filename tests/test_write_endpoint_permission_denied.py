"""非管理员的写端点必须在真实 ASGI 请求下被 403 拒绝（审计 P2 3.1）。

现状（2026-10-17 审计）：203 个根测试文件里只有 5 处断言了**业务性** 403，且集中在
stock_return / outsource 等少数端点。根套件的 `auth_headers` 夹具只用 admin
（`is_super=True`）→ 绝大多数用例跑在超管身份下，**权限依赖是否正确根本不参与判定**：
某端点漏写 `require_permission`、或把 `_manage` 写成 `_view`，根套件不会变红，而线上
表现是「普通员工能删单 / 能改采购单」。

本文件补的是**行为**侧（结构侧见
`fastapi_app/tests/test_write_routes_have_permission_dep.py`：它反射整棵路由树，保证
「每个写路由都有权限码依赖」，新增写端点漏挂权限会当场红）。

这里手挑几条真实写端点（URL 取自 `app.openapi()['paths']`，改写时以 openapi 为准）：
普通用户（零权限码）请求必须 403 —— 若某端点被降级成「只要登录就行」，本用例立刻红。
"""
from __future__ import annotations

import pytest

#: (method, url, 期望被拒的权限码之一)。权限码只作失败信息用，不参与判定。
#: URL 里 {id} 用 1 代替：即使该行不存在，权限依赖也会在 403 处先拦住（不落到 404 逻辑）。
WRITE_ENDPOINTS = [
    ('POST', '/api/v1/products/create', 'product_manage'),
    ('PUT', '/api/v1/products/edit/1', 'product_manage'),
    ('DELETE', '/api/v1/products/delete/1', 'product_manage'),
    ('POST', '/api/v1/orders/create', 'order_manage'),
    ('DELETE', '/api/v1/orders/delete/1', 'order_manage'),
    ('POST', '/api/v1/purchase-center/orders', 'purchase_center_manage'),
    ('DELETE', '/api/v1/purchase-center/orders/1', 'purchase_center_manage'),
    ('POST', '/api/v1/batch/import-orders', 'batch_import'),
    # 实测挂的是 batch_import + order_manage（评审 2026-11-19：原来声明 staging_manage 是错的，
    # 而声明一旦参与判定，写错就会当场红 —— 这正是「声明要可判定」的价值）。
    ('POST', '/api/v1/staging-orders/confirm', 'order_manage'),
]


@pytest.mark.parametrize(
    'method,url,code',
    WRITE_ENDPOINTS,
    ids=[f'{m}-{u.rsplit("/", 1)[-1] or u}' for m, u, _c in WRITE_ENDPOINTS],
)
@pytest.mark.asyncio
async def test_write_endpoint_denies_non_admin(async_client, non_admin_headers, method, url, code) -> None:
    resp = await async_client.request(method, url, headers=non_admin_headers, json={})

    assert resp.status_code == 403, (
        f'{method} {url} 对无权限用户返回 {resp.status_code}（应为 403）。'
        f' 期望缺少权限码 {code!r} —— 端点可能漏挂 require_permission，'
        f'或把 _manage 写成了 _view。响应: {resp.text[:300]}'
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'method,url,code',
    WRITE_ENDPOINTS,
    ids=[f'{m}-{u.rsplit("/", 1)[-1] or u}' for m, u, _c in WRITE_ENDPOINTS],
)
@pytest.mark.asyncio
async def test_same_request_not_403_for_admin(async_client, auth_headers, method, url, code) -> None:
    """阳性对照：同一请求以**超管**身份发出时不得是 403。

    没有这一条，「非超管 403」可能来自完全无关的原因（CSRF 拦截、路由不存在、请求体
    非法……），整组用例就退化成「随便什么都 403」的假绿 —— 正是审计 3.1 要消灭的形状。
    超管会越过权限层，随后通常因 `json={}` 不合法返回 422/400；唯一不允许的是 403。
    """
    resp = await async_client.request(method, url, headers=auth_headers, json={})

    resp = await async_client.request(method, url, headers=auth_headers, json={})

    # 只排除 403 不够：登录坏掉时这里收到的是 401，`401 != 403` 会让阳性对照静默失效，
    # 「超管能越过权限层」这个前提就从未被验证过。
    assert resp.status_code not in (401, 403), (
        f'{method} {url} 对超管返回 {resp.status_code}（不应是 401 也不应是 403）——'
        f' 401 说明超管身份没建立起来（夹具/登录坏了），403 说明那个 403 不是权限层给的。'
        f' 响应: {resp.text[:300]}'
    )


def test_declared_codes_are_actually_wired() -> None:
    """声明的权限码必须真的挂在那条路由上 —— 否则它只是失败信息里的死数据。

    推送前评审（2026-11-19）：`WRITE_ENDPOINTS` 第三列此前只出现在失败文案里，不参与判定，
    于是「把 `_manage` 写成 `_view`」这个审计要点根本没有判定力（零权限用户对两者都是 403）。
    这里把声明与**路由树上的实际权限码**对上：改成 `_view` 后本表与路由树不一致，当场红。

    比「造一个只带 `*_view` 的用户」更便宜，也不需要往测试库里种权限数据。
    """
    from fastapi_app.main import app
    from fastapi_app.tests._route_introspect import codes_for_request

    problems: list[str] = []
    for method, url, code in WRITE_ENDPOINTS:
        codes = codes_for_request(app, method, url)
        if codes is None:
            problems.append(f'{method} {url} 在路由树里找不到（URL 可能已改，请以 openapi 为准）')
        elif code not in codes:
            problems.append(f'{method} {url} 声明 {code!r}，实际挂的是 {sorted(codes)}')
    assert problems == [], '声明与接线漂移（权限码被降级/改名，或 URL 已改）：' + '；'.join(problems)
