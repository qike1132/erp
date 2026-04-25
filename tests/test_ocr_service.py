"""ocr_service 单元测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi_app.services.ocr_service import create_progress, get_progress


class TestOCRService:
    def test_create_progress(self):
        task_id = create_progress()
        assert task_id is not None
        assert isinstance(task_id, str)

    def test_get_progress_not_found(self):
        progress = get_progress('nonexistent_id')
        assert progress is not None
        assert progress['status'] == 'not_found'
