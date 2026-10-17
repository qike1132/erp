"""压测/性能脚本的写操作守卫（fail-closed）。

2026-10-17 审计 F-TEST-BE-TOP-02：tests/stress 下 15 个脚本硬编码
BASE_URL = "http://127.0.0.1:5002"（本机生产 uvicorn 回环口），除 stress_test.py
外的脚本没有任何守卫，一条命令即向生产灌真实建单请求。

本模块是 stress_test.py:769-774 守卫的共享版：
回环/空主机 + 未显式设置允许环境变量 → 直接终止进程。
"""
import os
from urllib.parse import urlparse

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1", ""}


def require_non_production(base_url: str, *, env_var: str = "STRESS_TEST_ALLOW_PROD") -> None:
    """base_url 指向回环地址且未显式允许时，终止进程（fail-closed）。

    对非回环地址（如专门的压测环境主机）不做拦截——守卫只针对
    「默认值即生产回环口」这一事故形状。
    """
    host = (urlparse(base_url).hostname or "").lower()
    if host in _LOOPBACK_HOSTS and os.getenv(env_var) != "1":
        raise SystemExit(
            f"拒绝运行：base_url={base_url} 指向本机（生产）。"
            f" 确认要对该环境执行写操作时，请显式设置 {env_var}=1。"
        )
