"""`adapters.clock` 的测试。

这个模块很小，但它补齐了 P1 领域层的**注入契约**：
`domain.readiness.wait_until` 要求调用方提供 `clock` 与 `sleep`，
领域层因此零 I/O、可用假时钟确定性地测；

生产运行时总得有人提供真实时间 —— 就是本模块。
"""

from __future__ import annotations

import time

import pytest

from server_manager_v8.adapters import clock as C


class TestMonotonic:
    def test_returns_float(self):
        assert isinstance(C.monotonic(), float)

    def test_never_goes_backwards(self):
        """★ monotonic 的核心性质：只前进，不受 NTP 校时 / 改系统时间影响。

        用 `time.time()` 算超时会出现：
          · 时钟被向后拨 → 超时永远不到达 → 等待循环卡死
          · 时钟被向前拨 → 超时立即到达 → 明明服务还在启动就判失败
        """
        values = [C.monotonic() for _ in range(50)]
        assert all(b >= a for a, b in zip(values, values[1:]))

    def test_matches_time_monotonic(self):
        assert abs(C.monotonic() - time.monotonic()) < 0.5

    def test_usable_as_domain_clock(self):
        """形状兼容：domain.readiness 只认 `Callable[[], float]`。"""
        assert callable(C.monotonic)


class TestSleep:
    def test_actually_sleeps(self):
        start = time.monotonic()
        C.sleep(0.01)
        assert time.monotonic() - start >= 0.005

    def test_accepts_zero(self):
        C.sleep(0)
        C.sleep(0.0)

    def test_usable_as_domain_sleep(self):
        assert callable(C.sleep)


class TestPerfCounter:
    def test_returns_float(self):
        assert isinstance(C.perf_counter(), float)

    def test_high_resolution_available(self):
        """perf_counter 用于测毫秒级耗时（探针 latency）。"""
        a = C.perf_counter()
        time.sleep(0.005)
        b = C.perf_counter()
        assert b > a


class TestSystemClock:
    def test_now_delegates_to_monotonic(self):
        assert abs(C.SystemClock().now() - C.monotonic()) < 0.5

    def test_sleep_delegates(self):
        start = time.monotonic()
        C.SystemClock().sleep(0.01)
        assert time.monotonic() - start >= 0.005

    def test_perf_delegates(self):
        assert abs(C.SystemClock().perf() - C.perf_counter()) < 0.5

    def test_object_is_callable_as_clock(self):
        """`__call__` 让对象本身能直接当 clock 参数传。"""
        obj = C.SystemClock()
        assert callable(obj)
        assert abs(obj() - C.monotonic()) < 0.5

    def test_frozen(self):
        obj = C.SystemClock()
        with pytest.raises(Exception):
            obj.now = lambda: 0.0

    def test_works_with_domain_wait_until(self):
        """★ 端到端：真实时钟 + 已满足的谓词 → 立即成功，不浪费时间。

        这条验证「打包传参」不会因为漏传 sleep 而退化成忙等。
        """
        from server_manager_v8.domain.readiness import WaitStatus, wait_until

        obj = C.SystemClock()
        outcome = wait_until(
            lambda: True,
            clock=obj.now,
            sleep=obj.sleep,
        )
        assert outcome.status is WaitStatus.SATISFIED
        assert outcome.attempts == 1


class TestPackingRationale:
    def test_clock_and_sleep_live_together(self):
        """打包的意义：漏传 sleep 会退化成忙等（疯狂占 CPU 却不推进时间）。

        所以应用层装配时应从这个对象同时取两者。
        """
        obj = C.SystemClock()
        assert hasattr(obj, 'now') and hasattr(obj, 'sleep')

    def test_adapters_package_reexports(self):
        """adapters 包应能直接取到这三个函数（惰性再导出）。"""
        import server_manager_v8.adapters as A

        assert A.monotonic is C.monotonic
        assert A.sleep is C.sleep
        assert A.perf_counter is C.perf_counter
        assert A.SystemClock is C.SystemClock
