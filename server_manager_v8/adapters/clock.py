"""时钟适配器 —— 为领域层提供真实时间与睡眠。

═══════════════════════════════════════════════════════════════════
为什么时钟也算「适配器」
═══════════════════════════════════════════════════════════════════

`domain.readiness.wait_until` 的签名要求调用方注入 `clock` 与 `sleep`：

    wait_until(predicate, policy, *, clock, sleep, aborted=None, observe=None)

领域层因此零 I/O、可 100% 单测（用假时钟做毫秒级确定性验证）。
但**生产运行时**总得有人提供真实时间 —— 那就是本模块。

这是「把不可控依赖变成注入参数」这条原则的落地端：
    领域层定义「我需要一个返回单调秒数的函数」
    适配层提供「用 time.monotonic 实现的那个函数」

═══════════════════════════════════════════════════════════════════
为什么用 monotonic 而不是 time.time()
═══════════════════════════════════════════════════════════════════

旧实现 `_wait_service_stopped` / `_wait_service_running` 用的就是 `time.monotonic()`，
本模块保持一致。

`time.time()` 是墙钟，会被 NTP 校时 / 手动改系统时间 / 夏令时**向前或向后**拨动。
用它算超时会出现：
    · 时钟被向后拨 → 超时永远不到达 → 等待循环卡死
    · 时钟被向前拨 → 超时立即到达 → 明明服务还在启动就判失败
`monotonic()` 保证只前进，不受校时影响 —— 这正是「超时预算」需要的语义。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable


def monotonic() -> float:
    """单调递增的秒数（不受系统校时影响）。

    供 `domain.readiness.wait_until(clock=monotonic, ...)` 使用。
    """
    return time.monotonic()


def sleep(seconds: float) -> None:
    """睡眠指定秒数。

    供 `domain.readiness.wait_until(sleep=sleep, ...)` 使用。
    """
    time.sleep(seconds)


def perf_counter() -> float:
    """高精度计时器，用于测量耗时（如探针 latency_ms）。"""
    return time.perf_counter()


@dataclass(frozen=True)
class SystemClock:
    """把上面三个函数打包成一个可注入的对象。

    两种用法都支持：
        wait_until(..., clock=real_clock.now, sleep=real_clock.sleep)   # 函数式
        wait_until(..., clock=real_clock, ...)                          # 对象式（需实现 __call__）

    打包的理由：应用层装配时要同时传 clock + sleep，
    分散传两个函数容易在某处漏传一个（漏了 `sleep` 会退化成忙等，
    疯狂占 CPU 却不推进时间）。打包后漏传不可能发生。

    ★ 它**不是** `domain` 的一部分：领域层只认 `Callable[[], float]` 这个形状，
      不认这个类。这保证了领域层对适配层零依赖。
    """

    def monotonic(self) -> float:
        """单调递增秒数（实现 `domain.ports.ClockPort`）。

        ★ 这是 `now()` 的**规范名**。两个名字并存的原因：
          本类早于 `ClockPort` 存在，旧调用点写的是 `now()`。
          保留 `now()` 作为别名以免破坏调用点，但**新代码一律用 `monotonic()`** ——
          因为它明确表达了「这是单调时钟，不是墙钟」，
          而这个区分在超时逻辑里是致命的（见模块 docstring）。

          代价是两个同义方法并存，属于迁移期债务。
          将来旧调用点清理完后，应删掉 `now()` 只留 `monotonic()`。
        """
        return time.monotonic()

    def now(self) -> float:
        """`monotonic()` 的迁移期别名。**新代码不要用**（名字有歧义）。"""
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def perf(self) -> float:
        return time.perf_counter()

    # 让对象本身也能直接当 clock 用
    def __call__(self) -> float:
        return self.monotonic()
