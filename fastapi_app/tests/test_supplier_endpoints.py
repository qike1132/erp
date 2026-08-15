"""供应商端点测试

覆盖 toggle_status 的 None 边界、不存在、db 异常分支，
以及 create/edit/delete 的 HTTP 状态码映射。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.api.v1.endpoints import supplier as supplier_module
from fastapi_app.services import purchase_supplier_service


class TestToggleStatus:
    @pytest.mark.asyncio
    async def test_toggle_status_not_found(self, client, mock_db):
        # endpoint 使用 SELECT ... FOR UPDATE 取行锁，mock db.execute 而非 db.get
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await client.post("/api/v1/suppliers/toggle-status/999")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "供应商不存在"

    @pytest.mark.asyncio
    async def test_toggle_status_none_to_true(self, client, mock_db, monkeypatch):
        """status=None（旧数据）应规范化为 True"""
        supplier = MagicMock()
        supplier.id = 1
        supplier.status = None  # 旧数据边界
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = supplier
        mock_db.execute = AsyncMock(return_value=mock_result)
        monkeypatch.setattr(supplier_module, "_invalidate_supplier_caches", AsyncMock())

        resp = await client.post("/api/v1/suppliers/toggle-status/1")

        assert resp.status_code == 200
        assert resp.json()["status"] is True
        assert "启用" in resp.json()["message"]

    @pytest.mark.asyncio
    async def test_toggle_status_true_to_false(self, client, mock_db, monkeypatch):
        supplier = MagicMock()
        supplier.id = 1
        supplier.status = True
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = supplier
        mock_db.execute = AsyncMock(return_value=mock_result)
        monkeypatch.setattr(supplier_module, "_invalidate_supplier_caches", AsyncMock())

        resp = await client.post("/api/v1/suppliers/toggle-status/1")

        assert resp.status_code == 200
        assert resp.json()["status"] is False
        assert "禁用" in resp.json()["message"]

    @pytest.mark.asyncio
    async def test_toggle_status_db_error(self, client, mock_db, monkeypatch):
        """db.commit 异常应返回 500 并 rollback"""
        supplier = MagicMock()
        supplier.id = 1
        supplier.status = True
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = supplier
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock(side_effect=SQLAlchemyError("db down"))
        monkeypatch.setattr(supplier_module, "_invalidate_supplier_caches", AsyncMock())

        resp = await client.post("/api/v1/suppliers/toggle-status/1")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "操作失败，请稍后重试"
        mock_db.rollback.assert_awaited()


class TestCreateSupplierEndpoint:
    @pytest.mark.asyncio
    async def test_create_success(self, client, mock_db, monkeypatch):
        """正常创建返回 200"""
        monkeypatch.setattr(supplier_module, "_invalidate_supplier_caches", AsyncMock())
        # service 层 create_supplier 先 execute 查重名，需返回 None（无冲突）
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=existing_result)
        mock_db.flush = AsyncMock()

        resp = await client.post("/api/v1/suppliers/create", json={
            "name": "新供应商", "contact_person": "张三", "phone": "138", "address": "", "remark": ""
        })

        assert resp.status_code == 200
        assert resp.json()["message"] == "供应商添加成功"

    @pytest.mark.asyncio
    async def test_create_duplicate_returns_400(self, client, mock_db, monkeypatch):
        """名称重复返回 400"""
        async def raise_value_error(*args, **kwargs):
            raise ValueError("供应商已存在")

        monkeypatch.setattr(supplier_module, "_invalidate_supplier_caches", AsyncMock())
        monkeypatch.setattr(purchase_supplier_service, "create_supplier", raise_value_error)

        resp = await client.post("/api/v1/suppliers/create", json={"name": "已存在"})

        assert resp.status_code == 400
        assert "已存在" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_missing_name_returns_422(self, client):
        """缺少必填字段 name 返回 422"""
        resp = await client.post("/api/v1/suppliers/create", json={"contact_person": "张三"})

        assert resp.status_code == 422


class TestEditSupplierEndpoint:
    @pytest.mark.asyncio
    async def test_edit_not_found_returns_404(self, client, mock_db, monkeypatch):
        """供应商不存在返回 404"""
        async def raise_not_found(*args, **kwargs):
            raise ValueError("供应商不存在")

        monkeypatch.setattr(supplier_module, "_invalidate_supplier_caches", AsyncMock())
        monkeypatch.setattr(purchase_supplier_service, "update_supplier", raise_not_found)

        resp = await client.put("/api/v1/suppliers/edit/999", json={"name": "X"})

        assert resp.status_code == 404
        assert resp.json()["detail"] == "供应商不存在"

    @pytest.mark.asyncio
    async def test_edit_duplicate_returns_400(self, client, mock_db, monkeypatch):
        """名称重复返回 400"""
        async def raise_dup(*args, **kwargs):
            raise ValueError("供应商名称已存在")

        monkeypatch.setattr(supplier_module, "_invalidate_supplier_caches", AsyncMock())
        monkeypatch.setattr(purchase_supplier_service, "update_supplier", raise_dup)

        resp = await client.put("/api/v1/suppliers/edit/1", json={"name": "重复名"})

        assert resp.status_code == 400
        assert "已存在" in resp.json()["detail"]


class TestDeleteSupplierEndpoint:
    @pytest.mark.asyncio
    async def test_delete_not_found_returns_404(self, client, mock_db, monkeypatch):
        """供应商不存在返回 404"""
        async def raise_not_found(*args, **kwargs):
            raise ValueError("供应商不存在")

        monkeypatch.setattr(supplier_module, "_invalidate_supplier_caches", AsyncMock())
        monkeypatch.setattr(purchase_supplier_service, "delete_supplier", raise_not_found)

        resp = await client.delete("/api/v1/suppliers/delete/999")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "供应商不存在"

    @pytest.mark.asyncio
    async def test_delete_has_association_returns_400(self, client, mock_db, monkeypatch):
        """有关联单据返回 400"""
        async def raise_assoc(*args, **kwargs):
            raise ValueError("该供应商已有相关BOM或采购订单数据，无法删除")

        monkeypatch.setattr(supplier_module, "_invalidate_supplier_caches", AsyncMock())
        monkeypatch.setattr(purchase_supplier_service, "delete_supplier", raise_assoc)

        resp = await client.delete("/api/v1/suppliers/delete/1")

        assert resp.status_code == 400
        assert "无法删除" in resp.json()["detail"]
