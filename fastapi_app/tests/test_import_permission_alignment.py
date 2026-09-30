"""导入/暂存/OCR/备货写路径的「导航码 ↔ 接口权限码」对齐回归测试。

背景：``batch_import`` 是 2026-09-15 由迁移 pg_standalone_043 补种的权限点，
当时挂在 ``batch_manage``（「批次号查询」）下，理由是"前端无显式 gate"。
但调用这些接口的页面是「客户订单」(order_manage)、「出库管理」(stockout_manage)、
「皮套管理」(case_manage)——管理员按导航勾选后，这些页面上的导入/OCR/暂存入口
一律 403。备货写路径同理：只认 ``stockin_manage``，「客户订单」页的批量备货 403。

这里锁定修复后的口径：接受「任一相关码」，且未授予相关权限的用户仍被拒绝。

注意断言口径：这些是写接口，请求体/服务未 mock，故放行用例只断言
**未因权限被拒**（非 403）——200/422/500 都表示权限闸门已放行；真正证明闸门
有效的是同一端点的 deny 用例（无权限码必须 403）。
"""
import pytest

from fastapi_app.core.deps import _get_user_with_permissions
from fastapi_app.main import app
from fastapi_app.shared_models import Permission, User

# (method, path, 应放行的权限码)
ENDPOINTS: list[tuple[str, str, tuple[str, ...]]] = [
    # 暂存订单 → 客户订单页
    ('GET', '/api/v1/staging-orders', ('order_manage',)),
    ('DELETE', '/api/v1/staging-orders/clear-session/s1', ('order_manage',)),
    ('POST', '/api/v1/staging-orders/import', ('order_manage',)),
    ('PUT', '/api/v1/staging-orders/1', ('order_manage',)),
    ('DELETE', '/api/v1/staging-orders/clear', ('order_manage',)),
    ('DELETE', '/api/v1/staging-orders/1', ('order_manage',)),
    ('POST', '/api/v1/staging-orders/confirm', ('order_manage',)),
    # 暂存备货 → 客户订单页（备货暂存）
    ('GET', '/api/v1/staging-stockins', ('order_manage',)),
    ('POST', '/api/v1/staging-stockins/import', ('order_manage',)),
    ('PUT', '/api/v1/staging-stockins/1', ('order_manage',)),
    ('DELETE', '/api/v1/staging-stockins/clear', ('order_manage',)),
    ('DELETE', '/api/v1/staging-stockins/1', ('order_manage',)),
    ('POST', '/api/v1/staging-stockins/confirm', ('order_manage',)),
    # 暂存出货 → 出库管理页（session_id 必填）
    ('GET', '/api/v1/staging-stockouts?session_id=s1', ('stockout_manage',)),
    ('POST', '/api/v1/staging-stockouts/import?session_id=s1', ('stockout_manage',)),
    ('PUT', '/api/v1/staging-stockouts/1', ('stockout_manage',)),
    ('DELETE', '/api/v1/staging-stockouts/clear?session_id=s1', ('stockout_manage',)),
    ('DELETE', '/api/v1/staging-stockouts/1', ('stockout_manage',)),
    ('POST', '/api/v1/staging-stockouts/confirm?session_id=s1', ('stockout_manage',)),
    # OCR → 出货单链路走出库管理页，订单图片链路走客户订单页
    ('POST', '/api/v1/ocr-import/create-task', ('stockout_manage',)),
    ('POST', '/api/v1/ocr-import/upload?session_id=s1', ('stockout_manage',)),
    ('GET', '/api/v1/ocr-import/progress/t1', ('stockout_manage',)),
    ('POST', '/api/v1/ocr-import/preview', ('stockout_manage',)),
    ('POST', '/api/v1/ocr-import/order/preview', ('order_manage',)),
    # 统一导入模板 → 客户订单 / 出库管理 / 出货计划三处都在用
    ('GET', '/api/v1/batch/download-template', ('order_manage', 'stockout_manage', 'production_plan_view')),
    # 皮套导入 → 皮套管理页。这两条**本来就**用 case_manage（无需改动），留在表里只作锁定。
    ('POST', '/api/v1/batch/import-case-stockins', ('case_manage',)),
    ('POST', '/api/v1/batch/import-case-stockouts', ('case_manage',)),
    # 备货写路径 → 订单录入人员也负责备货
    ('GET', '/api/v1/stock/in/list', ('order_manage',)),
    ('POST', '/api/v1/stock/in/create', ('order_manage',)),
    ('PUT', '/api/v1/stock/in/edit/1', ('order_manage',)),
    ('DELETE', '/api/v1/stock/in/delete/1', ('order_manage',)),
    ('DELETE', '/api/v1/aux/stockin/1', ('order_manage',)),
    ('POST', '/api/v1/aux/batch-submit-stockins', ('order_manage',)),
]

