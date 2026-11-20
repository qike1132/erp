"""B1 分区 P2 批次（2026-10-24 审计）回归锁：
- B1-03 生产记录负向变动/移出包装部的结余闸门；
- B1-04 暂存出货预检按结余口径重算（导入后 + 编辑路径）；
- B1-05 采购单 delete/complete/batch-complete 三入口行锁；
- B1-06 工厂汇总分摊的残差回填（Σ分摊 == 目标数量）；
- B1-07 退货产品搜索 ilike（PG like 大小写敏感）。

2026-10-17 审计 TEST 区（F2/F3/G3/G5/G6）修法：本文件原先用
``inspect.getsource`` + 子串匹配冒充「先锁后校验」「部门移出闸门」，
被测函数一次都没被调用（改坏实现仍绿）。现改为行为断言：
记录真实 DB 动作序列 / 调用真实函数并断言手算结果。
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services import purchase_order_crud as poc


# ---------------------------------------------------------------------------
# B1-05：三入口行锁（行为断言：第一个 DB 动作就是带 FOR UPDATE 的取行）
# ---------------------------------------------------------------------------
class _RecordingSession:
    """记录 DB 动作序列的假会话，用于锁序断言。

    F2（2026-10-17 审计）：旧用例断言 ``'with_for_update=True' in
    inspect.getsource(...)`` —— 「源码里出现过这个片段」不等于「加锁发生在
    校验之前」。把校验提前（例如先插一次无锁 ``db.get`` 预读、按状态提前
    return），加锁语句一字不动、用例照样绿，而 TOCTOU 窗口已经重新打开。
    这里改为记录真实调用序列：只要第一个 DB 动作不是带锁取行，断言即红。
    """

    def __init__(self, order=None, has_registration: bool = False) -> None:
        self.calls: list[tuple] = []
        self._order = order
        self._has_registration = has_registration

    async def get(self, model, ident, **kwargs):
        self.calls.append(('get', model.__name__, ident, dict(kwargs)))
        return self._order

    async def execute(self, stmt, *args, **kwargs):
        self.calls.append(('execute', str(stmt)))
        result = MagicMock()
        result.scalar_one_or_none.return_value = 1 if self._has_registration else None
        result.scalars.return_value.all.return_value = []
        return result

    async def flush(self):
        self.calls.append(('flush',))

    async def delete(self, obj):
        self.calls.append(('delete', type(obj).__name__))


async def test_delete_purchase_order_locks_row_before_any_other_db_work():
    """删除入口：拒绝路径（有来料登记）之前，第一个 DB 动作必须是带锁取行。

    期望值手工推导：``delete_purchase_order`` 先带锁取采购单行，随后才查来料
    登记并拒绝 —— 故 calls 的首项是带 ``with_for_update=True`` 的 ``get``。
    加锁被挪到校验之后时，首项会变成无锁 ``get`` 或直接是 ``execute``。
    """
    from fastapi_app.core.exceptions import ConflictError

    db = _RecordingSession(
        order=SimpleNamespace(id=42, order_no='PO-20261118-0001'), has_registration=True,
    )

    with pytest.raises(ConflictError, match='存在来料登记'):
        await poc.delete_purchase_order(db, 42)

    assert db.calls[0] == ('get', 'PurchaseOrder', 42, {'with_for_update': True}), (
        f'删除必须先锁后校验（B1-05），实际 DB 动作序列：{db.calls}'
    )


async def test_delete_purchase_order_missing_row_still_takes_lock():
    """行不存在也要走带锁 get —— 否则「查到不存在」是一个陈旧读。"""
    db = _RecordingSession(order=None)

    with pytest.raises(ValueError, match='采购订单不存在'):
        await poc.delete_purchase_order(db, 7)

    assert db.calls == [('get', 'PurchaseOrder', 7, {'with_for_update': True})]


async def test_complete_purchase_order_locks_row_before_status_guard():
    """完成入口：状态闸门必须在行锁之后，且拒绝前不得有第二个 DB 动作。"""
    order = SimpleNamespace(id=42, order_no='PO-1', status='cancelled')
    db = _RecordingSession(order=order)

    with pytest.raises(ValueError, match='状态不允许完成'):
        await poc.complete_purchase_order(db, 42)

    assert db.calls == [('get', 'PurchaseOrder', 42, {'with_for_update': True})], (
        f'完成必须先锁后校验（B1-05），实际 DB 动作序列：{db.calls}'
    )


async def test_batch_complete_locks_all_rows_in_first_statement():
    """批量完成：第一条语句就必须是 FOR UPDATE 的整批取回。"""
    db = _RecordingSession()

    result = await poc.batch_complete_purchase_orders(db, [1, 2])

    assert db.calls[0][0] == 'execute', f'第一条 DB 动作必须是批量取行，实际：{db.calls[0]}'
    assert 'FOR UPDATE' in db.calls[0][1].upper(), (
        f'批量取回必须带 FOR UPDATE（B1-05），实际语句：{db.calls[0][1]}'
    )
    # 空结果下逐单失败，且不得发生任何写入（来料登记/状态改动都在锁之后）
    assert result == {'completed': 0, 'errors': ['订单1不存在', '订单2不存在']}


# ---------------------------------------------------------------------------
# B1-06：分摊残差回填（mock 驱动真实函数）
# ---------------------------------------------------------------------------
async def test_factory_summary_allocation_residual_backfilled(monkeypatch):
    """3 行各 33.33 分摊 100 后，残差 0.01 回填最后一行 → Σ == 目标值。"""
    items = [
        SimpleNamespace(id=i, quantity=Decimal('40.00'), order_id=1, loss_rate=None)
        for i in (1, 2, 3)
    ]
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = items
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_mock)

    # 后置的备品覆盖写与金额重算打桩（数量分摊另由 G5 用例覆盖金额侧）
    monkeypatch.setattr(poc, '_recalc_orders_amount', AsyncMock())
    monkeypatch.setattr(poc, '_write_spare_rate_to_orders', AsyncMock(return_value=0))

    await poc.save_factory_summary_edits(
        db, [{'item_ids': [1, 2, 3], 'quantity': 100}], order_ids=[1],
    )

    total = sum(float(it.quantity) for it in items)
    assert abs(total - 100.0) < 1e-9, (
        f'分摊后合计 {total} 必须等于目标 100（残差回填，B1-06）'
    )
    # 逐行仍是 2 位精度
    for it in items:
        assert -it.quantity.as_tuple().exponent <= 2


# ---------------------------------------------------------------------------
# G5：采购金额重算（真函数、真算术，不打桩）
# ---------------------------------------------------------------------------
async def test_recalc_orders_amount_writes_hand_computed_totals():
    """G5（2026-10-17 审计）：金额重算此前整段 AsyncMock，零断言。

    工厂汇总分摊会改采购单数量并按备品率重算金额 —— 金额写错直接影响应付账款。

    手工推导（损耗率单位＝千分之几，备品率 50‰ = 5%）：
    行 1/行 3：quantity=40.00、unit_price=12.35、loss_rate=NULL → 有效率取订单级 50‰，
        计价数量 = 40 + 40×0.05 = 42.00 → 金额 = 12.35 × 42.00 = 518.70
    行 2：loss_rate=0（显式 0 不回退订单级）→ 计价数量 40.00 → 金额 = 494.00
    合计 = 518.70 + 494.00 + 518.70 = 1531.40
    """
    items = [
        SimpleNamespace(order_id=1, quantity=Decimal('40.00'), unit_price=Decimal('12.35'),
                        loss_rate=None, total_price=None),
        SimpleNamespace(order_id=1, quantity=Decimal('40.00'), unit_price=Decimal('12.35'),
                        loss_rate=0, total_price=None),
        SimpleNamespace(order_id=1, quantity=Decimal('40.00'), unit_price=Decimal('12.35'),
                        loss_rate=None, total_price=None),
    ]
    order = SimpleNamespace(id=1, spare_rate=50, total_amount=None)

    def _result(rows):
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        return result

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_result([order]), _result(items)])

    await poc._recalc_orders_amount(db, {1})

    assert [it.total_price for it in items] == [
        Decimal('518.70'), Decimal('494.00'), Decimal('518.70'),
    ], '逐行金额必须等于（数量按有效损耗率加放）×单价 的手算值'
    assert order.total_amount == Decimal('1531.40'), '采购单总金额必须是明细之和'


# ---------------------------------------------------------------------------
# G6：库存乐观锁重试路径（真实现，不替身）
# ---------------------------------------------------------------------------
class _NestedTx:
    """记录 savepoint 生命周期的最小异步上下文管理器。"""

    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def __aenter__(self):
        self.log.append('begin_nested')
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.log.append('rollback' if exc_type else 'commit')
        return False


async def test_optimistic_lock_retries_after_version_conflict():
    """G6（2026-10-17 审计）：库存扣减的重试路径此前全被替身替换。

    手工推导：库存 100、扣 10 ⇒ 90。第一次 UPDATE 命中 0 行（version 被并发
    改写）⇒ savepoint 回滚、丢弃陈旧对象、重读后重试一次成功。
    要锁住的三个性质：①本轮 savepoint 真的回滚了（否则陈旧写会留下）；
    ②重试前 expunge 陈旧对象（否则身份映射里仍是旧 version）；
    ③库存只被扣一次（90，不是 80）。
    """
    from fastapi_app.shared import stock_concurrency as sc

    log: list[str] = []
    stale = SimpleNamespace(id=5, current_stock=100, version=1)
    fresh = SimpleNamespace(id=5, current_stock=100, version=2)
    reads = iter([stale, fresh, fresh])

    def _read_result():
        result = MagicMock()
        result.scalar_one_or_none.return_value = next(reads)
        return result

    # 首次 UPDATE 未命中（0 行）→ 冲突；重试的 UPDATE 命中（1 行）→ 成功
    miss = MagicMock(rowcount=0)
    hit = MagicMock(rowcount=1)

    db = MagicMock()
    db.begin_nested = lambda: _NestedTx(log)
    db.refresh = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _read_result(),      # 第 1 次尝试：读产品（version=1）
        miss,                # 第 1 次尝试：UPDATE 未命中
        _read_result(),      # _classify_update_miss 重读判定原因
        _read_result(),      # 第 2 次尝试：重读产品（version=2）
        hit,                 # 第 2 次尝试：UPDATE 命中
    ])

    product = await sc.update_stock_with_optimistic_lock(db, 5, -10)

    assert log == ['begin_nested', 'rollback', 'begin_nested', 'commit'], (
        f'冲突轮必须回滚 savepoint 后再重试，实际：{log}'
    )
    db.expunge.assert_called_once_with(stale)
    assert product is fresh, '重试必须返回重读后的对象，而不是陈旧对象'

    # 写入口的最终值取自真正发出的 UPDATE 语句（db.refresh 在替身里是空操作，
    # 内存对象不会回填，故不能断言 product.current_stock）。取绑定值用编译器的公开
    # 接口 compile().params，不用 `_values` 这类私有结构（升级 SQLAlchemy 会误红）。
    from sqlalchemy.dialects import postgresql

    updates = [c.args[0] for c in db.execute.await_args_list
               if getattr(c.args[0], 'is_update', False)]
    assert len(updates) == 2, f'冲突轮与重试轮各发一次 UPDATE，实际 {len(updates)} 次'
    written = updates[1].compile(dialect=postgresql.dialect()).params
    assert written['current_stock'] == 90, '库存只允许被扣一次（100-10）'
    assert written['version'] == 3, '成功写入必须把 version 递增到重读后的 old+1'
    assert written['version_1'] == 2, '重试的 WHERE 必须用重读后的旧 version（=2）'


# ---------------------------------------------------------------------------
# B1-03：生产记录结余闸门
# ---------------------------------------------------------------------------
def _production_record(**overrides):
    """_apply_production_stock 及其 InventoryLog 写入、update_record 校验会访问的字段全集。"""
    base = {
        'id': 7, 'department': 'packaging', 'product_id': 5, 'quantity': 50,
        'product_name': '产品A', 'barcode': 'B1', 'production_date': None,
        'created_by': 'tester',
        # update_record 的校验/写回路径会读这些字段（G3 行为用例需要）
        'unit_price': 1.0, 'remark': None, 'is_custom': False,
        'custom_country': None, 'batch_no': None,
        'customer_id': None, 'customer_name': None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _db_returning(record):
    """让 ``db.execute(...).scalar_one_or_none()`` 返回指定记录的假会话。"""
    result = MagicMock()
    result.scalar_one_or_none.return_value = record
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


async def test_production_negative_delta_blocked_by_balance(monkeypatch):
    """packaging 记录的负向变动：结余不足必须拒绝（B1-03）。"""
    from fastapi_app.services import daily_production_service as dps

    record = _production_record()
    product = SimpleNamespace(current_stock=500, version=1, name='产品A')
    monkeypatch.setattr(dps, 'get_product_for_update', AsyncMock(return_value=product))
    monkeypatch.setattr(dps, 'apply_stock_delta_locked', AsyncMock())
    monkeypatch.setattr(
        'fastapi_app.services.stock_inventory_service.get_inventory_balance',
        AsyncMock(return_value=30),  # 结余 30 < 减量 50
    )

    with pytest.raises(ValueError, match='结余'):
        await dps._apply_production_stock(db=AsyncMock(), record=record, delta=-50)


async def test_production_negative_delta_passes_with_balance(monkeypatch):
    """结余充足时放行，且扣减真的以 -50 落到库存写入口（不是只「不抛异常」）。

    2026-11-18 评审：原来 await 一次就结束 —— 把 apply_stock_delta_locked 改成空操作
    本条照绿。这里断言它被 await 一次且拿到 -50（-50 由 delta 手写推导）。
    """
    from fastapi_app.services import daily_production_service as dps

    record = _production_record()
    product = SimpleNamespace(current_stock=500, version=1, name='产品A')
    apply_delta = AsyncMock()
    monkeypatch.setattr(dps, 'get_product_for_update', AsyncMock(return_value=product))
    monkeypatch.setattr(dps, 'apply_stock_delta_locked', apply_delta)
    monkeypatch.setattr(
        'fastapi_app.services.stock_inventory_service.get_inventory_balance',
        AsyncMock(return_value=60),
    )

    await dps._apply_production_stock(db=AsyncMock(), record=record, delta=-50)

    assert apply_delta.await_count == 1, '放行路径必须真的走库存写入口'
    args, kwargs = apply_delta.await_args
    assert -50 in args or kwargs.get('delta') == -50, (
        f'扣减必须传 -50，实际 args={args} kwargs={kwargs}'
    )


async def test_production_non_packaging_skips_balance_gate(monkeypatch):
    """非包装部记录不进结余公式：负向变动只走 current_stock 检查。"""
    from fastapi_app.services import daily_production_service as dps

    record = _production_record(department='handcraft')
    product = SimpleNamespace(current_stock=500, version=1, name='产品A')
    monkeypatch.setattr(dps, 'get_product_for_update', AsyncMock(return_value=product))
    monkeypatch.setattr(dps, 'apply_stock_delta_locked', AsyncMock())
    balance_mock = AsyncMock(side_effect=AssertionError('非包装部不应查结余'))
    monkeypatch.setattr(
        'fastapi_app.services.stock_inventory_service.get_inventory_balance', balance_mock)

    await dps._apply_production_stock(db=AsyncMock(), record=record, delta=-50)


# ---------------------------------------------------------------------------
# B1-03 + G3：update_record 的「旧行离开包装部口径」结余闸门（行为用例）
# ---------------------------------------------------------------------------
async def test_department_move_out_blocked_by_balance(monkeypatch):
    """G3（2026-10-17 审计）：部门移出闸门此前只有源码子串断言，零行为验证。

    F3 的改坏路径：把闸门函数体换成 ``pass`` 但保留那行注释，子串仍在、用例
    照绿 —— 生产记录从「包装部」移出时不再校验结余，包装部结余（= 包装入库 −
    已出货）被多算，``/stock`` 结余列与出货准入闸门全部基于错误值。

    期望值手工推导：old_quantity=100 > balance=60 ⇒ 必须拒。
    """
    from fastapi_app.services import daily_production_service as dps

    record = _production_record(quantity=100)
    db = _db_returning(record)
    calls: list[str] = []

    async def _fake_lock(_db, pid):
        calls.append(f'lock:{pid}')
        return SimpleNamespace(id=pid)

    async def _fake_balance(_db, pid):
        calls.append(f'balance:{pid}')
        return 60

    monkeypatch.setattr(dps, 'get_product_for_update', _fake_lock)
    monkeypatch.setattr(
        'fastapi_app.services.stock_inventory_service.get_inventory_balance', _fake_balance,
    )
    sync = AsyncMock()
    monkeypatch.setattr(dps, '_sync_stock_after_update', sync)

    with pytest.raises(ValueError, match='结余'):
        await dps.update_record(db, 7, department='handcraft')

    # 顺序也要锁住：把行锁挪到「读结余」之后，这两个动作仍都会发生，只是顺序反过来 ——
    # 而 H10 要的正是「锁在结余读取之前」（与出货链同一互斥区间），只断言「锁发生过」
    # 测不出这一点（2026-11-18 评审指出的假通过）。
    assert calls == ['lock:5', 'balance:5'], (
        f'必须先锁旧产品行、再读结余（H10），实际顺序：{calls}'
    )
    sync.assert_not_awaited()


async def test_department_move_out_passes_and_carries_old_snapshot(monkeypatch):
    """结余充足时放行，且库存联动收到的是**变更前**快照（OCR-F1）。

    合并编辑（部门 + 数量同次改）时 setattr 已把 record.* 更新为新值，闸门与
    联动都必须用变更前的 old_*；拿新值比较会在旧>新时绕过闸门、旧<新时误拒。
    """
    from fastapi_app.services import daily_production_service as dps

    record = _production_record(quantity=100)
    db = _db_returning(record)
    monkeypatch.setattr(dps, 'get_product_for_update', AsyncMock(return_value=SimpleNamespace(id=5)))
    monkeypatch.setattr(
        'fastapi_app.services.stock_inventory_service.get_inventory_balance',
        AsyncMock(return_value=200),
    )
    sync = AsyncMock()
    monkeypatch.setattr(dps, '_sync_stock_after_update', sync)

    await dps.update_record(db, 7, department='handcraft')

    assert sync.await_count == 1
    kwargs = sync.await_args.kwargs
    assert kwargs['old_department'] == 'packaging'
    assert kwargs['old_product_id'] == 5
    assert kwargs['old_quantity'] == 100


async def test_same_department_quantity_edit_skips_move_out_gate(monkeypatch):
    """只改数量（部门/产品不变）不进移出闸门 —— 负向路径由 _apply_production_stock 兜。"""
    from fastapi_app.services import daily_production_service as dps

    record = _production_record(quantity=100)
    db = _db_returning(record)
    monkeypatch.setattr(
        'fastapi_app.services.stock_inventory_service.get_inventory_balance',
        AsyncMock(side_effect=AssertionError('同部门改数量不得进移出闸门')),
    )
    sync = AsyncMock()
    monkeypatch.setattr(dps, '_sync_stock_after_update', sync)

    await dps.update_record(db, 7, quantity=80)

    assert sync.await_count == 1


def test_production_rejection_maps_to_400():
    """OCR-F2（2026-10-24 推送前评审）：PUT/DELETE 的业务拒绝必须 400 带文案。

    结余闸门以 ValueError 拒绝并附用户指引；端点若不映射，异常落全局兜底
    handler 变 500，文案全丢（用户可常规触达的拒绝路径不能表现为服务器错误）。
    """
    from pathlib import Path

    endpoint_src = Path(
        'fastapi_app/api/v1/endpoints/daily_production.py').read_text(encoding='utf-8')
    put_seg = endpoint_src[endpoint_src.find("async def update_record"):]
    assert 'except ValueError as e:' in put_seg, 'PUT 必须捕获 ValueError'
    seg_400 = put_seg[put_seg.find('except ValueError as e:'):][:200]
    assert 'status_code=400' in seg_400, 'PUT 的 ValueError 必须映射 400'
    # DELETE 同理（update_record 与 delete_record 函数名同名歧义，用路由段定位）
    assert endpoint_src.count('except ValueError as e:') >= 2, 'PUT 与 DELETE 都要映射'


# ---------------------------------------------------------------------------
# B1-04：暂存预检按结余重算
# ---------------------------------------------------------------------------
async def test_recalc_stock_check_flags_insufficient_balance(monkeypatch):
    """导入后重算：qty > 结余 → stock_check_passed=False 且文案带结余。"""
    from fastapi_app.services.staging import stockout as so

    rows = [
        SimpleNamespace(id=1, quantity=100, product_id=5, is_validated=True),
        SimpleNamespace(id=2, quantity=10, product_id=5, is_validated=True),
    ]
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = rows
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_mock)
    monkeypatch.setattr(
        'fastapi_app.services.stock_inventory_service.get_inventory_balance_detail_batch',
        AsyncMock(return_value={5: (100, -30)}),  # 结余 = 100 - 30 = 70
    )

    await so._recalc_stock_check_by_balance(db, 'sess-1')

    assert rows[0].stock_check_passed is False
    assert '结余 70' in rows[0].stock_check_message and '本次 100' in rows[0].stock_check_message
    assert rows[1].stock_check_passed is True
    assert '结余充足' in rows[1].stock_check_message


async def test_staging_edit_recalc_uses_balance(monkeypatch):
    """编辑路径（_stockout_extra_updates）直接按结余口径（B1-04）。"""
    from fastapi_app.services.staging import stockout as so

    entity = SimpleNamespace(
        product_id=5, quantity=100, stock_check_passed=True,
        stock_check_message='库存充足', stockout_date=None,
    )
    product = SimpleNamespace(current_stock=500)
    db = AsyncMock()
    db.get = AsyncMock(return_value=product)
    monkeypatch.setattr(
        'fastapi_app.services.stock_inventory_service.get_inventory_balance',
        AsyncMock(return_value=70),
    )

    await so._stockout_extra_updates(entity, {'quantity': 100}, db)

    assert entity.stock_check_passed is False, '结余 70 < 100 必须翻红（B1-04）'
    assert '结余 70' in entity.stock_check_message
