"""M3：外协状态筛选的进度聚合不得每页重复查询。"""
import pytest

from fastapi_app.services.outsource import _queries


@pytest.mark.asyncio
async def test_progress_attached_once_for_all_pages(monkeypatch):
    calls = []

    async def _fake_get(db, page, per_page, customer, factory, product_kw):
        total = per_page * 3
        if page <= 2:
            items = [{"id": page * per_page + i, "record_type": "order"} for i in range(per_page)]
        else:
            items = [{"id": total + 1, "record_type": "order"}]
        return {"items": items, "total": total}

    async def _fake_attach(db, items):
        calls.append(len(items))

    monkeypatch.setattr(
        "fastapi_app.services.order_crud.get_beile_orders_with_stockins", _fake_get
    )
    monkeypatch.setattr(_queries, "_attach_progress_to_orders", _fake_attach)
    monkeypatch.setattr(_queries, "_detach_page_items", lambda items: items)

    result = await _queries._scan_beile_items_with_progress(object(), None, None)

    assert len(calls) == 1, f"进度聚合被调用了 {len(calls)} 次（应按整次扫描只调一次）"
    assert calls[0] == len(result)
