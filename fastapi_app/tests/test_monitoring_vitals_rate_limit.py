"""匿名 vitals 上报端点必须有 IP 限流（M-1）。

背景：`POST /api/v1/monitoring/vitals` 为兼容 `navigator.sendBeacon`（无法带
Authorization 头）而**匿名**开放（`monitoring.py:45-46` 有说明），且没有任何
`@limiter.limit` —— 全局限流默认值是空（只对显式标注的端点限流），于是任何
匿名调用者可无限量写 `web_vital` 表与 Redis 流，构成存储洪泛面。

本用例锁住"超过限额后必须 429"。
"""
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

# 与端点上的限额保持一致：30/minute → 第 31 次必须被拦
_LIMIT = 30


async def test_vitals_endpoint_is_rate_limited(client):
    statuses = []
    for _ in range(_LIMIT + 1):
        resp = await client.post('/api/v1/monitoring/vitals', json=VITALS_PAYLOAD)
        statuses.append(resp.status_code)

    assert statuses[-1] == 429, (
        f'第 {_LIMIT + 1} 次匿名 vitals 上报未被限流（存储洪泛面）: {statuses}'
    )
