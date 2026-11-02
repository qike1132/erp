"""L5：DOCS/OpenAPI URL 必须在 app 创建期按运行时环境求值。"""


def test_resolve_docs_urls_by_runtime_flag(monkeypatch):
    from fastapi_app.main import resolve_docs_urls

    # 默认关闭：不是 production 也不再自动开启（APP_ENV 漏设即公开接口结构）。
    monkeypatch.delenv('API_DOCS_ENABLED', raising=False)
    assert resolve_docs_urls(True) == (None, None, None)
    assert resolve_docs_urls(False) == (None, None, None)

    # 显式开关才开启；生产环境即使开关为真也强制关闭。
    monkeypatch.setenv('API_DOCS_ENABLED', 'true')
    assert resolve_docs_urls(True) == (None, None, None)
    assert resolve_docs_urls(False) == ('/api/docs', '/api/redoc', '/api/openapi.json')


def test_app_uses_resolved_docs_urls():
    from fastapi_app.core.config import settings
    from fastapi_app.main import app, resolve_docs_urls

    docs, redoc, openapi = resolve_docs_urls(settings.is_production)
    assert app.docs_url == docs
    assert app.redoc_url == redoc
    assert app.openapi_url == openapi
