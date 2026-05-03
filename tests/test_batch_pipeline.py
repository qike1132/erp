"""
batch_pipeline 基类单元测试

覆盖：Pipeline execute 流程、文件大小限制、空数据、校验错误、持久化异常回滚
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services.batch_pipeline import (
    MAX_BATCH_UPLOAD_SIZE,
    BatchImportPipeline,
    BatchImportResult,
)

# ============================================================
# BatchImportResult
# ============================================================

class TestBatchImportResult:
    def test_default_values(self):
        r = BatchImportResult()
        assert r.success_count == 0
        assert r.error_count == 0
        assert r.total == 0
        assert r.errors == []
        assert r.created_ids == []

    def test_total_property(self):
        r = BatchImportResult(success_count=3, error_count=2)
        assert r.total == 5

    def test_to_dict_caps_errors(self):
        r = BatchImportResult(errors=[f"err{i}" for i in range(100)])
        d = r.to_dict()
        assert len(d["errors"]) == 50


# ============================================================
# Pipeline 实现 stub
# ============================================================

class StubPipeline(BatchImportPipeline):
    """用于测试的具体实现"""

    def __init__(self, parse_result=None, validate_result=None, persist_result=None,
                 persist_error=None):
        self._parse_result = parse_result or []
        self._validate_result = validate_result or ([], [])
        self._persist_result = persist_result or []
        self._persist_error = persist_error

    async def parse(self, content, db):
        return self._parse_result

    async def validate(self, raw_data, db):
        return self._validate_result

    async def persist(self, validated_data, db, user):
        if self._persist_error:
            raise self._persist_error
        return self._persist_result


def _make_upload_file(content: bytes):
    f = AsyncMock()
    f.read = AsyncMock(return_value=content)
    return f


# ============================================================
# Pipeline.execute
# ============================================================

class TestBatchImportPipeline:
    @pytest.mark.asyncio
    async def test_file_too_large(self):
        pipe = StubPipeline()
        big_file = _make_upload_file(b"x" * (MAX_BATCH_UPLOAD_SIZE + 1))
        db = AsyncMock()
        user = MagicMock()

        result = await pipe.execute(big_file, db, user)
        assert result.error_count == 1
        assert "文件大小超过限制" in result.errors[0]

    @pytest.mark.asyncio
    async def test_empty_parse_result(self):
        pipe = StubPipeline(parse_result=[])
        f = _make_upload_file(b"some data")
        db = AsyncMock()
        user = MagicMock()

        result = await pipe.execute(f, db, user)
        assert result.success_count == 0
        assert any("未找到有效数据" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_validation_errors_only(self):
        pipe = StubPipeline(
            parse_result=[{"row": 1}],
            validate_result=([], ["第1行: 缺少产品名称"]),
        )
        f = _make_upload_file(b"data")
        db = AsyncMock()
        user = MagicMock()

        result = await pipe.execute(f, db, user)
        assert result.error_count == 1
        assert result.success_count == 0

    @pytest.mark.asyncio
    async def test_successful_pipeline(self):
        pipe = StubPipeline(
            parse_result=[{"name": "A"}, {"name": "B"}],
            validate_result=([{"name": "A"}, {"name": "B"}], []),
            persist_result=[1, 2],
        )
        f = _make_upload_file(b"data")
        db = AsyncMock()
        user = MagicMock()

        result = await pipe.execute(f, db, user)
        assert result.success_count == 2
        assert result.created_ids == [1, 2]
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_persist_exception_rollback(self):
        pipe = StubPipeline(
            parse_result=[{"x": 1}],
            validate_result=([{"x": 1}], []),
            persist_error=RuntimeError("DB error"),
        )
        f = _make_upload_file(b"data")
        db = AsyncMock()
        user = MagicMock()

        result = await pipe.execute(f, db, user)
        assert result.error_count >= 1
        assert "导入失败" in result.errors[-1]
        db.rollback.assert_awaited_once()
