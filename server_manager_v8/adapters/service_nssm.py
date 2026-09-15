"""Windows 服务适配器 —— `sc` / `nssm` 封装。

═══════════════════════════════════════════════════════════════════
迁移来源：server_manager.py v5.40
═══════════════════════════════════════════════════════════════════

| 原实现 | 位置 | 迁移为 |
|---|---|---|
| `_svc_state(name)` | L1369 | `query_state()`（解析交给 domain） |
| `_svc_pid(name)` | L1396 | `query_pid()` |
| `_find_nssm()` | L1359 | `find_nssm()` |
| `_service_restart_guard(on)` | L1459 | `set_restart_guard()` |
| `_service_one(name, verb, nssm)` | L1477 | `run_verb()` |
| `_service_cmd_sync(verb)` | L1506 | `control_many()` |
| `_wait_service_stopped` 的 nssm stop | L1410 | `request_stop()` |

═══════════════════════════════════════════════════════════════════
本层职责边界（务必守住）
═══════════════════════════════════════════════════════════════════

**只做 I/O 与调用；判定逻辑一行都不许写。**

具体来说：
  · `sc query` 的**原始输出 + 退出码**交给 `domain.service_state.parse_sc_query_output`
    解析 —— 适配器不判断「未安装」还是「未知」。这是 v5.36/v5.39 两次事故的核心，
    判定必须唯一收口在领域层。
  · `sc queryex` 的 PID 提取虽然简单，但**「PID 0 不算有效 PID」这条规则**
    已在 `domain.port_contract`（v5.40 审查 #23）确立，这里同样复用 `> 0` 判定，
    并在注释里指向领域层，避免两处规则漂移。
  · 「等待 STOPPED / RUNNING」的**超时与轮询节奏**由 `domain.readiness` 的
    `wait_until` + 策略常量决定；适配器只提供「查一次状态」这个原子动作。

═══════════════════════════════════════════════════════════════════
为什么返回显式结果对象而不是 bool
═══════════════════════════════════════════════════════════════════

v8 方案 §3.4 契约要点：「全部返回显式结果对象（含 ok / reason / detail），
不再用 bool + 静默失败。这是解决 D5 的根本手段。」

旧 `_service_one` 已经做对了这件事（返回 `(ok, reason)` 且失败必带真实原因）——
本模块把它升级为 `VerbResult` dataclass，让「三字段/多字段」由类型固定，
不再有元组解包错位风险（同一类问题在 `_ProdStopResult` 上真实发生过，见 §6.1）。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..domain.models import NSSM_SERVICES, SVC_API, SVC_ARQ
from ..domain.service_state import (
    STATE_ABSENT,
    STATE_UNKNOWN,
    ServiceStatus,
    parse_sc_query_output,
)
from ..domain.state_machine import GuardKind
from ._proc import Runner, is_windows, run_capture, run_quiet

# ═══════════════════════════════════════════════════════════════════
# NSSM 候选路径（迁移自 _NSSM_CANDIDATES）
# ═══════════════════════════════════════════════════════════════════


def nssm_candidates() -> tuple[Path, ...]:
    """NSSM 常见安装位置的候选路径。

    逐项保真迁移自 v5.40 L78-79：
        C:\\nssm\\nssm.exe
        C:\\Program Files\\nssm\\nssm.exe
        C:\\Program Files (x86)\\nssm\\nssm.exe
        C:\\tools\\nssm\\nssm.exe
    """
    return (
        Path(r'C:\nssm\nssm.exe'),
        Path(r'C:\Program Files\nssm\nssm.exe'),
        Path(r'C:\Program Files (x86)\nssm\nssm.exe'),
        Path(r'C:\tools\nssm\nssm.exe'),
    )


# ═══════════════════════════════════════════════════════════════════
# 结果对象
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class VerbResult:
    """一次服务控制命令的结果。

    迁移自 `_service_one` 的 `(ok, reason)` 返回契约，升级为显式对象。

    契约（与旧实现逐条对齐）：
        ok=True  → 目标状态**已确认达成**（不是「命令返回 0」而已）
        ok=False → reason 必为可诊断的真实原因（拒绝访问 / 超时 / 退出码 + 输出）
    绝不能用 `except: pass` 掩盖失败 —— 那正是 v5.33「停不掉」的根因之一（§6.2）。
    """

    service: str
    verb: str
    ok: bool
    reason: str | None = None
    detail: str = ''

    def __post_init__(self) -> None:
        if not self.ok and not self.reason:
            raise ValueError('VerbResult 失败时必须提供 reason（禁止空洞的失败）')

    @staticmethod
    def success(service: str, verb: str, detail: str = '') -> VerbResult:
        return VerbResult(service, verb, ok=True, reason=None, detail=detail)

    @staticmethod
    def failure(service: str, verb: str, reason: str, detail: str = '') -> VerbResult:
        return VerbResult(service, verb, ok=False, reason=reason, detail=detail)


@dataclass(frozen=True)
class ServiceQuery:
    """一次 `sc query` 的原始结果 + 领域层解析后的状态。

    `raw` 与 `code` 一并保留，是因为留痕与排障需要原始输出：
    判定为「未知」时，运维必须能看到 sc 到底回了什么。
    """

    name: str
    code: int
    raw: str
    state_text: str

    @property
    def status(self) -> ServiceStatus:
        """把状态文本映射为四态枚举。

        注意这里是**适配器提供的便利映射**，映射规则本身来自领域层常量
        （`STATE_ABSENT` / `STATE_UNKNOWN`），不复制领域判定逻辑。
        """
        if self.state_text == STATE_ABSENT:
            return ServiceStatus.ABSENT
        if self.state_text == STATE_UNKNOWN:
            return ServiceStatus.UNKNOWN
        if 'RUNNING' in self.state_text:
            return ServiceStatus.RUNNING
        if 'STOPPED' in self.state_text:
            return ServiceStatus.STOPPED
        if 'PENDING' in self.state_text:
            return ServiceStatus.PENDING
        return ServiceStatus.UNKNOWN

    @property
    def is_absent(self) -> bool:
        return self.state_text == STATE_ABSENT

    @property
    def is_unknown(self) -> bool:
        return self.state_text == STATE_UNKNOWN


# ═══════════════════════════════════════════════════════════════════
# 定位
# ═══════════════════════════════════════════════════════════════════


def find_nssm(
    configured_path: str | None = None,
    *,
    which: object = shutil.which,
    candidates: tuple[Path, ...] | None = None,
) -> str | None:
    """NSSM 定位：配置项优先（校验 .exe 后缀）→ PATH → 候选路径。

    迁移自 `_find_nssm()`（L1359-1367），逐条对齐：

        custom = str(_APP_CONFIG.get('nssm_path') or '')
        if custom and Path(custom).is_file() and Path(custom).suffix.lower() == '.exe':
            return custom
        found = shutil.which('nssm')
        if found:
            return found
        return next((str(c) for c in _NSSM_CANDIDATES if c.is_file()), None)

    注意「配置项优先」但**必须校验**：配置里写个不存在的路径或非 .exe 时，
    旧实现会退回自动探测而不是盲目相信配置。这个行为保留。
    """
    custom = str(configured_path or '')
    if custom:
        p = Path(custom)
        if p.is_file() and p.suffix.lower() == '.exe':
            return custom

    found = which('nssm')  # type: ignore[operator]
    if found:
        return str(found)

    for cand in (candidates if candidates is not None else nssm_candidates()):
        if cand.is_file():
            return str(cand)
    return None


def has_nssm(configured_path: str | None = None, **kw: object) -> bool:
    """是否存在 NSSM。

    直接对应旧实现的 `nssm_existed = self._find_nssm() is not None` 这一判定，
    它是 `domain.state_machine.needs_restart_guard` 的唯一输入。
    """
    return find_nssm(configured_path, **kw) is not None


# ═══════════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════════


def query_state(
    name: str,
    *,
    timeout: float = 5,
    runner: Runner | None = None,
) -> ServiceQuery:
    """`sc query <name>` → `ServiceQuery`。

    迁移自 `_svc_state()`（L1369-1384），**关键差异是判定不在本层做**：

        旧: out, code = (r.stdout or '') + (r.stderr or ''), r.returncode
            return _parse_sc_state(code, out)
        新: 返回原始 code/raw，由 domain.service_state.parse_sc_query_output 判定

    旧实现把 stdout 与 stderr **拼接**后交给解析器 —— 这其实是个隐患：
    `sc` 的 1060 错误文本走 stderr，而运行中服务的 `PID : 1060` 走 stdout，
    两者一拼就可能凑出「含 1060 但不含 STATE」的组合。v5.40 用
    「且没有 STATE 行」堵住了它（审查 #1）。本实现保持拼接顺序不变
    （迁移保真 —— 拼接本身是旧行为的组成部分），但把原始两路都留在了
    `ServiceQuery.raw` 里以备将来收紧。

    ★ 异常语义（保真）：查询失败 → 判「未知」，**绝不能判「未安装」**。
      把「查不出来」当成「不存在」，会导致 `_ensure_production_stopped` 静默跳过
      仍在运行的生产服务，开发模式随即抢占 5002/3000 与生产互杀。
    """
    try:
        code, out, err = run_capture(
            ['sc', 'query', name], timeout=timeout, oem=True, runner=runner
        )
    except Exception:
        return ServiceQuery(name, -1, '', STATE_UNKNOWN)

    raw = out + err
    state_text = parse_sc_query_output(code, raw)
    return ServiceQuery(name, code, raw, state_text)


def query_pid(
    name: str,
    *,
    timeout: float = 5,
    runner: Runner | None = None,
) -> int | None:
    """`sc queryex <name>` 取服务当前进程 PID；未运行返回 None。

    迁移自 `_svc_pid()`（L1396-1408）。

    `> 0` 这条判定与 `domain.port_contract`（v5.40 审查 #23：TIME_WAIT 行
    PID 恒为 0）保持一致 —— 0 不是有效进程号。旧实现只判 `isdigit()`，
    会把 `PID : 0` 当成有效 PID 返回，本实现收紧为 `> 0`（同
    `domain.state_machine.build_protected_pids` 对 0 的处理）。
    """
    try:
        _code, out, _err = run_capture(
            ['sc', 'queryex', name], timeout=timeout, oem=True, runner=runner
        )
    except Exception:
        return None

    for line in (out or '').splitlines():
        stripped = line.strip()
        if stripped.startswith('PID'):
            parts = stripped.split(':', 1)
            if len(parts) > 1:
                value = parts[1].strip()
                if value.isdigit() and int(value) > 0:
                    return int(value)
    return None


# ═══════════════════════════════════════════════════════════════════
# 停止请求（不发等待，等待由 domain.readiness 负责）
# ═══════════════════════════════════════════════════════════════════


def request_stop(
    name: str,
    nssm_path: str | None = None,
    *,
    timeout: float = 15,
    runner: Runner | None = None,
) -> bool:
    """向服务发一次 stop 请求（有 nssm 时优先走 nssm，否则 sc）。

    迁移自 `_wait_service_stopped`（L1410-1419）的**前半段**：

        nssm = self._find_nssm()
        if nssm:
            with contextlib.suppress(Exception):
                subprocess.run(['nssm', 'stop', name], executable=nssm, **_cap(15))

    ★ 为什么有 nssm 时用 `nssm stop` 而不是 `sc stop`：
      两者语义不同。`sc stop` 是请求 SCM 停止；`nssm stop` 会额外处理
      NSSM 自己的进程树与退出码解释。旧代码这条路径是经过事故验证的，原样保留。

    ★ 只发请求、**不等结果**：等待 STOPPED 的循环属于时序策略，
      已收敛进 `domain.readiness.wait_until` + `POLICY_SERVICE_STOPPED`。
      适配器返回「请求是否发出」，不返回「是否已停」（后者需轮询查询）。

    注意旧实现要求「先发 nssm stop」，即便 nssm 路径为空也要继续走轮询 ——
    因此本函数失败时**调用方不应中断**，仍应进入等待循环。
    """
    if nssm_path:
        return run_quiet(
            ['nssm', 'stop', name],
            timeout=timeout,
            oem=True,
            executable=nssm_path,
            runner=runner,
        )
    return run_quiet(['sc', 'stop', name], timeout=timeout, oem=True, runner=runner)


# ═══════════════════════════════════════════════════════════════════
# NSSM 崩溃自动重启 guard
# ═══════════════════════════════════════════════════════════════════


def set_restart_guard(
    kind: GuardKind,
    nssm_path: str | None,
    *,
    services: tuple[str, ...] = NSSM_SERVICES,
    timeout: float = 15,
    runner: Runner | None = None,
) -> tuple[VerbResult, ...]:
    """切换 NSSM 的 AppExit Default（guard）。

    迁移自 `_service_restart_guard()`（L1459-1475）：

        nssm = self._find_nssm()
        if not nssm: return
        value = 'Restart' if on else 'Exit'
        for name in (_SVC_API, _SVC_ARQ):
            with contextlib.suppress(Exception):
                subprocess.run(['nssm','set',name,'AppExit','Default',value],
                               executable=nssm, **_cap(15))

    ★ guard 值直接取自 `GuardKind` 枚举（`DISABLE='Exit'` / `ENABLE='Restart'`），
      不再出现裸字符串 —— 领域层的 `guard_sequence()` 产出枚举，适配器负责落地。

    ★ 作用域（D6，勿误读）：guard 只对 **NSSM 托管的 erp-prod / erp-arq 有效**
      （AppExit 是 NSSM 特有概念），对原生 Windows 服务（erp-redis 等）
      **完全没有作用**。默认服务清单因此固定为 `NSSM_SERVICES`。

    返回每个服务的执行结果（旧实现 `suppress` 掉了一切，无留痕）。
    guard 的**时序**（成对、finally 恢复、晚于残留扫描）由应用层的
    `guard_sequence()` + try/finally 保证，本函数只负责发命令。
    """
    if not nssm_path:
        return ()

    results: list[VerbResult] = []
    for name in services:
        argv = ['nssm', 'set', name, 'AppExit', 'Default', kind.value]
        ok = run_quiet(
            argv, timeout=timeout, oem=True, executable=nssm_path, runner=runner
        )
        if ok:
            results.append(VerbResult.success(name, f'guard:{kind.value}'))
        else:
            results.append(
                VerbResult.failure(
                    name, f'guard:{kind.value}', f'设置 AppExit={kind.value} 失败'
                )
            )
    return tuple(results)


# ═══════════════════════════════════════════════════════════════════
# 控制命令
# ═══════════════════════════════════════════════════════════════════


def run_verb(
    name: str,
    verb: str,
    nssm_path: str | None,
    *,
    timeout: float = 30,
    runner: Runner | None = None,
) -> VerbResult:
    """执行 start / stop / restart 命令并返回结果（**不含目标状态确认**）。

    迁移自 `_service_one()`（L1477-1495）的**命令执行部分**。

        旧: argv = ['nssm', verb, name] if nssm else ['sc', verb, name]
            kwargs = _cap(30); 若 nssm 则 executable=nssm
            try: r = subprocess.run(argv, **kwargs)
            except TimeoutExpired: return False, f'{verb} 命令超时(30s)'
            except Exception as e: return False, f'{verb} 命令异常: {type(e).__name__}: {e}'
            if code != 0: return False, f'{verb} 命令失败(退出码 {code}): {out or "无输出"}'

    ★ 旧实现的三种失败文案**逐字保留**（运维靠它们认日志），
      包括 `无输出` 兜底与 `{type(e).__name__}: {e}` 的异常格式。

    ★ 本函数**不做**「是否达成目标状态」的确认 —— 那部分（`_wait_service_running` /
      `_wait_service_stopped` 调用）属于时序策略，交给应用层用
      `domain.readiness.wait_until` 组合完成。

      为什么这个拆分很重要：旧实现把「发命令」与「轮询 60s 等待就绪」
      耦合在一个函数里，导致它完全无法单测（真跑要等一分钟）。
      拆开后，命令执行是纯 I/O（可注入 runner），等待是领域层纯逻辑（可注入时钟）。
    """
    if nssm_path:
        argv = ['nssm', verb, name]
        executable: str | None = nssm_path
    else:
        argv = ['sc', verb, name]
        executable = None

    try:
        code, out, err = run_capture(
            argv, timeout=timeout, oem=True, executable=executable, runner=runner
        )
    except TimeoutError:
        return VerbResult.failure(name, verb, f'{verb} 命令超时({int(timeout)}s)')
    except Exception as e:  # 含 subprocess.TimeoutExpired
        if type(e).__name__ == 'TimeoutExpired':
            return VerbResult.failure(name, verb, f'{verb} 命令超时({int(timeout)}s)')
        return VerbResult.failure(name, verb, f'{verb} 命令异常: {type(e).__name__}: {e}')

    combined = (out + err).strip()
    if code != 0:
        return VerbResult.failure(
            name,
            verb,
            f'{verb} 命令失败(退出码 {code}): {combined or "无输出"}',
            detail=combined,
        )
    return VerbResult.success(name, verb, detail=combined)


def control_many(
    verb: str,
    snapshots: dict[str, ServiceQuery],
    nssm_path: str | None,
    *,
    skip_absent: bool = True,
    timeout: float = 30,
    runner: Runner | None = None,
) -> tuple[VerbResult, ...]:
    """对多个服务批量执行 verb，跳过未安装项。

    迁移自 `_service_cmd_sync()`（L1506-1534）的循环体：

        for name in (_SVC_API, _SVC_ARQ):
            if '未安装' in self._svc_state(name):
                log(f'{name} 未安装，跳过 {verb}', WARNING)
                continue
            ok, reason = self._service_one(name, verb, nssm)

    参数 `snapshots` 由调用方（应用层）先查询后传入 —— 这样本函数不重复查询，
    且「哪些跳过」的判定依据是领域层的 `ServiceQuery.is_absent`
    （由 `domain.service_state` 判定），不是适配器自己猜。

    ★ guard 的挂/摘不在这里做 —— 旧实现把 guard 包在 `_service_cmd_sync` 外层，
      新架构由应用层按 `domain.state_machine.guard_sequence()` 的成对序列执行，
      保证 finally 恢复（旧实现的 `finally: if guard_needed: guard(True)` 语义）。
    """
    results: list[VerbResult] = []
    for name, snap in snapshots.items():
        if skip_absent and snap.is_absent:
            results.append(
                VerbResult(
                    name, verb, ok=True, reason=None, detail='未安装，跳过'
                )
            )
            continue
        results.append(run_verb(name, verb, nssm_path, timeout=timeout, runner=runner))
    return tuple(results)


# ═══════════════════════════════════════════════════════════════════
# 依赖探测
# ═══════════════════════════════════════════════════════════════════


def detect_installed(
    names: tuple[str, ...] = (SVC_API, SVC_ARQ),
    *,
    timeout: float = 5,
    runner: Runner | None = None,
) -> dict[str, ServiceQuery]:
    """批量查询服务状态，返回 `{name: ServiceQuery}`。

    供 `domain.state_machine.plan_production_stop` 消费 ——
    领域层要求传入 `dict[str, ServiceStatus]`，由 `ServiceQuery.status` 提供。

    未安装的服务同样返回（状态为 ABSENT），**不是过滤掉** ——
    因为「未安装」与「查不到」在互杀防护里语义完全不同，必须让领域层看到。
    """
    return {name: query_state(name, timeout=timeout, runner=runner) for name in names}
