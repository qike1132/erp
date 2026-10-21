"""server_manager 包的进程/端口操作层(纯函数,无状态)。

从 app.py 迁出(T2 包化第 2 步)。本模块【只能】依赖标准库与
``server_manager.constants`` —— 不得依赖任何 UI 工具包,也不得反向引用本包的
app 模块(那会循环导入)。

凡需要项目路径或实例状态的函数一律由调用方**注入**:
``project_dir`` / ``msg_queue`` / ``managed_pids_fn`` / ``exclude`` ——
模块内不持有任何可变状态,各函数可独立测试与复用。
``kill_residual_async`` 的 ``managed_pids_fn`` 是受管 PID 提供者(app 的
``_managed_service_pids``),在 worker 线程内才调用(它要跑多次 sc query,放主线程会卡 UI)。
"""
import contextlib
import os
import re
import subprocess
import threading
import time

from server_manager.constants import _IS_WINDOWS


def taskkill(pid, force=True, tree=True):
    """统一的进程终止函数"""
    if not _IS_WINDOWS:
        return
    cmd = ['taskkill', '/F' if force else '', '/T' if tree else '', '/PID', str(pid)]
    cmd = [c for c in cmd if c]
    subprocess.run(cmd, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, timeout=10)

def taskkill_many(pids, force=True, tree=True):
    """批量终止多个 PID — 一次 taskkill 调用处理多个 /PID。

    为什么必须批量：taskkill 单进程约 100ms+，若端口被大量残留进程占用
    （例如数百个 nginx worker），逐个调用会耗时数十秒甚至分钟，导致启动流程
    卡死在"清理端口"阶段。taskkill 原生支持多个 /PID 参数，分批 40 个/次即可。
    """
    if not _IS_WINDOWS or not pids:
        return
    pids = [str(p) for p in pids]
    for i in range(0, len(pids), 40):
        cmd = ['taskkill', '/F' if force else '', '/T' if tree else '']
        for pid in pids[i:i + 40]:
            cmd += ['/PID', pid]
        cmd = [c for c in cmd if c]
        try:  # noqa: SIM105 — 清理失败不应阻断后续清理
            subprocess.run(cmd, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, timeout=30)
        except Exception:  # noqa: S110 — 同上，逐项清理 best-effort
            pass

def is_prod_runner_cmdline(cmdline):
    """精确判定「生产监督器」进程（P0-4 修复的基础判据）。

    为什么不能用 `'prod_runner' in cmdline`：宽子串会命中编辑器/日志查看器打开
    该文件、以及 NSSM 正在监管的服务进程 —— 误杀后者会被 AppExit=Default Restart
    在 5 秒后拉起，形成「杀不死」死循环。

    只认两种独立参数形态：
      1) 模块式 `-m fastapi_app.core.prod_runner`（NSSM 安装时的 AppParameters）
      2) 脚本式 `.../fastapi_app/core/prod_runner.py`
    """
    if not cmdline:
        return False
    for token in re.split(r'[\s"\']+', cmdline):
        tok = token.strip('",;').replace('\\', '/')
        if not tok:
            continue
        if tok == 'fastapi_app.core.prod_runner':
            return True
        if tok.endswith('fastapi_app/core/prod_runner.py'):
            return True
    return False


def collect_process_tree(root_pid):
    """递归收集子进程 PID。

    ★ 必须优先 psutil：本机安全策略已永久屏蔽 wmic / sc（Program Blacklist），
    原 wmic 实现只会静默返回空列表 —— 而 P0-4 的「受管进程集合」正建立在
    进程树之上，拿到空集就等于失去误杀闸门。wmic 仅作降级保留。
    """
    pids = []
    if not root_pid:
        return pids
    try:
        import psutil
        return [child.pid for child in psutil.Process(root_pid).children(recursive=True)]
    except ImportError:
        pass
    except Exception:
        return pids
    try:
        result = subprocess.run(['wmic', 'process', 'where', f'(ParentProcessId={root_pid})', 'get', 'ProcessId'], creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True, timeout=5)
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.isdigit() and int(line) != root_pid:
                pids.extend(collect_process_tree(int(line)))
                pids.append(int(line))
    except Exception:  # noqa: S110 — 进程枚举失败按空结果处理
        pass
    return pids


def find_port_pids(port, exclude=None):
    exclude = {str(p) for p in (exclude or ())}
    pids = set()
    try:
        output = subprocess.run(['netstat', '-ano'], creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True, timeout=10)
        for line in output.stdout.splitlines():
            if 'LISTENING' not in line and 'TIME_WAIT' not in line:
                continue
            parts = line.split()
            if len(parts) >= 5 and ':' in parts[1] and parts[1].rsplit(':', 1)[-1] == str(port) and parts[-1].isdigit() and int(parts[-1]) > 0:
                if parts[-1] not in exclude:
                    pids.add(parts[-1])
    except Exception:  # noqa: S110 — netstat 不可用时按空结果处理
        pass
    return list(pids)


