"""暂存出货库存预检回归测试（2026-10-17 审计 AUD-04）

缺陷：Excel 导入只要产品匹配就硬编码 stock_check_passed=True /「库存充足」，
编辑数量后预检不刷新——用户在确认弹窗里基于假信号拍板。OCR 路径则真查库存。

本测试不连库：产品映射与 Excel 解析均用替身。
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi_app.services.staging import _generic as staging_generic
from fastapi_app.services.staging import stockout as staging_stockout

SESSION_ID = 'audit-aud04'
XLSX_MAGIC = b'PK\x03\x04stub'


def _patch_excel(monkeypatch, rows):
    monkeypatch.setattr(
        staging_generic, 'read_excel_sheets_async', AsyncMock(return_value=(True, ['出货管理'], ''))
    )
    monkeypatch.setattr(
        staging_generic, 'parse_excel_file_async', AsyncMock(return_value=(True, rows, ''))
    )


def _fake_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


async def _import_stockout(monkeypatch, db, current_stock, qty=10):
    _patch_excel(monkeypatch, [{'产品名称': '产品A', '出货数量': qty}])
    product = SimpleNamespace(id=1, name='产品A', current_stock=current_stock)
    monkeypatch.setattr(
        staging_generic, '_build_product_map', AsyncMock(return_value={'产品A': product})
    )
    monkeypatch.setattr(staging_stockout, 'clear_staging_stockouts_by_session', AsyncMock(return_value=0))
    imported, _message, errors = await staging_stockout.import_staging_stockouts_from_excel(
        db, XLSX_MAGIC, SESSION_ID
    )
    assert errors == []
    assert imported == 1
    entity = db.add.call_args.args[0]
    return entity


class TestExcelImportPrecheck:
    async def test_insufficient_stock_is_flagged(self, monkeypatch):
        """库存 0 导入 10 → 预检必须失败并给出库存不足文案"""
        entity = await _import_stockout(monkeypatch, _fake_db(), current_stock=0, qty=10)

        assert entity.stock_check_passed is False
        assert entity.stock_check_message != '库存充足'
        assert '库存' in entity.stock_check_message

    async def test_sufficient_stock_passes(self, monkeypatch):
        entity = await _import_stockout(monkeypatch, _fake_db(), current_stock=100, qty=10)

        assert entity.stock_check_passed is True
        assert entity.stock_check_message == '库存充足'


class TestEditPrecheck:
    async def test_edit_quantity_recomputes_precheck(self):
        """编辑数量后预检必须重算（此前是 pass 空实现）"""
        entity = SimpleNamespace(
            product_id=1, quantity=130,
            stock_check_passed=True, stock_check_message='库存充足',
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=SimpleNamespace(id=1, current_stock=100))

        await staging_stockout._stockout_extra_updates(entity, {'quantity': 130}, db)

        assert entity.stock_check_passed is False
        assert entity.stock_check_message != '库存充足'

    async def test_edit_with_enough_stock_stays_passed(self):
        entity = SimpleNamespace(
            product_id=1, quantity=5,
            stock_check_passed=False, stock_check_message='库存不足',
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=SimpleNamespace(id=1, current_stock=100))

        await staging_stockout._stockout_extra_updates(entity, {'quantity': 5}, db)

        assert entity.stock_check_passed is True
        assert entity.stock_check_message == '库存充足'

    async def test_edit_to_unknown_product_invalidates_precheck(self):
        """改成匹配不到的产品名后，预检必须作废（2026-10-18 OCR 评审）。

        `_generic_update_staging_entity` 遇到未知产品名会把 product_id 置 None、
        is_validated 置 False；本 hook 若只按「product_id 非空」分支重算，
        上一轮导入留下的 stock_check_passed=True 会残留 —— 确认弹窗据此放行，
        且 confirm_staging_stockouts 的筛选条件含 stock_check_passed IS TRUE，
        这行会被选中再在确认阶段才被拒（用户看到两轮错误）。
        """
        entity = SimpleNamespace(
            product_id=None, quantity=10, is_validated=False,
            stock_check_passed=True, stock_check_message='库存充足',
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        await staging_stockout._stockout_extra_updates(
            entity, {'product_name': '不存在的产品', 'quantity': 10}, db
        )

        assert entity.stock_check_passed is False
        assert entity.stock_check_message == ''
