"""API 文档端点必须显式开启。

原先的规则是「不是 production 就开」。危害不在于生产环境，而在于
APP_ENV 漏设/写错时（NSSM 参数变更、临时手工启动）自动把 /api/docs、
/api/openapi.json 挂到经 nginx 反代的 /api/ 前缀下，等于对外公布完整接口结构。
改为「显式开关 + 生产强制关」后，漏设的默认行为是关闭。
"""
from __future__ import annotations

import pytest

from fastapi_app.main import resolve_docs_urls


def test_docs_disabled_when_flag_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('API_DOCS_ENABLED', raising=False)
    assert resolve_docs_urls(is_production=False) == (None, None, None)


def test_docs_enabled_only_by_explicit_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('API_DOCS_ENABLED', 'true')
    assert resolve_docs_urls(is_production=False) == (
        '/api/docs', '/api/redoc', '/api/openapi.json',
    )


def test_production_ignores_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('API_DOCS_ENABLED', 'true')
    assert resolve_docs_urls(is_production=True) == (None, None, None)
