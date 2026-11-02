"""生产环境未显式配置 CORS_ORIGINS 时，不得回退到开发默认列表。

回退的后果不是「多一点便利」：dev 列表经生产过滤器后仍留下
http://localhost*，这会让本机来源获得跨域/CSRF Origin 放行，
而运维以为「没配就等于没开」。
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def _restore_settings_singleton():
    import fastapi_app.core.config as config_module

    saved = config_module.settings
    yield
    config_module.settings = saved


def _settings(monkeypatch: pytest.MonkeyPatch, *, production: bool, cors: str | None):
    import fastapi_app.core.config as config_module

    monkeypatch.setenv('ALLOWED_HOSTS', '["erp.example.com"]')
    monkeypatch.setenv('SECRET_KEY', 'x' * 48)
    monkeypatch.setenv(
        'APP_ENV', 'production PYTHONUTF8=1' if production else 'development PYTHONUTF8=1',
    )
    # reload 会重跑 config.py 顶部的 load_dotenv()，把本机真实 .env 的
    # CORS_ORIGINS 重新灌回 os.environ，让「未配置」这个前提失效。
    monkeypatch.setattr('dotenv.load_dotenv', lambda *a, **k: None)
    if cors is None:
        monkeypatch.delenv('CORS_ORIGINS', raising=False)
    else:
        monkeypatch.setenv('CORS_ORIGINS', cors)
    importlib.reload(config_module)
    return config_module.Settings()


def test_production_without_cors_origins_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings(monkeypatch, production=True, cors=None)
    assert s.BACKEND_CORS_ORIGINS == []


def test_non_production_without_cors_origins_keeps_dev_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _settings(monkeypatch, production=False, cors=None)
    assert 'http://localhost:3000' in s.BACKEND_CORS_ORIGINS