def kill_port_sync(port, exclude=None, managed_pids_fn=None):
    """释放端口占用 —— 纯清扫原语，★ 永不 checkpoint。

    紧急停止的职责就是「取消 + 清扫」：它先 cancel() 再清扫，若本方法带
    checkpoint，清扫本身会立刻被自己的取消信号打断（实测：端口一个都没释放）。
    取消策略属于 worker 的步骤边界，不属于清扫原语 —— 想提前退出就在调用前 checkpoint。

    ★ 受管进程豁免：NSSM 托管的 erp-prod / erp-arq 进程**绝不能直接 kill**。
    原因：NSSM 配了 AppExit=Default Restart + AppRestartDelay=5000，杀掉后 5 秒即被
    重新拉起 —— 杀→复活→再杀是「杀不死」死循环，且会把生产后端反复打断。
    受管进程只能经 `nssm stop` 停止。
      · ``exclude``：调用方**已采集**的受管 PID（nssm stop 之前采样，stop 超时失败时兜底）。
      · ``managed_pids_fn``：受管 PID 的**提供者**，由本函数自行调用；其返回 ``None``
        表示「受管集合不可知」（探测通道不可用），此时 fail-safe 放弃清理。

    ★ 返回值（五态，**位标志**而非「两布尔按优先级」）：
      - 'clean'                本轮本来就没有占用者，无事可做
      - 'killed'               只终止了非受管占用者
      - 'all_exempted'         占用者全是受管进程（受豁免，一个都没杀）
      - 'killed_and_exempted'  既杀了非受管，又剩下了受管（两件事**都**发生了）
      - 'managed_unknown'      受管集合**不可知** → fail-safe 放弃清理

    为什么必须用位标志：若写成「先判 killed 再判 all_exempted」，遇到「第一轮杀了
    非受管、第二轮只剩受管」时只会返回 'killed'，把「仍有受管进程占着端口」这个
    事实吞掉，调用方就会误以为端口已干净（真值表场景 C3 实测）。
    """
    flags = 0                                   # 1=killed, 2=all_exempted，可叠加
    exempt = {int(p) for p in (exclude or ()) if str(p).strip().isdigit()}
    if managed_pids_fn is not None:
        managed = managed_pids_fn()
        if managed is None:
            # ★ 显式判 None，严禁 `or ()` / `or set()` 折叠 —— 折叠会把「不可知」
            # 静默转成「确认为空」，进而把受管进程当普通占用者杀掉（fail-open 误杀）。
            return 'managed_unknown'
        exempt |= {int(p) for p in managed if str(p).strip().isdigit()}
    for _ in range(3):
        # 不传 exclude 给 find_port_pids：这里要做集合差，才能区分
        # 「没占用者」与「占用者全是受管」这两种截然不同的结果。
        port_pids = {int(p) for p in find_port_pids(port) if str(p).strip().isdigit()}
        if not port_pids:
            break
        to_kill = port_pids - exempt
        if not to_kill:
            flags |= 2                          # 本轮占用者全为受管
            break
        # 批量终止：端口被海量进程占用时（如数百 nginx worker），
        # 逐个 taskkill 会耗时数十秒，批量可秒级完成。
        taskkill_many(sorted(to_kill))
        flags |= 1
        time.sleep(0.5)
    if flags == 3:
        return 'killed_and_exempted'
    if flags == 1:
        return 'killed'
    if flags == 2:
        return 'all_exempted'
    return 'clean'


def kill_process_tree(pid):
    if not pid:
        return
    try:
        if _IS_WINDOWS:
            taskkill(pid)
        else:
            import signal
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except Exception:
                with contextlib.suppress(Exception):
                    os.kill(pid, signal.SIGTERM)
    except Exception:  # noqa: S110 — kill 失败由上层汇总
        pass


def find_loose_prod_runner_pids(exclude=()):
    """精确定位「游离」的 prod_runner（不经 NSSM 托管的手工启动进程）。

    判据 = 命令行命中 is_prod_runner_cmdline（模块式/脚本式精确匹配），
    而非原先的 `-match 'prod_runner'` 宽子串扫描。
    """
    exclude = set(exclude or ())
    self_pid = os.getpid()
    pids = []
    try:
        import psutil
    except ImportError:
        return pids
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            pid = proc.info.get('pid')
            if not pid or pid == self_pid or pid in exclude:
                continue
            if is_prod_runner_cmdline(' '.join(proc.info.get('cmdline') or [])):
                pids.append(pid)
        except Exception:  # noqa: S112 — 单进程读取失败继续扫描
            continue
    return pids


