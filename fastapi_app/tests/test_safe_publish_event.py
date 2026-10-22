"""M11：事件发布的意外异常必须保留 traceback，避免症状与原因分离。"""
import logging

import pytest

from fastapi_app.core.exception_handler import safe_publish_event


@pytest.mark.asyncio
async def test_programming_error_logs_traceback(caplog):
    async def _boom(*args, **kwargs):
        raise TypeError("bad payload")

    with caplog.at_level(logging.ERROR):
        await safe_publish_event(_boom, "x", {})

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records, "意外异常必须记 ERROR"
    assert any(r.exc_info for r in error_records), "意外异常必须带 traceback"
