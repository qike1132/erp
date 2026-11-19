"""响应形状断言（测试侧共用）：审计 P2 3.3 / 2.5。

为什么单独一个模块：`test_smoke.py` 与 `test_forms.py` 都要断「列表端点真的返回了列表」，
两边各写一份必然漂移（改了一份另一份不知道）。这里是唯一实现。

它们原来只断 `status_code == 200` —— 端点返回 `{}`、标量、或只剩 `{"success": true}`
也照样「冒烟通过」，接口活着但契约已经变形却无人发现。
"""
from __future__ import annotations

#: 常见的「列表容器」键名（只是优先匹配，不是白名单）。
LIST_KEYS = ('items', 'data', 'records', 'list')


def find_list(payload):
    """在响应体里找列表容器，允许分页包一层（``{'data': {'items': [...]}}``）。

    不逐一登记键名（客户列表用 ``customers``、库存可能用 ``rows``……登记表必然漂移），
    改为接受「任一顶层值是列表」。仍然拦住审计要拦的形状：``{}`` / 标量 /
    只有 ``success``+``total`` 而没有任何列表。
    """
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return None
    for key in LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    for value in payload.values():
        if isinstance(value, list):
            return value
    for value in payload.values():
        if isinstance(value, dict):
            nested = find_list(value)
            if nested is not None:
                return nested
    return None


def assert_list_shape(resp, label: str) -> list:
    """断言 2xx + 存在列表容器 + `total`/`page` 若存在必须是整数；返回该列表。"""
    assert resp.status_code in (200, 201), (
        f'【{label}】→ HTTP {resp.status_code}: {resp.text[:200]}'
    )
    body = resp.json()
    container = find_list(body)
    assert container is not None, (
        f'【{label}】响应里没有列表容器（形状漂移）：'
        f'keys={sorted(body) if isinstance(body, dict) else type(body)}'
    )
    if isinstance(body, dict):
        for key in ('total', 'page', 'per_page'):
            if key in body:
                assert isinstance(body[key], int), (
                    f'【{label}】{key} 必须是整数，实际 {type(body[key])}'
                )
    return container
