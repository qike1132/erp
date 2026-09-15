"""Windows 进程适配器 —— 终止进程、端口占用、残留扫描。

═══════════════════════════════════════════════════════════════════
迁移来源：server_manager.py v5.40
═══════════════════════════════════════════════════════════════════

| 原实现 | 位置 | 迁移为 |
|---|---|---|
| `_taskkill(pid)` | L354 | `kill_pid()` |
| `_taskkill_many(pids)` | L363 | `kill_many()` |
| `_kill_process_tree(pid)` | L1101 | `kill_tree()` |
| `_kill_port_sync(port)` | L1089 | `kill_port_sync()` |
| `_get_port_occupier(port)` | L395 | `port_occupiers()` |
| `_find_port_pids(port)` | L1072 | `port_pids()` |
| `_kill_residual()` | L1818 | `scan_residual()` |

═══════════════════════════════════════════════════════════════════
本模块承载的**安全约定**（每一条都是事故换来的，改动前必读）
═══════════════════════════════════════════════════════════════════

**约定 1：绝无 shell 参与**
    所有命令一律「参数列表 + 字面量 argv[0]」，绝不拼字符串、绝不 `shell=True`。
    否则 PID 等外部数据进入命令行时可能被解释为 shell 语法。

**约定 2：绝不向上杀祖先链**
    `kill_many` 的 psutil 路径终止「自身 + 全部后代」，**绝不包含 parents()**。
    向上杀可能殃及 explorer.exe 等无辜进程（旧代码注释明确警告）。

**约定 3：psutil 路径必须与 `taskkill /T` 同语义（v5.40 审查 #4）**
    只杀 netstat 报告的单个 PID 是不够的：监听 socket 句柄会被
    `--reload` supervisor / npm 等**父子进程共享继承**，单杀一个后其余进程
    仍持有句柄，端口释放 3 轮重试空转后**静默失效**。
    所以必须终止整个「自身 + 后代」家族。

**约定 4：绝不做宽特征兜底（v5.33 P0-3 / v5.40 审查 #5）**
    残留扫描只认精准特征（`prod_runner` / `arq_app`）+ 项目标记二级校验
    （cmdline 或 cwd 含 `erp_system` / `frontend-vite`）。
    曾经的宽特征扫描（`python` / `node`）会误杀 NSSM 被管进程
    → AppExit 判为崩溃 → 5 秒自动重启 → **死循环**。
    psutil 缺失时记 WARNING 并跳过，**绝不降级为宽特征**。

**约定 5：宁可漏杀，不可误杀**
    cwd 读取失败（权限）按「无标记」处理 → 放行。这是有意为之的保守方向。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from ..domain.port_contract import (
    PortFilter,
    extract_port_pids,
    parse_netstat_occupiers,
    parse_tasklist_name,
)
from ..domain.results import KillResult
from ..domain.state_machine import build_protected_pids  # noqa: F401  (re-export 供调用方)
from ._proc import Runner, is_windows, run_capture, run_quiet

# ★ 类型权威定义在 domain 层（Port 签名的返回类型必须如此，见 domain/results.py）。
#   本模块保留 KillOutcome 这个名字是**迁移期兼容垫**：旧调用点/测试写作 KillOutcome，
#   二者是同一对象（别名），不是两个类型。将来调用点统一后可删。
KillOutcome = KillResult

# 端口释放的重试轮数与间隔（迁移自 `_kill_port_sync`）
KILL_PORT_ROUNDS = 3
KILL_PORT_INTERVAL_S = 0.5

# psutil 可选（缺失时 metrics 与残留扫描降级，进程终止退回 taskkill）
try:  # pragma: no cover - 环境相关
    import psutil
except Exception:  # pragma: no cover
    psutil = None  # type: ignore[assignment]


def has_psutil() -> bool:
    """psutil 是否可用。"""
    return psutil is not None


# ═══════════════════════════════════════════════════════════════════
# 结果对象
# ═══════════════════════════════════════════════════════════════════
#
# ★ 命名说明（P3 修正）：本层的端口占用「展示用」记录名为 PortOccupierInfo，
#   而不是 PortOccupier —— 因为 domain 层已有一个 PortOccupier
#   （字段是 pid:int / local_addr / state），两者同名不同型：
#
#       domain.PortOccupier      pid:int   ← netstat 原始行的领域表示
#       adapters.PortOccupierInfo pid:str   ← 附带进程名，供 UI 留痕展示
#
#   同名会让「类型标注到底指哪个」变成靠记忆的事，也会让
#   `from ... import PortOccupier` 的两个来源产生语义歧义。改名消除歧义，
#   领域层的 PortOccupier 保持唯一权威定义。


@dataclass(frozen=True)
class PortOccupierInfo:
    """端口占用者（PID + 进程名），**供留痕展示**。

    与 domain 的 `PortOccupier` 的区别：本类型带 `name`（进程名），
    因为它的用途是写进日志/UI 让人看懂「谁占着端口」；
    domain 的 `PortOccupier` 是 netstat 行的忠实表示，不含进程名解析。
    """

    port: int
    pid: str
    name: str

    def describe(self) -> str:
        """留痕文案（迁移自 `_release_ports` 的日志格式）。"""
        return f'端口 {self.port} 被 {self.name}(PID {self.pid}) 占用，即将释放'


@dataclass(frozen=True)
class ResidualScan:
    """残留进程扫描结果。

    `skipped_reason` 非空表示**扫描未执行**（如 psutil 缺失），
    而不是「扫描了没发现」。这个区分很重要 —— 旧实现把两者都表达为
    「无受害者」，会让运维误以为环境干净。
    """

    victims: tuple[int, ...] = ()
    protected: frozenset[int] = frozenset()
    skipped_reason: str | None = None

    @property
    def scanned(self) -> bool:
        return self.skipped_reason is None

    @property
    def found_any(self) -> bool:
        return bool(self.victims)


# ═══════════════════════════════════════════════════════════════════
# 终止
# ═══════════════════════════════════════════════════════════════════


def taskkill_argv(pid: int, *, force: bool = True, tree: bool = True) -> list[str]:
    """拼装 taskkill 参数列表。

    迁移自 `_taskkill()`（L358）的 argv 构造，抽成纯函数以便单测：
        ['taskkill'] + (['/F'] if force else []) + (['/T'] if tree else []) + ['/PID', str(int(pid))]

    ★ **纯函数**：不执行命令。放在适配层的理由是它的**输出**（argv 形状）
      是平台细节（taskkill 的参数语法），但构造过程零 I/O。
      抽出来是因为「参数顺序」曾被改错会导致 taskkill 静默失败。
    """
    argv = ['taskkill']
    if force:
        argv.append('/F')
    if tree:
        argv.append('/T')
    argv.extend(['/PID', str(int(pid))])
    return argv


def kill_pid(
    pid: int,
    *,
    force: bool = True,
    tree: bool = True,
    timeout: float = 10,
    runner: Runner | None = None,
) -> bool:
    """终止单个 PID（可选进程树）。尽力而为语义。

    迁移自 `_taskkill()`（L354-360）：非 Windows 或无 PID 直接返回，
    执行时 `suppress(Exception)` 吞掉一切错误。
    """
    if not is_windows() or not pid:
        return False
    return run_quiet(
        taskkill_argv(pid, force=force, tree=tree),
        timeout=timeout,
        oem=False,
        runner=runner,
    )


def kill_many(
    pids: Iterable[int],
    *,
    force: bool = True,
    tree: bool = True,
    timeout: float = 10,
    runner: Runner | None = None,
    process_factory: Any = None,
) -> KillOutcome:
    """批量终止；优先 psutil（无进程创建开销），缺失时逐个 taskkill。

    迁移自 `_taskkill_many()`（L363-392），**约定 2 与 3 都在这里**。

    旧实现逐行对应：

        for pid in pids:
            if pid in killed: continue          # 已处理过（后代可能与兄弟重叠）
            try: proc = psutil.Process(int(pid))
            except Exception: _taskkill(pid); continue   # 进程已退出 → 退回 taskkill
            family = [proc]
            family.extend(proc.children(recursive=True))  # 不含 parents！
            for p in family:
                killed.add(p.pid)
                p.kill()                          # 每个都单独 suppress

    ★ `killed` 集合的作用：某 PID 的「后代」可能同时也是另一条记录的 PID，
      去重避免重复 kill 与重复计数。

    ★ 非 Windows / 空列表 → 直接返回（旧实现首个判定）。

    参数 `process_factory` 供测试注入假的 psutil.Process。
    """
    if not is_windows():
        return KillOutcome(0, backend='none')

    pid_list = [int(p) for p in pids if p]
    if not pid_list:
        return KillOutcome(0, backend='none')

    if psutil is not None or process_factory is not None:
        factory = process_factory or psutil.Process
        killed: set[int] = set()
        for pid in pid_list:
            if pid in killed:
                continue
            try:
                proc = factory(pid)
            except Exception:
                # 进程已退出或无权访问 → 退回 taskkill（旧行为）
                kill_pid(pid, force=force, tree=tree, timeout=timeout, runner=runner)
                killed.add(pid)
                continue
            family = [proc]
            try:
                family.extend(proc.children(recursive=True))
            except Exception:
                pass
            for p in family:
                killed.add(p.pid)
                try:
                    p.kill()
                except Exception:
                    pass
        return KillOutcome(len(killed), backend='psutil')

    for pid in pid_list:
        kill_pid(pid, force=force, tree=tree, timeout=timeout, runner=runner)
    return KillOutcome(len(pid_list), backend='taskkill')


def kill_tree(
    pid: int,
    *,
    timeout: float = 10,
    runner: Runner | None = None,
) -> bool:
    """终止进程树。

    迁移自 `_kill_process_tree()`（L1101-1108）：
        Windows → _taskkill(pid)（默认 force+tree）
        其它    → os.kill(pid, 15)

    ★ SIGTERM(15) 而非 SIGKILL：非 Windows 分支保留旧语义（给进程清理机会）。
    """
    if not pid:
        return False
    if is_windows():
        return kill_pid(pid, timeout=timeout, runner=runner)
    try:
        os.kill(int(pid), 15)
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════
# 端口占用查询
# ═══════════════════════════════════════════════════════════════════


def netstat_lines(
    *, timeout: float = 10, runner: Runner | None = None
) -> tuple[str, str | None]:
    """采集 `netstat -ano` 输出**文本**。返回 `(output, error)`。

    与旧代码的差异：旧实现在两处各自 `subprocess.run(['netstat','-ano'])`
    （L399 的 5s、L1075 的 10s），本函数统一入口但**保留各自的 timeout 由调用方传**。

    ★ 返回**字符串**而不是行列表：`domain.port_contract.parse_netstat_occupiers`
      的契约就是「netstat 的 stdout 文本」，它内部自己做 `splitlines()`。
      适配器在这里拆行等于把领域层的解析职责切走一半 —— 正是要避免的事。
    """
    try:
        _code, out, _err = run_capture(
            ['netstat', '-ano'], timeout=timeout, oem=True, runner=runner
        )
        return out or '', None
    except Exception as e:
        return '', f'{type(e).__name__}: {e}'


def port_pids(
    port: int,
    *,
    timeout: float = 10,
    runner: Runner | None = None,
) -> tuple[list[str], str | None]:
    """查询监听指定端口的 PID 列表（**击杀口径：仅 LISTENING**）。

    迁移自 `_find_port_pids()`（L1072-1087）。

    v5.40 审查 #23：只认 LISTENING —— TIME_WAIT 会自行过期且不阻塞重绑，
    纳入击杀目标只会产生多余的击杀尝试（实测本机 TIME_WAIT 占 609/1157 行）。

    ★ 解析交给 `domain.port_contract.extract_port_pids`（列位精确匹配），
      本层只管取原始输出与留痕。旧实现在这里**内联**了解析逻辑，
      其中还有 `':' in parts[1]` 这类脆弱判定；收口到领域层后，
      子串误报（`:3000` 匹配 `:30000`、匹配到外部地址列）已在领域层被修掉。

    返回 `(pids, error)`：`error` 非空表示采集失败（旧实现会 log WARNING）。
    """
    output, err = netstat_lines(timeout=timeout, runner=runner)
    if err:
        return [], err
    return extract_port_pids(output, port, PortFilter.LISTENING_ONLY), None


def port_occupiers(
    port: int,
    *,
    timeout: float = 5,
    runner: Runner | None = None,
    name_resolver: Any = None,
) -> tuple[list[PortOccupier], str | None]:
    """查询占用指定端口的进程 `(pid, name)` 列表（**留痕口径：LISTENING 或 ESTABLISHED**）。

    迁移自 `_get_port_occupier()`（L395-415）。

    ★ 两种口径刻意不同（详见 `domain.port_contract` 模块文档）：
        · 击杀 → 仅 LISTENING（TIME_WAIT 会自行过期）
        · 留痕 → LISTENING 或 ESTABLISHED（连接方也是占用者，运维需要知道）

    ★ v5.40 审查 #6 + D14：本函数在轻量停止的端口释放关键路径上，
      查询失败**必须留痕但不阻断** —— 保留「尽力而为」的失败语义，
      仍返回已收集项，同时把 error 交给调用方去 log。

    参数 `name_resolver` 供测试注入（默认走 tasklist）。
    """
    occupiers: list[PortOccupier] = []

    output, err = netstat_lines(timeout=timeout, runner=runner)
    if err:
        return [], err

    parsed = parse_netstat_occupiers(
        output, port, PortFilter.LISTENING_OR_ESTABLISHED
    )
    resolver = name_resolver or (
        lambda pid: resolve_process_name(pid, timeout=timeout, runner=runner)
    )
    seen: set[str] = set()
    for item in parsed:
        pid = str(item.pid)
        if pid in seen:
            continue
        seen.add(pid)
        name = resolver(pid)
        occupiers.append(PortOccupierInfo(port, pid, name))
    return occupiers, None


def resolve_process_name(
    pid: str,
    *,
    timeout: float = 5,
    runner: Runner | None = None,
) -> str:
    """`tasklist /FI "PID eq <pid>" /FO CSV /NH` → 进程名；失败返回「未知进程」。

    迁移自 `_get_port_occupier` 的内层（L404-409）：

        name = '未知进程'
        with suppress(Exception):
            tasklist = subprocess.run(['tasklist','/FI',f'PID eq {pid}','/FO','CSV','/NH'], **_cap(5))
            lines = [ln.strip() for ln in (tasklist.stdout or '').splitlines() if ln.strip()]
            if lines and len(lines[0].split('","')) >= 2:
                name = lines[0].split('","')[0].strip('"')

    ★ 解析（`split('","')` 那套脆弱逻辑）收口到 `domain.port_contract.parse_tasklist_name`。
    """
    try:
        _code, out, _err = run_capture(
            ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'],
            timeout=timeout,
            oem=True,
            runner=runner,
        )
    except Exception:
        return '未知进程'
    return parse_tasklist_name(out or '')


# ═══════════════════════════════════════════════════════════════════
# 端口清场（带重试）
# ═══════════════════════════════════════════════════════════════════


def kill_port_sync(
    port: int,
    *,
    sleep: Any = None,
    rounds: int = KILL_PORT_ROUNDS,
    interval_s: float = KILL_PORT_INTERVAL_S,
    timeout: float = 10,
    runner: Runner | None = None,
) -> KillOutcome:
    """3 轮重试终止端口占用进程（应对 PID 复用 / 延迟释放）。

    迁移自 `_kill_port_sync()`（L1089-1096）：

        for _ in range(3):
            pids = self._find_port_pids(port)
            if not pids: return
            _taskkill_many(pids)
            time.sleep(0.5)

    ★ 每轮**重新查询**而非复用首轮结果 —— 这是旧实现的关键设计：
      被杀进程的句柄可能被兄弟进程继承，重启后端口会出现新占用者，
      必须重新发现。这也解释了为什么「只杀一次」会静默失效。

    ★ `sleep` 可注入（默认 `time.sleep`），让单测不真实等待。
      这是 domain.readiness 同一个设计原则在适配层的延伸：
      虽然适配层允许 I/O，但可注入就能**确定性地**测试重试轮数。
    """
    import time as _time

    sleeper = sleep or _time.sleep
    if not is_windows():
        return KillOutcome(0, rounds=0, backend='none')

    total = 0
    last_backend = 'none'
    for idx in range(rounds):
        pids, err = port_pids(port, timeout=timeout, runner=runner)
        if err or not pids:
            return KillOutcome(total, rounds=idx + 1, backend=last_backend)
        outcome = kill_many(pids, timeout=timeout, runner=runner)
        total += outcome.targeted
        last_backend = outcome.backend
        sleeper(interval_s)

    return KillOutcome(total, rounds=rounds, backend=last_backend)


# ═══════════════════════════════════════════════════════════════════
# 残留进程扫描
# ═══════════════════════════════════════════════════════════════════

# 项目标记二级校验（v5.40 审查 #5）—— 宽特征必须叠加这两个标记之一
PROJECT_MARKERS: tuple[str, ...] = ('erp_system', 'frontend-vite')

# 业务进程精准特征（绝不误杀 NSSM 被管进程）
PROTECTED_CMDLINE_MARKERS: tuple[str, ...] = ('prod_runner', 'arq_app')


def is_residual_candidate(
    *,
    pid: int,
    cmdline: Sequence[str] | None,
    process_name: str,
    cwd: str,
    protected: frozenset[int],
    ancestor_pids: Iterable[int] = (),
) -> bool:
    """判定某进程是否为「需清理的游离残留」。

    **这是本模块唯一含判定的函数**（其余都是纯 I/O），
    因为它把 `domain.state_machine.is_residual_prod_runner`（精准特征）
    与 v5.40 审查 #5 的**项目标记二级校验**组合起来，本身是一条完整规则。

    逐条迁移自 `_kill_residual`（L1837-1861），顺序严格保持：

        1. pid 为空 → 不是                                    （is_residual 内部判）
        2. pid 在白名单（自身 + 服务 PID）→ 不是              （is_residual 内部判）
        3. cmdline 含 prod_runner → 不是候选                  ← 但注意旧实现这里
           「跳过」的是「NSSM 被管业务进程」，需与 protected 区分
        4. 祖先链含白名单 PID → 不是（服务进程的后代受保护）
        5. 项目标记校验：cmdline 或 cwd 含 erp_system / frontend-vite，
           否则不是（宁可漏杀，不可误杀）
        6. 特征命中：uvicorn / vite / node(进程名) / python+fastapi_app → 是

    ★ 第 3 条（`prod_runner` / `arq_app`）与 `is_residual_prod_runner` 的
      `'prod_runner' in cmdline` 名称相似但**语义相反**，极易混淆：
        · `is_residual_prod_runner` 回答「这是不是**要清**的游离残留」
        · 本处第 3 条回答「这是不是**绝不能碰**的 NSSM 被管进程」
      旧实现正是在这里 `continue` 掉它们。两者对 `prod_runner` 的处理方向
      **互不相同**，所以这里**不能**复用领域层那个函数的返回值 ——
      只复用其 PID 白名单部分（`pid in protected`）。

    ★ `cwd` 读取失败按空串处理 → 无标记 → 放行（约定 5）。
    """
    # 2：PID 白名单（自身 + 自己的服务 PID）—— 与领域层同一判据
    if not pid or pid in protected:
        return False

    joined = ' '.join(cmdline or [])
    low = joined.lower()
    pname = (process_name or '').lower()
    cwd_s = (cwd or '').lower()

    # 3：NSSM 被管业务进程 —— 误杀会被 AppExit 判为崩溃并自动重启
    if any(marker in low for marker in PROTECTED_CMDLINE_MARKERS):
        return False

    # 4：服务进程的后代同样受保护
    if any(anc in protected for anc in ancestor_pids):
        return False

    # 5：项目标记二级校验（宽特征的必要护栏）
    if not any(marker in low or marker in cwd_s for marker in PROJECT_MARKERS):
        return False

    # 6：特征命中
    if (
        'uvicorn' in low
        or 'vite' in low
        or 'node' in pname
        or ('python' in pname and 'fastapi_app' in low)
    ):
        return True

    return False


def scan_residual(
    *,
    protected: frozenset[int] = frozenset(),
    process_iter: Any = None,
) -> ResidualScan:
    """扫描游离残留进程（不执行终止）。

    迁移自 `_kill_residual()`（L1818-1869）的**扫描部分**，
    把「终止」拆出去（调用方拿到 `victims` 后再 `kill_tree`），
    这样扫描可以被安全地单测。

    ★ psutil 缺失 → 返回 `skipped_reason`（**不做宽特征兜底**）。
      旧实现：`log WARNING 缺少 psutil，跳过残留进程清理（不做宽特征兜底）`。

    ★ 白名单由调用方构造 —— 通常用
      `domain.state_machine.build_protected_pids(self_pid, service_pids)`
      （v5.33 P0-3 的修复点）。
    """
    if not is_windows():
        return ResidualScan(skipped_reason='非 Windows 平台')

    it = process_iter or (psutil.process_iter if psutil is not None else None)
    if it is None:
        return ResidualScan(
            protected=protected,
            skipped_reason='缺少 psutil，跳过残留进程清理（不做宽特征兜底）',
        )

    victims: list[int] = []
    for proc in it(['pid', 'name', 'cmdline']):
        try:
            info = proc.info
            pid = info.get('pid')
            cmdline = info.get('cmdline') or []
            pname = info.get('name') or ''
            try:
                cwd = str(proc.cwd() or '')
            except Exception:
                cwd = ''
            ancestor_pids: list[int] = []
            try:
                ancestor_pids = [anc.pid for anc in proc.parents()]
            except Exception:
                ancestor_pids = []

            if is_residual_candidate(
                pid=pid,
                cmdline=cmdline,
                process_name=pname,
                cwd=cwd,
                protected=protected,
                ancestor_pids=ancestor_pids,
            ):
                victims.append(int(pid))
        except Exception:
            continue

    return ResidualScan(victims=tuple(victims), protected=protected)
