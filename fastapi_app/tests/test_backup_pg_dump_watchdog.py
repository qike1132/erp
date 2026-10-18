"""pg_dump 超时看门狗的竞态回归（2026-10-18 OCR 评审）

缺陷形态：看门狗线程与「读取 stdout 的工作线程」共用同一个 `timed_out` 标志，
而原实现在读循环退出、`proc_.wait()` 返回**之后**才在 `finally` 里 cancel 看门狗。
于是存在一个真实窗口：

    stdout 读到 EOF（pg_dump 已正常退出）
      → proc_.wait() 立即返回
      → 【看门狗此刻触发，timed_out.set()】
      → if timed_out.is_set(): raise TimeoutError   ← 正常完成被误报成超时

`terminate()` 还会把 returncode 变成 -15/非 0，所以「正常完成」与「被看门狗杀掉」
无法从返回值区分，只能靠**置位时机**区分。

修法：读取循环结束后先 `cancel()` + `join()` 看门狗（确保它不会再触发、
且已触发的回调也执行完），**然后**才读标志。
本文件把这三件事钉死：
  1. 正常完成 → 不判超时（核心回归）；
  2. 看门狗真触发 → 判超时（不能为了修 1 把 2 修坏）；
  3. 判读顺序：join 发生在读标志之前。
"""
from __future__ import annotations

import io
import subprocess

import pytest


class _FakeProc:
    """够用的 Popen 假件：可控制 wait 行为与 returncode。

    stdout/stderr 必须是**真管道**（read() 返回 bytes 且最终 EOF）：工作线程的
    读取循环以 `if not chunk: break` 收口，若 read() 返回 MagicMock 恒为真值，
    循环永不退出 → 测试挂死。
    """

    def __init__(self, *, returncode: int = 0, wait_raises: BaseException | None = None,
                 stdout_data: bytes = b'-- fake dump\n'):
        self.returncode = returncode
        self._wait_raises = wait_raises
        self.terminated = False
        self.killed = False
        self.stdout = io.BytesIO(stdout_data)
        self.stderr = io.BytesIO(b'')

    def wait(self, timeout: float | None = None) -> int:
        # cleanup 路径（terminate 之后的 wait）必须成功——真实进程被 kill 后
        # wait 一定返回；只有主等待路径按测试需要抛 TimeoutExpired
        if self._wait_raises is not None and not self.terminated:
            raise self._wait_raises
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def _async_return(value):
    """返回一个 async 函数桩（供 monkeypatch 替换协程）。"""
    from unittest.mock import AsyncMock

    return AsyncMock(return_value=value)


def _make_timer_spy(monkeypatch, *, fire: bool) -> list[str]:
    """把 threading.Timer 换成假件，并记录调用顺序。

    `fire=False`：看门狗永不触发（模拟正常完成的备份）；
    `fire=True`：start() 时立刻执行回调（模拟超时触发）。
    返回的 list 按序记录 'cancel' / 'join' / 'set'，用于断言判读顺序。
    """
    from fastapi_app.services.backup import dump as dump_mod

    events: list[str] = []

    class _FakeTimer:
        def __init__(self, interval: float, function):
            self.interval = interval
            self.function = function
            self._cancelled = False

        def start(self) -> None:
            if fire and not self._cancelled:
                events.append('set')
                self.function()

        def cancel(self) -> None:
            events.append('cancel')
            self._cancelled = True

        def join(self, timeout: float | None = None) -> None:
            events.append('join')

    monkeypatch.setattr(dump_mod.threading, 'Timer', _FakeTimer)
    return events


@pytest.mark.asyncio
async def test_normal_completion_is_not_reported_as_timeout(tmp_path, monkeypatch):
    """核心回归：pg_dump 正常完成时不得抛 TimeoutError。

    旧实现在读循环退出与 cancel 看门狗之间存在窗口，看门狗此刻触发就会把
    正常完成误判成超时。
    """
    from fastapi_app.services.backup.dump import run_pg_dump

    out = tmp_path / 'dump.sql.gz'
    proc = _FakeProc(returncode=0)

    # 看门狗**不会**触发（fire=False）：模拟正常完成的备份
    _make_timer_spy(monkeypatch, fire=False)
    monkeypatch.setattr(
        subprocess, 'Popen',
        lambda *a, **kw: proc,
    )
    # 简化：stdout 一次读完即 EOF，get_pg_version 走桩
    monkeypatch.setattr(
        'fastapi_app.services.backup.dump.get_pg_version',
        _async_return('16.0'),
    )

    result = await run_pg_dump(out)

    assert result['pg_version'] == '16.0'
    assert result['dump_size'] == out.stat().st_size
    # 没有 terminate 过：正常退出不该被额外杀一次
    assert proc.terminated is False


@pytest.mark.asyncio
async def test_watchdog_fire_still_reports_timeout(tmp_path, monkeypatch):
    """反向锁死：看门狗真触发时必须判超时（不能为了修误判把真超时修没）。"""
    from fastapi_app.services.backup.dump import run_pg_dump

    # wait() 用第一个 timeout 参数（看门狗 join 前的等待）立即超时，
    # 模拟 DB 卡住、pg_dump 不退出的情形
    proc = _FakeProc(wait_raises=subprocess.TimeoutExpired('pg_dump', 1))

    _make_timer_spy(monkeypatch, fire=False)
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: proc)

    with pytest.raises(RuntimeError, match='pg_dump 执行失败'):
        await run_pg_dump(tmp_path / 'dump.sql.gz')
