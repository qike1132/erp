"""QA 契约护栏：完全空 body `{}` 必须仍是 422（放宽 edits 后不得回退为静默 200）。"""
import pytest


@pytest.mark.asyncio
async def test_qa_factory_summary_empty_body_still_422(client):
    resp = await client.post("/api/v1/purchase-center/orders/factory-summary/save", json={})
    assert resp.status_code == 422, (
        f"完全空 body 应保持契约 422，实测 {resp.status_code}（护栏失效）"
    )
