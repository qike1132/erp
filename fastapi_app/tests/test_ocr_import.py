"""OCR 出货单识别接口测试"""
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest


class TestOcrImportEndpoints:
    @pytest.mark.asyncio
    async def test_create_ocr_task_success(self, client):
        """测试创建 OCR 识别任务 - 正常返回 task_id"""
        with patch('fastapi_app.services.ocr_service.create_progress',
                    new_callable=AsyncMock, return_value='test-task-id-001'):
            response = await client.post("/api/v1/ocr-import/create-task")
            assert response.status_code == 200
            data = response.json()
            assert 'task_id' in data
            assert data['task_id'] == 'test-task-id-001'

    @pytest.mark.asyncio
    async def test_get_ocr_progress_success(self, client):
        """测试查询 OCR 识别进度 - 正常返回"""
        mock_progress = {
            'task_id': 'test-task-id-001',
            'status': 'done',
            'percent': 100,
            'message': '处理完成',
        }

        with patch('fastapi_app.services.ocr_service.get_progress',
                    new_callable=AsyncMock, return_value=mock_progress):
            response = await client.get("/api/v1/ocr-import/progress/test-task-id-001")
            assert response.status_code == 200
            data = response.json()
            assert data['status'] == 'done'
            assert data['percent'] == 100

    @pytest.mark.asyncio
    async def test_get_ocr_progress_not_found(self, client):
        """测试查询 OCR 识别进度 - 任务不存在"""
        with patch('fastapi_app.services.ocr_service.get_progress',
                    new_callable=AsyncMock, return_value=None):
            response = await client.get("/api/v1/ocr-import/progress/nonexistent-id")
            assert response.status_code == 200
            data = response.json()
            assert data['status'] == 'not_found'

    @pytest.mark.asyncio
    async def test_upload_unsupported_file_format(self, client, mock_db):
        """测试上传 OCR 文件 - 不支持的文件格式"""
        files = [
            ('files', ('test.doc', BytesIO(b'document content'), 'application/msword'))
        ]
        response = await client.post(
            "/api/v1/ocr-import/upload",
            files=files,
            params={'session_id': 'test-session-001'}
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True or data['file_count'] == 0
        assert len(data['errors']) > 0
        assert '不支持' in data['errors'][0]

    @pytest.mark.asyncio
    async def test_preview_unsupported_file_format(self, client):
        """测试预览 OCR 文件 - 不支持的文件格式"""
        files = {
            'file': ('test.doc', BytesIO(b'document content'), 'application/msword')
        }
        response = await client.post("/api/v1/ocr-import/preview", files=files)
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_preview_empty_file(self, client):
        """测试预览 OCR 文件 - 空文件"""
        files = {
            'file': ('test.pdf', BytesIO(b''), 'application/pdf')
        }
        response = await client.post("/api/v1/ocr-import/preview", files=files)
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_with_valid_task_id(self, client, mock_db):
        """测试上传 OCR 文件 - 传入有效的 task_id"""
        with patch('fastapi_app.services.ocr_service._progress_store',
                    {'existing-task-id': {'status': 'pending', 'percent': 0, 'message': ''}}):
            with patch('fastapi_app.services.ocr_service._update_progress',
                        new_callable=AsyncMock):
                with patch('fastapi_app.services.ocr_service.import_staging_stockouts_from_file',
                            new_callable=AsyncMock,
                            return_value=(0, 'no files', [])):
                    files = [
                        ('files', ('test.pdf', BytesIO(b'%PDF-1.4 fake'), 'application/pdf'))
                    ]
                    response = await client.post(
                        "/api/v1/ocr-import/upload",
                        files=files,
                        params={'session_id': 'test-session-001', 'task_id': 'existing-task-id'}
                    )
                    assert response.status_code == 200
                    data = response.json()
                    assert data['task_id'] == 'existing-task-id'
