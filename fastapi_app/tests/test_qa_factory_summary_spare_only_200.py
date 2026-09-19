"""QA 契约护栏：`edits=[] + spare_rate + order_ids` 必须 200（放宽 edits 的合法路径，不得被护栏误伤）。"""
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_qa_factory_summary_edits_empty_with_spare_rate_ok(client):
    with patch(
        'fastapi_app.services.purchase_center_service.save_factory_summary_edits',
        new_callable=AsyncMock,
        return_value={'updated_count': 0, 'spare_updated_count': 1},
    ):
        resp = await client.post(
            "/api/v1/purchase-center/orders/factory-summary/save",
            json={'edits': [], 'spare_rate': 50, 'order_ids': [1]},
        )
    assert resp.status_code == 200, (
        f"仅改损耗率的合法请求被护栏误伤：实测 {resp.status_code}"
    )
