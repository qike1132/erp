"""L 回归：审批列表 status 筛选收窄为 Literal（2026-11-21 全量审计）。

此前自由字符串的未知值在 service 里静默返回空列表（200），用户以为
「没有该状态的审批」；Literal 让非法值 422 显式报错（对照 order.py:241 的
同形态 400 口径——Query 校验走 FastAPI 422 通道）。
"""


async def test_approval_list_unknown_status_is_422(async_client, auth_headers):
    resp = await async_client.get(
        "/api/v1/approvals/list", params={"status": "garbage"}, headers=auth_headers)
    assert resp.status_code == 422, (resp.status_code, resp.text[:200])


async def test_approval_list_known_status_still_ok(async_client, auth_headers):
    resp = await async_client.get(
        "/api/v1/approvals/list", params={"status": "pending"}, headers=auth_headers)
    assert resp.status_code == 200, (resp.status_code, resp.text[:200])
