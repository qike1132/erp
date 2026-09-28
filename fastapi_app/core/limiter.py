"""限流器实例（独立模块，避免循环导入）

main.py 导入 api_router → endpoints → main.py 会形成循环导入，
因此将 limiter 单例抽离到本模块。endpoints 直接从此处导入 limiter 即可。

main.py 导入后可按需覆盖 limiter.key_func（例如使用基于 user_id 的限流键）。
线上 key_func 已按 **user_id** 限流、未登录才退回 IP，故内网多用户共享出口 IP
不会互相拖累。

开关（2026-09-28 上线前审计修复）：
- 默认**开启**。此前 `enabled=False` 把**所有** `@limiter.limit(...)` 装饰器都变成
  空操作 —— auth / report / stock / daily_production 上写好的限流全部静默失效。
- 排障时可设 `RATE_LIMIT_ENABLED=false` 临时关闭（例如定位误拦时）。
- Redis 不可用时自动回退到进程内存限流（此时多 worker 间不再共享计数）。
"""
import os
import threading
import time
import warnings

from slowapi import Limiter
from slowapi.util import get_remote_address


def limiter_enabled_from_env() -> bool:
    """限流开关：默认开启；仅显式的假值（false/0）才关闭。

    空值与无法识别的取值一律按**开启**处理 —— 限流失效是安全问题，
    不该因为环境变量写错而静默关闭。
    """
    return os.getenv('RATE_LIMIT_ENABLED', 'true').strip().lower() not in ('false', '0')


def limiter_default_limits_from_env() -> list[str]:
    """全局默认限流：**默认空**，即「只对显式标注 @limiter.limit 的端点限流」。

    为什么不直接启用原值 `60/minute`：该值写下来后限流长期被 `enabled=False` 架空，
    **从未在真实流量下验证过**。按用户计 60 次/分钟，正常用户快速浏览（每页多次
    API 调用）就可能触顶 —— 上线日给用户弹 429 比不限流更糟。实测：开启该全局值后，
    单次后端测试会话就产生了 172 次 429。

    需要时用环境变量显式开启，观察无误拦后再逐步收紧：
        RATE_LIMIT_DEFAULT=300/minute
    """
    raw = os.getenv('RATE_LIMIT_DEFAULT', '').strip()
    return [raw] if raw else []


with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Config file .* not found")
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=limiter_default_limits_from_env(),
        enabled=limiter_enabled_from_env(),
        config_filename=os.devnull,
        storage_uri=os.getenv("REDIS_CACHE_URL") or "memory://",
        in_memory_fallback_enabled=True,
        in_memory_fallback=["60/minute"],
    )


class MemorySlidingWindowLimiter:
    """进程内滑动窗口限流器（Redis 故障时的轻量降级存储）

    每个 key 维护一个时间戳列表，仅统计窗口内的命中次数；
    被拒绝的请求同样计数（与 Redis incr 行为一致，防止锁定期内被绕过）。
    多 worker 间不共享，仅提供进程级防护。
    """

    # 桶数量上限，超过后清理长期不活跃的桶，防止内存无限膨胀
    MAX_BUCKETS = 10000
    # 桶的最后命中早于该秒数视为不活跃（取值需大于业务最大窗口）
    STALE_BUCKET_SECONDS = 600.0

    def __init__(self):
        self._buckets: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, window: float, limit: int) -> bool:
        """记录一次请求，返回是否在限额内（超限的请求同样计数）"""
        now = time.monotonic()
        cutoff = now - window
        with self._lock:
            timestamps = [t for t in self._buckets.get(key, ()) if t > cutoff]
            timestamps.append(now)
            self._buckets[key] = timestamps
            self._cleanup(now)
            return len(timestamps) <= limit

    def _cleanup(self, now: float) -> None:
        """桶数超上限时清理长期不活跃的桶；仍超限则移除最早写入的桶"""
        if len(self._buckets) <= self.MAX_BUCKETS:
            return
        stale_cutoff = now - self.STALE_BUCKET_SECONDS
        for k in [k for k, ts in self._buckets.items() if ts[-1] <= stale_cutoff]:
            del self._buckets[k]
        while len(self._buckets) > self.MAX_BUCKETS:
            self._buckets.pop(next(iter(self._buckets)))


# 进程内存降级限流器实例（Redis 故障时由各端点显式使用）
memory_limiter = MemorySlidingWindowLimiter()
