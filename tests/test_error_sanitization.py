"""错误消息脱敏单元测试"""
import os
from unittest.mock import patch

import pytest
from fastapi_app.core.config import settings


class TestErrorSanitization:
    def test_sanitize_in_production_hides_internal_error(self):
        with patch.object(settings, 'FASTAPI_DEBUG', False):
            msg = settings.sanitize_error(Exception("数据库连接超时: host=pg.internal (SQL: SELECT)"))
            assert 'pg.internal' not in msg
            assert 'SQL' not in msg
            assert 'SELECT' not in msg
            assert '服务器内部错误' in msg

    def test_sanitize_in_debug_returns_full_message(self):
        with patch.object(settings, 'FASTAPI_DEBUG', True):
            msg = settings.sanitize_error(Exception("数据库连接超时"))
            assert '数据库连接超时' in msg

    def test_sanitize_in_development_env_returns_full_message(self):
        with patch.object(settings, 'FASTAPI_DEBUG', False):
            with patch.dict(os.environ, {'APP_ENV': 'development'}):
                msg = settings.sanitize_error(Exception("内部错误详情"))
                assert '内部错误详情' in msg

    def test_sanitize_business_error_value_error_passes_through(self):
        with patch.object(settings, 'FASTAPI_DEBUG', False):
            msg = settings.sanitize_business_error(ValueError("库存不足"))
            assert '库存不足' in msg

    def test_sanitize_business_error_key_error_hides_in_production(self):
        with patch.object(settings, 'FASTAPI_DEBUG', False):
            msg = settings.sanitize_business_error(KeyError("secret_config"))
            assert 'secret_config' not in msg
            assert '服务器内部错误' in msg

    def test_sanitize_business_error_generic_exception_hides(self):
        with patch.object(settings, 'FASTAPI_DEBUG', False):
            msg = settings.sanitize_business_error(Exception("pg_host=10.0.0.1"))
            assert '10.0.0.1' not in msg
            assert '服务器内部错误' in msg
