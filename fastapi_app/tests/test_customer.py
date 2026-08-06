"""客户管理模块测试"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCustomerSchemas:
    def test_customer_create(self):
        from fastapi_app.schemas.customer import CustomerCreate
        data = CustomerCreate(name="测试客户", contact="张三", phone="13800138000")
        assert data.name == "测试客户"

    def test_customer_create_required_name(self):
        from pydantic import ValidationError

        from fastapi_app.schemas.customer import CustomerCreate
        with pytest.raises(ValidationError):
            CustomerCreate()

    def test_customer_update_optional(self):
        from fastapi_app.schemas.customer import CustomerUpdate
        data = CustomerUpdate()
        assert data.name is None
        assert data.status is None

    def test_customer_response(self):
        from fastapi_app.schemas.customer import CustomerResponse
        resp = CustomerResponse(id=1, name="测试客户", status=True)
        assert resp.name == "测试客户"

    def test_customer_toggle_response(self):
        from fastapi_app.schemas.customer import CustomerToggleResponse
        resp = CustomerToggleResponse(status=True, message="客户已启用")
        assert resp.status is True


class TestCustomerService:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.delete = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock()
        db.get = AsyncMock()
        return db

    @pytest.fixture
    def mock_customer(self):
        c = MagicMock()
        c.id = 1
        c.name = "测试客户"
        c.status = True
        c.customer_code = None
        c.contact = None
        c.phone = None
        c.address = None
        c.note = None
        return c

    @pytest.mark.asyncio
    async def test_get_customers(self, mock_db, mock_customer):
        from fastapi_app.services.customer_service import get_customers
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_customer]
        mock_db.execute = AsyncMock(return_value=mock_result)

        customers = await get_customers(mock_db)
        assert len(customers['items']) == 1

    @pytest.mark.asyncio
    async def test_create_customer_success(self, mock_db):
        from fastapi_app.services.customer_service import create_customer
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        await create_customer(mock_db, "新客户", "张三", "138", "地址", "备注")
        assert mock_db.add.called

    @pytest.mark.asyncio
    async def test_create_customer_duplicate(self, mock_db, mock_customer):
        from fastapi_app.services.customer_service import create_customer
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_customer
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="客户名称已存在"):
            await create_customer(mock_db, "测试客户", None, None, None, None)

    @pytest.mark.asyncio
    async def test_delete_customer_with_orders(self, mock_db, mock_customer):
        from fastapi_app.services.customer_service import delete_customer
        mock_db.get = AsyncMock(return_value=mock_customer)
        # Mock order exists
        mock_order_result = MagicMock()
        mock_order_result.scalar_one_or_none.return_value = MagicMock()
        mock_empty_result = MagicMock()
        mock_empty_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[mock_order_result, mock_empty_result, mock_empty_result])

        with pytest.raises(ValueError, match="相关单据"):
            await delete_customer(mock_db, 1)

    @pytest.mark.asyncio
    async def test_toggle_status(self, mock_db, mock_customer):
        from fastapi_app.services.customer_service import toggle_customer_status
        mock_db.get = AsyncMock(return_value=mock_customer)

        await toggle_customer_status(mock_db, 1)
        assert mock_customer.status is False  # toggled

    @pytest.mark.asyncio
    async def test_search_customers(self, mock_db, mock_customer):
        from fastapi_app.services.customer_service import search_customers
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_customer]
        mock_db.execute = AsyncMock(return_value=mock_result)

        results = await search_customers(mock_db, "测试")
        assert len(results) == 1


class TestCustomerEndpoints:
    @pytest.mark.asyncio
    async def test_list_customers(self, client, mock_db):
        mock_customer = MagicMock()
        mock_customer.id = 1
        mock_customer.name = "测试客户"
        mock_customer.customer_code = None
        mock_customer.contact = None
        mock_customer.phone = None
        mock_customer.address = None
        mock_customer.note = None
        mock_customer.status = True
        mock_customer.create_time = MagicMock()
        mock_customer.create_time.strftime.return_value = "2024-01-01 00:00"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_customer]
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/v1/customers/list")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_create_customer(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.post("/api/v1/customers/create", json={
            "name": "新客户", "contact": "张三", "phone": "13800138000"
        })
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_toggle_status(self, client, mock_db):
        mock_customer = MagicMock()
        mock_customer.status = True
        mock_db.get = AsyncMock(return_value=mock_customer)

        response = await client.post("/api/v1/customers/toggle-status/1")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_active_names(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/v1/customers/active-names")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_customer_integrity_error(self, client, mock_db):
        """DELETE /api/v1/customers/delete/{id} 触发外键约束时应返回 400"""
        from sqlalchemy.exc import IntegrityError
        from unittest.mock import AsyncMock

        async def _raise_integrity(*_args, **_kwargs):
            raise IntegrityError("fk constraint", params=None, orig=Exception("fk"))

        mock_db.commit = AsyncMock(side_effect=_raise_integrity)
        mock_db.rollback = AsyncMock()

        with patch("fastapi_app.api.v1.endpoints.customer.customer_service.delete_customer", AsyncMock()):
            response = await client.delete("/api/v1/customers/delete/1")

        assert response.status_code == 400
        assert "相关单据" in response.json()["detail"]
        assert mock_db.rollback.called
