"""auth.py 中提取的登录 helper 函数 - 单元测试

覆盖 P1-1 重构提取的 helper：
- _check_login_rate_limit（Redis burst + window 双计数器，降级内存限流）
- _set_login_cookies（httpOnly cookie 设置，SameSite/Secure 自适应）
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request, Response

from fastapi_app.api.v1.endpoints import auth


def _make_request(scheme="http", headers=None):
    """构造 mock Request，支持 scheme 与自定义 header"""
    request = MagicMock(spec=Request)
    request.url.scheme = scheme
    request.headers = headers or {}
    return request


# ============================================================================
# _check_login_rate_limit
# ============================================================================
class TestCheckLoginRateLimit:
    @pytest.mark.asyncio
    async def test_rate_limit_passes_when_under_burst_limit(self):
        """burst 与 window 计数均未超阈值时应正常返回（不抛异常）"""
        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=(1, 1))
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)
        mock_redis.expire = AsyncMock()
        with patch('fastapi_app.core.redis_wrapper.get_client', return_value=mock_redis):
            await auth._check_login_rate_limit("192.168.1.1")
        # 验证 expire 被调用以设置过期时间
        assert mock_redis.expire.await_count == 2

    @pytest.mark.asyncio
    async def test_rate_limit_raises_429_when_burst_exceeded(self):
        """burst 计数超过 LOGIN_BURST_LIMIT 时应抛 429"""
        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=(auth.LOGIN_BURST_LIMIT + 1, 1))
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)
        mock_redis.expire = AsyncMock()
        with patch('fastapi_app.core.redis_wrapper.get_client', return_value=mock_redis):
            with pytest.raises(HTTPException) as exc_info:
                await auth._check_login_rate_limit("10.0.0.1")
        assert exc_info.value.status_code == 429
        assert "1分钟" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_rate_limit_raises_429_when_window_exceeded(self):
        """window 计数超过 LOGIN_ATTEMPT_LIMIT 时应抛 429"""
        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=(1, auth.LOGIN_ATTEMPT_LIMIT + 1))
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)
        mock_redis.expire = AsyncMock()
        with patch('fastapi_app.core.redis_wrapper.get_client', return_value=mock_redis):
            with pytest.raises(HTTPException) as exc_info:
                await auth._check_login_rate_limit("10.0.0.2")
        assert exc_info.value.status_code == 429
        assert "5分钟" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_rate_limit_falls_back_to_memory_when_redis_unavailable(self):
        """Redis 不可用时应降级到进程内存滑动窗口限流"""
        with patch('fastapi_app.core.redis_wrapper.get_client', side_effect=ConnectionError("no redis")), \
             patch.object(auth.memory_limiter, 'hit', return_value=True):
            # 不应抛异常（内存限流放行）
            await auth._check_login_rate_limit("10.0.0.3")

    @pytest.mark.asyncio
    async def test_rate_limit_memory_limiter_rejects_burst(self):
        """内存限流 burst 超限时应抛 429"""
        with patch('fastapi_app.core.redis_wrapper.get_client', side_effect=ConnectionError("no redis")), \
             patch.object(auth.memory_limiter, 'hit', return_value=False), pytest.raises(HTTPException) as exc_info:
            await auth._check_login_rate_limit("10.0.0.4")
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_rate_limit_redis_none_client_falls_back_to_memory(self):
        """get_client 返回 None 时应降级到内存限流"""
        with patch('fastapi_app.core.redis_wrapper.get_client', return_value=None), \
             patch.object(auth.memory_limiter, 'hit', return_value=True):
            await auth._check_login_rate_limit("10.0.0.5")

    @pytest.mark.asyncio
    async def test_rate_limit_memory_limiter_rejects_window(self):
        """内存限流 burst 放行但 window 超限时应抛 429"""
        with patch('fastapi_app.core.redis_wrapper.get_client', side_effect=ConnectionError("no redis")), \
             patch.object(auth.memory_limiter, 'hit', side_effect=[True, False]):
            with pytest.raises(HTTPException) as exc_info:
                await auth._check_login_rate_limit("10.0.0.6")
        assert exc_info.value.status_code == 429
        assert "5分钟" in exc_info.value.detail


# ============================================================================
# _set_login_cookies
# ============================================================================
class TestSetLoginCookies:
    def test_set_cookies_http_uses_lax_samesite_no_secure(self):
        """HTTP 非 Capacitor 请求应设置 samesite=lax, secure=False"""
        response = MagicMock(spec=Response)
        request = _make_request(scheme="http", headers={})
        auth._set_login_cookies(response, request, "at", "rt", 3600, 86400)
        assert response.set_cookie.call_count == 2
        access_call = response.set_cookie.call_args_list[0]
        assert access_call.kwargs['samesite'] == 'lax'
        assert access_call.kwargs['secure'] is False
        assert access_call.kwargs['httponly'] is True
        assert access_call.kwargs['max_age'] == 3600

    def test_set_cookies_https_uses_none_samesite_secure(self):
        """HTTPS 请求应设置 samesite=none, secure=True"""
        response = MagicMock(spec=Response)
        request = _make_request(scheme="https", headers={})
        auth._set_login_cookies(response, request, "at", "rt", 3600, 86400)
        access_call = response.set_cookie.call_args_list[0]
        assert access_call.kwargs['samesite'] == 'none'
        assert access_call.kwargs['secure'] is True

    def test_set_cookies_https_via_forwarded_proto(self):
        """x-forwarded-proto=https 时应视为 HTTPS"""
        response = MagicMock(spec=Response)
        request = _make_request(scheme="http", headers={"x-forwarded-proto": "https"})
        auth._set_login_cookies(response, request, "at", "rt", 3600, 86400)
        access_call = response.set_cookie.call_args_list[0]
        assert access_call.kwargs['samesite'] == 'none'
        assert access_call.kwargs['secure'] is True

    def test_set_cookies_capacitor_http_uses_lax_no_secure(self):
        """Capacitor 客户端 HTTP 请求应设置 samesite=lax, secure=False"""
        response = MagicMock(spec=Response)
        request = _make_request(scheme="http", headers={"x-client-type": "capacitor"})
        auth._set_login_cookies(response, request, "at", "rt", 3600, 86400)
        access_call = response.set_cookie.call_args_list[0]
        assert access_call.kwargs['samesite'] == 'lax'
        assert access_call.kwargs['secure'] is False

    def test_set_cookies_localhost_origin_treated_as_capacitor(self):
        """origin=http://localhost 应识别为 Capacitor 场景"""
        response = MagicMock(spec=Response)
        request = _make_request(scheme="http", headers={"origin": "http://localhost:8100"})
        auth._set_login_cookies(response, request, "at", "rt", 3600, 86400)
        access_call = response.set_cookie.call_args_list[0]
        assert access_call.kwargs['samesite'] == 'lax'
        assert access_call.kwargs['secure'] is False

    def test_set_cookies_sets_both_access_and_refresh_tokens(self):
        """应同时设置 access_token 与 refresh_token 两个 cookie"""
        response = MagicMock(spec=Response)
        request = _make_request(scheme="http", headers={})
        auth._set_login_cookies(response, request, "access_val", "refresh_val", 3600, 86400)
        keys = [c.kwargs['key'] for c in response.set_cookie.call_args_list]
        assert 'access_token' in keys
        assert 'refresh_token' in keys
        refresh_call = response.set_cookie.call_args_list[1]
        assert refresh_call.kwargs['value'] == 'refresh_val'
        assert refresh_call.kwargs['max_age'] == 86400
