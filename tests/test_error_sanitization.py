"""错误消息脱敏单元测试"""
import os
from unittest.mock import patch

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


class TestEndpointSanitizers:
    """端点侧脱敏口径（P2-8，2026-10-17 审计备份区）。

    `order.py` 曾把备份模块的**私有** `core.backup_progress._sanitize_error` 当通用脱敏器：
    那个函数只做「路径替换 + 截断 200 字」，SQLAlchemy 原文（表名、列名、WHERE 片段）会
    原样进 500 响应体 —— 生产环境把库结构回给客户端。正确入口是 `settings.sanitize_error`
    （生产恒为「服务器内部错误，请联系管理员」）。
    """

    def test_order_endpoints_use_settings_sanitizer(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / 'fastapi_app' / 'api' / 'v1'
               / 'endpoints' / 'order.py').read_text(encoding='utf-8')
        assert 'backup_progress' not in src, (
            'order.py 不得再从备份模块引入脱敏器（那个只做路径替换，会把 SQL 原文回给客户端）'
        )
        assert '_sanitize_error' not in src, (
            'order.py 里不得再出现私有脱敏器调用 —— 每个 500 分支都必须走 settings.sanitize_error'
        )
        assert src.count('settings.sanitize_error(') >= 2, (
            'order.py 有两处 500 分支（订单列表 / 合并记录），都必须用 settings.sanitize_error'
        )

    def test_order_style_detail_leaks_nothing_in_production(self):
        """按 order.py 的拼法（``f"获取订单列表失败: {sanitized}"``）在生产环境不泄露。"""
        with patch.object(settings, 'FASTAPI_DEBUG', False), \
             patch.dict(os.environ, {'APP_ENV': 'production'}):
            detail = (
                '获取订单列表失败: '
                + settings.sanitize_error(Exception('SELECT order_no FROM orders WHERE id=1'))
            )
        for leaked in ('SELECT', 'orders', 'order_no'):
            assert leaked not in detail, f'500 详情泄露了库结构：{detail}'
