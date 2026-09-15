"""装配容器 —— 唯一知道「哪个 Protocol 用哪个具体实现」的地方。

═══════════════════════════════════════════════════════════════════
这是整个应用里唯一 import adapters 的「上层」文件
═══════════════════════════════════════════════════════════════════

四层架构的依赖方向：

    L4 Presentation ──┐
                      ├──→ L3 Application ──→ L2 Domain ←── L1 Adapter
    L1 Adapter ───────┘                                    （实现 Protocol）

L3 的用例只认 `domain.ports` 里的 Protocol，看不到 `adapters`。
那么「具体的 Windows 实现从哪进来」？就在**这一层之外** —— 容器。

`container.py` 位于包根（与 `domain` / `application` / `adapters` 平级），
它**不属于任何一层**，因此可以同时 import adapters 与 application 而不违规。
它是 composition root：把「依赖倒置」的倒置点集中到一处，
让其余所有代码都只依赖抽象。

★ 这条边界的实际价值：用例层的 782 个测试里没有一个 import adapters，
  全部跑在 Fake 上 —— 可以在没有 Windows、没有 nssm、没有真实服务的
  机器上完整验证业务逻辑。

═══════════════════════════════════════════════════════════════════
★ 为什么容器里要有「降级」逻辑，而不是让用例去判断
═══════════════════════════════════════════════════════════════════

`Deps.metrics` / `notify` / `storage` 允许为 `None`，语义是「该功能不可用」。
那么「什么时候不可用」由谁判定？

    不能是用例 —— 用例看不到 `psutil` 是否存在（那是 I/O 世界的事）。

所以容器在装配时判定：`psutil` 缺失 → `metrics=None`（而非塞一个
「永远返回 0%」的假实现）。用例拿到 `None` 会**明确告知用户指标不可用**，
而不是显示 0% —— 「0% CPU」和「测不到 CPU」是两件完全不同的事，
后者常被误读成「系统空闲」。

同理 `storage=None`：配置文件连读都读不了时，用例必须报「无法读取配置」
而不是拿一个空 dict 当默认配置（那等于静默把用户配置清零）。

═══════════════════════════════════════════════════════════════════
★ 关键约定：容器**不做 I/O**
═══════════════════════════════════════════════════════════════════

`build_container()` 里的 `JsonStorage(path)` 只是**存下路径**，
不读文件；`NssmService(nssm_path=...)` 也不去探测 nssm。

理由：构造期做 I/O 会让「装配」失败原因不确定（网络盘没挂载、
权限不足、文件被占用…），而这些失败应该在**用例执行时**以
`OpResult.failure` 的形式呈现给用户，而不是在程序启动时就崩掉。
启动即崩会让用户看不到任何有用信息。

唯一的例外是 `probe_environment()` —— 它是**显式**的环境探测入口，
由启动流程主动调用，其结果用于决定 `metrics` 是否为 `None`。
它被单独放出来，就是为了让「这里有 I/O」一眼可见。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .adapters import (
    audit_jsonl,
    clock as clock_mod,
    metrics_psutil,
    notify_win,
    storage_json,
)
from .adapters.port_impls import HttpHealth, JsonStorage, NssmService, WinProcess
from .application.auth.session import Session
from .application.event_bus import EventBus
from .application.usecases.deps import Deps
from .domain.models import SVC_API, SVC_ARQ
from .domain.permissions import Role

# ═══════════════════════════════════════════════════════════════════
# 默认参数
# ═══════════════════════════════════════════════════════════════════

#: 受管服务名（与 domain.models 的注册表一致；此处只做默认值，不复制领域规则）
DEFAULT_SERVICE_NAMES: tuple[str, ...] = (SVC_API, SVC_ARQ)

#: 默认端口（配置文件缺失时的兜底）
DEFAULT_PORTS: dict[str, int] = {
    'backend': 5002,
    'frontend': 3000,
    'redis': 6379,
}

#: 配置文件候选名（依次尝试，第一个存在的胜出）
CONFIG_CANDIDATES: tuple[str, ...] = (
    'erp_server_config.json',
    'server_config.json',
)

#: 审计日志文件名
AUDIT_FILENAME = 'audit.jsonl'


# ═══════════════════════════════════════════════════════════════════
# 环境探测（★ 这里是容器里唯一做 I/O 的地方）
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Environment:
    """一次环境探测的结果。

    ★ 每个「不可用」都带 `reasons`，因为它要如实展示给用户 ——
      「指标不可用」而没说原因，用户只能来问我们。
    """

    #: psutil 是否可用（决定 metrics 端口是否装配）
    has_psutil: bool = False
    #: pywebview 是否可用（决定能否用系统通知气泡）
    has_webview: bool = False
    #: 是否 Windows（非 Windows 上服务/进程端口全部不可用）
    is_windows: bool = True
    #: 配置文件路径（探测到的第一个存在的候选；都没找到则为首选候选）
    config_path: Path | None = None
    #: 配置是否存在
    config_exists: bool = False
    #: 探测过程中的说明（含所有降级原因）
    notes: list[str] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        """是否处于降级状态（有任何一项不可用）。"""
        return bool(self.notes) or not self.has_psutil or not self.is_windows


def _module_available(name: str) -> bool:
    """模块是否可导入（不真正 import，避免加载重依赖的副作用）。"""
    import importlib.util  # noqa: PLC0415

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        # ValueError: 模块在 sys.modules 里但 __spec__ 为 None
        return False


def resolve_config_path(base_dir: str | Path | None = None) -> Path:
    """定位配置文件（依次尝试候选名，返回第一个存在的；都不存在则返回首选）。

    ★ 都不存在时返回**首选候选**而不是 None —— 调用方需要一个可写路径，
      首次运行时要用它落盘默认配置。返回 None 会迫使每个调用方
      再写一遍「没有就用哪个」的兜底，那才是重复。
    """
    root = Path(base_dir) if base_dir else _default_base_dir()
    for name in CONFIG_CANDIDATES:
        candidate = root / name
        if candidate.exists():
            return candidate
    return root / CONFIG_CANDIDATES[0]


def _default_base_dir() -> Path:
    """配置与审计的默认目录。

    ★ 打包后是 exe 所在目录（用户可见、可备份），
      开发态是仓库根 —— 两种形态下都指向「用户能找到的地方」，
      而不是 CWD（从桌面快捷方式启动时 CWD 可能是 system32）。
    """
    if getattr(sys, 'frozen', False):                       # PyInstaller 打包态
        return Path(sys.executable).resolve().parent
    # server_manager_v8/container.py → 上溯两级 = 仓库根
    return Path(__file__).resolve().parent.parent


def probe_environment(base_dir: str | Path | None = None) -> Environment:
    """探测运行环境，产出一份「哪些能力可用」的报告。

    ★ 显式入口 —— 由启动流程主动调用。构造函数里不做探测，
      以免「装配」变成会失败的 I/O 操作。

    ★ 探测完**一次性构造** Environment，而不是先建对象再逐个赋值 ——
      Environment 是 frozen 的，逐字段赋值会 FakeInstanceError；
      更重要的是：一份「探测到一半」的环境报告比没有报告更危险
      （比如 has_psutil 还没填就被人读了，会误判为不可用）。
    """
    has_psutil = metrics_psutil.available()
    is_windows = sys.platform == 'win32'
    has_webview = _module_available('webview')

    path = resolve_config_path(base_dir)
    config_exists = path.exists()

    notes: list[str] = []
    if not has_psutil:
        notes.append('psutil 不可用：无法采集 CPU / 内存指标（不会以 0% 冒充）')
    if not is_windows:
        notes.append(f'当前系统为 {sys.platform}：服务与进程管理功能不可用')
    if not has_webview:
        notes.append('pywebview 不可用：系统通知将回退为日志记录')
    if not config_exists:
        notes.append(f'配置文件不存在（将使用默认值）：{path}')

    return Environment(
        has_psutil=has_psutil,
        has_webview=has_webview,
        is_windows=is_windows,
        config_path=path,
        config_exists=config_exists,
        notes=notes,
    )


# ═══════════════════════════════════════════════════════════════════
# 容器
# ═══════════════════════════════════════════════════════════════════


@dataclass
class Container:
    """装配好的对象图。

    `deps` 交给用例（它们是 Protocol 类型）；其余字段是容器自己管理的
    长生命周期对象（会话、总线、审计日志），Presentation 层会用到。

    ★ `session` / `event_bus` 单例的原因：
      · `Session` 保存当前角色与提权过期时间 —— 每次新建就等于把用户
        的提权状态丢掉，UI 会表现为「刚提权完又变回只读」。
      · `EventBus` 保存订阅者 —— 新建总线等于所有订阅静默失效，
        且不会报错（`emit` 到一个空总线是合法操作），属于最难查的那类 bug。
    """

    deps: Deps
    session: Session
    event_bus: EventBus
    env: Environment
    config_path: Path
    audit_path: Path
    #: 保留原始构造参数，便于重建（如测试或配置变更后复位）
    params: dict[str, Any] = field(default_factory=dict)

    # ── 便捷访问（避免调用方到处 deps.xxx.yyy）──────────────────

    @property
    def ports(self) -> dict[str, int]:
        return dict(self.deps.ports)

    @property
    def paths(self) -> dict[str, str]:
        return dict(self.deps.paths)

    @property
    def actor(self) -> str:
        return self.deps.actor

    def degraded_notes(self) -> list[str]:
        """当前所有降级说明（UI 启动横幅用）。

        ★ 只报「环境探测没报过」的那些 —— 探测已覆盖 psutil / webview /
          Windows / 配置文件四类，再按端口是否为 None 重复报一遍
          会让用户看到两条同样的告警（信息冗余会让人以为有两个问题）。

          判断依据是「该能力已由探测覆盖」这个**事实**，而不是拿中文
          标签去注释文字里搜子串 —— 后者会在文案改动时静默失效。
        """
        notes = list(self.env.notes)
        #: 探测已覆盖的能力 → 不再按 None 重复报告
        covered = {
            'metrics': True,   # probe_environment 已检查 psutil
            'notify': True,    # probe_environment 已检查 pywebview
            'storage': False,  # 配置**文件**是否存在不等于 StoragePort 可用
        }
        for key, label in (('metrics', '指标采集'), ('notify', '系统通知'),
                           ('storage', '配置存取')):
            if getattr(self.deps, key) is None and not covered.get(key, False):
                notes.append(f'{label}不可用')
        return notes


def build_container(
    *,
    base_dir: str | Path | None = None,
    config_path: str | Path | None = None,
    audit_path: str | Path | None = None,
    ports: dict[str, int] | None = None,
    paths: dict[str, str] | None = None,
    actor: str = 'local',
    default_role: Role = Role.VIEWER,
    event_bus: EventBus | None = None,
    env: Environment | None = None,
    on_handler_error: Any = None,
) -> Container:
    """装配完整对象图。

    参数全部可覆盖，便于测试与「配置变更后重建」。

    ★ 不做 I/O：只构造对象、记录路径。实际读文件发生在用例执行时。
    """
    base = Path(base_dir) if base_dir else _default_base_dir()
    cfg = Path(config_path) if config_path else resolve_config_path(base)
    aud = Path(audit_path) if audit_path else _default_audit_path(cfg)

    # 环境探测（唯一 I/O 来源）。调用方若已探测过可传入复用，
    # 避免在同一启动流程里对文件系统查两遍。
    environment = env if env is not None else probe_environment(base)

    bus = event_bus if event_bus is not None else EventBus(
        on_handler_error=on_handler_error,
    )

    # ── 时钟：所有「时间」都从这里取 ──────────────────────────
    system_clock = clock_mod.SystemClock()

    # ── 会话：单例，事件走同一条总线 ──────────────────────────
    session = Session(
        clock=system_clock,
        default_role=default_role,
        emit=bus.emit,
    )

    # ── 无条件可用的 Port ─────────────────────────────────────
    storage = JsonStorage(cfg)
    audit = audit_jsonl.JsonlAuditLog(aud)

    # ── 条件可用的 Port（★ 不可用就如实给 None，不给假实现）────
    metrics = metrics_psutil.PsutilMetrics(clock=system_clock.now) \
        if environment.has_psutil else None
    notify = _build_notify(environment)

    deps = Deps(
        clock=system_clock,
        service=NssmService(),
        process=WinProcess(),
        health=HttpHealth(clock=system_clock),
        audit=audit,
        event_bus=bus,
        metrics=metrics,
        notify=notify,
        storage=storage,
        ports=dict(ports) if ports else dict(DEFAULT_PORTS),
        paths=dict(paths) if paths else {},
        actor=actor,
    )

    return Container(
        deps=deps,
        session=session,
        event_bus=bus,
        env=environment,
        config_path=cfg,
        audit_path=aud,
        params={
            'base_dir': str(base),
            'config_path': str(cfg),
            'audit_path': str(aud),
            'actor': actor,
            'default_role': default_role,
        },
    )


def _build_notify(environment: Environment) -> Any:
    """构造通知端口。

    ★ 无论有无 pywebview 都返回一个 `WinNotifier` —— 因为它自带
      多级降级（气泡 → 弹窗 → 日志），而「有没有气泡」是它内部的事。
      这与 `metrics` 的处理不同：指标没有「降级实现」可言
      （采不到就是采不到，编一个 0% 是错的），通知则有合理的降级链。
    """
    if environment.has_webview:
        return notify_win.WinNotifier()
    # 无 webview：禁掉 messagebox 回退（在无 GUI 环境会阻塞），只记日志
    return notify_win.WinNotifier(fallback_to_messagebox=False)


def _default_audit_path(config_path: Path) -> Path:
    """审计日志路径：与配置文件同目录。"""
    return config_path.parent / AUDIT_FILENAME


# ═══════════════════════════════════════════════════════════════════
# 配置同步（把外部配置灌进 Deps）
# ═══════════════════════════════════════════════════════════════════


def apply_config(container: Container, config: dict[str, Any]) -> Container:
    """把一份**已归一化**的配置应用到容器，返回新的容器。

    ★ 返回新容器而不是原地改：`Container` 不是 frozen，但 `Deps` 是。
      原地改 `deps` 字段会破坏「Deps 一旦装配就不变」的约定，
      使「这个用例用的是哪份配置」变得不可追溯。
      重建的成本很低（不做 I/O），换来的可追溯性很值。

    调用方（Presentation）在配置保存成功后调它，让后续用例立即生效。
    """
    ports = dict(container.deps.ports)
    paths = dict(container.deps.paths)

    if isinstance(config.get('api_port'), int):
        ports['backend'] = int(config['api_port'])
    if isinstance(config.get('web_port'), int):
        ports['frontend'] = int(config['web_port'])
    if isinstance(config.get('redis_port'), int):
        ports['redis'] = int(config['redis_port'])

    for key in ('redis_exe', 'nssm_path'):
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            paths[key] = value.strip()

    return build_container(
        base_dir=container.params.get('base_dir'),
        config_path=container.params.get('config_path'),
        audit_path=container.params.get('audit_path'),
        ports=ports,
        paths=paths,
        actor=container.deps.actor,
        default_role=container.session.role,
        event_bus=container.event_bus,   # ★ 复用总线，保住所有订阅者
        env=container.env,
    )


__all__ = [
    'AUDIT_FILENAME',
    'CONFIG_CANDIDATES',
    'Container',
    'DEFAULT_PORTS',
    'DEFAULT_SERVICE_NAMES',
    'Environment',
    'apply_config',
    'build_container',
    'probe_environment',
    'resolve_config_path',
]
