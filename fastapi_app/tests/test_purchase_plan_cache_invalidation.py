"""采购计划缓存失效：plan_fifo 与 plan_prod_fifo 必须同批清（2026-10-30 审计 A-H2）。

计划明细改数量/改期/增删后，日历与月度聚合读的是 plan_prod_fifo 的生产摊派；
此前 `_invalidate_plan_caches` 只清 plan_fifo，生产进度最长 30 分钟显示旧值。
"""
import pytest

from fastapi_app.services import purchase_plan_common as ppc


@pytest.mark.asyncio
async def test_invalidate_plan_caches_clears_both_fifo_prefixes(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def fake_fifo(month: str) -> None:
        calls.append(('fifo', month))

    async def fake_prod(month: str) -> None:
        calls.append(('prod', month))

    async def fake_invalidate(strategy, pattern) -> None:
        calls.append(('cache', pattern))

    monkeypatch.setattr(ppc, '_invalidate_fifo_cache', fake_fifo)
    monkeypatch.setattr(ppc, '_invalidate_production_fifo_cache', fake_prod)
    monkeypatch.setattr(ppc.cache_mgr, 'invalidate', fake_invalidate)
    monkeypatch.setattr(ppc, 'invalidate_local_cache', lambda pattern: calls.append(('l1', pattern)))

    await ppc._invalidate_plan_caches('2026-10')

    assert ('fifo', '2026-10') in calls
    assert ('prod', '2026-10') in calls, 'plan_prod_fifo 未失效：生产进度会陈旧'
    assert ('l1', 'plan_fifo:2026-10') in calls
    assert ('l1', 'plan_prod_fifo:2026-10') in calls
