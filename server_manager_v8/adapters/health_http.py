"""HTTP 健康探针适配器。

═══════════════════════════════════════════════════════════════════
迁移来源：server_manager.py v5.40
═══════════════════════════════════════════════════════════════════

| 原实现 | 位置 | 迁移为 |
|---|---|---|
| `_OPENER_DIRECT` 全局实例 | L70 | `build_direct_opener()` |
| `_probe_http(url, timeout)` | L1428 | `probe(url)` |

═══════════════════════════════════════════════════════════════════
★ 必须直连本机，绝不走系统代理（2026-09-10 实证的根因）
═══════════════════════════════════════════════════════════════════

本机设置了 `HTTP_PROXY` / `HTTPS_PROXY=127.0.0.1:57562`（代理客户端）且无 `NO_PROXY`。
`urllib` 默认会读取系统代理 —— **包括 Windows 注册表代理设置** ——
于是探测 `127.0.0.1:5002` / `127.0.0.1:3000` 的请求会被路由进代理。

后果（真实发生）：
    代理客户端抖动时健康检查间歇性失败 → `prod_runner` 触发
    「连续失败 20s → 强制重启」的**后端重启风暴**，
    而应用本身完全正常（被杀前 0 秒间隔、业务日志连续）。
    管理器的启动就绪判定同样会被误导。

解法：`ProxyHandler({})` 显式清空代理，保证探针**永远直连**。

这条不是「顺手加的健壮性」，而是针对一个已定位事故的定点修复。
迁入适配层时**必须原样保留**，且要有测试守住（见 tests/adapters/test_health_http.py）。

═══════════════════════════════════════════════════════════════════
为什么返回 HealthSample 而不是 bool
═══════════════════════════════════════════════════════════════════

旧 `_probe_http` 返回 bool（无异常即通过），信息量太低：
探针失败时无法区分「连接被拒」/「超时」/「返回 500」，
而这三种在排障时指向完全不同的方向。

新实现返回 `HealthSample(ok, latency_ms, detail)`，
但**判定语义保持完全一致**：任何异常 → ok=False（与旧实现同）。
即：只要 HTTP 层能拿到响应（即使状态码是 500），旧实现也算「通过」。
这个「宽松」语义是刻意的 —— 探针的目的是「端口是否在响应」，
不是「业务是否健康」（后者由 prod_runner 自身的健康检查负责）。
改动它会让启动就绪判定变严，可能引入「明明起来了却判失败」的新故障。
"""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from ..domain.results import HealthSample as DomainHealthSample

# 默认探针超时（迁移自 `_probe_http(url, timeout=2)`）
DEFAULT_PROBE_TIMEOUT = 2.0


@dataclass(frozen=True)
class HealthSample(DomainHealthSample):
    """一次探针的采样结果。

    ok         : 是否通过（**语义与旧 bool 完全一致**：无异常即 True）
    latency_ms : 耗时（毫秒），用于诊断「慢但能通」与「直接失败」的区别
    status_code: HTTP 状态码（拿不到时为 None）
    detail     : 失败原因摘要（异常类型 + 文本），成功时为空

    ★ P3 起**继承** domain 的同名类型（不再重复定义）。

      为什么是继承而不是别名：本层要给 `latency_ms` 一个**更宽的默认值语义**
      （旧实现用 `time.perf_counter()` 差值，天然是 float）。字段与守卫逻辑
      完全复用 domain 定义，仅在此登记「本实现产出的值来自 perf_counter」。

      为什么不能各自定义两份：`HealthPort.probe()` 返回的类型必须是领域层的，
      否则适配器在语法上无法满足 Protocol。
    """

    ok: bool
    latency_ms: float = 0.0
    status_code: int | None = None
    detail: str = ''

    def __post_init__(self) -> None:
        if not self.ok and not self.detail:
            # 失败必须可诊断（与 domain.readiness 的 WaitOutcome.failure_reason 同一原则）
            raise ValueError('HealthSample 失败时必须提供 detail')


def build_direct_opener() -> Any:
    """构造**不走任何代理**的 opener。

    迁移自 L70 的 `_OPENER_DIRECT`，改为工厂函数 ——
    旧实现是模块级单例（import 时即构造），在测试里不好替换也不好在非 Windows 下隔离。
    工厂函数让调用方按需构造，也便于注入假的 opener 做单测。
    """
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def probe(
    url: str,
    *,
    timeout: float = DEFAULT_PROBE_TIMEOUT,
    opener: Any = None,
    clock: Callable[[], float] | None = None,
) -> HealthSample:
    """单次 HTTP 探针。直连，不走系统代理。

    迁移自 `_probe_http()`（L1428-1434）：

        try:
            _OPENER_DIRECT.open(url, timeout=timeout)
            return True
        except Exception:
            return False

    ★ 语义保真要点：
      1. 使用**直连 opener**（见模块文档，这是定点修复不是可选优化）
      2. `except Exception` 吞掉一切 → ok=False。旧实现如此，
         因为探针的调用方（`wait_until` 循环）会靠「重复探测 + 超时」处理失败，
         单次失败不该冒泡。
      3. **不检查状态码** —— 旧实现拿到响应即算通过（见模块文档末段）。
         这里保留该行为。`status_code` 只作为诊断信息采集，不影响 ok。

    `clock` 可注入以便测试耗时统计（默认用 `time.perf_counter`）。
    """
    import time as _time

    now = clock or _time.perf_counter
    op = opener if opener is not None else build_direct_opener()
    start = now()
    try:
        response = op.open(url, timeout=timeout)
    except Exception as e:
        elapsed = (now() - start) * 1000.0
        return HealthSample(
            ok=False,
            latency_ms=elapsed,
            status_code=None,
            detail=f'{type(e).__name__}: {e}',
        )

    elapsed = (now() - start) * 1000.0
    status = None
    try:
        status = getattr(response, 'status', None) or getattr(response, 'code', None)
    except Exception:
        status = None
    finally:
        # 旧实现没有显式关闭响应；这里补上以避免连接泄漏。
        # 注意：这不改变任何判定行为（ok 已在上面决定），属纯粹的资源管理。
        try:
            response.close()
        except Exception:
            pass

    return HealthSample(ok=True, latency_ms=elapsed, status_code=status)


def make_probe_fn(**kwargs: Any) -> Callable[[str], bool]:
    """构造 `domain.readiness` 需要的谓词形探针：`url -> bool`。

    domain 层的 `wait_until` 接受 `predicate: Callable[[], bool]`，
    而探针需要 url 参数。应用层通常这样组合：

        probe_one = make_probe_fn()
        wait_until(lambda: probe_one('http://127.0.0.1:5002/api/health'), policy)

    提供这个工厂是为了避免各调用点重复写 `lambda: probe(url).ok` ——
    重复写会让「判定口径」有机会在某一处被写错（例如写成 `not .ok`）。
    """
    def _probe(url: str) -> bool:
        return probe(url, **kwargs).ok

    return _probe
