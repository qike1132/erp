"""生产计划模块端点测试"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestProductionSummaryEndpoints:

    @pytest.mark.asyncio
    async def test_list_craft_works_success(self, client, mock_db):
        mock_service_result = {
            'data': [
                {
                    'id': 1,
                    'worker_name': '张三',
                    'quantity': 50,
                    'work_date': '2026-04-15',
                    'remark': '',
                    'create_time': '2026-04-15 10:00',
                    'created_by': 'admin',
                }
            ],
            'daily_summary': {
                '2026-04-15': {'craft_qty': 50, 'case_out_qty': 30}
            },
            'total': 1,
        }
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.get_craft_works = AsyncMock(return_value=mock_service_result)
            response = await client.get(
                "/api/v1/production-summary/craft/list",
                params={"year": 2026, "month": 4},
            )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['total'] == 1
        assert len(data['data']) == 1
        assert data['data'][0]['worker_name'] == '张三'

    @pytest.mark.asyncio
    async def test_create_craft_work_is_gone(self, client, mock_db):
        """审计 #6：旧表写入口停用，必须 410 且说明去处。

        拦的错：端点继续往 `craft_work` 静默写 —— 记录进去了，任何页面都看不见。
        """
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.create_craft_work = AsyncMock(return_value=MagicMock())
            response = await client.post(
                "/api/v1/production-summary/craft/create",
                json={
                    "worker_name": "张三",
                    "quantity": 50,
                    "work_date": "2026-04-15",
                    "remark": "",
                },
            )
        assert response.status_code == 410
        assert '/production' in response.json()['detail']
        # 关键：停用的入口不得再落库
        mock_svc.create_craft_work.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_craft_work_gone_even_for_invalid_payload(self, client, mock_db):
        """挡的错：以为「先校验再拒绝」，让一个能通过的校验把写入放回来。"""
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            response = await client.post(
                "/api/v1/production-summary/craft/create",
                json={
                    "worker_name": "张三",
                    "quantity": 50,
                    "work_date": "invalid-date",
                },
            )
        assert response.status_code == 410
        mock_svc.create_craft_work.assert_not_called()

    @pytest.mark.asyncio
    async def test_edit_craft_work_is_gone(self, client, mock_db):
        """审计 M-1（2026-11-21）：旧表写入口的 PUT 与 create 同口径停用，必须 410。

        拦的错：编辑「成功」写进没有任何页面会再读取的 `craft_work` 旧表——
        用户以为改生效了，实际是黑洞写入。
        """
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.update_craft_work = AsyncMock(return_value=None)
            response = await client.put(
                "/api/v1/production-summary/craft/edit/1",
                json={
                    "quantity": 80,
                    "remark": "更新数量",
                },
            )
        assert response.status_code == 410
        assert '/production' in response.json()['detail']
        # 关键：停用的入口不得再落库
        mock_svc.update_craft_work.assert_not_called()

    @pytest.mark.asyncio
    async def test_edit_craft_work_gone_even_for_invalid_payload(self, client, mock_db):
        """挡的错：以为「先校验再拒绝」，让一个能通过的校验把编辑放回来。"""
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            response = await client.put(
                "/api/v1/production-summary/craft/edit/999",
                json={"work_date": "invalid-date"},
            )
        assert response.status_code == 410
        mock_svc.update_craft_work.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_craft_work_is_gone(self, client, mock_db):
        """审计 M-1（2026-11-21）：旧表 DELETE 与 create 同口径停用，必须 410 且不得落库。"""
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.delete_craft_work = AsyncMock(return_value=None)
            response = await client.delete("/api/v1/production-summary/craft/delete/1")
        assert response.status_code == 410
        assert '/production' in response.json()['detail']
        mock_svc.delete_craft_work.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_packaging_records_success(self, client, mock_db):
        mock_service_result = {
            'data': [
                {
                    'id': 1,
                    'customer': '测试客户',
                    'product_name': '测试产品A',
                    'barcode': '6901234567890',
                    'quantity': 30,
                    'pack_date': '2026-04-15',
                    'remark': '',
                }
            ],
            'total': 1,
        }
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.get_packaging_records = AsyncMock(return_value=mock_service_result)
            response = await client.get(
                "/api/v1/production-summary/packaging/list",
                params={"year": 2026, "month": 4},
            )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['total'] == 1
        assert data['data'][0]['customer'] == '测试客户'

    @pytest.mark.asyncio
    async def test_create_packaging_record_is_gone(self, client, mock_db):
        """审计 #6：包装部旧表写入口同样 410，且不得落库。"""
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.create_packaging_record = AsyncMock(return_value=MagicMock())
            response = await client.post(
                "/api/v1/production-summary/packaging/create",
                json={
                    "customer": "测试客户",
                    "product_name": "测试产品A",
                    "barcode": "6901234567890",
                    "quantity": 30,
                    "pack_date": "2026-04-15",
                    "remark": "",
                },
            )
        assert response.status_code == 410
        assert '/production' in response.json()['detail']
        mock_svc.create_packaging_record.assert_not_called()

    @pytest.mark.asyncio
    async def test_edit_packaging_record_is_gone(self, client, mock_db):
        """审计 M-1（2026-11-21）：包装部旧表 PUT 与 create 同口径停用，必须 410。"""
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.update_packaging_record = AsyncMock(return_value=None)
            response = await client.put(
                "/api/v1/production-summary/packaging/edit/1",
                json={"quantity": 50},
            )
        assert response.status_code == 410
        assert '/production' in response.json()['detail']
        mock_svc.update_packaging_record.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_packaging_record_is_gone(self, client, mock_db):
        """审计 M-1（2026-11-21）：包装部旧表 DELETE 与 create 同口径停用，必须 410。"""
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.delete_packaging_record = AsyncMock(return_value=None)
            response = await client.delete("/api/v1/production-summary/packaging/delete/1")
        assert response.status_code == 410
        assert '/production' in response.json()['detail']
        mock_svc.delete_packaging_record.assert_not_called()

    @pytest.mark.asyncio
    async def test_production_summary_success(self, client, mock_db):
        mock_summary_result = {
            'data': [
                {
                    'date': '2026-04-15',
                    'case_out_qty': 30,
                    'craft_qty': 50,
                    'packaging_qty': 40,
                }
            ],
            'monthly_summary': {
                'total_case_out': 900,
                'total_craft': 1000,
                'total_packaging': 800,
            },
            'total': 1,
        }
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.get_production_summary = AsyncMock(return_value=mock_summary_result)
            response = await client.get(
                "/api/v1/production-summary/summary",
                params={"year": 2026, "month": 4},
            )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['total'] == 1


