"""purchase_supplier_service 单元测试

使用 AsyncMock + SQLAlchemy 2.0 风格，匹配当前 async 函数签名。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services.purchase_supplier_service import (
    create_supplier,
    delete_supplier,
    get_suppliers,
    update_supplier,
)


def _make_supplier_mock(sid: int, name: str = "Supplier A"):
    """构造 Supplier ORM 替身"""
    s = MagicMock()
    s.id = sid
    s.name = name
    s.contact_person = "John"
    s.phone = "123"
    s.address = "Addr"
    s.remark = ""
    s.status = True
    s.created_at = None
    return s


class TestGetSuppliers:
    @pytest.mark.asyncio
    async def test_get_suppliers_basic(self):
        """基础分页查询：count + list 两次 execute"""
        db = MagicMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [_make_supplier_mock(1)]
        db.execute = AsyncMock(side_effect=[count_result, list_result])

        result = await get_suppliers(db, page=1, per_page=20)

        assert result["total"] == 1
        assert result["page"] == 1
        assert result["per_page"] == 20
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "Supplier A"

    @pytest.mark.asyncio
    async def test_get_suppliers_empty(self):
        db = MagicMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[count_result, list_result])

        result = await get_suppliers(db)

        assert result["total"] == 0
        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_get_suppliers_with_search(self):
        """搜索关键词传入时，count 与 list 都应触发"""
        db = MagicMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[count_result, list_result])

        await get_suppliers(db, search="广州")

        # 两次 execute 都应被调用
        assert db.execute.await_count == 2


class TestCreateSupplier:
    @pytest.mark.asyncio
    async def test_create_supplier_success(self):
        db = MagicMock()
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=existing_result)
        db.add = MagicMock(side_effect=lambda x: setattr(x, "id", 1))
        db.flush = AsyncMock()

        result = await create_supplier(db, {"name": "新供应商", "contact_person": "张三"})

        assert result["id"] == 1
        assert result["name"] == "新供应商"
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_supplier_duplicate_raises(self):
        db = MagicMock()
        existing = MagicMock()
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = existing
        db.execute = AsyncMock(return_value=existing_result)

        with pytest.raises(ValueError, match="供应商已存在"):
            await create_supplier(db, {"name": "已存在供应商"})


class TestUpdateSupplier:
    @pytest.mark.asyncio
    async def test_update_supplier_not_found(self):
        db = MagicMock()
        db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="供应商不存在"):
            await update_supplier(db, 999, {"name": "X"})

    @pytest.mark.asyncio
    async def test_update_supplier_duplicate_name(self):
        db = MagicMock()
        existing_supplier = _make_supplier_mock(1, "Old")
        db.get = AsyncMock(return_value=existing_supplier)
        dup_result = MagicMock()
        dup_result.scalar_one_or_none.return_value = MagicMock()  # 已有同名
        db.execute = AsyncMock(return_value=dup_result)

        with pytest.raises(ValueError, match="供应商名称已存在"):
            await update_supplier(db, 1, {"name": "Duplicate"})

    @pytest.mark.asyncio
    async def test_update_supplier_no_change_skips_sync(self):
        """所有字段未变时，_sync_supplier_info 应早返回，不触发任何 UPDATE"""
        db = MagicMock()
        # 旧值与新值完全一致
        supplier = _make_supplier_mock(1, "SameName")
        supplier.contact_person = "SameContact"
        supplier.phone = "SamePhone"
        supplier.address = "SameAddr"
        db.get = AsyncMock(return_value=supplier)
        # 同名检查返回 None（无冲突）
        dup_result = MagicMock()
        dup_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=dup_result)
        db.flush = AsyncMock()

        await update_supplier(db, 1, {
            "name": "SameName",
            "contact_person": "SameContact",
            "phone": "SamePhone",
            "address": "SameAddr",
            "remark": "",
        })

        # 仅同名检查的 1 次 execute，不应有任何 UPDATE 语句
        assert db.execute.await_count == 1
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_supplier_patch_keeps_unprovided_fields(self):
        """PATCH 语义：未提供的字段保留旧值"""
        db = MagicMock()
        supplier = _make_supplier_mock(1, "OldName")
        supplier.contact_person = "OldContact"
        supplier.phone = "OldPhone"
        supplier.address = "OldAddr"
        db.get = AsyncMock(return_value=supplier)
        dup_result = MagicMock()
        dup_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=dup_result)
        db.flush = AsyncMock()

        # 只提供 name，不提供其他字段
        await update_supplier(db, 1, {"name": "NewName"})

        # name 已更新，其他字段保留旧值
        assert supplier.name == "NewName"
        assert supplier.contact_person == "OldContact"
        assert supplier.phone == "OldPhone"
        assert supplier.address == "OldAddr"

    @pytest.mark.asyncio
    async def test_update_supplier_name_change_triggers_full_sync(self):
        """name 变更应触发所有关联表 UPDATE（物料表+PO+POItem+MaterialReg 双轨同步）"""
        db = MagicMock()
        supplier = _make_supplier_mock(1, "OldName")
        db.get = AsyncMock(return_value=supplier)
        dup_result = MagicMock()
        dup_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=dup_result)
        db.flush = AsyncMock()

        await update_supplier(db, 1, {"name": "NewName"})

        # 1 次同名检查 + 11 次 UPDATE（双轨同步）：
        # - 物料表 3 表 × 2 (按 id + 按 name) = 6
        # - PurchaseOrder 1 (按 id) + 1 (按 name) = 2
        # - PurchaseOrderItem 1 (按 name)
        # - MaterialRegistration 1 (按 id) + 1 (按 name) = 2
        assert db.execute.await_count == 1 + 11

    @pytest.mark.asyncio
    async def test_update_supplier_contact_only_triggers_po_sync(self):
        """仅 contact 变更（name 未变）应只触发 PurchaseOrder 1 次 UPDATE"""
        db = MagicMock()
        supplier = _make_supplier_mock(1, "SameName")
        supplier.contact_person = "OldContact"
        db.get = AsyncMock(return_value=supplier)
        dup_result = MagicMock()
        dup_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=dup_result)
        db.flush = AsyncMock()

        await update_supplier(db, 1, {"contact_person": "NewContact"})

        # 1 次同名检查 + 1 次 PurchaseOrder UPDATE（物料表/POItem/MaterialReg 不触发）
        assert db.execute.await_count == 2
        assert supplier.contact_person == "NewContact"


class TestDeleteSupplier:
    @pytest.mark.asyncio
    async def test_delete_supplier_not_found(self):
        db = MagicMock()
        db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="供应商不存在"):
            await delete_supplier(db, 999)

    @pytest.mark.asyncio
    async def test_delete_supplier_has_bom(self):
        """关联 ProductMaterial 时应被拒"""
        db = MagicMock()
        supplier = _make_supplier_mock(1, "X")
        db.get = AsyncMock(return_value=supplier)

        # 单次 execute 返回 5 个 EXISTS 结果（has_material=True）
        exists_result = MagicMock()
        exists_result.one.return_value = (True, False, False, False, False)
        db.execute = AsyncMock(return_value=exists_result)

        with pytest.raises(ValueError, match="无法删除"):
            await delete_supplier(db, 1)

    @pytest.mark.asyncio
    async def test_delete_supplier_has_material_registration(self):
        """关联来料登记（MaterialRegistration）时应被拒

        来料登记引用是后加的关联检查，漏测会让"有来料登记的供应商可被删"回归。
        """
        db = MagicMock()
        supplier = _make_supplier_mock(1, "X")
        db.get = AsyncMock(return_value=supplier)

        exists_result = MagicMock()
        exists_result.one.return_value = (False, False, False, False, True)
        db.execute = AsyncMock(return_value=exists_result)

        with pytest.raises(ValueError, match="无法删除"):
            await delete_supplier(db, 1)

    @pytest.mark.asyncio
    async def test_delete_supplier_no_association(self):
        """无关联时可删除"""
        db = MagicMock()
        supplier = _make_supplier_mock(1, "X")
        db.get = AsyncMock(return_value=supplier)

        exists_result = MagicMock()
        exists_result.one.return_value = (False, False, False, False, False)
        db.execute = AsyncMock(return_value=exists_result)
        db.delete = AsyncMock()
        db.flush = AsyncMock()

        result = await delete_supplier(db, 1)

        assert result["id"] == 1
        assert result["name"] == "X"
        db.delete.assert_called_once_with(supplier)
