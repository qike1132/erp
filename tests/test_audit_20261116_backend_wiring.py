"""2026-11-16 上线前审计的其余后端修复回归（A-27 / A-39 / A-40 / A-53 / A-56 / A-11 / A-38）。

本文件只放**不需要数据库**的断言：纯函数行为、可 mock 的调用序列，以及「接线类」的
源码断言（本仓既有先例：`test_stock_chip_cache_invalidation.py::test_get_all_customers_disables_l1`
就是读源码钉装饰器参数）。每条的变异点写在用例注释里。
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # tests/ 的上一级才是仓库根


def _src(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding='utf-8')


# ---------------------------------------------------------------- A-27
async def test_revoke_isolates_failed_purchase_orders(monkeypatch):
    """单张 pending 单删不掉时必须逐单隔离，其余仍被撤销（审计 A-27）。

    变异：把 `async with db.begin_nested()` 去掉 → 第二张单抛错会让 `delete_calls`
    只有 1 次且用例红。
    """
    from fastapi_app.services import purchase_order_revoke as revoke

    deleted: list[int] = []

    async def fake_delete(db, po_id):
        deleted.append(po_id)
        if po_id == 2:
            raise RuntimeError('该单已有来料登记')

    monkeypatch.setattr(
        'fastapi_app.services.purchase_order_crud.delete_purchase_order', fake_delete,
    )
    monkeypatch.setattr(revoke, '_load_sku_order_ids', None, raising=False)

    class _Nested:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    db = MagicMock()
    db.begin_nested = lambda: _Nested()
    db.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: []))
    db.flush = AsyncMock()

    targets = [SimpleNamespace(id=1), SimpleNamespace(id=2), SimpleNamespace(id=3)]
    result = await revoke._revoke_targets(db, targets)

    assert deleted == [1, 2, 3], '第二张失败后必须继续处理第三张'
    assert result['revoked'] == 2
    assert result['failed_po_ids'] == [2]


# ---------------------------------------------------------------- A-39 / A-40
def test_case_inventory_stats_only_counts_roots():
    """「皮套种类」必须只算主件，与列表/分页同口径（审计 A-39）。"""
    src = _src('fastapi_app/services/case/queries.py')
    match = re.search(r'async def _compute_inventory_stats.*?(?=\nasync def |\n\ndef )', src, re.S)
    assert match, '未找到 _compute_inventory_stats'
    body = match.group(0)
    assert 'Case.parent_id.is_(None)' in body, '统计未限定主件：皮套种类会把配件算进去'


def test_case_stock_shortage_message_reports_pre_change_stock():
    """库存不足文案里的「当前库存」必须是变更前的值（审计 A-40）。"""
    src = _src('fastapi_app/services/case/commands.py')
    assert '当前库存: {case_obj.current_stock + delta}' not in src, (
        '文案仍在报「调整后」的值：该分支只在调整后为负时触发，印出来必是负数'
    )
    assert '当前库存: {case_obj.current_stock}，需要: {abs(delta)}' in src


# ---------------------------------------------------------------- A-53
async def test_save_query_flushes_before_serializing(monkeypatch):
    """save_query 必须先 flush 再 to_dict，否则响应里 id/create_time 恒为 null（A-53）。

    变异：删掉 `await db.flush()` → 序列化时 id 仍为 None，用例红。
    """
    from fastapi_app.services import purchase_history_service as svc

    calls: list[str] = []
    added: dict[str, object] = {}

    class _FakeSavedQuery:
        def __init__(self, **_kwargs):
            self.id = None

        def to_dict(self):
            calls.append('to_dict')
            assert self.id is not None, '未 flush 就序列化：id / create_time 会是 null'
            return {'id': self.id}

    monkeypatch.setattr(svc, 'SavedQuery', _FakeSavedQuery)

    db = MagicMock()

    def _add(obj):
        added['obj'] = obj
        calls.append('add')

    async def _flush():
        calls.append('flush')
        added['obj'].id = 42  # 自增主键只有 flush 之后才存在

    db.add = _add
    db.flush = _flush

    await svc.save_query(db, {'name': 'n', 'conditions': {}}, user_id=1, username='u')

    assert calls[:2] == ['add', 'flush'], f'调用顺序不对: {calls}'
    assert 'to_dict' in calls


# ---------------------------------------------------------------- A-56
def test_readiness_hides_restore_detail_from_anonymous_callers():
    """匿名可达的 readiness 不得返回恢复明细（库名/快照名/hint）（审计 A-56）。"""
    src = _src('fastapi_app/core/health.py')
    match = re.search(r'async def readiness_probe\(.*?(?=\nasync def )', src, re.S)
    assert match, '未找到 readiness_probe'
    body = match.group(0)
    assert 'restore_payload' in body, '响应里没有脱敏后的 restore_payload'
    assert '_is_direct_loopback(request)' in body, (
        '未按「本机直连」收口：匿名经 nginx 的请求也会拿到完整恢复明细'
    )
    assert re.search(r'"restore": restore_payload', body), '响应仍在用未脱敏的 restore'


# ---------------------------------------------------------------- A-11
def test_case_export_runs_openpyxl_in_thread():
    """皮套导出必须在 to_thread 里构表，不能堵住事件循环（审计 A-11）。"""
    src = _src('fastapi_app/api/v1/endpoints/case_endpoint.py')
    assert 'await asyncio.to_thread(inventory_to_xlsx' in src
    assert 'await asyncio.to_thread(movements_to_xlsx' in src
    assert '\n        content = inventory_to_xlsx(rows)' not in src


# ---------------------------------------------------------------- A-38
def test_inventory_pagination_falls_back_to_first_page():
    """越界页必须回退第 1 页重查，而不是把 total_items 写死 0（审计 A-38）。"""
    src = _src('fastapi_app/services/stock_inventory_service.py')
    assert "if not rows and page > 1:" in src, '缺少越界页回退分支'
    assert "params['offset'] = 0" in src
    assert 'page = 1' in src


@pytest.mark.parametrize('needle', ['stock:stats*'])
def test_stock_stats_pattern_present_in_both_invalidation_paths(needle):
    """两处入口（域映射表 + 直连函数）都要清 stock:stats（审计 A-26）。"""
    assert needle in _src('fastapi_app/core/cache.py')
    assert needle in _src('fastapi_app/core/cache_invalidation.py')
