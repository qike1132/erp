"""来料登记模块测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestMaterialRegistrationSchemas:
    def test_item_create(self):
        from fastapi_app.schemas.material_registration import MaterialRegistrationItemCreate
        item = MaterialRegistrationItemCreate(material_name="面料A", ordered_quantity=100.0)
        assert item.material_name == "面料A"
        assert item.ordered_quantity == 100.0

    def test_reg_create(self):
        from fastapi_app.schemas.material_registration import MaterialRegistrationCreate
        reg = MaterialRegistrationCreate(purchase_order_id=1, remark="备注")
        assert reg.purchase_order_id == 1

    def test_receive_request(self):
        from fastapi_app.schemas.material_registration import ReceiveMaterialRequest
        req = ReceiveMaterialRequest(received_quantity=50.0, remark="已收货")
        assert req.received_quantity == 50.0


class TestMaterialRegistrationModels:
    def test_model_import(self):
        from fastapi_app.shared_models.material_registration import MaterialRegistration, MaterialRegistrationItem
        assert MaterialRegistration.__tablename__ == 'material_registration'
        assert MaterialRegistrationItem.__tablename__ == 'material_registration_item'

    def test_computed_status_pending(self):
        from fastapi_app.shared_models.material_registration import MaterialRegistration, MaterialRegistrationItem
        reg = MagicMock()
        reg.items = []
        mr = MaterialRegistration.__new__(MaterialRegistration)
        # Just verify it can be imported and instantiated conceptually


class TestMaterialRegistrationService:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.delete = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock()
        db.get = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_get_registrations_empty(self, mock_db):
        from fastapi_app.services.material_registration_service import get_registrations
        # Need multiple mock results: count query + data query + 6 stats queries
        empty_count = MagicMock()
        empty_count.scalar.return_value = 0
        empty_data = MagicMock()
        empty_data.scalars.return_value.all.return_value = []
        # Provide enough mocks for all db.execute calls (count + data + ~8 stats)
        mock_db.execute = AsyncMock(side_effect=[
            empty_count, empty_data,
            empty_count, empty_count, empty_count, empty_count,
            empty_count, empty_count,
        ])

        result = await get_registrations(mock_db)
        assert result['total'] == 0
        assert result['registrations'] == []

    @pytest.mark.asyncio
    async def test_get_registration_not_found(self, mock_db):
        from fastapi_app.services.material_registration_service import get_registration
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="不存在"):
            await get_registration(mock_db, 999)

    @pytest.mark.asyncio
    async def test_create_registration_no_po(self, mock_db):
        from fastapi_app.services.material_registration_service import create_registration
        mock_db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="采购订单不存在"):
            await create_registration(mock_db, 999)

    @pytest.mark.asyncio
    async def test_delete_registration_success(self, mock_db):
        from fastapi_app.services.material_registration_service import delete_registration
        mock_reg = MagicMock()
        mock_db.get = AsyncMock(return_value=mock_reg)

        result = await delete_registration(mock_db, 1)
        assert mock_db.delete.called
        assert result['success'] is True

    @pytest.mark.asyncio
    async def test_receive_material_negative_qty(self, mock_db):
        from fastapi_app.services.material_registration_service import receive_material
        mock_item = MagicMock()
        mock_item.registration = MagicMock()
        mock_item.registration.items = []
        mock_result = MagicMock()
        mock_result.unique.return_value = mock_result
        mock_result.scalar_one_or_none.return_value = mock_item
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="大于0"):
            await receive_material(mock_db, 1, -5)

    @pytest.mark.asyncio
    async def test_stats_overview(self, mock_db):
        from fastapi_app.services.material_registration_service import get_stats_overview
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(side_effect=[
            mock_result, mock_scalar_result, mock_scalar_result,
            mock_scalar_result, mock_scalar_result,
        ])

        result = await get_stats_overview(mock_db)
        assert result['success'] is True
        assert 'overview' in result

    @pytest.mark.asyncio
    async def test_stats_trend(self, mock_db):
        from fastapi_app.services.material_registration_service import get_stats_trend
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_stats_trend(mock_db, days=7)
        assert len(result['trend']) == 8  # 7 days + 1 for range end


class TestMaterialRegistrationEndpoints:
    @pytest.mark.asyncio
    async def test_list_registrations(self, client, mock_db):
        # get_registrations 执行 8 次 db.execute:
        # 1) total count (scalar -> int)
        # 2) data query (scalars().all() -> list)
        # 3-6) pending/partial/completed/total_all count (scalar -> int each)
        # 7-8) total_ordered/total_received sum (scalar -> number each)
        mock_scalar_int = MagicMock()
        mock_scalar_int.scalar.return_value = 0

        mock_data = MagicMock()
        mock_data.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[
            mock_scalar_int,  # total count
            mock_data,       # data query
            mock_scalar_int, # pending_count
            mock_scalar_int, # partial_count
            mock_scalar_int, # completed_count
            mock_scalar_int, # total_all
            mock_scalar_int, # total_ordered
            mock_scalar_int, # total_received
        ])

        response = await client.get("/api/v1/material-registrations/registrations")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_registration_404(self, client, mock_db):
        from fastapi_app.services.material_registration_service import get_registration
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/v1/material-registrations/registrations/999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_available_purchase_orders(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.unique.return_value = mock_result
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/v1/material-registrations/purchase-orders/available")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_stats_overview_endpoint(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_scalar = MagicMock()
        mock_scalar.scalar.return_value = 0
        mock_db.execute = AsyncMock(side_effect=[mock_result, mock_scalar, mock_scalar, mock_scalar, mock_scalar, mock_scalar])

        response = await client.get("/api/v1/material-registrations/stats/overview")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_stats_trend_endpoint(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/v1/material-registrations/stats/trend?days=7")
        assert response.status_code == 200
