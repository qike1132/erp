"""报表流水行内操作（出货 / 备货抵扣 / 退货）新增能力的单元测试（2026-10-07）。

覆盖：
- 行内操作权限裁决 `_ensure_row_action_permission`（出货/抵扣各自独立，manage 兜底）
- 聚合行还原读取 `get_stockout_records` / `get_stockreturn_records`（单号过滤 + 映射）
- 退货原子编辑 `edit_stockreturn`（取消 + 重建；非 active / 无关联出货 / 不存在 的拒绝）
- NO_MANAGE_INHERIT 四眼原则：持 report_manage 不得经子权限继承获得新码
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from fastapi_app.api.v1.endpoints.stock import _ensure_row_action_permission
from fastapi_app.services.stock_inventory_service import (
    _parse_nos,
    get_stockout_records,
    get_stockreturn_records,
)
from fastapi_app.services.stock_return_service import edit_stockreturn


class _User:
    """最小 User 替身：只实现 has_permission。"""

    def __init__(self, *perms: str):
        self._perms = set(perms)

    def has_permission(self, code: str) -> bool:
        return code in self._perms


def _rows_result(rows: list):
    """构造 db.execute(...).scalars().unique().all() 的返回值。"""
    result = MagicMock()
    result.scalars.return_value.unique.return_value.all.return_value = rows
    return result


def _one_result(obj):
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    return result


# ---------------------------------------------------------------------------
# 权限裁决
# ---------------------------------------------------------------------------
class TestRowActionPermission:
    def test_manage_allows_both(self):
        user = _User('stockout_manage')
        _ensure_row_action_permission(user, is_deduction=False, action='edit')
        _ensure_row_action_permission(user, is_deduction=True, action='delete')

    def test_stockout_codes_only_apply_to_stockout_rows(self):
        user = _User('stockout_edit', 'stockout_delete')
        _ensure_row_action_permission(user, is_deduction=False, action='edit')
        _ensure_row_action_permission(user, is_deduction=False, action='delete')
        with pytest.raises(HTTPException) as ei:
            _ensure_row_action_permission(user, is_deduction=True, action='edit')
        assert ei.value.status_code == 403

    def test_deduction_codes_only_apply_to_deduction_rows(self):
        user = _User('deduction_edit', 'deduction_delete')
        _ensure_row_action_permission(user, is_deduction=True, action='edit')
        _ensure_row_action_permission(user, is_deduction=True, action='delete')
        with pytest.raises(HTTPException):
            _ensure_row_action_permission(user, is_deduction=False, action='edit')

    def test_edit_code_does_not_grant_delete(self):
        user = _User('stockout_edit')
        with pytest.raises(HTTPException):
            _ensure_row_action_permission(user, is_deduction=False, action='delete')

    def test_no_permission_fails_closed(self):
        with pytest.raises(HTTPException) as ei:
            _ensure_row_action_permission(_User(), is_deduction=False, action='edit')
        assert ei.value.status_code == 403


# ---------------------------------------------------------------------------
# 还原读取
# ---------------------------------------------------------------------------
class TestStockoutRecords:
    async def test_empty_nos_returns_empty_without_query(self, mock_db):
        assert await get_stockout_records(mock_db, kind='stockout', nos='  ,  ') == []
        mock_db.execute.assert_not_awaited()

    async def test_stockout_kind_filters_independent_only(self, mock_db):
        so = MagicMock()
        so.id = 1
        so.stockout_no = 'SO-1'
        so.stockout_date = None
        so.customer = '客户A'
        so.product_id = 3
        so.product = None
        so.quantity = 10
        so.returned_quantity = 2
        so.note = '备注'
        so.stockin_id = None
        so.order_id = 7
        mock_db.execute = AsyncMock(return_value=_rows_result([so]))

        rows = await get_stockout_records(mock_db, kind='stockout', nos='SO-1,SO-2')

        stmt = str(mock_db.execute.await_args.args[0])
        assert 'stockin_id IS NULL' in stmt
        assert rows[0]['stockout_no'] == 'SO-1'
        assert rows[0]['quantity'] == 10
        assert rows[0]['returned_quantity'] == 2
        assert rows[0]['stockin_id'] is None

    async def test_deduction_kind_filters_linked_only(self, mock_db):
        mock_db.execute = AsyncMock(return_value=_rows_result([]))
        await get_stockout_records(mock_db, kind='deduction', nos='PO-1')
        stmt = str(mock_db.execute.await_args.args[0])
        assert 'stockin_id IS NOT NULL' in stmt
        assert 'order' in stmt  # 按订单号匹配需 join order

    def test_parse_nos_trims_dedups_limits(self):
        assert _parse_nos(' A , ,B,A ') == ['A', 'B']
        assert _parse_nos('') == []
        assert _parse_nos(','.join(str(i) for i in range(600)), limit=500).__len__() == 500


class TestStockreturnRecords:
    async def test_empty_nos_returns_empty(self, mock_db):
        assert await get_stockreturn_records(mock_db, nos='') == []
        mock_db.execute.assert_not_awaited()

    async def test_filters_active_and_maps(self, mock_db):
        sr = MagicMock()
        sr.id = 9
        sr.return_no = 'SR-1'
        sr.return_date = None
        sr.customer = '客户B'
        sr.product_id = 4
        sr.product = None
        sr.quantity = 5
        sr.stockout_id = 2
        sr.stockout = None
        sr.reason = '破损'
        sr.note = '备注'
        mock_db.execute = AsyncMock(return_value=_rows_result([sr]))

        rows = await get_stockreturn_records(mock_db, nos='SR-1')

        compiled = mock_db.execute.await_args.args[0].compile()
        assert 'active' in compiled.params.values()  # 仅 active
        assert rows[0]['return_no'] == 'SR-1'
        assert rows[0]['quantity'] == 5
        assert rows[0]['stockout_id'] == 2


# ---------------------------------------------------------------------------
# 退货原子编辑
# ---------------------------------------------------------------------------
def _active_return():
    sr = MagicMock()
    sr.id = 11
    sr.status = 'active'
    sr.stockout_id = 5
    sr.quantity = 3
    sr.return_date = None
    sr.reason = '旧原因'
    sr.note = '旧备注'
    sr.return_no = 'SR-OLD'
    return sr


class TestEditStockreturn:
    async def test_cancel_then_recreate(self, mock_db):
        old = _active_return()
        mock_db.execute = AsyncMock(return_value=_one_result(old))
        with patch('fastapi_app.services.stock_return_service.cancel_stockreturn', new_callable=AsyncMock) as mock_cancel, \
             patch('fastapi_app.services.stock_return_service.create_stockreturn', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = {'id': 99, 'return_no': 'SR-NEW'}

            result = await edit_stockreturn(
                mock_db, return_id=11, quantity=8, return_date_str='2026-05-01',
                reason='新原因', note='新备注', operator_id=1,
            )

        mock_cancel.assert_awaited_once()
        assert mock_cancel.await_args.args[1] == 11
        mock_create.assert_awaited_once()
        call = mock_create.await_args
        assert call.args[1] == 5          # stockout_id 沿用
        assert call.args[2] == 8          # 新数量
        assert call.args[3] == '2026-05-01'
        assert call.args[4] == '新原因'
        assert call.args[5] == '新备注'
        assert result == {'id': 99, 'return_no': 'SR-NEW'}

    async def test_keeps_old_values_when_omitted(self, mock_db):
        old = _active_return()
        mock_db.execute = AsyncMock(return_value=_one_result(old))
        with patch('fastapi_app.services.stock_return_service.cancel_stockreturn', new_callable=AsyncMock), \
             patch('fastapi_app.services.stock_return_service.create_stockreturn', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = {'id': 99, 'return_no': 'SR-NEW'}
            await edit_stockreturn(mock_db, return_id=11, quantity=None, return_date_str=None,
                                   reason=None, note=None, operator_id=1)
        call = mock_create.await_args
        assert call.args[2] == 3          # 沿用旧数量
        assert call.args[4] == '旧原因'
        assert call.args[5] == '旧备注'

    async def test_rejects_missing(self, mock_db):
        mock_db.execute = AsyncMock(return_value=_one_result(None))
        with pytest.raises(ValueError, match='不存在'):
            await edit_stockreturn(mock_db, return_id=1, quantity=1, return_date_str=None,
                                   reason=None, note=None)

    async def test_rejects_already_cancelled(self, mock_db):
        old = _active_return()
        old.status = 'cancelled'
        mock_db.execute = AsyncMock(return_value=_one_result(old))
        with pytest.raises(ValueError, match='已取消'):
            await edit_stockreturn(mock_db, return_id=11, quantity=1, return_date_str=None,
                                   reason=None, note=None)

    async def test_rejects_without_stockout(self, mock_db):
        old = _active_return()
        old.stockout_id = None
        mock_db.execute = AsyncMock(return_value=_one_result(old))
        with pytest.raises(ValueError, match='未关联出货'):
            await edit_stockreturn(mock_db, return_id=11, quantity=1, return_date_str=None,
                                   reason=None, note=None)


# ---------------------------------------------------------------------------
# 四眼原则：新码不被 report_manage 继承
# ---------------------------------------------------------------------------
class TestNoManageInherit:
    def _user_with_parent(self, parent_code: str, child_codes: list[str]):
        from fastapi_app.shared_models import Permission, User

        children = []
        for code in child_codes:
            child = Permission()
            child.code = code
            children.append(child)
        parent = Permission()
        parent.code = parent_code
        parent.parent_id = None
        parent.children = children
        user = User()
        user.is_super = False
        user.permissions = [parent]
        return user

    @pytest.mark.parametrize('code', [
        'stockout_edit', 'stockout_delete', 'deduction_edit',
        'deduction_delete', 'return_edit', 'return_delete',
    ])
    def test_new_codes_require_explicit_grant(self, code):
        user = self._user_with_parent('report_manage', [code])
        # 父权限自身可通过；子码不得经继承放行
        assert user.has_permission('report_manage') is True
        assert user.has_permission(code) is False

    def test_explicit_child_grant_passes(self):
        user = self._user_with_parent('report_manage', ['stockout_edit'])
        # 直接持有子码（挂在 permissions 列表里）时应放行
        user.permissions[0].children = []
        from fastapi_app.shared_models import Permission
        direct = Permission()
        direct.code = 'stockout_edit'
        direct.parent_id = 1
        direct.children = []
        user.permissions.append(direct)
        assert user.has_permission('stockout_edit') is True
