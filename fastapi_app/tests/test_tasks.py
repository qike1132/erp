"""异步任务接口测试（基于 ARQ）"""
from unittest.mock import AsyncMock, patch

import pytest


class TestTasksEndpoints:
    @pytest.mark.asyncio
    async def test_task_status_not_found(self, client):
        """GET /api/v1/tasks/status/{task_id} — 任务不存在时返回 404"""
        with patch(
            "fastapi_app.api.v1.endpoints.tasks._job_status",
            new=AsyncMock(return_value=("NOT_FOUND", None)),
        ):
            with patch("fastapi_app.api.v1.endpoints.tasks._get_arq_job", new=AsyncMock()):
                response = await client.get("/api/v1/tasks/status/nonexistent-task-id")
                assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_task_status_in_progress(self, client):
        """GET /api/v1/tasks/status/{task_id} — 任务执行中返回 STARTED"""
        with patch(
            "fastapi_app.api.v1.endpoints.tasks._job_status",
            new=AsyncMock(return_value=("STARTED", None)),
        ):
            with patch("fastapi_app.api.v1.endpoints.tasks._get_arq_job", new=AsyncMock()):
                response = await client.get("/api/v1/tasks/status/task-in-progress")
                assert response.status_code == 200
                data = response.json()
                assert data["task_id"] == "task-in-progress"
                assert data["status"] == "STARTED"

    @pytest.mark.asyncio
    async def test_task_status_completed_task(self, client):
        """GET /api/v1/tasks/status/{task_id} — 任务已完成"""
        result = {"file_path": "/tmp/export.xlsx", "filename": "export.xlsx"}  # noqa: S108 测试 mock 路径
        with patch(
            "fastapi_app.api.v1.endpoints.tasks._job_status",
            new=AsyncMock(return_value=("SUCCESS", result)),
        ):
            with patch("fastapi_app.api.v1.endpoints.tasks._get_arq_job", new=AsyncMock()):
                response = await client.get("/api/v1/tasks/status/test-task-id")
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "SUCCESS"
                assert data["result"] is not None
                assert data["result"]["file_path"] == "/tmp/export.xlsx"  # noqa: S108 - mock 返回值断言，非真实文件操作

    @pytest.mark.asyncio
    async def test_task_status_failed_task(self, client):
        """GET /api/v1/tasks/status/{task_id} — 任务执行失败"""
        with patch(
            "fastapi_app.api.v1.endpoints.tasks._job_status",
            new=AsyncMock(return_value=("FAILURE", {"error": "Import failed"})),
        ):
            with patch("fastapi_app.api.v1.endpoints.tasks._get_arq_job", new=AsyncMock()):
                response = await client.get("/api/v1/tasks/status/failed-task-id")
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "FAILURE"
                assert data["result"] is not None
                assert "error" in data["result"]

    @pytest.mark.asyncio
    async def test_task_status_redis_unavailable(self, client):
        """GET /api/v1/tasks/status/{task_id} — Redis 不可用时返回 503"""
        from fastapi import HTTPException

        async def _raise_503(_task_id):
            raise HTTPException(status_code=503, detail="异步任务服务暂不可用，请稍后重试")

        with patch("fastapi_app.api.v1.endpoints.tasks._get_arq_job", new=_raise_503):
            response = await client.get("/api/v1/tasks/status/any-task-id")
            assert response.status_code == 503

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
