"""系统指标采集适配器 —— psutil 封装，缺失时降级。

═══════════════════════════════════════════════════════════════════
★ 核心保真点：`None` 不等于「全 0 的样本」
═══════════════════════════════════════════════════════════════════

这是本模块最容易被「顺手优化」掉的地方，单独讲清。

旧实现的问题：psutil 缺失时把指标当作 0 展示 —— 界面上 CPU 0% / 内存 0%，
运维看到的是「一切正常」，实际是「什么都没测到」。这是**静默失败**的
一个典型变体：不是没输出，而是输出了一个看起来正常的假值。

本实现严格区分两种状态：

    MetricsSample(cpu_percent=0.0, ...)   → 「我观测到 CPU 是 0%」
    None                                   → 「我测不到（psutil 没装）」

前端与告警判定都必须按这个区分分支处理（显示「指标不可用」而非 0%）。

═══════════════════════════════════════════════════════════════════
采样频率与 CPU 首次读数的陷阱
═══════════════════════════════════════════════════════════════════

`psutil.cpu_percent()` 是**有状态**的：首次调用（`interval=None`）返回
自模块加载以来的平均值，通常是无意义的数字。正确做法是：
    · 第一次调用只做「预热」，丢弃返回值
    · 或传 `interval` 让 psutil 内部阻塞采样

本实现采用**预热法**（`prime()`），因为它不阻塞 —— 采样线程要保持 2s 节拍，
在采样函数里阻塞 1 秒会打乱节奏。

`prime()` 需要在**应用启动时调用一次**（container 装配阶段）。
"""

from __future__ import annotations

import time
from typing import Any

from ..domain.results import MetricsSample

#: 采样间隔（v8 方案 §3.2「2s 采样」）
DEFAULT_SAMPLE_INTERVAL_S = 2.0

try:  # pragma: no cover - 环境相关
    import psutil
except Exception:  # pragma: no cover
    psutil = None  # type: ignore[assignment]


def available() -> bool:
    """psutil 是否可用。"""
    return psutil is not None


class PsutilMetrics:
    """基于 psutil 的指标采集。

    实现 `domain.ports.MetricsPort`。
    """

    def __init__(self, *, clock: Any = None) -> None:
        # clock 只用于给样本打时间戳。默认直接用 time.time 是因为
        # 时间戳是**数据**不是**时序控制**，不需要注入假时钟来做确定性测试
        # （测试关心的是「有没有采到」，不是「采在第几毫秒」）。
        self._clock = clock or time.time
        self._primed = False

    def available(self) -> bool:
        return psutil is not None

    def prime(self) -> None:
        """预热 CPU 计数器（应用启动时调一次）。

        必须在第一次 `sample()` 之前调用，否则首个样本的 cpu_percent
        是「自 psutil 模块加载以来」的平均值 —— 一个没有意义的数字。
        """
        if psutil is None:
            return
        try:
            psutil.cpu_percent(interval=None)
            self._primed = True
        except Exception:  # noqa: BLE001 —— 预热失败不致命，后续照常采
            self._primed = False

    def sample(self) -> MetricsSample | None:
        """采一次指标。

        psutil 不可用 → 返回 `None`（**不是全 0 样本**，见模块 docstring）。
        采集过程中抛异常 → 同样返回 None，但把异常文本放进 detail
        （下次可尝试通过 `last_error` 取出，供 UI 提示用）。
        """
        if psutil is None:
            return None

        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()

            # 进程数用 len(psutil.pids()) 而不是 cpu_count() ——
            # 后者是核数，跟「当前有多少进程」完全不是一回事
            procs = len(psutil.pids())

            return MetricsSample(
                ts=float(self._clock()),
                cpu_percent=float(cpu),
                mem_percent=float(mem.percent),
                mem_rss_mb=float(self._used_mb(mem)),
                procs=int(procs),
            )
        except Exception as exc:  # noqa: BLE001
            # 采集失败返回 None（而不是 0 样本），失败原因留在 detail 供诊断。
            # 这里**不抛出** —— 采样线程不能因单次失败而死掉。
            self._last_error = f'{type(exc).__name__}: {exc}'
            return None

    @staticmethod
    def _used_mb(mem: Any) -> float:
        """已用内存 MB。

        用 `total - available` 而非 `used`：
        `psutil.virtual_memory().used` 在 Windows 上不含缓存/缓冲，
        与任务管理器显示的「使用中」口径不一致，用户会质疑数字。
        `total - available` 与 Windows 任务管理器的「使用中」基本对齐。
        """
        total = getattr(mem, 'total', 0) or 0
        avail = getattr(mem, 'available', 0) or 0
        return max(0.0, (total - avail) / (1024 * 1024))

    @property
    def last_error(self) -> str:
        """最近一次采集失败的原因（空串表示无失败记录）。"""
        return getattr(self, '_last_error', '')


__all__ = [
    'DEFAULT_SAMPLE_INTERVAL_S',
    'PsutilMetrics',
    'available',
]
