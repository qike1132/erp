"""BOM 保存·隐藏款标记（``product_role.is_hidden``）回归测试。

需求：
- 右键指定任意角色为隐藏款，随保存 BOM 持久化；
- 每个 SKU 至多一个隐藏款：重复指定自动替换（后者生效）；
- 旧客户端不提交 ``is_hidden`` 时不得清掉已保存的标记。

纯解析器测试（不连库）：``resolve_role_rows`` 只依赖 ``product.roles`` 与 ``db.flush``。
"""
from unittest.mock import MagicMock

import pytest

from fastapi_app.services.product.bom_role_resolver import resolve_role_rows
from fastapi_app.shared_models import ProductRole


def _role(rid: int, name: str, *, hidden: bool = False) -> ProductRole:
    return ProductRole(id=rid, product_id=1, role_name=name, is_hidden=hidden)


def _db(next_new_id: int = 101) -> MagicMock:
    """db 桩：flush 时给新建的 ProductRole 分配 id（真库由 sequence 负责）。"""
    db = MagicMock()
    db.add = MagicMock()

    async def _flush():
        for call in db.add.call_args_list:
            obj = call.args[0]
            if isinstance(obj, ProductRole) and obj.id is None:
                obj.id = next_new_id

    db.flush = _flush
    return db


async def _resolve(roles, payload):
    return await resolve_role_rows(
        payload_roles=payload,
        existing_product_roles=roles,
        db=_db(),
        product_id=1,
        username='tester',
    )


class TestHiddenRolePersistence:
    @pytest.mark.asyncio
    async def test_designate_marks_only_target(self):
        a, b = _role(1, '角色A'), _role(2, '角色B')
        result = await _resolve([a, b], [
            {'id': 1, 'role_name': '角色A', 'is_hidden': True},
            {'id': 2, 'role_name': '角色B', 'is_hidden': False},
        ])
        assert a.is_hidden is True
        assert b.is_hidden is False
        assert result.hidden_role_id == 1

    @pytest.mark.asyncio
    async def test_duplicate_designation_keeps_last_and_clears_previous(self):
        """需求 4：重复指定 = 自动替换（后者生效），不会出现两个隐藏款。"""
        a, b = _role(1, '角色A', hidden=True), _role(2, '角色B')
        result = await _resolve([a, b], [
            {'id': 1, 'role_name': '角色A', 'is_hidden': True},
            {'id': 2, 'role_name': '角色B', 'is_hidden': True},
        ])
        assert a.is_hidden is False
        assert b.is_hidden is True
        assert result.hidden_role_id == 2

    @pytest.mark.asyncio
    async def test_cancel_clears_flag(self):
        a = _role(1, '角色A', hidden=True)
        result = await _resolve([a], [{'id': 1, 'role_name': '角色A', 'is_hidden': False}])
        assert a.is_hidden is False
        assert result.hidden_role_id is None

    @pytest.mark.asyncio
    async def test_legacy_payload_without_field_keeps_existing_flag(self):
        """旧客户端（不带 is_hidden）保存 BOM 不得清掉已指定的隐藏款。"""
        a = _role(1, '角色A', hidden=True)
        result = await _resolve([a], [{'id': 1, 'role_name': '角色A'}])
        assert a.is_hidden is True
        assert result.hidden_role_id == 1

    @pytest.mark.asyncio
    async def test_new_role_can_be_designated_on_creation(self):
        """新建角色与指定隐藏款同一次保存提交：新行落库即带标记。"""
        result = await _resolve([], [
            {'role_key': 'rk-1', 'role_name': '角色G', 'is_hidden': True},
        ])
        assert result.hidden_role_id == 101
        assert result.temp_role_map == {'rk-1': 101}
