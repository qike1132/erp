"""采购订单自动生成：提交后就地生成 / 候选过滤（回归守卫）

背景：采购中心原先靠人工在「待审核订单」tab 勾选后点「一键审核订单」生成采购单，
那条路径是**在 HTTP 请求内同步**调用 ``generate_purchase_orders_from_customer_orders``。
现改为自动：订单/备货创建、BOM 保存的**事务提交成功后**由 post-commit 回调**就地**跑
一次自动生成（开独立会话，复用同一生成函数）。**不使用 ARQ** —— worker 不跑时
（如 GUI 开发栈托管）任务会静默滞留，用户看到「生成中…」永不推进。

本文件锁死不变量：
1. 生成发生在**事务提交之后**（注册阶段绝不执行）；
2. 同一事务只触发一次（按回调列表去重）；跨事务各自触发；
3. 失败 best-effort（不冒泡，不影响下单/保存）；
4. 生成后失效采购缓存并广播 ``purchase_order_created``（无生成则不广播）；
5. 候选只包含「全部 SKU 有 BOM」的未处理单（缺 BOM 的单不生成）。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.core.exceptions import db_transaction, run_post_commit_callbacks
from fastapi_app.services.purchase._auto_generate import (
    _run_auto_generate,
    schedule_auto_generate_purchase_orders,
    schedule_bom_saved_side_effects,
)
from fastapi_app.services.purchase_order_revoke import schedule_stockin_deleted_side_effects

_GEN_TARGET = 'fastapi_app.services.purchase_order_generate.auto_generate_purchase_orders'
_FACTORY_TARGET = 'fastapi_app.core.database.require_async_session_local'
_INVALIDATE_TARGET = 'fastapi_app.core.cache.invalidate_cache'
_PUBLISH_TARGET = 'fastapi_app.services.notification_service.publish_event'


def _patch_session():
    """让 _run_auto_generate 拿到一个**独立**的假会话工厂。

    独立是关键：``_run_auto_generate`` 自己开事务并提交，若复用被测会话，
    内层 commit 会混进外层的调用序列（测试断言失真）。
    """
    inner_db = AsyncMock()
    inner_db.info = {}
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=inner_db)
    cm.__aexit__ = AsyncMock(return_value=False)
    return patch(_FACTORY_TARGET, return_value=lambda: cm)


async def test_schedule_registers_callback_without_running(mock_db):
    """注册阶段只入队回调、不执行；显式执行回调后才跑生成。"""
    gen = AsyncMock(return_value={'success': True, 'generated_count': 1, 'customer_count': 1})
    with _patch_session(), patch(_GEN_TARGET, new=gen), \
         patch(_INVALIDATE_TARGET, new=AsyncMock()), patch(_PUBLISH_TARGET, new=AsyncMock()):
        schedule_auto_generate_purchase_orders(mock_db)
        gen.assert_not_awaited()
        assert mock_db.info.get('post_commit_callbacks'), '回调未入队，会被静默丢弃'

        await run_post_commit_callbacks(mock_db)
        gen.assert_awaited_once()


async def test_schedule_runs_after_commit(mock_db):
    """走 db_transaction 的写路径：commit 成功后才跑生成。"""
    calls = []

    def _record_generate(*_a, **_k):
        calls.append('generate')
        return {'success': True, 'generated_count': 0, 'customer_count': 0}

    gen = AsyncMock(side_effect=_record_generate)
    mock_db.commit = AsyncMock(side_effect=lambda: calls.append('commit'))

    with _patch_session(), patch(_GEN_TARGET, new=gen), \
         patch(_INVALIDATE_TARGET, new=AsyncMock()), patch(_PUBLISH_TARGET, new=AsyncMock()):
        async with db_transaction(mock_db):
            schedule_auto_generate_purchase_orders(mock_db)
            assert calls == [], '事务体（提交前）内不得生成'

        assert calls == ['commit', 'generate'], f'提交先于生成被破坏: {calls}'


async def test_schedule_rollback_discards_generate(mock_db):
    """事务回滚时不得生成。"""
    gen = AsyncMock()
    with _patch_session(), patch(_GEN_TARGET, new=gen):
        with pytest.raises(RuntimeError):
            async with db_transaction(mock_db):
                schedule_auto_generate_purchase_orders(mock_db)
                raise RuntimeError('boom')

    gen.assert_not_awaited()


async def test_schedule_dedups_within_transaction(mock_db):
    """同一事务重复注册 → 只触发一次。"""
    gen = AsyncMock(return_value={'success': True, 'generated_count': 0, 'customer_count': 0})
    with _patch_session(), patch(_GEN_TARGET, new=gen), \
         patch(_INVALIDATE_TARGET, new=AsyncMock()):
        schedule_auto_generate_purchase_orders(mock_db)
        schedule_auto_generate_purchase_orders(mock_db)
        assert len(mock_db.info.get('post_commit_callbacks') or []) == 1, '重复注册应去重'

        await run_post_commit_callbacks(mock_db)
        gen.assert_awaited_once()


async def test_schedule_runs_again_in_next_transaction(mock_db):
    """同一会话跨事务：去重只限当前事务，每次提交都要各自触发。

    回归守卫：去重若改用 ``session.info`` 上的持久标记，第二次事务起会被永久屏蔽。
    """
    gen = AsyncMock(return_value={'success': True, 'generated_count': 0, 'customer_count': 0})
    with _patch_session(), patch(_GEN_TARGET, new=gen), \
         patch(_INVALIDATE_TARGET, new=AsyncMock()):
        async with db_transaction(mock_db):
            schedule_auto_generate_purchase_orders(mock_db)
        async with db_transaction(mock_db):
            schedule_auto_generate_purchase_orders(mock_db)
    assert gen.await_count == 2, '第二个事务未触发（去重跨越了事务边界）'


async def test_run_generate_failure_is_swallowed(mock_db):
    """生成失败 best-effort：不冒泡（不影响下单/保存本身）。"""
    gen = AsyncMock(side_effect=RuntimeError('db down'))
    with _patch_session(), patch(_GEN_TARGET, new=gen):
        schedule_auto_generate_purchase_orders(mock_db)
        await run_post_commit_callbacks(mock_db)  # 不抛异常即通过


async def test_schedule_tolerates_no_info_session():
    """无 info 属性的会话（测试桩/轻量包装）不得崩溃。"""
    class _NoInfo:
        pass

    schedule_auto_generate_purchase_orders(_NoInfo())  # 不抛异常即通过


async def test_run_generate_invalidates_and_broadcasts():
    """生成 N 单 → 失效三个采购缓存前缀 + 广播 purchase_order_created。"""
    gen = AsyncMock(return_value={'success': True, 'generated_count': 2, 'customer_count': 1})
    inv = AsyncMock()
    pub = AsyncMock()
    with _patch_session(), patch(_GEN_TARGET, new=gen), \
         patch(_INVALIDATE_TARGET, new=inv), patch(_PUBLISH_TARGET, new=pub):
        await _run_auto_generate()

    assert inv.await_count == 3, '三个采购缓存前缀都应失效'
    pub.assert_awaited_once()
    assert pub.await_args.args[0] == 'purchase_order_created'


async def test_run_generate_skips_broadcast_when_nothing_generated():
    """无生成 → 不广播（避免无谓的前端刷新）。"""
    gen = AsyncMock(return_value={'success': True, 'generated_count': 0, 'customer_count': 0})
    pub = AsyncMock()
    with _patch_session(), patch(_GEN_TARGET, new=gen), \
         patch(_INVALIDATE_TARGET, new=AsyncMock()), patch(_PUBLISH_TARGET, new=pub):
        await _run_auto_generate()

    pub.assert_not_awaited()


def test_no_arq_registration():
    """不再依赖 ARQ：任务函数不得注册进 worker（否则又退回「worker 不跑就不生成」）。"""
    from fastapi_app.core import arq_app

    func_names = [f.__name__ for f in arq_app.WorkerSettings.functions]
    assert 'auto_generate_purchase_orders_task' not in func_names
    assert 'auto-generate-purchase-orders' not in [s['name'] for s in arq_app.cron_schedules]


# ===== 删空 BOM → 撤销该产品 pending 采购单（2026-10-10 规则） =====

class _FakeResult:
    """极简 DB 结果桩：支持 .first() / .scalars().unique().all() / .all()。"""

    def __init__(self, *, first=None, scalars_list=None, rows=None):
        self._first = first
        self._scalars_list = scalars_list
        self._rows = rows

    def first(self):
        return self._first

    def scalars(self):
        return _FakeScalars(self._scalars_list or [])

    def all(self):
        return self._rows or []


class _FakeScalars:
    def __init__(self, items):
        self._items = items

    def unique(self):
        return self

    def all(self):
        return self._items


async def test_bom_saved_runs_revoke_then_generate(mock_db):
    """BOM 保存提交后：先撤销（若删空），再自动生成——顺序不能反。"""
    order = []

    async def _revoke(*_a, **_k):
        order.append('revoke')

    async def _gen(*_a, **_k):
        order.append('generate')

    with _patch_session(), \
         patch('fastapi_app.services.purchase_order_revoke.'
               'revoke_pending_purchase_orders_for_product', new=_revoke), \
         patch('fastapi_app.services.purchase._auto_generate._run_auto_generate', new=_gen):
        schedule_bom_saved_side_effects(mock_db, 20909)
        assert order == [], '注册阶段不得执行'
        await run_post_commit_callbacks(mock_db)

    assert order == ['revoke', 'generate'], f'顺序错: {order}'


async def test_revoke_skips_when_product_still_has_bom():
    """该产品仍有 BOM 物料 → 一张单都不撤（本规则只处理「删空」）。"""
    from fastapi_app.services.purchase_order_revoke import (
        revoke_pending_purchase_orders_for_product,
    )

    db = AsyncMock()
    with patch('fastapi_app.services.purchase._unprocessed._fetch_bom_product_ids',
               new=AsyncMock(return_value={20909})):  # 仍有 BOM
        res = await revoke_pending_purchase_orders_for_product(db, 20909)
    assert res == {'revoked': 0, 'orders_reset': 0}


async def test_revoke_deletes_pending_pos_and_resets_source_orders():
    """删空 BOM：撤掉覆盖该产品的 pending 采购单，并把来源订单状态重算回「待备货」。"""
    from fastapi_app.services.purchase_order_revoke import (
        revoke_pending_purchase_orders_for_product,
    )

    po_hit = MagicMock()
    po_hit.id = 501
    po_other = MagicMock()
    po_other.id = 502
    order_obj = MagicMock()
    order_obj.id = 68939
    order_obj.status = '已备货'

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalars_list=[po_hit, po_other]),   # pending 采购单
        _FakeResult(rows=[(501, 68939)]),               # sku 行（source_record_type='order'）
        _FakeResult(scalars_list=[order_obj]),          # 来源订单
    ])
    db.flush = AsyncMock()
    delete_po = AsyncMock()

    with patch('fastapi_app.services.purchase._unprocessed._fetch_bom_product_ids',
               new=AsyncMock(return_value=set())), \
         patch('fastapi_app.services.purchase._common.fetch_po_sku_pids_map',
               new=AsyncMock(return_value={501: [20909], 502: [999]})), \
         patch('fastapi_app.services.purchase_order_crud.delete_purchase_order', new=delete_po), \
         patch('fastapi_app.services.order_utils.compute_order_status_from_db',
               new=AsyncMock(return_value='待备货')):
        res = await revoke_pending_purchase_orders_for_product(db, 20909)

    assert res == {'revoked': 1, 'orders_reset': 1}, res
    delete_po.assert_awaited_once_with(db, 501)   # 只撤覆盖该产品的那张
    assert order_obj.status == '待备货', '来源订单应被重算回待备货'


# ===== 删除备货记录 → 撤销其 pending 采购单 =====

async def test_stockin_deleted_revokes_and_invalidates(mock_db):
    """备货删除提交后：撤销引用它的 pending 采购单 + 失效采购缓存（与 ORDER_DELETED 同款）。"""
    revoke = AsyncMock()
    inval = AsyncMock()

    with _patch_session(), \
         patch('fastapi_app.services.purchase_order_revoke.'
               'revoke_pending_purchase_orders_for_stockin', new=revoke), \
         patch('fastapi_app.services.purchase._auto_generate.invalidate_purchase_caches', new=inval):
        schedule_stockin_deleted_side_effects(mock_db, 777)
        revoke.assert_not_awaited()
        await run_post_commit_callbacks(mock_db)

    revoke.assert_awaited_once()
    inval.assert_awaited_once()


async def test_revoke_for_stockin_deletes_pos_and_resets_source_orders():
    """删备货：撤掉引用它的 pending 采购单，并把来源订单状态重算回「待备货」。"""
    from fastapi_app.services.purchase_order_revoke import (
        revoke_pending_purchase_orders_for_stockin,
    )

    po = MagicMock()
    po.id = 601
    order_obj = MagicMock()
    order_obj.id = 68939
    order_obj.status = '已备货'

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _FakeResult(rows=[(601,)]),                  # sku：引用该备货的 pending 采购单 id
        _FakeResult(scalars_list=[po]),              # pending 采购单
        _FakeResult(rows=[(601, 68939)]),            # 这些单的来源订单
        _FakeResult(scalars_list=[order_obj]),       # 来源订单对象
    ])
    db.flush = AsyncMock()
    delete_po = AsyncMock()

    with patch('fastapi_app.services.purchase_order_crud.delete_purchase_order', new=delete_po), \
         patch('fastapi_app.services.order_utils.compute_order_status_from_db',
               new=AsyncMock(return_value='待备货')):
        res = await revoke_pending_purchase_orders_for_stockin(db, 777)

    assert res == {'revoked': 1, 'orders_reset': 1}, res
    delete_po.assert_awaited_once_with(db, 601)
    assert order_obj.status == '待备货', '来源订单应被重算回待备货'


# ===== 删除客户订单（订单流水）→ 撤销其 pending 采购单 =====

async def test_revoke_for_order_deletes_pos_and_resets_other_orders():
    """删订单：撤掉引用它的 pending 采购单，并把同单**其余**来源订单状态重算回真实值。"""
    from fastapi_app.services.purchase_order_revoke import revoke_pending_purchase_orders_for_order

    po = MagicMock()
    po.id = 701
    other_order = MagicMock()
    other_order.id = 68940
    other_order.status = '已备货'

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _FakeResult(rows=[(701,)]),                    # sku：引用该订单的 pending 采购单 id
        _FakeResult(scalars_list=[po]),                # pending 采购单
        _FakeResult(rows=[(701, 68940)]),              # 同单其余来源订单
        _FakeResult(scalars_list=[other_order]),       # 其余来源订单对象
    ])
    db.flush = AsyncMock()
    delete_po = AsyncMock()

    with patch('fastapi_app.services.purchase_order_crud.delete_purchase_order', new=delete_po), \
         patch('fastapi_app.services.order_utils.compute_order_status_from_db',
               new=AsyncMock(return_value='待备货')):
        res = await revoke_pending_purchase_orders_for_order(db, 68939)

    assert res == {'revoked': 1, 'orders_reset': 1}, res
    delete_po.assert_awaited_once_with(db, 701)
    assert other_order.status == '待备货', '同单其余来源订单不该被永久卡在「已备货」'


async def test_order_deleted_event_revokes_and_cleans_up(monkeypatch):
    """ORDER_DELETED 事件 → 撤销引用该订单的 pending 采购单 + 兜底 JSON 清理。"""
    import fastapi_app.services.purchase_center_service  # noqa: F401  确保订阅已注册
    from fastapi_app.core.domain_events import DomainEvent, DomainEventType, publish

    revoke = AsyncMock()
    cleanup = AsyncMock()
    invalidate = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=AsyncMock())
    cm.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr('fastapi_app.services.purchase_order_revoke.'
                        'revoke_pending_purchase_orders_for_order', revoke)
    monkeypatch.setattr('fastapi_app.services.purchase_center_service.'
                        'cleanup_orphan_pending_purchase_orders', cleanup)
    monkeypatch.setattr('fastapi_app.services.purchase._auto_generate.'
                        'invalidate_purchase_caches', invalidate)
    monkeypatch.setattr('fastapi_app.core.database.get_async_db_context', lambda: cm)

    await publish(DomainEvent(event_type=DomainEventType.ORDER_DELETED, domain='order',
                              payload={'order_id': 68939}))

    revoke.assert_awaited_once()
    cleanup.assert_awaited_once()
    invalidate.assert_awaited_once()   # 撤销发生在删除端点失效之后，必须再失效一次


async def test_list_candidates_filters_out_orders_without_bom(monkeypatch):
    """候选过滤：只保留「全部 SKU 都有 BOM」的记录；缺 BOM 的不生成。"""
    from fastapi_app.services.purchase import _unprocessed as up

    monkeypatch.setattr(up, '_build_unprocessed_union', lambda: MagicMock())
    # select(...) 仅为构造 SQL，本用例不跑 SQL —— 桩掉它，让 unified.c.* 的取值不被 SQLAlchemy 解析。
    monkeypatch.setattr(up, 'select', lambda *a, **k: object())

    class _Result:
        def all(self):
            return [object(), object()]

    monkeypatch.setattr(up, '_load_unprocessed_sources', AsyncMock(return_value=({}, {})))
    monkeypatch.setattr(up, '_build_records_in_sql_order', lambda rows, om, sm: [
        {'composite_id': 'order:1', 'customer': 'A', 'order_no': 'O1', 'record_type': 'order',
         'source_order_id': 1, 'product_id': 10, 'items': [{'product_id': 10}]},
        {'composite_id': 'order:2', 'customer': 'B', 'order_no': 'O2', 'record_type': 'order',
         'source_order_id': 2, 'product_id': 11, 'items': [{'product_id': 11}]},
    ])
    monkeypatch.setattr(up, '_collect_record_product_ids', lambda records: [10, 11])
    monkeypatch.setattr(up, '_fetch_bom_product_ids', AsyncMock(return_value={10}))

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Result())

    result = await up.list_auto_generate_candidates(db)
    assert [c['composite_id'] for c in result] == ['order:1'], '缺 BOM 的记录不得进入候选'


async def test_existing_pending_lookup_filters_in_sql():
    """Z02-R3：幂等回查必须把 source_order_ids 匹配下推到 SQL（JSONB @>）。"""
    from fastapi_app.services.purchase_order_generate import (
        fetch_existing_pending_for_composite_ids,
    )

    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)

    assert await fetch_existing_pending_for_composite_ids(db, ['order:5', 'stockin:3']) == []

    stmt = db.execute.await_args.args[0]
    sql = str(stmt.compile())
    assert 'JSONB' in sql.upper()
    assert '@>' in sql, f'匹配未下推到 SQL：{sql}'