class TestExportRowLimitMapsTo413:
    """审计 #5：报表导出超 1 万行不得静默截断出文件，必须 413。

    旧实现是 `limit(MAX+1)` 后只 logger.warning 再 records[:10000]，端点照常 200
    返回一份少行的 Excel —— 用户拿它去对账，账永远对不上却没有任何信号。
    现在的契约：服务层 `ensure_within_export_limit` 抛 ValueError，端点映射 413。
    """

    @pytest.mark.asyncio
    async def test_craft_export_over_limit_returns_413_and_no_file(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.export_craft_works = AsyncMock(
                side_effect=ValueError('导出数据量过大（20001 行，上限 20000），请缩小筛选范围后分批导出')
            )
            response = await client.get('/api/v1/production-summary/craft/export')

        assert response.status_code == 413
        assert '导出数据量过大' in response.json()['detail']
        # 拦的错：413 之外还照样吐出 xlsx 附件（前端会当成导出成功）
        assert 'attachment' not in response.headers.get('content-disposition', '')

    @pytest.mark.asyncio
    async def test_packaging_export_over_limit_returns_413_and_no_file(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.export_packaging_records = AsyncMock(
                side_effect=ValueError('导出数据量过大（20001 行，上限 20000），请缩小筛选范围后分批导出')
            )
            response = await client.get('/api/v1/production-summary/packaging/export')

        assert response.status_code == 413
        assert 'attachment' not in response.headers.get('content-disposition', '')

    @pytest.mark.asyncio
    async def test_craft_export_within_limit_still_returns_xlsx(self, client, mock_db):
        # 反向断言：别把上界写成一有数据就拒（正常行数必须照常出文件）
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.export_craft_works = AsyncMock(return_value=b'PK\x03\x04fake-xlsx')
            response = await client.get('/api/v1/production-summary/craft/export')

        assert response.status_code == 200
        assert response.headers['content-disposition'] == 'attachment; filename=craft_work_export.xlsx'

    @pytest.mark.asyncio
    async def test_packaging_export_within_limit_still_returns_xlsx(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.export_packaging_records = AsyncMock(return_value=b'PK\x03\x04fake-xlsx')
            response = await client.get('/api/v1/production-summary/packaging/export')

        assert response.status_code == 200
        assert response.headers['content-disposition'] == 'attachment; filename=packaging_export.xlsx'


class TestServiceExportLimitWiring:
    """锁住「服务层真的调了 ensure_within_export_limit」这一步。

    端点 413 的用例把服务层打成桩，证明不了超限判定还在；这里直接在服务层验证：
    计数查询超限 → ValueError，且**不会**把记录读出来做成 Excel。
    """

    @pytest.mark.asyncio
    async def test_craft_export_raises_before_reading_rows(self):
        from fastapi_app.services import production_summary_service

        db = MagicMock()
        # 计数查询返回 20001 > EXPORT_MAX_ROWS(20000)
        db.scalar = AsyncMock(return_value=20001)
        db.scalars = AsyncMock()

        with pytest.raises(ValueError, match='导出数据量过大'):
            await production_summary_service.export_craft_works(db)

        db.scalars.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_packaging_export_raises_before_reading_rows(self):
        from fastapi_app.services import production_summary_service

        db = MagicMock()
        db.scalar = AsyncMock(return_value=20001)
        db.execute = AsyncMock()

        with pytest.raises(ValueError, match='导出数据量过大'):
            await production_summary_service.export_packaging_records(db)

        db.execute.assert_not_awaited()
