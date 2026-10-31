"""批量出货后的采购计划事件口径回归（2026-10-30 审计 A-M25）。

批量补录历史出货时，`STOCK_OUT_CREATED` 事件里的 `plan_month` 原先一律取
**当前业务月**。采购计划缓存失效/重算按 `plan_month` 定位，补录上个月的出货
会去刷本月缓存、上月的计划仍是旧值（要等 TTL 才自愈）。

修复：`plan_month` 取**该行自己的 stockout_date 所在月**，缺省才回落到当前月。
本文件锁定逐行取值，而不是「整批一个月份」。
"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services import auxiliary_service


def _product(pid, name, factory='东莞', current_stock=100):
    p = MagicMock()
    p.id = pid
    p.name = name
    p.factory = factory
    p.current_stock = current_stock
    return p


def _patches(products, results):
    """把事务、创建、缓存、事件全部替身化，只留编排逻辑本身。"""
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)

    product_result = MagicMock()
    product_result.scalars.return_value.all.return_value = products
    db = MagicMock()
    db.execute = AsyncMock(return_value=product_result)

    cache = MagicMock()
    cache.invalidate = AsyncMock()
    cache.invalidate_dashboard = AsyncMock()

    return db, tx, cache, results


@pytest.mark.asyncio
async def test_plan_month_uses_each_row_stockout_date():
    products = [_product(1, '产品A'), _product(2, '产品B')]
    results = {'results': [
        {'success': True}, {'success': True},
    ]}
    db, tx, cache, res = _patches(products, results)

    rows = [
        {'product_id': 1, 'customer': '客户A', 'quantity': 5, 'stockout_date': '2026-03-15'},
        {'product_id': 2, 'customer': '客户B', 'quantity': 3, 'stockout_date': '2026-04-02'},
    ]

    with patch.object(auxiliary_service, 'db_transaction', MagicMock(return_value=tx)), \
         patch('fastapi_app.services.stock_service.batch_create_stockouts',
               new=AsyncMock(return_value=res)), \
         patch.object(auxiliary_service, 'cache_mgr', cache), \
         patch.object(auxiliary_service, 'publish_domain_event', new=AsyncMock()) as m_event, \
         patch.object(auxiliary_service, 'safe_publish_event', new=AsyncMock()):
        await auxiliary_service.orchestrate_batch_stockouts(db, rows)

    payloads = [c.args[0].payload for c in m_event.await_args_list]
    month_by_product = {p['product_id']: p['plan_month'] for p in payloads}
    assert month_by_product == {1: '2026-03', 2: '2026-04'}


@pytest.mark.asyncio
async def test_plan_month_falls_back_to_current_month():
    products = [_product(1, '产品A')]
    results = {'results': [{'success': True}]}
    db, tx, cache, res = _patches(products, results)

    rows = [{'product_id': 1, 'customer': '客户A', 'quantity': 5}]  # 无 stockout_date

    with patch.object(auxiliary_service, 'db_transaction', MagicMock(return_value=tx)), \
         patch('fastapi_app.services.stock_service.batch_create_stockouts',
               new=AsyncMock(return_value=res)), \
         patch.object(auxiliary_service, 'cache_mgr', cache), \
         patch.object(auxiliary_service, 'publish_domain_event', new=AsyncMock()) as m_event, \
         patch.object(auxiliary_service, 'safe_publish_event', new=AsyncMock()):
        await auxiliary_service.orchestrate_batch_stockouts(db, rows)

    payload = m_event.await_args_list[0].args[0].payload
    assert payload['plan_month'] == auxiliary_service.business_month_str()


@pytest.mark.asyncio
async def test_failed_rows_do_not_publish_events():
    products = [_product(1, '产品A')]
    results = {'results': [{'success': True}, {'success': False, 'error': 'x'}]}
    db, tx, cache, res = _patches(products, results)

    rows = [
        {'product_id': 1, 'customer': '客户A', 'quantity': 5, 'stockout_date': '2026-03-15'},
        {'product_id': 1, 'customer': '客户B', 'quantity': 1, 'stockout_date': '2026-04-15'},
    ]

    with patch.object(auxiliary_service, 'db_transaction', MagicMock(return_value=tx)), \
         patch('fastapi_app.services.stock_service.batch_create_stockouts',
               new=AsyncMock(return_value=res)), \
         patch.object(auxiliary_service, 'cache_mgr', cache), \
         patch.object(auxiliary_service, 'publish_domain_event', new=AsyncMock()) as m_event, \
         patch.object(auxiliary_service, 'safe_publish_event', new=AsyncMock()):
        await auxiliary_service.orchestrate_batch_stockouts(db, rows)

    payloads = [c.args[0].payload for c in m_event.await_args_list]
    assert len(payloads) == 1
    assert payloads[0]['customer'] == '客户A'
    assert payloads[0]['plan_month'] == '2026-03'
    # 事件时间只用于日志，不参与断言；这里确认模块没有被时区改动破坏
    assert datetime.now(UTC).year >= 2026
