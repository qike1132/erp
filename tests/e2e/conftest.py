"""浏览器 E2E 运行边界。

旧 Selenium 套件默认连接生产 :5002 并直接创建订单、入库和审批，已移除。
本目录只保留目标守卫；真实浏览器回归由 ``frontend-vite/tests/e2e`` 的
Playwright 用例承担，使用模拟 API，不写真实业务数据。
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest

_PRODUCTION_PORTS = {3000, 5002}
_LOOPBACK_HOSTS = {'127.0.0.1', 'localhost', '::1'}


def _unsafe_target_reason(raw_url: str | None) -> str | None:
    """返回拒绝原因；None 表示目标符合隔离浏览器 E2E 要求。"""
    if not raw_url:
        return '必须显式设置 E2E_BASE_URL，禁止使用生产默认地址'
    try:
        parsed = urlparse(raw_url)
        port = parsed.port
    except ValueError:
        return 'E2E_BASE_URL 不是合法 URL'
    if parsed.scheme not in {'http', 'https'}:
        return 'E2E_BASE_URL 只允许 http/https'
    if (parsed.hostname or '').lower() not in _LOOPBACK_HOSTS:
        return 'E2E_BASE_URL 必须指向本机隔离实例，禁止内网/生产主机'
    if port is None:
        return 'E2E_BASE_URL 必须显式写出隔离实例端口'
    if port in _PRODUCTION_PORTS:
        return f'E2E_BASE_URL 端口 {port} 是生产拓扑端口'
    return None


def pytest_addoption(parser):
    parser.addoption(
        '--e2e',
        action='store_true',
        default=False,
        help='运行标记为 e2e 的浏览器测试',
    )


def pytest_configure(config):
    config.addinivalue_line('markers', 'e2e: 浏览器端到端测试')


def pytest_collection_modifyitems(config, items):
    if not config.getoption('--e2e'):
        skip = pytest.mark.skip(reason='需要 --e2e 且显式隔离 E2E_BASE_URL')
        for item in items:
            # 只按显式 marker 过滤，不能按关键字或目录：目录名 tests/e2e 会让
            # test_target_guard.py 也命中 'e2e' 而被连带 skip，守卫等于没跑。
            # marker 全局生效，未来放到其它目录的 e2e 用例也不会漏 skip。
            if item.get_closest_marker('e2e') is not None:
                item.add_marker(skip)
        return

    reason = _unsafe_target_reason(os.getenv('E2E_BASE_URL'))
    if reason:
        pytest.exit(f'拒绝运行浏览器 E2E：{reason}', returncode=2)


@pytest.fixture(scope='session')
def e2e_base_url() -> str:
    raw_url = os.getenv('E2E_BASE_URL')
    reason = _unsafe_target_reason(raw_url)
    if reason:
        pytest.fail(f'拒绝运行浏览器 E2E：{reason}')
    return raw_url.rstrip('/')
