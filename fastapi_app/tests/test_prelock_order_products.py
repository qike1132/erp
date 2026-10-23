"""P1-03 回归：整单预锁集合必须包含 OrderItem 产品，并按 id 升序加锁；
编辑审批必须先预锁产品、再锁 Order（P→O），不能反序。
"""
from unittest.mock import AsyncMock, MagicMock

from fastapi_app.services import approval_service
from fastapi_app.services.order import commands
from fastapi_app.shared_models import ApprovalRequest


async def test_prelock_includes_order_items_and_sorts_ascending():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        MagicMock(scalar_one_or_none=MagicMock(return_value=91)),          # order.product_id
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[7])))),   # stock_out
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[42])))),  # order_item
    ])
    locked: list[int] = []

    async def _fake_lock(_db, pid):
        locked.append(pid)

    original = commands.get_product_for_update
    commands.get_product_for_update = _fake_lock
    try:
        await commands._prelock_order_products(db, 7)
    finally:
        commands.get_product_for_update = original

    assert locked == [7, 42, 91]


async def test_approve_edit_prelocks_products_before_order_lock(monkeypatch):
    approval = MagicMock()
    approval.order_id = 7
    approval.requester_id = 2
    approval.status = ApprovalRequest.STATUS_PENDING
    approval.operation_type = ApprovalRequest.OPERATION_EDIT
    approval.operation_type_display = '编辑订单'
    order = MagicMock()
    order.id = 7
    order.is_deleted = False
    order.order_no = 'ORD-7'

    events: list[str] = []

    async def _fake_prelock(_db, _order_id):
        events.append('prelock')

    async def _fake_handler(_db, _approval, _order, _user):
        events.append('handler')

    monkeypatch.setattr(approval_service, '_get_pending_approval', AsyncMock(return_value=approval))
    monkeypatch.setattr(approval_service, '_validate_not_self_approval', lambda *a: None)
    monkeypatch.setattr(approval_service, '_OPERATION_HANDLERS',
                        {ApprovalRequest.OPERATION_EDIT: _fake_handler})
    monkeypatch.setattr(approval_service, '_create_approval_log', AsyncMock())
    monkeypatch.setattr(commands, '_prelock_order_products', _fake_prelock)

    db = AsyncMock()
    db.get = AsyncMock(return_value=order)

    async def _execute(_stmt):
        events.append('lock_order')
        return MagicMock(scalar_one=MagicMock(return_value=order))

    db.execute = _execute
    db.flush = AsyncMock()

    await approval_service.approve_request(db, 1, MagicMock(id=1))

    assert events == ['prelock', 'lock_order', 'handler']
