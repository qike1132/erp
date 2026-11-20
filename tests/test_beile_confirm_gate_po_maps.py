"""湖北确认门控必须复用 _fetch_completed_po_maps（审计 L-01/L-02）。"""
from fastapi_app.services.order import beile


async def test_confirm_gates_use_shared_po_maps(monkeypatch):
    calls = []

    async def fake_maps(db):
        calls.append(db)
        return ({7: [object()]}, {('客户A', '产品A'): [object()]}, {})

    monkeypatch.setattr(beile, '_fetch_completed_po_maps', fake_maps)

    assert await beile._order_has_completed_po(None, 7) is True
    assert await beile._order_has_completed_po(None, 8) is False
    assert await beile._stockin_has_completed_po(None, '客户A', '产品A') is True
    assert await beile._stockin_has_completed_po(None, '客户A', '产品B') is False
    assert len(calls) == 4, '两个门控都应调用同一映射实现'
