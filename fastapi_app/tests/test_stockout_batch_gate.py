"""出货批次级闸门测试（mock，不依赖真库）

覆盖 _process_single_stockout 的批次分支：
- 指定批次且充足 → 放行，batch_no 落到 stock_out
- 指定批次不足 → 拦截（提示含批次号与可用量）
- 批次不足但产品级结余充足 → 仍拦截（批次是硬约束）
- 不传 batch_no → 走原路径（向后兼容）
"""
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi_app.services import stock_service


def _make_product(pid=1, name='产品A', current_stock=10**6):
    p = MagicMock()
    p.id = pid
    p.name = name
    p.current_stock = current_stock
    return p


def _shipment(available=1000):
    return {
        'available_quantity': available,
        'order_quantity': available,
        'shipped_quantity': 0,
        'orders': [{'order_id': 1, 'available': available, 'quantity': available}],
    }


def _item(quantity, batch_no=None):
    d = {'product_id': 1, 'customer': '客户A', 'quantity': quantity, 'note': '', 'id': 'x1'}
    if batch_no is not None:
        d['batch_no'] = batch_no
    return d


async def _run(mock_db, item, *, batch_available=0):
    """跑单条出库，patch 掉行锁/闸门/批次可用/乐观锁，返回结果。"""
    with patch('fastapi_app.services.stock_service.get_product_for_update',
               new_callable=AsyncMock, return_value=_make_product()), \
         patch('fastapi_app.services.stock_service.get_inventory_balance',
               new_callable=AsyncMock, return_value=10**9), \
         patch('fastapi_app.services.stock_service.calculate_available_shipment_quantity',
               new_callable=AsyncMock, return_value=_shipment()), \
         patch('fastapi_app.services.stock_service.generate_stockout_number',
               new_callable=AsyncMock, return_value='SO-TEST-0001'), \
         patch('fastapi_app.services.finished_stock_service.get_batch_available',
               new_callable=AsyncMock, return_value=batch_available), \
         patch('fastapi_app.services.stock_out_service.apply_stock_delta_locked',
               new_callable=AsyncMock, return_value=_make_product()), \
         patch('fastapi_app.services.stock_service.log_inventory_change'):
        return await stock_service.batch_create_stockouts(mock_db, [item])


async def test_batch_sufficient_passes(mock_db):
    r = await _run(mock_db, _item(50, 'B1'), batch_available=100)
    assert r['results'][0]['success'] is True


async def test_batch_insufficient_blocked(mock_db):
    r = await _run(mock_db, _item(150, 'B1'), batch_available=100)
    res = r['results'][0]
    assert res['success'] is False
    assert 'B1' in res['error'] and '100' in res['error']


async def test_batch_insufficient_blocks_even_if_product_level_ok(mock_db):
    # 产品级结余被 patch 成 10^9（充足），批次只有 10 → 仍拦截
    r = await _run(mock_db, _item(999, 'B2'), batch_available=10)
    assert r['results'][0]['success'] is False


async def test_no_batch_backward_compatible(mock_db):
    # 不传 batch_no → 不查批次，走原路径放行
    r = await _run(mock_db, _item(50), batch_available=0)
    assert r['results'][0]['success'] is True