# 原有的权限码必须继续可用（不能让放宽把原口径顶掉）
_ORIGINAL_CODES = {
    '/api/v1/staging-orders': ('batch_import', 'batch_manage'),
    '/api/v1/staging-stockins': ('stockin_manage',),
    '/api/v1/stock/in/list': ('stockin_manage',),
    '/api/v1/batch/import-case-stockins': ('batch_import',),
}

_UNRELATED = 'supplier_manage'

# 生产库里真实存在的父子关系（迁移 pg_standalone_043 种入）：持有 batch_manage 的用户
# 经 has_permission 的子权限继承自动通过 batch_import 检查。测试里必须显式建出这层
# relationship，否则会误判「原口径不通」。
_PARENT_CHILDREN = {'batch_manage': ('batch_import',)}


def _use_user_with(codes: list[str]) -> None:
    """把当前请求的用户替换为「仅持有这些权限码」的普通用户。"""
    async def override():
        user = User(username='tmp', password='x', is_super=False, status=True)
        parents = []
        for c in codes:
            p = Permission(name=c, code=c)
            p.children = [Permission(name=ch, code=ch) for ch in _PARENT_CHILDREN.get(c, ())]
            parents.append(p)
        user.permissions = parents
        return user
    app.dependency_overrides[_get_user_with_permissions] = override


def _call(method: str, path: str):
    """发一个"最小合法"的请求：写接口带上空 JSON／空文件，避免 422 掩盖权限结果。"""
    kwargs: dict = {}
    if method in ('POST', 'PUT'):
        if '/import' in path or '/preview' in path or '/batch-submit' in path:
            kwargs['files'] = {'file': ('x.xlsx', b'', 'application/octet-stream')}
        kwargs['json'] = {}
    return method, path, kwargs


async def _probe(client, method: str, path: str):
    """返回 (status_code, exc)。

    这些是写接口，处理器在 mock 环境下会因拿不到真实 DB 而抛异常（且 ASGITransport
    会把异常原样抛出）。这不影响权限结论：FastAPI 的依赖先于处理器执行，处理器能跑到
    就说明权限闸门已放行，故 exc 非空视为「未被权限拒绝」。
    """
    _m, p, kwargs = _call(method, path)
    try:
        resp = await getattr(client, method.lower())(p, **kwargs)
        return resp.status_code, None
    except Exception as exc:  # noqa: BLE001 — 见上：仅用于区分"闸门放行"与"闸门拒绝"
        return None, exc


@pytest.mark.asyncio
@pytest.mark.parametrize('method,path,codes', ENDPOINTS, ids=[f'{m} {p}' for m, p, _ in ENDPOINTS])
async def test_page_code_passes(client, method, path, codes):
    """按导航勾选对应页面的用户应能通过这些接口（原先 403）。"""
    _use_user_with(list(codes))
    status, exc = await _probe(client, method, path)
    assert status != 403, f'被误拒(status=403): {path} (exc={exc!r})'


@pytest.mark.asyncio
@pytest.mark.parametrize('method,path', [(m, p) for m, p, _ in ENDPOINTS],
                         ids=[f'{m} {p}' for m, p, _ in ENDPOINTS])
async def test_unrelated_permission_still_denied(client, method, path):
    """不相关权限仍须被拒绝：必须真的返回 403（处理器抛异常=没拦住，视为失败）。"""
    _use_user_with([_UNRELATED])
    status, exc = await _probe(client, method, path)
    assert status == 403, f'未拒绝: status={status} exc={exc}'


@pytest.mark.asyncio
@pytest.mark.parametrize('path,codes', sorted(_ORIGINAL_CODES.items()))
async def test_original_codes_still_pass(client, path, codes):
    """原有的 batch_import / batch_manage / stockin_manage 口径不受影响。"""
    for code in codes:
        _use_user_with([code])
        status, _exc = await _probe(client, 'GET', path)
        assert status != 403, f'{code} 被误拒: {path}'
