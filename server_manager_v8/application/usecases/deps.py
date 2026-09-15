"""用例层的依赖集合 —— 所有用例共享的一组注入 Port。

═══════════════════════════════════════════════════════════════════
为什么要有 Deps 这个「参数包」
═══════════════════════════════════════════════════════════════════

每个用例都需要若干 Port（服务、进程、健康、审计…）。若每个用例的
构造函数都逐个接收，会有三个问题：

1. **参数爆炸**：`StartDev(service, process, health, audit, bus, clock, ...)`
   加一个新 Port 要改所有用例的签名与所有调用点。
2. **漏传风险**：应用层有 8~10 个 Port，手工传参漏一个就是
   `None` 在运行时才炸（或更糟：静默用了错误默认值）。
3. **测试繁琐**：每个测试都要把 8 个 Fake 组装一遍。

`Deps` 把这些收进一个 frozen dataclass，用例统一接收 `deps`，
测试用一个 `make_deps()` 工厂造全套 Fake。

═══════════════════════════════════════════════════════════════════
★ 这里放的是 Protocol 类型，不是具体实现
═══════════════════════════════════════════════════════════════════

`Deps` 的字段类型全部来自 `domain.ports`。具体实现
（`adapters.port_impls.NssmService` 等）由 `container.py` 在装配时塞进来。

这是依赖倒置的落点：**用例层看不到 adapters 的存在**，
因此它可以在没有 Windows、没有真实服务的 CI 里完整测试。
（这条由 `scripts/check_domain_purity.py` 的应用层门禁强制。）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...domain.ports import (
    AuditPort,
    ClockPort,
    HealthPort,
    MetricsPort,
    NotifyPort,
    ProcessPort,
    ServicePort,
    StoragePort,
)
from ..event_bus import EventBus


@dataclass(frozen=True)
class Deps:
    """用例依赖集合。

    `event_bus` 类型是具体的 `EventBus` 而非 Protocol —— 这是有意的：
    事件总线是**应用层内部**的组件（同在 L3），不是跨层契约，
    给它做 Protocol 抽象没有收益（不会换成别的实现）。
    """

    #: 运行时必填
    clock: ClockPort
    service: ServicePort
    process: ProcessPort
    health: HealthPort
    audit: AuditPort
    event_bus: EventBus

    #: 可选（功能降级用）
    #:
    #: `None` 的语义与「全 0 值」严格区分：
    #: 例如 metrics=None 表示「指标功能不可用」，
    #: 用例必须据此**明确告知用户**，而不是显示 0%。
    metrics: MetricsPort | None = None
    notify: NotifyPort | None = None
    storage: StoragePort | None = None

    #: 运行参数（来自配置，非 Port）
    ports: dict[str, int] = field(default_factory=dict)
    paths: dict[str, str] = field(default_factory=dict)

    #: 审计操作者标识（单机工具用固定值；将来接账号体系时替换）
    actor: str = 'local'


def make_deps(**overrides: Any) -> Deps:
    """构造 Deps（测试便捷入口，未指定的用 Fake）。

    ★ 放在**生产代码**里而不是 conftest 里，是因为有两类真实消费者：
        · 测试（造全套 Fake）
        · `container.py` 的降级路径（某些 Port 不可用时的最小可用组合）
    """
    from tests.application.conftest import (  # noqa: PLC0415
        FakeAudit, FakeClock, FakeHealth, FakeNotify, FakeProcess,
        FakeService, FakeStorage,
    )

    defaults: dict[str, Any] = {
        'clock': FakeClock(),
        'service': FakeService(),
        'process': FakeProcess(),
        'health': FakeHealth(),
        'audit': FakeAudit(),
        'event_bus': EventBus(on_handler_error=lambda exc, ev: None),
        'notify': FakeNotify(),
        'storage': FakeStorage(),
    }
    defaults.update(overrides)
    return Deps(**defaults)


__all__ = ['Deps', 'make_deps']
