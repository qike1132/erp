"""限流键必须绑定用户身份，而不是仅 IP（P0-6(d)）。

背景：slowapi 在**装饰时**就把 key_func 绑进 Limit 对象
（.venv/Lib/site-packages/slowapi/extension.py:663 keyfunc = key_func or self._key_func），
所以 main.py 里事后 limiter.key_func = _rate_limit_key 对已装饰路由**静默无效**
（Lead 探针：装饰后改 lim.key_func 仍输出 decorated route keys used -> ['BEFORE(ip)']）。

本文件锁定修复：5 个装饰端点显式 key_func=rate_limit_key，且限流桶随用户身份
（而非仅 IP）变化 —— 同一 IP 上的不同用户不共享配额。
"""
import pytest
from slowapi.util import get_remote_address
from starlette.requests import Request

from fastapi_app.core import deps as deps_mod
from fastapi_app.core.limiter import limiter, rate_limit_key

# 5 个显式装饰端点（slowapi 用 <module>.<func> 作键）
_DECORATED_ROUTES = {
    'fastapi_app.api.v1.endpoints.auth.api_login': '100 per 1 minute',
    'fastapi_app.api.v1.endpoints.daily_production.export_records': '100 per 1 minute',
    'fastapi_app.api.v1.endpoints.monitoring.receive_vitals': '30 per 1 minute',
    'fastapi_app.api.v1.endpoints.report.export_report': '100 per 1 minute',
    'fastapi_app.api.v1.endpoints.stock.export_inventory': '100 per 1 minute',
}

# 与端点限额一致：30/minute -> 第 31 次必须被拦
_LIMIT = 30

VITALS_PAYLOAD = {
    'vitals': [
        {
            'name': 'LCP',
            'value': 1200.0,
            'rating': 'good',
            'delta': 1200.0,
            'navigationType': 'navigate',
            'timestamp': 1_700_000_000_000,
        },
    ],
}


def _request(ip='10.9.9.9'):
    return Request({
        'type': 'http',
        'http_version': '1.1',
        'method': 'GET',
        'scheme': 'http',
        'path': '/api/v1/x',
        'raw_path': b'/api/v1/x',
        'query_string': b'',
        'root_path': '',
        'headers': [],
        'client': (ip, 4711),
        'server': ('testserver', 80),
    })


def test_identity_key_is_not_the_default_ip_key():
    assert rate_limit_key is not get_remote_address, '限流键退回了纯 IP 解析'


@pytest.mark.parametrize('route_key,rate', sorted(_DECORATED_ROUTES.items()))
def test_decorated_route_binds_identity_key_func(route_key, rate):
    """装饰时就必须绑定 rate_limit_key（事后改 limiter.key_func 无效）。"""
    limits = limiter._route_limits.get(route_key)
    assert limits, f'{route_key} 没有登记路由级限流（装饰器丢失？）'
    assert [str(limit.limit) for limit in limits] == [rate], f'{route_key} 限额漂移: {[str(l.limit) for l in limits]}'
    for limit in limits:
        assert limit.key_func is rate_limit_key, (
            f'{route_key} 的限流键仍是 {limit.key_func}，装饰处未显式传 key_func=rate_limit_key'
        )


def test_key_ignores_ip_when_identity_is_present(monkeypatch):
    """同一用户换 IP 仍落同一桶（否则多 IP 即可绕过限额）。"""
    monkeypatch.setattr(deps_mod, '_resolve_user_id', lambda request: 4242)
    assert rate_limit_key(_request('10.0.0.1')) == rate_limit_key(_request('10.0.0.99')) == 'user:4242'


def test_key_differs_between_users_on_the_same_ip(monkeypatch):
    """同一 IP 上的不同用户必须各自计桶。"""
    ids = iter([4242, 4243])
    monkeypatch.setattr(deps_mod, '_resolve_user_id', lambda request: next(ids))
    assert rate_limit_key(_request('10.0.0.1')) != rate_limit_key(_request('10.0.0.1'))


def test_anonymous_requests_fall_back_to_ip(monkeypatch):
    """未登录（vitals sendBeacon）没有身份可绑，仍按 IP 计桶。"""
    monkeypatch.setattr(deps_mod, '_resolve_user_id', lambda request: None)
    assert rate_limit_key(_request('10.0.0.1')) == get_remote_address(_request('10.0.0.1'))
    assert rate_limit_key(_request('10.0.0.1')) != rate_limit_key(_request('10.0.0.2'))


@pytest.mark.asyncio
async def test_rate_limit_bucket_follows_identity_end_to_end(client, monkeypatch):
    """端到端：匿名端点按身份计桶 —— 用户 A 配额用尽后，用户 B 仍可上报。"""
    monkeypatch.setattr(deps_mod, '_resolve_user_id', lambda request: 7101)
    statuses = []
    for _ in range(_LIMIT + 1):
        resp = await client.post('/api/v1/monitoring/vitals', json=VITALS_PAYLOAD)
        statuses.append(resp.status_code)
    assert statuses[-1] == 429, f'同一身份的 {_LIMIT + 1} 次上报未被限流: {statuses}'

    monkeypatch.setattr(deps_mod, '_resolve_user_id', lambda request: 7102)
    fresh = await client.post('/api/v1/monitoring/vitals', json=VITALS_PAYLOAD)
    assert fresh.status_code != 429, (
        f'换了用户身份仍被限流（{fresh.status_code}）—— 限流键没有跟着身份走，很可能仍是 IP'
    )
