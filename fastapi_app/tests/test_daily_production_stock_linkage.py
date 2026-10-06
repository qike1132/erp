"""生产即入库 - 库存联动测试（2026-10-06 用户裁决）

覆盖 daily_production_service._apply_production_stock 在三条写路径上的行为：
- 创建：product 匹配 → current_stock 增加 + InventoryLog('生产入库')
- 创建：product_id 为空 → 不产生任何库存变化（与 /stock 口径一致）
- 更新：同产品差额调整；换产品旧退新进
- 删除：current_stock 回退；库存不足按全仓负库存政策拦截
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.daily_production_service import (
    create_record,
    delete_record,
    update_record,
)


def _record(rid=7, department='filling', product_id=11, quantity=100):
    record = MagicMock()
    record.id = rid
    record.department = department
    record.product_id = product_id
    record.product_name = '网易 鲨鱼'
    record.barcode = 'BC11'
    record.quantity = quantity
    record.unit_price = 7
    record.production_date = date(2026, 10, 6)
    record.created_by = '张三'
    record.remark = None
    return record


def _product(pid=11, current_stock=0):
    product = MagicMock()
    product.id = pid
    product.name = '网易 鲨鱼'
    product.current_stock = current_stock
    return product


def _db_with_record(record):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = record
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_create_increases_stock_and_writes_log():
    db = _db_with_record(None)
    product = _product(current_stock=0)
    with patch('fastapi_app.services.daily_production_service.get_product_for_update',
               new_callable=AsyncMock, return_value=product):
        await create_record(
            db, department='filling', product_id=11, product_name='网易 鲨鱼',
            barcode='BC11', unit_price=7, quantity=8888,
            production_date_str='2026-10-06', created_by='张三',
        )
    assert product.current_stock == 8888
    log = db.add.call_args_list[-1].args[0]
    assert log.change_type == '生产入库'
    assert log.change_quantity == 8888
    assert log.related_id is not None


@pytest.mark.asyncio
async def test_create_without_product_id_skips_stock():
    db = _db_with_record(None)
    with patch('fastapi_app.services.daily_production_service.get_product_for_update',
               new_callable=AsyncMock) as mock_get:
        record = await create_record(
            db, department='filling', product_id=None, product_name='未匹配产品',
            barcode='', unit_price=7, quantity=100,
            production_date_str='2026-10-06', created_by='张三',
        )
    mock_get.assert_not_awaited()
    stock_adds = [c for c in db.add.call_args_list if isinstance(c.args[0], MagicMock) and hasattr(c.args[0], 'current_stock')]
    assert not stock_adds  # 无产品可加
    assert record.quantity == 100


@pytest.mark.asyncio
async def test_update_same_product_applies_delta():
    record = _record(quantity=100)
    product = _product(current_stock=100)
    db = _db_with_record(record)
    with patch('fastapi_app.services.daily_production_service.get_product_for_update',
               new_callable=AsyncMock, return_value=product):
        await update_record(db, 7, quantity=80, created_by='张三')
    assert product.current_stock == 80  # 100 - 20
    log = db.add.call_args_list[-1].args[0]
    assert log.change_quantity == -20
    assert log.change_type == '生产入库冲销'


@pytest.mark.asyncio
async def test_update_product_change_rolls_back_old_applies_new():
    record = _record(product_id=11, quantity=100)
    old_product = _product(pid=11, current_stock=100)
    new_product = _product(pid=12, current_stock=0)
    db = _db_with_record(record)

    async def _get_product(db_, pid):
        return old_product if pid == 11 else new_product

    with patch('fastapi_app.services.daily_production_service.get_product_for_update',
               side_effect=_get_product):
        await update_record(db, 7, product_id=12, quantity=60, created_by='张三')
    assert old_product.current_stock == 0    # 回退 100
    assert new_product.current_stock == 60   # 全额入账


@pytest.mark.asyncio
async def test_delete_decreases_stock():
    record = _record(quantity=100)
    product = _product(current_stock=100)
    db = _db_with_record(record)
    with patch('fastapi_app.services.daily_production_service.get_product_for_update',
               new_callable=AsyncMock, return_value=product):
        await delete_record(db, 7, operator='李四')
    assert product.current_stock == 0
    db.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_blocked_when_stock_already_shipped():
    """已出库消耗掉的数量不允许通过删生产记录洗成负库存（全仓负库存政策）"""
    record = _record(quantity=100)
    product = _product(current_stock=30)  # 已出货 70
    db = _db_with_record(record)
    with patch('fastapi_app.services.daily_production_service.get_product_for_update',
               new_callable=AsyncMock, return_value=product):
        with pytest.raises(Exception, match='库存为负数'):
            await delete_record(db, 7, operator='李四')
    db.delete.assert_not_awaited()
    assert product.current_stock == 30  # 未被扣减
