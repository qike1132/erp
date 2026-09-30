"""创建生产记录：响应必须带回新记录的 id。

背景：录入弹窗的「撤销」是**物理删除**，必须先精确定位刚创建的那一条。
此前 POST 只回 { success, message }，客户端只能靠「猜最新一条」—— 对删除而言不可接受。
"""
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi_app.core.deps import resolve_production_write_scope
from fastapi_app.main import app

_PAYLOAD = {
    'department': 'filling',
    'product_name': '白兔公仔',
    'barcode': '690',
    'unit_price': 7,
    'quantity': 10,
    'production_date': '2026-09-29',
    'remark': '',
}


def _created_record(record_id: int):
    record = MagicMock()
    record.id = record_id
    return record


class TestCreateRecordReturnsId:
    async def test_create_response_carries_new_record_id(self, client):
        app.dependency_overrides[resolve_production_write_scope] = lambda: None
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.create_record = AsyncMock(return_value=_created_record(42))
            response = await client.post('/api/v1/daily-production/records', json=_PAYLOAD)

        assert response.status_code == 200
        body = response.json()
        assert body['success'] is True
        assert body['id'] == 42

    async def test_create_response_id_is_none_when_service_has_no_id(self, client):
        # 服务层若返回无 id 的对象（防御），响应退化为 None 而不是崩掉
        app.dependency_overrides[resolve_production_write_scope] = lambda: None
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.create_record = AsyncMock(return_value=MagicMock(id=None))
            response = await client.post('/api/v1/daily-production/records', json=_PAYLOAD)

        assert response.status_code == 200
        assert response.json()['id'] is None

    async def test_update_response_keeps_id_default_none(self, client):
        # 更新/删除端点的响应刻意保持不变：id 缺省 None，不误报一个 id
        app.dependency_overrides[resolve_production_write_scope] = lambda: None
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            record = MagicMock()
            record.id = 7
            record.department = 'filling'
            mock_svc.get_record = AsyncMock(return_value=record)
            mock_svc.update_record = AsyncMock(return_value=record)
            response = await client.put('/api/v1/daily-production/records/7', json={'quantity': 20})

        assert response.status_code == 200
        assert response.json()['id'] is None
