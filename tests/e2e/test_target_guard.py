"""浏览器 E2E 目标守卫：任何生产入口都必须在启动浏览器前被拒绝。"""
import pytest

from tests.e2e.conftest import _unsafe_target_reason


@pytest.mark.parametrize(
    ('url', 'fragment'),
    [
        (None, '必须显式设置'),
        ('http://127.0.0.1:5002', '生产拓扑端口'),
        ('http://localhost:3000', '生产拓扑端口'),
        ('http://192.168.0.95:5099', '禁止内网/生产主机'),
        ('http://127.0.0.1', '显式写出'),
        ('ftp://127.0.0.1:5099', 'http/https'),
    ],
)
def test_unsafe_targets_are_rejected(url, fragment):
    reason = _unsafe_target_reason(url)
    assert reason is not None
    assert fragment in reason


def test_safe_loopback_ephemeral_port_is_allowed():
    assert _unsafe_target_reason('http://127.0.0.1:5099') is None
    assert _unsafe_target_reason('https://localhost:8443') is None
