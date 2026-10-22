"""L8：开发默认 CORS 不得包含 null 源。"""


def test_dev_cors_default_has_no_null_origin():
    from fastapi_app.core.config import DEFAULT_DEV_CORS_ORIGINS

    origins = [o.strip() for o in DEFAULT_DEV_CORS_ORIGINS.split(',')]
    assert 'null' not in origins
