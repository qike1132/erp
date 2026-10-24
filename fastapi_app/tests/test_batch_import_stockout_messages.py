"""P1-02 回归：综合导入（core 路径）出货失败必须给出原因。

原实现产品不存在/客户为空/库存不足/无可出货订单/超量时静默 `return False`，
用户只看到「跳过 N 行」不知原因。本文件锁住行级错误消息与多命中识别。
"""
from unittest.mock import AsyncMock, MagicMock

from fastapi_app.services import batch_import_core
from fastapi_app.services.batch_import_core import ImportDeps


class _Nested:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


def _db(products=None):
    db = AsyncMock()
    db.begin_nested = MagicMock(return_value=_Nested())
    result = MagicMock()
    result.scalars.return_value.all.return_value = products or []
    db.execute = AsyncMock(return_value=result)
    return db


def _product(pid: int = 1):
    product = MagicMock()
    product.id = pid
    product.name = f'产品{pid}'
    product.current_stock = 100
    product.factory = ''
    return product


async def test_unknown_product_reports_reason():
    row = {'产品名称': '不存在的产品', '数量': 1, '客户名称': '客户A'}
    count, messages = await batch_import_core.import_stockouts_from_data(_db([]), [row])
    assert count == 0
    assert any('不存在' in m for m in messages)


async def test_ambiguous_product_reports_reason():
    """barcode 无唯一约束：多命中必须拒绝，不能静默取任意一条。"""
    row = {'产品名称': '重复条码', '数量': 1, '客户名称': '客户A'}
    count, messages = await batch_import_core.import_stockouts_from_data(
        _db([_product(1), _product(2)]), [row])
    assert count == 0
    assert any('命中多条' in m for m in messages)


async def test_no_available_order_reports_reason(monkeypatch):
    # AUD-01 结余闸门位于订单余量校验之前；本用例聚焦订单余量文案，
    # 桩掉结余查询（mock db 无法执行结余 SQL）。
    from fastapi_app.services import stock_out_service
    monkeypatch.setattr(stock_out_service, '_assert_inventory_balance', AsyncMock())
    deps = ImportDeps(
        calculate_available_shipment_quantity=AsyncMock(return_value={
            'available_quantity': 0, 'order_quantity': 0,
            'shipped_quantity': 0, 'orders': [],
        }),
    )
    row = {'产品名称': '产品A', '数量': 1, '客户名称': '客户A'}
    count, messages = await batch_import_core.import_stockouts_from_data(
        _db([_product()]), [row], deps=deps)
    assert count == 0
    assert any('没有可用的订单支持出货' in m for m in messages)


async def test_missing_customer_reports_reason():
    row = {'产品名称': '产品A', '数量': 1, '客户名称': ''}
    count, messages = await batch_import_core.import_stockouts_from_data(_db(), [row])
    assert count == 0
    assert any('出货必须选择客户' in m for m in messages)
