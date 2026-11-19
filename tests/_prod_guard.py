"""压测/性能脚本的写操作守卫（fail-closed）。

2026-10-17 审计 F-TEST-BE-TOP-02：tests/stress 下 15 个脚本硬编码
BASE_URL = "http://127.0.0.1:5002"（本机生产 uvicorn 回环口），除 stress_test.py
外的脚本没有任何守卫，一条命令即向生产灌真实建单请求。

本模块是 stress_test.py:769-774 守卫的共享版：
回环/空主机 + 未显式设置允许环境变量 → 直接终止进程。
"""
import ipaddress
import os
import re
from urllib.parse import urlparse

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1", ""}


def _is_blocked_host(host: str) -> bool:
    """回环 / 未指定地址判定。

    2026-11-19（审计 2.3 补测时发现）：只比对字面量集合会漏掉 IPv6 的**长写**与其它等价
    形式 —— ``urlparse('http://[0:0:0:0:0:0:0:1]:5002').hostname`` 给的是
    ``'0:0:0:0:0:0:0:1'``，不在集合里，于是守卫把「本机生产」当成「专门的压测环境」放行。
    ``ipaddress`` 归一化后覆盖长写/IPv4-mapped（``::ffff:127.0.0.1``）；另外处理 FQDN
    尾点（``localhost.``）与省略写法（``127.1``，``ipaddress`` 不接受但系统解析器认）。
    """
    host = host.rstrip('.') or host
    if host in _LOOPBACK_HOSTS:
        return True
    if re.fullmatch(r'127(?:\.\d{1,3}){1,3}', host):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if address.is_loopback or address.is_unspecified:
        return True
    mapped = getattr(address, 'ipv4_mapped', None)
    return mapped is not None and (mapped.is_loopback or mapped.is_unspecified)


def require_non_production(base_url: str, *, env_var: str = "STRESS_TEST_ALLOW_PROD") -> None:
    """base_url 指向回环地址且未显式允许时，终止进程（fail-closed）。

    对非回环地址（如专门的压测环境主机）不做拦截——守卫只针对
    「默认值即生产回环口」这一事故形状。
    """
    host = (urlparse(base_url).hostname or "").lower()
    if _is_blocked_host(host) and os.getenv(env_var) != "1":
        raise SystemExit(
            f"拒绝运行：base_url={base_url} 指向本机（生产）。"
            f" 确认要对该环境执行写操作时，请显式设置 {env_var}=1。"
        )


def mask_dsn(dsn: str) -> str:
    """隐去 DSN 中的口令，用于异常/日志输出（不得把生产密码打进 CI 日志）。"""
    try:
        parsed = urlparse(dsn)
    except ValueError:
        return "<unparsable-dsn>"
    if not parsed.password:
        return dsn
    return dsn.replace(f":{parsed.password}@", ":***@")


def require_non_production_database(
    database_url: str, *, env_var: str = "PERF_TEST_ALLOW_PROD_DB",
) -> None:
    """DATABASE_URL 不指向 ``*_test`` 库且未显式允许时，终止进程（fail-closed）。

    2026-11-03 审查 S4：``tests/qa/performance_benchmark.py`` 与 ``_bench.py`` 在
    **import 时**就 ``create_engine(settings.DATABASE_URL)``，而本机 DATABASE_URL
    指向生产库——一条 ``python tests/qa/performance_benchmark.py`` 就是对生产库发查询，
    绕过了 ``tests/stress`` 自 2026-10-17 起建立的 require_non_production 纪律。

    与 ``tests/e2e_api/conftest.py`` 的库名口径一致：**任何** ``*_test`` 库都放行，
    其余一律拒绝（不写死 erp_system_test，避免把 erp_system_e2e_test 误判成生产）。
    """
    try:
        database = (urlparse(database_url).path or "").lstrip("/").rstrip("/")
    except ValueError:
        database = ""
    if not database.endswith("_test") and os.getenv(env_var) != "1":
        raise SystemExit(
            f"拒绝运行：DATABASE_URL 指向的库 {database!r} 不是 *_test 库"
            f"（{mask_dsn(database_url)}）。"
            f" 确认要对非测试库执行只读基准时，请显式设置 {env_var}=1。"
        )
