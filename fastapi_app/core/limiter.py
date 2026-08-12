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