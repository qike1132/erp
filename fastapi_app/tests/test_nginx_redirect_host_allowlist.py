"""3000 端口的 301 不得回显未校验的 Host 头。

`return 301 https://$host$request_uri` 把客户端可控的 Host 直接写进
Location，构成 Host 头开放重定向。部署主机名固定为 192.168.0.95，
因此改为固定目标 + 未知 Host 拒绝。

静态断言是这套配置唯一可自动化的护栏：nginx 配置无法在 pytest 里执行。
"""
from __future__ import annotations

from pathlib import Path

CONF = Path(__file__).resolve().parents[2] / 'config' / 'nginx-windows.conf'


def _conf_text() -> str:
    return CONF.read_text(encoding='utf-8')


def test_redirect_target_is_fixed_host() -> None:
    assert 'return 301 https://192.168.0.95$request_uri;' in _conf_text()


def test_redirect_does_not_echo_host_header() -> None:
    assert 'https://$host' not in _conf_text()


def test_unknown_host_is_rejected() -> None:
    text = _conf_text()
    assert '$host != "192.168.0.95"' in text
    assert 'return 421;' in text
