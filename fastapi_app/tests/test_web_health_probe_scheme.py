"""web 入口健康探针的 scheme 自适应。

背景（2026-10-09 新机事故第四类）：探针硬编码 `http://127.0.0.1:<web_port>/nginx-health`，
erp-web/nginx 给 :3000 上 TLS 后明文请求得到 400 → `frontend_ok` 恒 false、
watchdog 恒报 `web_entry=fail`（服务其实完全正常）。修复：scheme 由 `WEB_HEALTH_SCHEME`
提供（默认 http，未上 TLS 的机器行为不变），https 时探针容忍自签证书
（回环探针只判「端口有人在服务」，不做证书链校验）。
"""
from __future__ import annotations

import importlib.util
import ssl
import sys
import urllib.request
from pathlib import Path
from types import ModuleType

import pytest

from fastapi_app.core import prod_runner

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def watchdog() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "erp_watchdog_under_test", ROOT / "scripts" / "ops" / "watchdog.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # 必须先注册进 sys.modules：watchdog 用 `from __future__ import annotations`，
    # dataclasses 解析字符串注解时要按 __module__ 反查模块，缺席会直接抛错。
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    yield mod
    sys.modules.pop(spec.name, None)


# ---------------------------------------------------------------- prod_runner

def test_scheme_defaults_to_http(monkeypatch) -> None:
    monkeypatch.delenv("WEB_HEALTH_SCHEME", raising=False)
    assert prod_runner._web_health_scheme() == "http"


def test_scheme_honors_env_and_blank_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("WEB_HEALTH_SCHEME", "HTTPS")
    assert prod_runner._web_health_scheme() == "https"
    monkeypatch.setenv("WEB_HEALTH_SCHEME", "   ")
    assert prod_runner._web_health_scheme() == "http"


def test_http_opener_is_shared_direct_opener() -> None:
    assert prod_runner._probe_opener("http") is prod_runner._OPENER_DIRECT


def test_https_opener_tolerates_self_signed() -> None:
    opener = prod_runner._probe_opener("https")
    handlers = [h for h in opener.handlers if isinstance(h, urllib.request.HTTPSHandler)]
    assert handlers, 'https 探针必须带 HTTPSHandler'
    ctx = handlers[0]._context
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False


def test_frontend_probe_uses_configured_scheme(monkeypatch) -> None:
    """探针 URL 必须按配置拼 scheme（回归：曾硬编码 http）。"""
    seen: dict[str, str] = {}

    def fake_http_ok(url, timeout=5.0, expect_substr=None, opener=None):
        seen['url'] = url
        return True

    monkeypatch.setattr(prod_runner, '_http_ok', fake_http_ok)
    monkeypatch.setenv('WEB_HEALTH_SCHEME', 'https')
    sup = prod_runner.Supervisor(workers=1, api_port=5002, web_port=3000, with_arq=False)
    assert sup._frontend_probe_ok() is True
    assert seen['url'] == 'https://127.0.0.1:3000/nginx-health'


# ------------------------------------------------------------------- watchdog

def test_watchdog_ssl_context_only_for_https(watchdog) -> None:
    assert watchdog._ssl_context_for('http://127.0.0.1:3000/nginx-health') is None
    ctx = watchdog._ssl_context_for('https://127.0.0.1:3000/nginx-health')
    assert ctx is not None
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False


def test_watchdog_web_url_default_follows_scheme(watchdog, monkeypatch) -> None:
    monkeypatch.delenv('WATCHDOG_WEB_URL', raising=False)
    monkeypatch.setenv('WEB_HEALTH_SCHEME', 'https')
    assert watchdog.build_parser().parse_args([]).web_url == 'https://127.0.0.1:3000'
    monkeypatch.setenv('WEB_HEALTH_SCHEME', 'http')
    assert watchdog.build_parser().parse_args([]).web_url == 'http://127.0.0.1:3000'
