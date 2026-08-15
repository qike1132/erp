"""
熔断器模式实现 - 保护外部服务调用

当外部服务（S3/FCM/OCR）连续失败达到阈值时自动熔断，
快速失败避免级联故障，超时后进入半开状态试探恢复。

使用方式：
    from fastapi_app.core.circuit_breaker import circuit

    @circuit(name="s3_upload", failure_threshold=5, recovery_timeout=30)
    async def upload_to_s3(data: bytes, key: str):
        return await s3_client.put_object(...)
"""
import asyncio
import logging
import time
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)


class CircuitState:
    """熔断器状态"""
    CLOSED = "closed"      # 正常工作
    OPEN = "open"           # 熔断中，快速失败
    HALF_OPEN = "half_open" # 半开状态，试探恢复


class CircuitBreaker:
    """异步熔断器"""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        success_threshold: int = 2,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                return CircuitState.HALF_OPEN
            return CircuitState.OPEN
        return self._state

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """通过熔断器调用函数"""
        async with self._lock:
            current_state = self.state

            if current_state == CircuitState.OPEN:
                logger.warning("熔断器 [%s] 处于 OPEN 状态，快速失败", self.name)
                raise CircuitBreakerOpenError(
                    f"熔断器 [{self.name}] 已开启，请稍后重试"
                )

        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise

    async def _on_success(self):
        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info("熔断器 [%s] 恢复正常 (CLOSED)", self.name)
            elif self.state == CircuitState.CLOSED:
                self._failure_count = 0

    async def _on_failure(self):
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self.state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._success_count = 0
                logger.warning("熔断器 [%s] 半开状态失败，重新开启 (OPEN)", self.name)
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "熔断器 [%s] 失败次数达阈值 (%d)，开启熔断 (OPEN)",
                    self.name, self._failure_count
                )

    def reset(self):
        """手动重置熔断器"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0


class CircuitBreakerOpenError(Exception):
    """熔断器开启异常"""
    pass


# 全局熔断器注册表
_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(name: str) -> CircuitBreaker:
    """获取或创建熔断器实例"""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name=name)
    return _breakers[name]


def circuit(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
    success_threshold: int = 2,
):
    """熔断器装饰器工厂

    Args:
        name: 熔断器名称（用于日志和监控）
        failure_threshold: 连续失败次数阈值
        recovery_timeout: 熔断恢复超时（秒）
        success_threshold: 半开状态成功次数阈值
    """
    breaker = CircuitBreaker(
        name=name,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
        success_threshold=success_threshold,
    )
    _breakers[name] = breaker

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await breaker.call(func, *args, **kwargs)
        return wrapper
    return decorator


def get_all_breaker_status() -> dict[str, dict]:
    """获取所有熔断器状态（用于监控端点）"""
    return {
        name: {
            "state": b.state,
            "failure_count": b._failure_count,
            "success_count": b._success_count,
        }
        for name, b in _breakers.items()
    }