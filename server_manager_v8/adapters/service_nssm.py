"""NSSM / Windows 服务适配器 — 实现 domain.ports.ServicePort。

迁移来源（server_manager.py v6）：
    - ``_find_nssm`` → 配置优先 → PATH → 候选路径
    - ``_svc_state`` → state（sc query + OEM 解码 + 中文服务名保护）
    - ``_svc_pid`` → pid（sc queryex）
    - ``_nssm_install`` → install（两步装 + AppExit Default Restart + 依赖探测）
    - ``_detect_service_deps`` → detect_dependencies（wmic 解析 + env 覆盖）
    - ``_wait_service_stopped`` → wait_state（STOP_PENDING 语义必须保留）

v6 踩坑语义（逐行保留，勿"优化"掉）：
    1. 停止服务必须等到确认 STOPPED —— STOP_PENDING 期间强杀被管进程会被
       AppExit Default Restart 判定为崩溃而自动重启，与目标模式抢占端口
    2. PYTHONUTF8=1 下 sc/nssm 输出按 OEM 代码页解码，否则中文服务名被误判未安装
    3. 探测失败返回 UNKNOWN，**不得**降级为 STOPPED（会误判已停止而漏停服务）
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import replace

from server_manager_v8.domain import (
    OpResult,
    ServiceSpec,
    ServiceState,
)

from ._proc import IS_WINDOWS, CommandError, run_capture

__all__ = [
    'SERVICE_DEP_PATTERN',
    'NssmServiceAdapter',
    'parse_sc_state',
    'parse_wmic_deps',
]

# 服务依赖：postgres/redis/memurai（v6 原样迁移）
SERVICE_DEP_PATTERN = re.compile(r'postgres|redis|memurai', re.IGNORECASE)

# NSSM 常见安装位置（配置可覆盖）
_NSSM_CANDIDATES = (
    r'C:\nssm\nssm.exe',
    r'C:\Program Files\nssm\nssm.exe',
    r'C:\Program Files (x86)\nssm\nssm.exe',
    r'C:\tools\nssm\nssm.exe',
)

_STATE_MAP = {
    'RUNNING': ServiceState.RUNNING,
    'STOPPED': ServiceState.STOPPED,
    'PAUSED': ServiceState.PAUSED,
    'START_PENDING': ServiceState.UNKNOWN,
    'STOP_PENDING': ServiceState.UNKNOWN,
    'CONTINUE_PENDING': ServiceState.UNKNOWN,
    'PAUSE_PENDING': ServiceState.UNKNOWN,
}


def parse_sc_state(output: str, returncode: int) -> ServiceState:
    """解析 sc query 输出（纯函数，可单测）。

    返回码 1060（服务不存在）/ 无 SERVICE_NAME 行 → ABSENT。
    探测异常（pending 态等）→ UNKNOWN，绝不降级为 STOPPED。
    """
    if returncode != 0 or 'SERVICE_NAME' not in (output or ''):
        return ServiceState.ABSENT
    for line in output.splitlines():
        if 'STATE' not in line:
            continue
        if ':' not in line:
            continue
        # 形如 '        STATE              : 4  RUNNING' → 取最后一个词（状态名）
        raw = line.split(':', 1)[1].split()[-1].upper()
        return _STATE_MAP.get(raw, ServiceState.UNKNOWN)
    return ServiceState.UNKNOWN


def parse_wmic_deps(output: str, pattern: re.Pattern[str] = SERVICE_DEP_PATTERN) -> list[str]:
    """解析 wmic service get Name,StartMode,State 输出（纯函数，可单测）。

    只纳入 Auto + Running 且命中 postgres/redis/memurai 的服务，
    排除只读副本（replica）。
    """
    deps: list[str] = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        state, mode = parts[-1], parts[-2]
        name = ' '.join(parts[:-2])
        if mode == 'Auto' and state == 'Running' and pattern.search(name) \
                and 'replica' not in name.lower():
            deps.append(name)
    return deps


class NssmServiceAdapter:
    """NSSM 服务操作。构造时注入 nssm_path（配置项）与 project_dir（AppDirectory）。"""

    def __init__(self, nssm_path: str = '', project_dir: str = '') -> None:
        self._nssm_override = nssm_path or ''
        self.project_dir = project_dir or ''

    # ---- 内部命令 ----

    def _nssm(self, *args: str, timeout: float = 15.0) -> OpResult:
        """执行 nssm 命令，统一显式化失败。"""
        nssm = self._find_nssm()
        if not nssm:
            return OpResult.failure('未找到 NSSM，请安装或配置 nssm_path')
        try:
            cap = run_capture(list(args), executable=nssm, timeout=timeout)
        except CommandError as exc:
            return OpResult.failure(str(exc))
        if cap.returncode != 0:
            return OpResult.failure(
                f'nssm {" ".join(args[:2])} 失败（返回码 {cap.returncode}）: {cap.combined.strip()[:120]}',
                detail=cap.combined,
            )
        return OpResult.success(detail=cap.combined.strip())

    def _find_nssm(self) -> str | None:
        if self._nssm_override:
            p = self._nssm_override
            if p.lower().endswith('.exe') and os.path.isfile(p):
                return p
        found = self._sc_which_nssm()
        if found:
            return found
        for cand in _NSSM_CANDIDATES:
            if os.path.isfile(cand):
                return cand
        return None

    @staticmethod
    def _sc_which_nssm() -> str | None:
        """等价 shutil.which('nssm')：扫描 PATH。"""
        path = os.environ.get('PATH', '')
        for d in path.split(os.pathsep):
            if not d:
                continue
            cand = os.path.join(d, 'nssm.exe')
            if os.path.isfile(cand):
                return cand
        return None

    # ---- ServicePort 实现 ----

    def state(self, name: str) -> ServiceState:
        if not IS_WINDOWS:
            return ServiceState.UNKNOWN
        try:
            cap = run_capture(['sc', 'query', name], timeout=5)
        except CommandError:
            return ServiceState.UNKNOWN
        return parse_sc_state(cap.stdout, cap.returncode)

    def pid(self, name: str) -> int | None:
        if not IS_WINDOWS:
            return None
        try:
            cap = run_capture(['sc', 'queryex', name], timeout=5)
        except CommandError:
            return None
        for line in cap.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith('PID') and ':' in stripped:
                value = stripped.split(':', 1)[1].strip()
                if value.isdigit():
                    return int(value)
        return None

    def install(self, spec: ServiceSpec) -> OpResult:
        """安装服务（L3 高危）。

        v6 分步语义：先仅注册应用路径（避免 NSSM 弹 GUI），再设置参数与属性，
        最后写 DependOnService（开机防重启风暴）。
        """
        if not IS_WINDOWS:
            return OpResult.failure('非 Windows 平台，无法安装服务')
        if not spec.executable or not os.path.isfile(spec.executable):
            return OpResult.failure(f'可执行文件不存在: {spec.executable!r}')
        result = self._nssm('install', spec.name, spec.executable, timeout=30)
        if not result.ok:
            return result
        if spec.params:
            self._nssm('set', spec.name, 'AppParameters', ' '.join(spec.params))
        directory = spec.directory or self.project_dir
        log_path = os.path.join(directory, 'logs', f'{spec.name}.log') if directory else ''
        settings: list[tuple[str, str]] = [
            ('AppDirectory', directory),
            ('AppRotateFiles', '1'),
            ('AppRotateBytes', '10485760'),
            ('AppExit', 'Default Restart'),
            ('AppRestartDelay', '5000'),
            ('Start', 'SERVICE_AUTO_START' if spec.startup_type == 'auto' else 'SERVICE_DEMAND_START'),
            ('AppNoConsole', '1'),
        ]
        if log_path:
            settings.append(('AppStdout', log_path))
            settings.append(('AppStderr', log_path))
        if spec.env_extra:
            settings.append(('AppEnvironmentExtra', ' '.join(f'{k}={v}' for k, v in spec.env_extra)))
        for key, value in settings:
            self._nssm('set', spec.name, key, value)
        deps = self.detect_dependencies()
        if deps:
            self._nssm('set', spec.name, 'DependOnService', ' '.join(deps))
            return OpResult.success(detail=f'deps={",".join(deps)}')
        return OpResult.success(detail='未探测到 PG/Redis 服务依赖')

    def uninstall(self, name: str) -> OpResult:
        if not IS_WINDOWS:
            return OpResult.failure('非 Windows 平台')
        return self._nssm('remove', name, 'confirm', timeout=30)

    def control(self, name: str, cmd: str) -> OpResult:
        """服务控制：start / stop / restart。"""
        if cmd not in ('start', 'stop', 'restart'):
            return OpResult.failure(f'未知控制命令 {cmd!r}')
        if not IS_WINDOWS:
            return OpResult.failure('非 Windows 平台')
        return self._nssm(cmd, name, timeout=30)

    def wait_state(self, name: str, want: ServiceState, timeout_s: float = 45.0) -> bool:
        """轮询等待服务到达目标状态。

        v6 语义（勿改）：停止时必须确认 STOPPED 才算完成；STOP_PENDING 期间
        强杀被管进程会被 AppExit Default Restart 判定为崩溃自动重启。
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.state(name) is want:
                return True
            time.sleep(1)
        return False

    def detect_dependencies(self) -> list[str]:
        """扫描本机 PG/Redis/Memurai 服务名（SERVICE_DEPENDS_ON 可显式覆盖）。"""
        custom = os.getenv('SERVICE_DEPENDS_ON', '').strip()
        if custom:
            return [s.strip() for s in custom.replace(';', ',').split(',') if s.strip()]
        if not IS_WINDOWS:
            return []
        try:
            cap = run_capture(['wmic', 'service', 'get', 'Name,StartMode,State'], timeout=30)
        except CommandError:
            return []
        return parse_wmic_deps(cap.stdout)

    # ---- 便捷组合（Application 层可直接调用） ----

    def wait_running_with_probe(
        self, name: str, api_port: int, timeout_s: float = 60.0,
        health_timeout: float = 2.0,
    ) -> OpResult:
        """v6 ``_wait_service_running`` 迁移：服务 RUNNING 后再探测业务就绪。"""
        import urllib.request

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.state(name) is not ServiceState.RUNNING:
                time.sleep(1)
                continue
            try:
                urllib.request.urlopen(
                    f'http://127.0.0.1:{api_port}/api/health', timeout=health_timeout,
                )
                return OpResult.success()
            except Exception:
                time.sleep(1)
        return OpResult.failure(f'{name} 在 {timeout_s:g}s 内未就绪（含健康检查）')


def attach_service_deps(spec: ServiceSpec, deps: list[str]) -> ServiceSpec:
    """把探测到的依赖写入 ServiceSpec（frozen dataclass → replace）。"""
    if not deps:
        return spec
    return replace(spec, depends_on=tuple(deps))
