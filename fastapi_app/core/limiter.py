"""限流器实例（独立模块，避免循环导入）

main.py 导入 api_router → endpoints → main.py 会形成循环导入，
因此将 limiter 单例抽离到本模块。endpoints 直接从此处导入 limiter 即可。

main.py 导入后可按需覆盖 limiter.key_func（例如使用基于 user_id 的限流键）。
"""
import os
import warnings

from slowapi import Limiter
from slowapi.util import get_remote_address

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Config file .* not found")
    # Redis 分布式限流：解决多 worker 下 slowapi 内存计数漂移问题
    # Redis 不可用时自动回退到进程内存限流（此时多 worker 间不再共享计数）
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["60/minute"],
        enabled=True,
        config_filename=os.devnull,
        storage_uri=os.getenv("REDIS_CACHE_URL") or "memory://",
        in_memory_fallback_enabled=True,
        in_memory_fallback=["60/minute"],
    )