"""资源指标适配器 — 实现 domain.ports.MetricsPort。

迁移来源（server_manager.py v6 MetricsSampler）：2s 采样 CPU / 内存 / 磁盘 /
网络速率 / 进程 Top5。psutil 缺失时 sample() 返回 None（由调用方降级，
不抛异常 —— ports.py 契约明文规定）。
"""

from __future__ import annotations

import threading
import time

from server_manager_v8.domain import MetricsSample

__all__ = ['MetricsSamplerLoop', 'PsutilMetricsAdapter']

try:
    import psutil
except ImportError:  # pragma: no cover - 依赖可选
    psutil = None

_DISK_CACHE_TTL = 30.0  # 磁盘采样开销大，30s 缓存（v6 语义）


class PsutilMetricsAdapter:
    """psutil 采样适配器。采样线程由 Application 层驱动。"""

    def __init__(self, project_dir: str = '') -> None:
        self._project_dir = project_dir or ''
        self._last_net = None
        self._last_ts: float | None = None
        self._disk_cache: tuple[float, float | None] = (0.0, None)

    def available(self) -> bool:
        return psutil is not None

    def sample(self) -> MetricsSample | None:
        if psutil is None:
            return None
        now = time.time()
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory().percent
            disk = self._disk_percent(now)
            dn_mb, up_kb = self._net_rates(now)
            procs = self._top_procs(limit=5)
        except (psutil.Error, OSError):
            return None
        return MetricsSample(
            cpu=round(cpu, 1),
            mem=round(mem, 1),
            disk=round(disk, 1),
            net_dn_mb=round(dn_mb, 2),
            net_up_kb=round(up_kb, 1),
            procs=procs,
        )

    # ---- 内部 ----

    def _disk_percent(self, now: float) -> float:
        cached_ts, cached = self._disk_cache
        if cached is None or now - cached_ts > _DISK_CACHE_TTL:
            target = self._project_dir or '.'
            cached = psutil.disk_usage(target).percent  # type: ignore[union-attr]
            self._disk_cache = (now, cached)
        return cached or 0.0

    def _net_rates(self, now: float) -> tuple[float, float]:
        net = psutil.net_io_counters()  # type: ignore[union-attr]
        dn = up = 0.0
        if self._last_net is not None and self._last_ts:
            dt = max(0.2, now - self._last_ts)
            dn = max(0.0, (net.bytes_recv - self._last_net.bytes_recv) / dt / 1024 / 1024)
            up = max(0.0, (net.bytes_sent - self._last_net.bytes_sent) / dt / 1024)
        self._last_net, self._last_ts = net, now
        return dn, up

    @staticmethod
    def _top_procs(*, limit: int = 5) -> tuple[tuple[str, float, float], ...]:
        if psutil is None:
            return ()
        rows: list[tuple[str, float, float]] = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):  # type: ignore[union-attr]
            try:
                info = proc.info
                name = info.get('name') or ''
                cpu_pct = info.get('cpu_percent')
                mem_pct = info.get('memory_percent') or 0.0
                if cpu_pct is None:
                    continue
                rows.append((f'{name} ({info.get("pid")})', float(cpu_pct), float(mem_pct)))
            except (psutil.NoSuchProcess, psutil.AccessDenied):  # type: ignore[union-attr]
                continue
        rows.sort(key=lambda row: row[1], reverse=True)
        return tuple(rows[:limit])


class MetricsSamplerLoop:
    """2s 采样循环（v6 MetricsSampler 迁移）：后台线程驱动回调，可停止。"""

    INTERVAL = 2.0

    def __init__(self, adapter: PsutilMetricsAdapter, on_sample) -> None:
        self._adapter = adapter
        self._on_sample = on_sample
        self._stop = threading.Event()

    def start(self) -> None:
        self._stop = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        if self._adapter.available():
            self._adapter.sample()  # 建立 cpu_percent 基线（v6 语义：首次返回 0）
        while not self._stop.wait(self.INTERVAL):
            sample = self._adapter.sample()
            if sample is not None:
                self._on_sample(sample)
