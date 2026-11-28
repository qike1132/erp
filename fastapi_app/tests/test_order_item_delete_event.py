"""末项删除订单明细 = 整单删除时，必须发布 ORDER_DELETED 领域事件。

背景（2026-10-13 生产事故）：报表页删除订单明细走 `DELETE /orders/items/{id}`；
末项删除会转成整单软删，但该端点没发 ORDER_DELETED，采购中心订阅不到，
两条已自动生成的 pending 采购单（PO-20261013-23761/23763）残留在 /purchase。

本文件锁两件事：
1. 末项删除（整单真删）→ 发 ORDER_DELETED，payload 带 order_id；
2. service 在末项分支回传 order_id，供端点层发布使用。
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi_app.core.domain_events import DomainEventType
from fastapi_app.services.order import commands as order_commands


async def test_delete_last_item_publishes_order_deleted(client, mock_db):
    """末项删除 → 端点必须发布 ORDER_DELETED，采购中心才能撤回 pending 采购单。"""
    publish = AsyncMock()

    async def _fake_delete_order_item(db, item_id, user):
        return {
            'success': True,
            'message': '订单删除成功！',
            'order_id': 92706,
        }

    with patch(
        'fastapi_app.api.v1.endpoints.order.order_service.delete_order_item',
        new=AsyncMock(side_effect=_fake_delete_order_item),
    ), patch(
        'fastapi_app.api.v1.endpoints.order.publish_domain_event', new=publish,
    ):
        response = await client.delete('/api/v1/orders/items/27946')

    assert response.status_code == 200
    publish.assert_awaited_once()
    event = publish.await_args.args[0]
    assert event.event_type == DomainEventType.ORDER_DELETED
    assert event.payload == {'order_id': 92706}


async def test_last_item_delete_service_returns_order_id(mock_db, monkeypatch):
    """service 末项分支必须把 order_id 透出，否则端点拿不到要撤销的订单。"""
    head = SimpleNamespace(order_id=7, product_id=None, order_product_id=None)
    order = SimpleNamespace(id=7, is_deleted=False)

    # 2026-10-19 OCR 第三轮 H2 对齐 M4 重构后的 db.execute 调用序列——
    # ① one_or_none 取明细 head；随后 _prelock_order_products 预锁段：
    # ② select(Order.product_id) 无锁预读（None → 不入锁集合）、
    # ③ select(StockOut.product_id).distinct() 出库产品集（空；head.
    # product_id=None 同样过滤）——两者皆空故无 get_product_for_update；
    # ④ select(Order).with_for_update() 订单行；⑤ 备货抵扣 SUM、
    # ⑥ 兄弟明细 COUNT（=1 → 走末项分支，delete_order 已被替换）。
    head_result = MagicMock()
    head_result.one_or_none.return_value = head
    order_pid_result = MagicMock()
    order_pid_result.scalar_one_or_none.return_value = None
    stockout_pids_result = MagicMock()
    stockout_pids_result.scalars.return_value.all.return_value = []
    item_pids_result = MagicMock()
    item_pids_result.scalars.return_value.all.return_value = []
    order_result = MagicMock()
    order_result.scalar_one_or_none.return_value = order
    deducted_result = MagicMock()
    deducted_result.scalar_one.return_value = 0
    siblings_result = MagicMock()
    siblings_result.scalar_one.return_value = 1

    mock_db.execute = AsyncMock(
        side_effect=[head_result, order_pid_result, stockout_pids_result,
                     item_pids_result, order_result, deducted_result, siblings_result]
    )

    captured: dict = {}

    async def _fake_delete_order(db, order_id, user):
        captured['order_id'] = order_id
        return {'success': True, 'message': '订单删除成功！'}

    monkeypatch.setattr(order_commands, 'delete_order', _fake_delete_order)

    result = await order_commands.delete_order_item(mock_db, 27946, MagicMock())

    assert captured['order_id'] == 7
    assert result['order_id'] == 7
