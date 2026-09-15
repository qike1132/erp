"""领域模型 —— Process / Service / HealthProbe / Dependency。

**说明**：本模块不是逐行迁移，而是**为已有散落概念建立的显式模型**。
原 server_manager.py 里这些概念以裸字符串/元组形式存在：

    _SVC_API = 'erp-prod'            → Service 名称（裸字符串）
    _SVC_ARQ = 'erp-arq'
    _DEFAULT_REDIS_SERVICES = [...]  → 服务名列表
    ('dual_dev', '开发模式')          → 模式（裸字符串元组）
    proc.pid / proc                     → 进程（subprocess.Popen）

本模块把它们收敛为不可变值对象，使「服务是什么、进程是什么、依赖是什么」
成为可传递、可校验、可测试的类型。

借鉴来源（重构方案 §2.3 第 1 项）：
    F1bonacc1/process-compose —— 声明式进程定义 + depends_on 依赖 + 健康探针
    其领域模型 Process / Project / HealthProbe / Dependency 与本模块一一对应。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .port_contract import is_valid_port
from .service_state import ServiceStatus

# ═══════════════════════════════════════════════════════════════════
# 服务标识
# ═══════════════════════════════════════════════════════════════════

#: 服务名常量（迁移自 server_manager.py 的 _SVC_API / _SVC_ARQ）
SVC_API = 'erp-prod'
SVC_ARQ = 'erp-arq'

#: NSSM 托管的服务（受 AppExit 崩溃自动重启影响）
NSSM_SERVICES: tuple[str, ...] = (SVC_API, SVC_ARQ)

#: Redis 原生 Windows 服务默认列表（迁移自 _DEFAULT_REDIS_SERVICES）
DEFAULT_REDIS_SERVICES: tuple[str, ...] = ('erp-redis', 'erp-redis-broker')


class ServiceKind(Enum):
    """服务的托管方式 —— 决定用哪套控制手段。

    ★ 这是原代码里一个**致命的隐性区分**（v5.39 审查 💭#20 指出：
      `_svc_*` 管原生服务、`_service_*` 管 NSSM 托管服务，一个字母之差语义完全不同）。
      显式建模后，新维护者不会再混淆。

    NSSM 与 NATIVE 的关键差异（`_service_restart_guard` 的 D6 注释）：
        AppExit 是 NSSM 特有概念 —— guard 对 NATIVE 服务**完全没有作用**。
    """

    NSSM = 'nssm'
    """NSSM 托管（erp-prod / erp-arq）。受 AppExit 自动重启影响，stop 前须挂 guard。"""

    NATIVE = 'native'
    """原生 Windows 服务（erp-redis / erp-redis-broker）。由 SCM 直接管辖。"""


@dataclass(frozen=True)
class Service:
    """一个被管理的 Windows 服务。"""

    name: str
    kind: ServiceKind = ServiceKind.NSSM
    description: str = ''

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError(f'服务名非法: {self.name!r}')

    @property
    def is_nssm(self) -> bool:
        return self.kind is ServiceKind.NSSM

    def __str__(self) -> str:
        return self.name


#: 预置服务定义（迁移自原模块级常量）
SERVICE_API = Service(SVC_API, ServiceKind.NSSM, 'ERP 后端 API + nginx')
SERVICE_ARQ = Service(SVC_ARQ, ServiceKind.NSSM, 'ERP 异步任务 worker')
SERVICE_REDIS = Service('erp-redis', ServiceKind.NATIVE, 'Redis 缓存 (6379)')
SERVICE_REDIS_BROKER = Service('erp-redis-broker', ServiceKind.NATIVE, 'Redis 队列 (6380)')

MANAGED_NSSM_SERVICES: tuple[Service, ...] = (SERVICE_API, SERVICE_ARQ)
MANAGED_REDIS_SERVICES: tuple[Service, ...] = (SERVICE_REDIS, SERVICE_REDIS_BROKER)


# ═══════════════════════════════════════════════════════════════════
# 健康探针
# ═══════════════════════════════════════════════════════════════════


class ProbeKind(Enum):
    """探针类型。"""

    HTTP = 'http'
    """HTTP GET 返回 2xx 即通过。"""

    SERVICE_STATE = 'service_state'
    """服务状态判定（RUNNING / STOPPED）。"""

    TCP = 'tcp'
    """TCP 可连接即通过（prod_runner 探活用）。"""


@dataclass(frozen=True)
class HealthProbe:
    """一个健康探针定义。

    迁移自原 `_wait_service_running` 内的硬编码探针：

        api_ready = self._probe_http(f'http://127.0.0.1:{_PORTS.api}/api/health')
        web_ready = self._probe_http(f'http://127.0.0.1:{_PORTS.web}/nginx-health')

    原实现的 URL 是 f-string 拼死在方法体里，此处改为声明式定义，
    且**路径可配置**（解决 v8 方案 D15「健康检查硬编码」）。
    """

    name: str
    kind: ProbeKind
    url: str = ''
    description: str = ''

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError('探针必须有 name')
        if self.kind is ProbeKind.HTTP and not self.url:
            raise ValueError(f'HTTP 探针 {self.name} 必须有 url')


def build_probes(api_port: int, web_port: int) -> tuple[HealthProbe, ...]:
    """按端口构造标准探针集合。

    对应 `_wait_service_running` 的三项全过：
        RUNNING + /api/health + /nginx-health

    注意 `need_web` 的语义：只有 name == SVC_API 时才需要 nginx 探针
    （erp-prod 承载 API 与 nginx；erp-arq 不承载前端）。
    """
    if not is_valid_port(api_port) or not is_valid_port(web_port):
        raise ValueError(f'端口非法: api={api_port!r} web={web_port!r}')
    return (
        HealthProbe('api', ProbeKind.HTTP, f'http://127.0.0.1:{api_port}/api/health', '后端 API'),
        HealthProbe('web', ProbeKind.HTTP, f'http://127.0.0.1:{web_port}/nginx-health', 'nginx 前端探针'),
    )


def probes_for_service(service_name: str, api_port: int, web_port: int) -> tuple[HealthProbe, ...]:
    """按服务名返回需要的探针（迁移 `need_web = name == _SVC_API` 语义）。"""
    probes = list(build_probes(api_port, web_port))
    if service_name != SVC_API:
        probes = [p for p in probes if p.name != 'web']
    return tuple(probes)


# ═══════════════════════════════════════════════════════════════════
# 进程
# ═══════════════════════════════════════════════════════════════════


class ProcessRole(Enum):
    """进程在系统中的角色 —— 决定清理时的保护策略。"""

    BACKEND = 'backend'
    """开发模式后端（uvicorn）。"""

    FRONTEND = 'frontend'
    """开发模式前端（vite）。"""

    WORKER = 'worker'
    """ARQ worker。"""

    PROD_RUNNER = 'prod_runner'
    """手动启动的生产运行器（不受 NSSM 控制，需单独清理）。"""

    @property
    def label(self) -> str:
        return {'backend': '后端', 'frontend': '前端', 'worker': 'worker',
                'prod_runner': 'prod_runner'}[self.value]


@dataclass
class ProcessRef:
    """一个被管理的进程引用。

    不持有 subprocess.Popen 本身（那是 adapter 的细节），
    只记录领域层需要的：PID、角色、名称。
    """

    pid: int
    role: ProcessRole
    name: str = ''

    def __post_init__(self) -> None:
        if not isinstance(self.pid, int) or self.pid <= 0:
            raise ValueError(f'PID 非法: {self.pid!r}')

    @property
    def label(self) -> str:
        return self.name or self.role.label


# ═══════════════════════════════════════════════════════════════════
# 依赖
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Dependency:
    """服务依赖声明。

    迁移自 `_nssm_install` 的 `DependOnService` 写入逻辑：
    扫描 PostgreSQL / Redis / Memurai 写入依赖，**避免开机重启风暴**
    （v8 方案 §1.6 列为本项目「踩过坑才有的设计」之一）。
    """

    service: str
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.service:
            raise ValueError('dependency 必须指定 service')


#: 已知的依赖候选服务名（迁移自 _detect_service_deps 的扫描目标）
DEPENDENCY_CANDIDATES: tuple[str, ...] = (
    'postgresql-x64-16', 'postgresql-x64-15', 'postgresql-x64-14',
    'erp-redis', 'erp-redis-broker', 'Memurai', 'Redis',
)


def detect_dependencies(installed_services: frozenset[str] | set[str]) -> Dependency | None:
    """从已安装服务集合中检测依赖（迁移 `_detect_service_deps` 的纯逻辑部分）。

    原实现直接调 `sc` 查询，此处剥离 I/O —— 调用方传入已查询到的服务名集合。

    返回 None 表示无依赖（原实现此时不写 DependOnService）。
    """
    found = tuple(s for s in DEPENDENCY_CANDIDATES if s in installed_services)
    if not found:
        return None
    return Dependency(service=SVC_API, depends_on=found)


# ═══════════════════════════════════════════════════════════════════
# 运行模式（模式互斥的领域概念）
# ═══════════════════════════════════════════════════════════════════


class RunMode(Enum):
    """运行模式。

    迁移自原 `_mode` 属性的字符串值（'none' / 'dual_dev' / 'prod'）。
    """

    NONE = 'none'
    DUAL_DEV = 'dual_dev'
    PROD = 'prod'

    @property
    def label(self) -> str:
        return {'none': '未运行', 'dual_dev': '开发模式', 'prod': '生产模式'}[self.value]

    @property
    def conflicts_with(self) -> RunMode | None:
        """与之互斥的模式（启动自己前必须先停它）。"""
        return {RunMode.NONE: None, RunMode.DUAL_DEV: RunMode.PROD,
                RunMode.PROD: RunMode.DUAL_DEV}[self]


@dataclass(frozen=True)
class ServiceSnapshot:
    """某个服务在某一时刻的观测快照。

    把「状态 + PID + 原始文本」打包，避免原实现里
    分别调 `_svc_state` / `_svc_pid` 导致的**多次查询不一致**
    （两次 sc 查询之间服务可能已改变状态）。
    """

    service: str
    status: ServiceStatus
    raw_state: str = ''
    pid: int | None = None

    @property
    def is_running(self) -> bool:
        return self.status is ServiceStatus.RUNNING

    @property
    def blocks_switch(self) -> bool:
        """是否阻断模式切换 —— 未知/运行中/中间态都阻断。"""
        return self.status.is_conservatively_running
