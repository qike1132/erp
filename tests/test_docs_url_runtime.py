"""L5：DOCS/OpenAPI URL 必须在 app 创建期按运行时环境求值。"""


def test_resolve_docs_urls_by_runtime_flag():
    from fastapi_app.main import resolve_docs_urls

    assert resolve_docs_urls(True) == (None, None, None)
    assert resolve_docs_urls(False) == ('/api/docs', '/api/redoc', '/api/openapi.json')


def test_app_uses_resolved_docs_urls():
    from fastapi_app.core.config import settings
    from fastapi_app.main import app, resolve_docs_urls

    docs, redoc, openapi = resolve_docs_urls(settings.is_production)
    assert app.docs_url == docs
    assert app.redoc_url == redoc
    assert app.openapi_url == openapi
