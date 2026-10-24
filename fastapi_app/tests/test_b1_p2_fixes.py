"""B1 分区 P2 批次（2026-10-24 审计）回归锁：
- B1-03 生产记录负向变动/移出包装部的结余闸门；
- B1-04 暂存出货预检按结余口径重算（导入后 + 编辑路径）；
- B1-05 采购单 delete/complete/batch-complete 三入口行锁；
- B1-06 工厂汇总分摊的残差回填（Σ分摊 == 目标数量）；
- B1-07 退货产品搜索 ilike（PG like 大小写敏感）。
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services import purchase_order_crud as poc


# ---------------------------------------------------------------------------
# B1-05：三入口行锁（接线断言）
# ---------------------------------------------------------------------------
def test_delete_and_complete_wire_row_locks():
    import inspect

    for fn_name in ('delete_purchase_order', 'complete_purchase_order'):
        src = inspect.getsource(getattr(poc, fn_name))
        assert 'with_for_update=True' in src, f'{fn_name} 必须先锁后校验（B1-05）'


def test_batch_complete_wires_row_locks():
    import inspect

    src = inspect.getsource(poc.batch_complete_purchase_orders)
    assert '.with_for_update()' in src, '批量完成必须逐单 FOR UPDATE（B1-05）'


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

    # 后置的备品覆盖写与金额重算打桩（本测试只关心数量分摊）
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
# B1-03：生产记录结余闸门
# ---------------------------------------------------------------------------
def _production_record(**overrides):
    """_apply_production_stock 及其 InventoryLog 写入会访问的字段全集。"""
    base = {
        'id': 7, 'department': 'packaging', 'product_id': 5, 'quantity': 50,
        'product_name': '产品A', 'barcode': 'B1', 'production_date': None,
        'created_by': 'tester',
    }
    base.update(overrides)
    return SimpleNamespace(**base)


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
    """结余充足时放行（净减量 ≤ 结余）。"""
    from fastapi_app.services import daily_production_service as dps

    record = _production_record()
    product = SimpleNamespace(current_stock=500, version=1, name='产品A')
    monkeypatch.setattr(dps, 'get_product_for_update', AsyncMock(return_value=product))
    monkeypatch.setattr(dps, 'apply_stock_delta_locked', AsyncMock())
    monkeypatch.setattr(
        'fastapi_app.services.stock_inventory_service.get_inventory_balance',
        AsyncMock(return_value=60),
    )

    await dps._apply_production_stock(db=AsyncMock(), record=record, delta=-50)


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


def test_department_move_out_guard_wired():
    """B1-03：update_record 必须含「旧行离开包装部口径」的结余守卫。

    OCR-F1（2026-10-24 推送前评审）：闸门基准必须是变更前的 old_product_id/
    old_quantity——合并编辑（部门+数量同次改）时 setattr 已把 record.* 更新为
    新值，拿新值比较会在旧>新时绕过闸门、旧<新时误拒。
    """
    import inspect

    from fastapi_app.services import daily_production_service as dps

    src = inspect.getsource(dps.update_record)
    assert 'old_department' in src, '必须捕获变更前的部门'
    gate = src[src.find('old_department == \'packaging\''):] if 'old_department' in src else ''
    assert gate, '必须有包装部口径移出闸门'
    assert 'old_quantity > balance' in gate, (
        '闸门比较必须用 old_quantity（OCR-F1：合并编辑下 record.quantity 已是新值）'
    )
    assert 'get_inventory_balance(db, old_product_id)' in gate, (
        '部门移出+换产品同次编辑时，结余必须查旧产品（包装部合计减少发生在旧产品）'
    )
    assert '结余' in gate


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
        'fastapi_app.services.stock_inventory_service.get_inventory_balance',
        AsyncMock(return_value=70),
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
