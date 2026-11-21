"""M-28 回归：手工采购单幂等键（2026-11-21 全量审计）。

此前 POST /purchase-center/orders 无幂等键（一键生成同模块已有 X-Idempotency-Key
机制而手工创建未接入），uq_po_pending_dedup 只盖 source_order_ids 非空的生成单
→ 双击/重试产生重复 pending 采购单。修复：create_purchase_order 接入幂等三件套
（acquire_key_lock/load_replay/save_result，与一键生成共用登记表），端点收键、
业务校验失败改 400、幂等冲突 409。

走真实 HTTP 层（编号内核的独立短事务用全局引擎，需完整 app 启动）。
"""
from copy import deepcopy

_PAYLOAD = {
    'materials': [{'material_name': '物料A', 'quantity': 10, 'unit_price': 2.5,
                   'supplier_name': '供应商甲'}],
    'customer_name': '客户甲',
}

_URL = '/api/v1/purchase-center/orders'


async def test_manual_create_po_replays_with_same_key(async_client, auth_headers):
    headers = {**auth_headers, 'X-Idempotency-Key': 'm28-api-1'}
    r1 = await async_client.post(_URL, json=deepcopy(_PAYLOAD), headers=headers)
    assert r1.status_code == 200, r1.text[:300]
    b1 = r1.json()
    assert b1['success'] is True and b1.get('idempotent') is None
    r2 = await async_client.post(_URL, json=deepcopy(_PAYLOAD), headers=headers)
    assert r2.status_code == 200, r2.text[:300]
    b2 = r2.json()
    assert b2.get('idempotent') is True, b2
    assert b2['order_no'] == b1['order_no']


async def test_manual_create_po_conflicts_on_payload_change(async_client, auth_headers):
    headers = {**auth_headers, 'X-Idempotency-Key': 'm28-api-2'}
    r1 = await async_client.post(_URL, json=deepcopy(_PAYLOAD), headers=headers)
    assert r1.status_code == 200, r1.text[:300]
    changed = deepcopy(_PAYLOAD)
    changed['materials'][0]['quantity'] = 99
    r2 = await async_client.post(_URL, json=changed, headers=headers)
    assert r2.status_code == 409, (r2.status_code, r2.text[:200])


async def test_manual_create_po_without_key_creates(async_client, auth_headers):
    """兼容旧调用方：不带键时行为与修复前一致（直接建单，无登记）。"""
    r = await async_client.post(_URL, json=deepcopy(_PAYLOAD), headers=auth_headers)
    assert r.status_code == 200, r.text[:300]
    assert r.json().get('idempotent') is None

    # 空明细被 schema min_length 在 422 层拦截（400 分支只兜服务层 ValueError，
    # 与一键生成的 error_map 同款接线，不再单测）。
