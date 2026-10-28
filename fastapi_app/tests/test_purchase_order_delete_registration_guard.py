"""删除有来料登记的采购单必须返回 409，而不是 IntegrityError → 500（审计 P1-4）。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError

from fastapi_app.core.exceptions import ConflictError
from fastapi_app.services.purchase_bom_copy_service import batch_delete_purchase_orders
from fastapi_app.services.purchase_order_crud import delete_purchase_order


class _One:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _Scalars:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Scalar:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


def _order(order_id: int, order_no: str):
    return SimpleNamespace(id=order_id, order_no=order_no, supplier_name='', customer_name='')


def _fake_db() -> AsyncMock:
    db = AsyncMock()
    db.get = AsyncMock()
    db.execute = AsyncMock()
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    return db


async def test_single_delete_with_registration_raises_conflict() -> None:
    db = _fake_db()
    db.get.return_value = _order(7, 'PO-7')
    db.execute.side_effect = [_One(99), object(), object()]

    with pytest.raises(ConflictError, match='存在来料登记'):
        await delete_purchase_order(db, 7)

    assert db.execute.await_count == 1, '命中登记后不得继续删除明细'
    db.delete.assert_not_awaited()


async def test_single_delete_without_registration_succeeds() -> None:
    db = _fake_db()
    db.get.return_value = _order(7, 'PO-7')
    db.execute.side_effect = [_One(None), object(), object()]

    result = await delete_purchase_order(db, 7)

    assert result == {'id': 7, 'order_no': 'PO-7'}
    assert db.delete.await_count == 1
    assert db.flush.await_count == 1


async def test_single_delete_translates_integrity_error_to_conflict() -> None:
    db = _fake_db()
    db.get.return_value = _order(7, 'PO-7')
    db.execute.side_effect = [_One(None), IntegrityError('DELETE', {}, Exception('fk'))]

    with pytest.raises(ConflictError, match='引用'):
        await delete_purchase_order(db, 7)


async def test_batch_delete_with_registration_rejects_whole_batch() -> None:
    db = _fake_db()
    db.execute.side_effect = [
        _Scalars([_order(1, 'PO-1'), _order(2, 'PO-2')]),
        _Rows([SimpleNamespace(purchase_order_id=1, purchase_order_no='PO-1')]),
        _Scalar(0),
        _Scalar(0),
    ]

    with pytest.raises(ConflictError, match='PO-1'):
        await batch_delete_purchase_orders(db, [1, 2])

    db.delete.assert_not_awaited()


async def test_batch_delete_without_registration_succeeds() -> None:
    db = _fake_db()
    db.execute.side_effect = [
        _Scalars([_order(1, 'PO-1'), _order(2, 'PO-2')]),
        _Rows([]),
        _Rows([(1, 2), (2, 3)]),
    ]

    result = await batch_delete_purchase_orders(db, [1, 2])

    assert result['deleted_count'] == 2
    assert db.execute.await_count == 3, '明细计数必须一次 GROUP BY，不得逐单查询'
    assert db.delete.await_count == 2
    assert db.flush.await_count == 1


async def test_batch_delete_translates_integrity_error_to_conflict() -> None:
    db = _fake_db()
    db.execute.side_effect = [
        _Scalars([_order(1, 'PO-1')]),
        _Rows([]),
        _Rows([(1, 0)]),
    ]
    db.flush.side_effect = IntegrityError('DELETE', {}, Exception('fk'))

    with pytest.raises(ConflictError, match='引用'):
        await batch_delete_purchase_orders(db, [1])
