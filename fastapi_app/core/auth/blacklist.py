"""
Token 黑名单/撤销（core/deps 拆分子模块）

职责：已撤销 token 的 jti 黑名单管理。
Redis 不可用时降级到进程级本地 LRU 缓存（fail-open/fail-closed 双模式）。
"""
import logging
import threading
import time
from collections import OrderedDict
from datetime import UTC, datetime

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


class _LRUSet:
    """进程级 LRU 集合，用于 token 黑名单的本地降级缓存

    多 worker 间不共享，仅作为 Redis 故障时的降级方案。
    使用 threading.Lock 保护 OrderedDict 操作，确保多线程安全。
    """

    def __init__(self, maxsize: int = 1000):
        self._maxsize = maxsize
        self._data: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, key: str) -> None:
        with self._lock:
            self._data[key] = None
            self._data.move_to_end(key)
            if len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    def contains(self, key: str) -> bool:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return True
            return False


_LOCAL_REVOKED_JTIS = _LRUSet(maxsize=1000)


def _note_redis_failure(exc: Exception) -> None:
    """把裸客户端命令的失败告知缓存管理器（自愈/退避）。

    裸客户端路径不经过 `RedisCacheManager` 的包装方法，因此**不会**自动触发
    降级与退避 —— 而 `is_token_revoked(fail_closed=True)` 正是那条 fail-closed
    路径：若不告知，Redis 持续不可用时每个请求都会真连一次（最多 5s）并各打日志。
    告知后连接类错误会让客户端降级、并对后续所有调用方短路直到退避窗口过期。
    """
    # 走 redis_wrapper 的钩子，不直接依赖 utils.redis_cache（见该模块的同名函数说明）
    from fastapi_app.core.redis_wrapper import note_command_failure
    note_command_failure(exc)


async def revoke_token(jti: str, exp: int) -> None:
    """将 token 的 jti 加入 Redis 黑名单，TTL 设为 token 剩余有效期

    登出时调用，确保已签发的 token 无法继续使用。
    Redis 不可用时静默失败（token 仍会自然过期），但会同步写入本地 LRU 缓存作为降级。
    """
    remaining = max(exp - int(datetime.now(UTC).timestamp()), 0)
    if remaining <= 0:
        return
    # 始终写入本地 LRU 缓存（无论 Redis 是否可用），作为后续 Redis 故障时的降级依据
    _LOCAL_REVOKED_JTIS.add(jti)
    try:
        from fastapi_app.core.redis_wrapper import get_client, note_command_success

        redis = get_client()
        if redis:
            await redis.set(f"token_blacklist:{jti}", "1", ex=remaining)
            note_command_success()
    except Exception as e:  # defensive: Redis 故障时本地 LRU 缓存已写入，继续服务
        _note_redis_failure(e)
        logger.debug("token 黑名单写入失败", exc_info=True)


# fail-open 降级 critical 日志的上次记录时间（monotonic），用于限频避免刷屏
_last_revocation_critical_at = 0.0
_REVOCATION_CRITICAL_INTERVAL = 60.0  # 限频时间窗（秒）


def _log_revocation_degraded(exc_info: bool = False) -> None:
    """Redis 黑名单校验降级（fail-open）时记录 critical 日志（60 秒时间窗限频）"""
    global _last_revocation_critical_at
    now = time.monotonic()
    if now - _last_revocation_critical_at < _REVOCATION_CRITICAL_INTERVAL:
        return
    _last_revocation_critical_at = now
    logger.critical(
        "Redis 黑名单校验不可用，token 撤销检查降级为本地缓存（fail-open），已撤销的 token 可能被放行",
        exc_info=exc_info,
    )


async def is_token_revoked(jti: str | None, *, fail_closed: bool = False) -> bool:
    """检查 token 是否已被撤销（在黑名单中）

    Redis 不可用时降级到本地 LRU 缓存：
    - 本地缓存命中则返回 True（已撤销）
    - 本地缓存未命中：
      - fail_closed=True（敏感端点）：抛出 401 拒绝请求（fail-closed）
      - fail_closed=False（默认）：返回 False 放行（fail-open），并记录限频 critical 日志
    本地缓存是进程级的，多 worker 间不共享，作为降级方案可接受。
    """
    if not jti:
        return False
    try:
        from fastapi_app.core.redis_wrapper import get_client, note_command_success

        redis = get_client()
        if redis:
            revoked = bool(await redis.exists(f"token_blacklist:{jti}"))
            note_command_success()
            return revoked
        # Redis 客户端未初始化，降级到本地 LRU 缓存
        if _LOCAL_REVOKED_JTIS.contains(jti):
            return True
        if fail_closed:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='令牌状态校验不可用，请重新登录')
        _log_revocation_degraded()
        return False
    except HTTPException:
        raise
    except Exception as e:  # defensive: Redis 不可用时降级到本地 LRU 缓存
        # 告知缓存管理器（连接类错误会降级并短路后续请求，见 _note_redis_failure）
        _note_redis_failure(e)
        if _LOCAL_REVOKED_JTIS.contains(jti):
            return True
        if fail_closed:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='令牌状态校验不可用，请重新登录') from None
        _log_revocation_degraded(exc_info=True)
        return False
