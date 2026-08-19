"""异步任务接口测试"""
from unittest.mock import MagicMock, patch

import pytest


class TestTasksEndpoints:
    @pytest.mark.asyncio
    async def test_task_status_celery_unavailable(self, client):
        """GET /api/v1/tasks/status/{task_id} — Celery 未安装时应返回 503"""
        # 确保 Celery 不可用
        with patch("fastapi_app.api.v1.endpoints.tasks._celery_available", None):
            with patch("fastapi_app.api.v1.endpoints.tasks._get_celery_app", return_value=None):
                response = await client.get("/api/v1/tasks/status/nonexistent-task-id")
                assert response.status_code == 503
                data = response.json()
                assert "Celery" in data.get("detail", "") or "503" in str(data.get("status_code", ""))

    @pytest.mark.asyncio
    async def test_task_status_missing_task(self, client):
        """GET /api/v1/tasks/status/{task_id} — Celery 可用时查询不存在任务"""
        mock_celery = MagicMock()
        mock_result = MagicMock()
        mock_result.status = "PENDING"
        mock_result.ready.return_value = False
        mock_celery.AsyncResult.return_value = mock_result

        with patch("fastapi_app.api.v1.endpoints.tasks._celery_available", True):
            with patch("fastapi_app.api.v1.endpoints.tasks._get_celery_app", return_value=mock_celery):
                response = await client.get("/api/v1/tasks/status/nonexistent-task-id")
                assert response.status_code == 200
                data = response.json()
                assert data["task_id"] == "nonexistent-task-id"
                assert data["status"] == "PENDING"

    @pytest.mark.asyncio
    async def test_task_status_completed_task(self, client):
        """GET /api/v1/tasks/status/{task_id} — 任务已完成"""
        mock_celery = MagicMock()
        mock_result = MagicMock()
        mock_result.status = "SUCCESS"
        mock_result.ready.return_value = True
        mock_result.successful.return_value = True
        mock_result.result = {"file_path": "/tmp/export.xlsx", "filename": "export.xlsx"}  # noqa: S108 测试 mock 路径
        mock_celery.AsyncResult.return_value = mock_result

        with patch("fastapi_app.api.v1.endpoints.tasks._celery_available", True):
            with patch("fastapi_app.api.v1.endpoints.tasks._get_celery_app", return_value=mock_celery):
                response = await client.get("/api/v1/tasks/status/test-task-id")
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "SUCCESS"
                assert data["result"] is not None

    @pytest.mark.asyncio
    async def test_task_status_failed_task(self, client):
        """GET /api/v1/tasks/status/{task_id} — 任务执行失败"""
        mock_celery = MagicMock()
        mock_result = MagicMock()
        mock_result.status = "FAILURE"
        mock_result.ready.return_value = True
        mock_result.successful.return_value = False
        mock_result.result = Exception("Import failed")
        mock_celery.AsyncResult.return_value = mock_result

        with patch("fastapi_app.api.v1.endpoints.tasks._celery_available", True):
            with patch("fastapi_app.api.v1.endpoints.tasks._get_celery_app", return_value=mock_celery):
                response = await client.get("/api/v1/tasks/status/failed-task-id")
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "FAILURE"
                assert data["result"] is not None
                assert "error" in data["result"]

    @pytest.mark.asyncio
    async def test_import_orders_invalid_file(self, client):
        """POST /api/v1/tasks/import-orders — 不支持的文件类型应返回 400"""
        response = await client.post("/api/v1/tasks/import-orders", files={
            "file": ("test.txt", b"invalid content", "text/plain")
        })
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_export_report_invalid_type(self, client):
        """POST /api/v1/tasks/export-report — 不支持的报表类型应返回 400"""
        response = await client.post("/api/v1/tasks/export-report", json={
            "report_type": "invalid_type",
        })
        assert response.status_code == 400
