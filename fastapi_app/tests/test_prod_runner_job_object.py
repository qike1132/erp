"""Windows Job Object（kill-on-close）回归锁：监督器怎么死都不许留孤儿。

2026-10-26 连续四次孤儿事件的根因：

- NSSM 的 `erp-prod` 服务参数是 ``AppNoConsole=1`` → **没有控制台** →
  ``SetConsoleCtrlHandler`` 永远收不到控制台事件 → 停机时 ``shutdown()`` 根本不会被调用；
- NSSM 未开 ``AppKillProcessTree`` → 它不杀子进程树；
- 于是 NSSM ``TerminateProcess`` 掉监督器，uvicorn 主进程 + 8 个 worker 变成**孤儿**，
  继续占着 :5002。Windows 的 ``SO_REUSEADDR`` 允许新实例再绑同一端口 →
  **两个 LISTEN 并存** → 连接被随机分给其中一方 → 接口偶发挂死。

Job Object 的 ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` 从根上解决：成员随作业句柄关闭
被操作系统连带杀掉，**监督器无论怎么死都不会留孤儿**。

本文件锁三件事：
1. 作业句柄关闭 → 成员进程被杀；
2. 子进程自动继承作业归属（worker 也被连带回收）；
3. 作业不可用时安静退回原路径（不阻断生产）。
"""
from __future__ import annotations

import os
import sys
import time

import psutil
import pytest

from fastapi_app.core import prod_runner as pr

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Job Object 仅 Windows")


def _spawn_sleeper() -> psutil.Popen:
    """拉起一个只睡不动的子进程（psutil.Popen 与 subprocess.Popen 同源）。"""
    return psutil.Popen([sys.executable, "-c", "import time; time.sleep(120)"])


def test_job_close_kills_member_processes():
    """关闭作业句柄 → 成员必须被杀（等价于「监督器被 TerminateProcess」）。"""
    job = pr._create_kill_on_close_job()
    assert job, "无法创建 kill-on-close 作业"
    proc = _spawn_sleeper()
    try:
        assert pr._assign_to_job(job, proc), "加入作业失败"
        assert proc.poll() is None
        pr._close_job(job)   # 触发 kill-on-close
        deadline = time.monotonic() + 10
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.2)
        assert proc.poll() is not None, "关闭作业后成员仍在运行——孤儿没被根治"
    finally:
        if proc.poll() is None:
            proc.kill()
        pr._close_job(job)


def test_member_children_inherit_job_membership():
    """孙进程（uvicorn 的 worker）自动继承作业归属 → 父被连带杀掉时一起死。"""
    job = pr._create_kill_on_close_job()
    assert job
    proc = psutil.Popen(
        [sys.executable, "-c",
         "import subprocess, sys, time; "
         "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
         "time.sleep(120)"],
    )
    try:
        assert pr._assign_to_job(job, proc)
        time.sleep(2.0)  # 等它把孙进程拉起来
        pr._close_job(job)
        deadline = time.monotonic() + 10
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.2)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
        pr._close_job(job)


def test_job_unavailable_is_non_fatal():
    """作业不可用时安静退回原清理路径，不得阻断生产。"""
    assert pr._assign_to_job(None, None) is False
    assert pr._close_job(None) is None
    assert pr._close_job(0) is None
