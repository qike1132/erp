"""删除：范围校验 + 删除前审计快照（物理删除，日志是唯一追溯手段）"""
import logging
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi_app.core.deps import resolve_production_write_scope
from fastapi_app.main import app
from fastapi_app.services.daily_production_service import delete_record


def _record(department='filling'):
    record = MagicMock()
    record.id = 7
    record.department = department
    record.product_name = '白兔公仔 40cm'
    record.barcode = '6901234'
    record.quantity = 620
    record.unit_price = 7
    record.production_date = date(2026, 9, 29)
    record.created_by = '张三'
    return record


class TestDeleteRecordAudit:
    async def test_snapshot_and_operator_are_logged_before_delete(self, caplog):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _record()
        db.execute = AsyncMock(return_value=result)

        # 记录 db.delete 被调用「那一刻」日志里已有什么，用来证明快照先于删除落盘
        log_when_deleted: dict[str, str] = {}

        async def _capture(record):
            log_when_deleted['text'] = caplog.text

        db.delete = AsyncMock(side_effect=_capture)

        with caplog.at_level(
            logging.INFO, logger='fastapi_app.services.daily_production_service',
        ), patch(
            # 本测试关注审计快照时序；库存联动另有专属测试（test_daily_production_stock_linkage.py）
            'fastapi_app.services.daily_production_service._apply_production_stock',
            new_callable=AsyncMock,
        ):
            await delete_record(db, 7, operator='李四')

        text = caplog.text
        assert '白兔公仔 40cm' in text
        assert '6901234' in text
        assert '620' in text
        assert '2026-09-29' in text
        assert '张三' in text   # 原录单人
        assert '李四' in text   # 本次操作人
        db.delete.assert_awaited_once()
        # 物理删除不可恢复：快照必须早于 delete，否则删除失败时证据丢失
        assert '白兔公仔 40cm' in log_when_deleted['text']
        assert 'operator=李四' in log_when_deleted['text']

    async def test_missing_record_raises_value_error(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        try:
            await delete_record(db, 999, operator='李四')
        except ValueError as exc:
            assert '不存在' in str(exc)
        else:
            raise AssertionError('记录不存在时应抛 ValueError')

        db.delete.assert_not_awaited()


class TestDeleteEndpointScope:
    async def test_out_of_scope_record_is_rejected_403(self, client):
        app.dependency_overrides[resolve_production_write_scope] = lambda: {'filling'}
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_record = AsyncMock(return_value=_record('packaging'))
            mock_svc.delete_record = AsyncMock(return_value=None)
            response = await client.delete('/api/v1/daily-production/records/7')
            mock_svc.delete_record.assert_not_awaited()
        assert response.status_code == 403

    async def test_in_scope_record_is_deleted_with_operator(self, client):
        app.dependency_overrides[resolve_production_write_scope] = lambda: {'filling'}
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_record = AsyncMock(return_value=_record('filling'))
            mock_svc.delete_record = AsyncMock(return_value=None)
            response = await client.delete('/api/v1/daily-production/records/7')
            called_kwargs = mock_svc.delete_record.await_args.kwargs
        assert response.status_code == 200
        assert called_kwargs['operator'] == 'admin'

    async def test_missing_record_returns_404(self, client):
        app.dependency_overrides[resolve_production_write_scope] = lambda: {'filling'}
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_record = AsyncMock(return_value=None)
            mock_svc.delete_record = AsyncMock(return_value=None)
            response = await client.delete('/api/v1/daily-production/records/999')
            mock_svc.delete_record.assert_not_awaited()
        assert response.status_code == 404
