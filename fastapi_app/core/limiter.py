"""限流器实例（独立模块，避免循环导入）

main.py 导入 api_router → endpoints → main.py 会形成循环导入，
因此将 limiter 单例抽离到本模块。endpoints 直接从此处导入 limiter 即可。

main.py 导入后可按需覆盖 limiter.key_func（例如使用基于 user_id 的限流键）。

内网环境宽松配置：
- 全局限流关闭（enabled=False），避免内网正常操作被误拦截
- 各端点装饰器（@limiter.limit）同步失效
- Redis 不可用时自动回退到进程内存限流（此时多 worker 间不再共享计数）
"""
import os
import threading
import time
import warnings

from slowapi import Limiter
from slowapi.util import get_remote_address

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Config file .* not found")
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["60/minute"],
        enabled=False,  # 内网环境关闭全局限流
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