# F3-10：只有「运行时」进程才可能是本项目的残留；编辑器/终端/explorer 的命令行
# 里出现项目路径是常态，按路径裸匹配会误杀它们。
_RESIDUAL_PROCESS_NAMES = {
    'python', 'python.exe', 'pythonw', 'pythonw.exe',
    'py', 'py.exe', 'node', 'node.exe', 'uvicorn', 'uvicorn.exe',
}


def find_project_residual_pids(project_dir, exclude=()):
    """扫描本项目的残留开发/调试进程（P0-4）。

    替代原先「凡名字带 python / node 一律杀」的宽特征扫描 —— 那会误杀 NSSM
    受管的生产进程，以及机器上任何无关的 Python / Node 程序。
    现判据：命令行或工作目录指向本项目，且不在排除集内。
    """
    exclude = set(exclude or ())
    exclude.add(os.getpid())
    with contextlib.suppress(Exception):
        exclude.add(os.getppid())  # PyInstaller onefile 的 bootloader 父进程
    # 分隔符归一化必须**两侧同做**：下面把 cmdline/cwd 的 '/' 换成 '\\' 再比对，
    # 若 project 仍留着 POSIX 分隔符，Linux 上就永远匹配不上（CI 里
    # test_editor_with_project_path_is_not_killed 因此拿到空列表 —— 真实残留
    # 进程会被漏杀，属于只在非 Windows 侧静默失效的判据缺陷）。
    project = str(project_dir).lower().replace('/', '\\')
    pids = []
    try:
        import psutil
    except ImportError:
        return pids
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            pid = proc.info.get('pid')
            if not pid or pid in exclude:
                continue
            proc_name = str(proc.info.get('name') or '').lower()
            if proc_name not in _RESIDUAL_PROCESS_NAMES:
                continue
            cmdline = ' '.join(proc.info.get('cmdline') or []).lower().replace('/', '\\')
            matched = project in cmdline
            if not matched:
                with contextlib.suppress(Exception):
                    matched = project in str(proc.cwd()).lower().replace('/', '\\')
            if matched:
                pids.append(pid)
        except Exception:  # noqa: S112 — 单进程读取失败继续扫描
            continue
    return pids


def kill_residual_async(msg_queue, project_dir, managed_pids_fn):
    """清理本项目残留进程（P0-4：精确特征 + 受管进程豁免）。

    stop_all 是「紧急重置」，但不能以误杀 NSSM 受管进程为代价 —— 原实现按
    进程名把 python / node 全杀，杀掉 erp-prod 后 NSSM 5 秒拉起 → 死循环。

    ``managed_pids_fn()`` 返回 ``None`` 表示「受管集合不可知」（探测通道不可用）：
    此时**放弃清理并告警**（fail-safe），绝不按空集排除后照杀。
    """
    def _kill_worker():
        if not _IS_WINDOWS:
            return
        try:
            msg_queue.put(('log', {'text': "正在扫描残留进程..."}))
            managed = managed_pids_fn()
            # ★ P0-2（最严重的一条）：`managed is None` 表示「受管集合不可知」，
            # 绝不能交给 `find_project_residual_pids(exclude=...)` —— 该方法首行是
            # `exclude = set(exclude or ())`，会把 None 静默折叠成空集，
            # 于是**所有**本项目进程（含 erp-prod / erp-arq）都被判为「残留」，
            # 紧接着 taskkill 会真的把它们杀掉 → NSSM 5 秒拉起 → 死循环。
            # 正确处置：fail-safe —— 告警并放弃本轮清理（宁可不清，不可误杀）。
            if managed is None:
                msg_queue.put(('log', {
                    'text': '无法确认 NSSM 受管进程集合（服务查询失败），'
                            '为避免误杀生产进程，已跳过残留清理。请稍后重试。',
                    'level': 'WARNING',
                }))
                return
            if managed:
                msg_queue.put(('log', {'text': f'已识别 {len(managed)} 个 NSSM 受管进程，不在清理范围内'}))
            pids = find_project_residual_pids(project_dir, exclude=managed)
            if not pids:
                msg_queue.put(('log', {'text': '未发现本项目残留进程'}))
                return
            msg_queue.put(('log', {'text': f"发现 {len(pids)} 个本项目残留进程，正在终止..."}))
            for pid in pids:
                with contextlib.suppress(Exception):
                    taskkill(pid)
        except Exception as e:
            msg_queue.put(('log', {'text': f"清理残留进程出错: {e}", 'level': 'WARNING'}))
    threading.Thread(target=_kill_worker, daemon=True).start()
