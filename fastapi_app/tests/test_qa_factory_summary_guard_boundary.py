"""QA 契约护栏：仅有目标订单、或仅有损耗率的 payload，必须 422（不得静默 200）。

`edits` 放宽为可空是为支持「仅改损耗率也要落库」（PRD Q1），其合法形态恒为
`edits=[] + spare_rate + order_ids` 三者齐备（见 test_qa_factory_summary_spare_only_200.py）。
除此之外的两种残缺形态都没有任何可落库内容：

- `{'order_ids': [1]}`：有目标无内容——既无 edit 也无 rate，落库是空操作；
- `{'spare_rate': 50}`：无目标订单——后端无从定位要写入的采购单。

二者若返回 200，客户端会误以为已落库（静默失败）。本用例锁定 FIX-5 收紧后的边界：
必须 422，且不得触达服务层。
"""
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_qa_factory_summary_guard_boundary_behavior(client):
    observed = {}
    with patch(
        'fastapi_app.services.purchase_center_service.save_factory_summary_edits',
        new_callable=AsyncMock,
        return_value={'updated_count': 0, 'spare_updated_count': 0},
    ) as mock_svc:
        for name, payload in (
            ('order_ids_only', {'order_ids': [1]}),
            ('spare_rate_only', {'spare_rate': 50}),
        ):
            resp = await client.post(
                "/api/v1/purchase-center/orders/factory-summary/save", json=payload,
            )
            observed[name] = resp.status_code

    # 两类「无可保存内容」的 payload 都必须被护栏拦下，且不产生任何服务层调用
    assert observed == {'order_ids_only': 422, 'spare_rate_only': 422}, (
        f"护栏边界行为与预期不一致：{observed}"
    )
    mock_svc.assert_not_awaited()


@pytest.mark.asyncio
async def test_qa_factory_summary_degenerate_edits_still_422(client):
    """退化的 edits 条目（无 item_ids / 无 quantity）同样必须 422。

    服务层对每个编辑项有 `if not item_ids or new_quantity is None: continue`
    （purchase_order_crud.apply_factory_summary_edits），因此这类条目**零写入**。
    若仅按「列表长度 > 0」判空，它们会越过护栏、以 200 返回，形成新的静默成功——
    即 FIX-5 本要消灭的那类缺陷。本用例锁死「按服务层同一判据过滤后再判空」。
    """
    with patch(
        'fastapi_app.services.purchase_center_service.save_factory_summary_edits',
        new_callable=AsyncMock,
        return_value={'updated_count': 0, 'spare_updated_count': 0},
    ) as mock_svc:
        for name, payload in (
            ('empty_object', {'edits': [{}]}),
            ('empty_item_ids', {'edits': [{'item_ids': [], 'quantity': 5}]}),
            ('null_quantity', {'edits': [{'item_ids': [1], 'quantity': None}]}),
        ):
            resp = await client.post(
                '/api/v1/purchase-center/orders/factory-summary/save', json=payload,
            )
            assert resp.status_code == 422, (
                f'{name} 的退化 edits 应 422（零写入不得静默成功），实测 {resp.status_code}'
            )
    mock_svc.assert_not_awaited()
