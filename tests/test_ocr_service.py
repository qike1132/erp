"""ocr_service 单元测试（进度接口为 async，2026-10-17 审计 AUD-03）"""
import pytest

from fastapi_app.services.ocr_service import create_progress, get_progress


class TestOCRService:
    @pytest.mark.asyncio
    async def test_create_progress(self):
        task_id = await create_progress()
        assert task_id is not None
        assert isinstance(task_id, str)

    @pytest.mark.asyncio
    async def test_get_progress_not_found(self):
        progress = await get_progress('nonexistent_id')
        assert progress is None
