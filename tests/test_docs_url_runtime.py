"""L5：DOCS/OpenAPI URL 必须在 app 创建期按运行时环境求值。"""


def test_resolve_docs_urls_by_runtime_flag():
    from fastapi_app.main import resolve_docs_urls

    assert resolve_docs_urls(True) == (None, None, None)
    assert resolve_docs_urls(False) == ('/api/docs', '/api/redoc', '/api/openapi.json')
