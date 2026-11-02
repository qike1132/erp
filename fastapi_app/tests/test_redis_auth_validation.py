"""生产环境 Redis 连接串必须带认证凭据。

config/redis-broker.conf 在仓内没有 requirepass，靠注册表/环境变量注入；
灾备重建时若漏注入，6379/6380 将匿名可读写。代码侧至少要在启动时发现
「连接串里根本没有凭据」并告警；显式 REQUIRE_REDIS_AUTH=true 时拒绝启动。
"""
from __future__ import annotations

import pytest

from fastapi_app.core.config import validate_redis_auth


def test_url_without_password_warns() -> None:
    warnings = validate_redis_auth(
        {'REDIS_URL': 'redis://127.0.0.1:6379/0'}, require_auth=False,
    )
    assert warnings and 'REDIS_URL' in warnings[0]


def test_url_with_password_passes() -> None:
    assert validate_redis_auth(
        {'REDIS_URL': 'redis://:s3cret@127.0.0.1:6379/0'}, require_auth=False,
    ) == []


def test_url_with_user_and_password_passes() -> None:
    assert validate_redis_auth(
        {'REDIS_BROKER_URL': 'redis://erp:pw@127.0.0.1:6380/0'}, require_auth=False,
    ) == []


def test_username_without_password_warns() -> None:
    warnings = validate_redis_auth(
        {'REDIS_URL': 'redis://erp@127.0.0.1:6379/0'}, require_auth=False,
    )
    assert warnings


def test_empty_url_is_ignored() -> None:
    assert validate_redis_auth(
        {'REDIS_URL': '', 'REDIS_BROKER_URL': ''}, require_auth=False,
    ) == []


def test_require_auth_is_fatal() -> None:
    with pytest.raises(RuntimeError, match='Redis 认证'):
        validate_redis_auth(
            {'REDIS_BROKER_URL': 'redis://127.0.0.1:6380/0'}, require_auth=True,
        )
