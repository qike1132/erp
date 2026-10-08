"""生产环境判定 _is_production_env 的回归测试。

背景（2026-09-15 上线演练真实事故）：scripts/migrate/ 旧安装脚本把 NSSM
AppEnvironmentExtra 写成单个字符串，NSSM 按第一个 '=' 拆分后 APP_ENV 变成
"production FASTAPI_DEBUG=false PYTHONPATH=..."，整串比较永远判不成 production，
文档端点与安全闸门全部失效。修复：只取第一个空白 token 比较，并锁定该行为。
"""
from __future__ import annotations

import os

import pytest

from fastapi_app.core.config import _is_production_env


@pytest.fixture(autouse=True)
def _restore_app_env(monkeypatch: pytest.MonkeyPatch):
    """每个用例后恢复原始 APP_ENV，避免污染其它测试。"""
    original = os.environ.get('APP_ENV')
    yield
    if original is None:
        os.environ.pop('APP_ENV', None)
    else:
        os.environ['APP_ENV'] = original


class TestMalformedAppEnv:
    """畸形 APP_ENV（历史 NSSM 安装 Bug 产物）必须仍判定为生产环境。"""

    def test_malformed_nssm_bundle(self, monkeypatch: pytest.MonkeyPatch):
        """历史 Bug 的精确复现：整个 env 串被写进 APP_ENV。"""
        monkeypatch.setenv(
            'APP_ENV',
            'production FASTAPI_DEBUG=false PYTHONPATH=D:\\erp_system '
            'PYTHONUTF8=1 PYTHONUNBUFFERED=1 UVICORN_WORKERS=4',
        )
        assert _is_production_env() is True

    def test_simple_production(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv('APP_ENV', 'production')
        assert _is_production_env() is True

    def test_prod_shorthand(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv('APP_ENV', 'prod')
        assert _is_production_env() is True

    def test_case_insensitive(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv('APP_ENV', 'Production')
        assert _is_production_env() is True

    def test_development(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv('APP_ENV', 'development')
        assert _is_production_env() is False

    def test_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv('APP_ENV', raising=False)
        assert _is_production_env() is False

    def test_malformed_development_bundle(self, monkeypatch: pytest.MonkeyPatch):
        """同理，development 开头的畸形串不得误判为 production。"""
        monkeypatch.setenv('APP_ENV', 'development FASTAPI_DEBUG=true UVICORN_WORKERS=1')
        assert _is_production_env() is False


class TestProductionGatesUnderMalformedEnv:
    """畸形 APP_ENV 下，文档端点关闭与安全闸门必须仍然生效。

    DOCS_URL / BACKEND_CORS_ORIGINS 是类定义期求值的字段默认值，
    修改环境变量后必须 reload 模块才能反映到 Settings()。
    """

    @pytest.fixture(autouse=True)
    def _prod_required_env(self, monkeypatch: pytest.MonkeyPatch):
        """本类用例靠 importlib.reload 重跑模块级 Settings()；CI 干净检出无 .env，
        必须显式给出生产必需项 —— 否则 reload 会在 ALLOWED_HOSTS 缺失处直接
        RuntimeError，用例根本到不了断言。"""
        monkeypatch.setenv('ALLOWED_HOSTS', '["erp.example.com"]')
        monkeypatch.setenv('SECRET_KEY', 'x' * 48)
        # 不给 CORS 时 reload 会用类默认串（含 'null'），生产下同样触发 null 闸门；
        # 显式给合法源，把本类用例聚焦在各自被测的闸门上。
        monkeypatch.setenv('CORS_ORIGINS', 'https://erp.example.com')

    @pytest.fixture(autouse=True)
    def _restore_settings_singleton(self):
        """reload 会重新执行模块级 ``settings = Settings()``，把全局单例替换为
        本用例 monkeypatch 环境下的新实例。若不恢复，后续用例里 ``from config
        import settings`` 会拿到「生产环境固化值」的单例（如 BACKEND_CORS_ORIGINS
        已被生产规则过滤掉 null），与当时 ``_is_production_env()`` 的判定脱节，
        导致 test_cors_origin_production_filter 的装配一致性断言假失败。
        """
        import fastapi_app.core.config as config_module

        saved = config_module.settings
        yield
        config_module.settings = saved

    def test_docs_urls_disabled(self, monkeypatch: pytest.MonkeyPatch):
        import importlib

        import fastapi_app.core.config as config_module

        monkeypatch.setenv(
            'APP_ENV',
            'production FASTAPI_DEBUG=false PYTHONPATH=D:\\erp_system PYTHONUTF8=1',
        )
        importlib.reload(config_module)
        s = config_module.Settings()
        assert s.is_production is True
        assert s.DOCS_URL is None
        assert s.REDOC_URL is None
        assert s.OPENAPI_URL is None

    def test_cors_still_filtered(self, monkeypatch: pytest.MonkeyPatch):
        """生产模式下 'null' 源被过滤，https 与 localhost 源保留。"""
        import importlib

        import fastapi_app.core.config as config_module

        monkeypatch.setenv('APP_ENV', 'production PYTHONUTF8=1')
        monkeypatch.setenv('CORS_ORIGINS', 'http://localhost:3000,null,https://erp.example.com')
        importlib.reload(config_module)
        s = config_module.Settings()
        assert s.is_production is True
        assert 'null' not in s.BACKEND_CORS_ORIGINS
        assert 'http://localhost:3000' in s.BACKEND_CORS_ORIGINS
        assert 'https://erp.example.com' in s.BACKEND_CORS_ORIGINS
