"""跨事件循环安全的子进程执行辅助。

背景：Windows 上 uvicorn 工作进程使用 SelectorEventLoop，该循环不支持
asyncio.create_subprocess_exec（抛 NotImplementedError），导致备份 pg_dump /
还原 psql 链路在 API 进程内直接崩溃（ARQ worker 的 Proactor 循环则正常）。
统一改为线程池包装同步 subprocess API，不依赖事件循环的子进程 transport，
在任何事件循环下均可工作。
"""
from __future__ import annotations

import asyncio
import subprocess


async def run_proc(args: list[str], *, env: dict | None = None,
                   timeout: float | None = None) -> subprocess.CompletedProcess:
    """执行子进程并捕获 stdout/stderr；timeout 到期自动 kill 并抛内建 TimeoutError。

    替代 asyncio.create_subprocess_exec + communicate() 组合，
    异常语义与旧实现一致：TimeoutError / OSError / ValueError。
    """
    def _run() -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                args, capture_output=True, env=env, timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(str(e)) from None

    return await asyncio.to_thread(_run)
