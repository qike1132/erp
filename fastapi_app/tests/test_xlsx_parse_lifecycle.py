"""M1 回归锁：XLSX 解析的线程与临时文件生命周期必须闭环。

背景（2026-10-26 上线前检查 M1）
-------------------------------
`asyncio.wait_for` 对同步解析线程只是**停止等待**，线程会继续跑。原实现：

* 解析走默认 executor（与 `asyncio.to_thread` 共用），病态解析会饿死同进程其它
  线程池调用；
* 超时返回后没有任何「线程真实结束」的信号，临时文件在 `finally` 里立刻删，
  Windows 上因仍被占用而删除失败，只留一条 WARNING —— 文件静静留在 %TEMP%。

修复：专用有界线程池 + `pending_parse_count()` 可观测 + `cleanup` 在线程**真正
结束**后执行 + 删除重试。本文件用**真实的**不可取消同步阻塞（threading.Event）
验证，不用可取消协程模拟。
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from fastapi_app.services import batch_import_parser, xlsx_budget
from fastapi_app.services.xlsx_budget import (
    XlsxBudgetError,
    pending_parse_count,
    run_sync_with_timeout,
)


def _wait_until(predicate, *, timeout: float = 5.0) -> bool:
    """同步等待（用于回调在线程中触发的断言）。"""
    deadline = threading.Event()
    waited = 0.0
    while waited < timeout:
        if predicate():
            return True
        deadline.wait(0.02)
        waited += 0.02
    return predicate()


@pytest.mark.asyncio
async def test_parse_runs_on_dedicated_bounded_pool():
    """解析必须离开默认 executor：线程名带专用前缀，避免抢占 to_thread 的池。"""
    seen = {}

    def _fn():
        seen['thread'] = threading.current_thread().name
        return 'ok'

    assert await run_sync_with_timeout(_fn, timeout=5) == 'ok'
    assert seen['thread'].startswith('xlsx-parse'), seen


@pytest.mark.asyncio
async def test_timeout_returns_early_but_tracks_real_completion():
    """超时立即失败，但线程终态仍可跟踪；cleanup 只在线程真正结束后执行。"""
    release = threading.Event()
    finished = threading.Event()
    cleaned = threading.Event()

    def _blocking():
        release.wait(10)  # 真实、不可取消的同步阻塞
        finished.set()
        return 'late'

    with pytest.raises(XlsxBudgetError, match='超时'):
        await run_sync_with_timeout(
            _blocking, timeout=0.05, cleanup=cleaned.set,
        )

    assert pending_parse_count() >= 1, '超时返回后线程仍在跑，必须可见'
    assert not cleaned.is_set(), 'cleanup 不得在超时返回时提前执行（文件仍被占用）'

    release.set()
    assert await asyncio.to_thread(_wait_until, finished.is_set), '阻塞线程应已结束'
    assert await asyncio.to_thread(_wait_until, cleaned.is_set), \
        'cleanup 必须在线程真实结束后执行（否则 Windows 上删不掉临时文件）'
    assert await asyncio.to_thread(_wait_until, lambda: pending_parse_count() == 0)


@pytest.mark.asyncio
async def test_cleanup_runs_normally_on_success():
    calls = []

    assert await run_sync_with_timeout(lambda: 1, timeout=5, cleanup=lambda: calls.append(1)) == 1
    assert await asyncio.to_thread(_wait_until, lambda: calls == [1])


def test_cleanup_temp_file_retries_while_file_is_busy(tmp_path, monkeypatch):
    """Windows「文件被占用」是瞬时状态：必须重试，而不是删除一次失败就放过。"""
    target = tmp_path / 'upload.xlsx'
    target.write_bytes(b'x')
    real_unlink = xlsx_budget.os.unlink
    attempts = {'n': 0}

    def _flaky_unlink(path, *a, **k):
        attempts['n'] += 1
        if attempts['n'] < 3:
            raise PermissionError('file in use')
        return real_unlink(path, *a, **k)

    monkeypatch.setattr(batch_import_parser.os, 'unlink', _flaky_unlink)

    assert batch_import_parser.cleanup_temp_file(str(target), attempts=5, delay=0) is True
    assert not target.exists()
    assert attempts['n'] == 3


def test_cleanup_temp_file_reports_final_failure(tmp_path, caplog):
    # 目录无法被 unlink（两个平台都稳定抛 OSError），用它代替真实文件占用来构造
    # 「怎么删都删不掉」，避免 monkeypatch 全局 os.unlink 影响 pytest 自身。
    target = tmp_path / 'locked.xlsx'
    target.mkdir()

    with caplog.at_level('ERROR'):
        assert batch_import_parser.cleanup_temp_file(str(target), attempts=2, delay=0) is False

    assert any('清理临时文件失败' in r.getMessage() for r in caplog.records), \
        '最终失败必须 ERROR 留痕（否则临时文件无声堆积）'


@pytest.mark.asyncio
async def test_save_uploaded_file_cleans_up(tmp_path):
    class _File:
        filename = 'a.xlsx'

        async def read(self, _n):
            return b'PK\x03\x04data'

    async with batch_import_parser._save_uploaded_file(_File()) as path:
        assert await asyncio.to_thread(lambda: __import__('os').path.exists(path))
    assert not await asyncio.to_thread(lambda: __import__('os').path.exists(path))
