"""共享 Redis 客户端必须有超时与关停释放（评审 2026-10-10 P1-7）。

背景：core/redis_client.py 的 aioredis.from_url(url) 裸建连接，无
socket_timeout/socket_connect_timeout —— Redis 挂起（而非拒绝）时，
备份进度 WebSocket 等消费方可无限阻塞；且客户端无 aclose，进程关停
泄漏连接。修法：from_url 带双超时；新增 close_async_redis_client()
并在 main.py 关停序调用。
"""
import ast
from pathlib import Path

import fastapi_app.core.redis_client as rc


def test_from_url_passes_socket_timeouts():
    """from_url 调用必须带 socket_timeout 与 socket_connect_timeout。"""
    src = Path(rc.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "from_url"
    ]
    assert calls, "未找到 from_url 调用"
    names = {kw.arg for kw in calls[0].keywords}
    assert "socket_timeout" in names, "from_url 缺 socket_timeout —— Redis 挂起时消费方无限阻塞"
    assert "socket_connect_timeout" in names, "from_url 缺 socket_connect_timeout"
    assert "max_connections" in names


def test_close_helper_exists_and_called_at_shutdown():
    """必须有 close_async_redis_client，且 main.py 关停序调用它。"""
    assert hasattr(rc, "close_async_redis_client"), (
        "redis_client 缺 close_async_redis_client —— 关停泄漏连接"
    )
    main_src = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
    assert "close_async_redis_client" in main_src, (
        "main.py 关停序未调用 close_async_redis_client"
    )
