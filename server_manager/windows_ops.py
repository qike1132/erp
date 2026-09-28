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
        try:
            subprocess.run(cmd, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, timeout=30)
        except Exception:
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
    except Exception:
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
    except Exception:
        pass
    return list(pids)


def kill_port_sync(port, exclude=None):
    """释放端口占用 —— 纯清扫原语，★ 永不 checkpoint。

    紧急停止的职责就是「取消 + 清扫」：它先 cancel() 再清扫，若本方法带
    checkpoint，清扫本身会立刻被自己的取消信号打断（实测：端口一个都没释放）。
    取消策略属于 worker 的步骤边界，不属于清扫原语 —— 想提前退出就在调用前 checkpoint。

    ★ exclude：跳过这些 PID（NSSM 受管服务进程）。受管进程绝不能被 kill ——
    NSSM AppExit=Default Restart 会在 5 秒后把被强杀的进程拉起，形成「紧急停止
    变成重启」。紧急停止路径先经 nssm stop 正常停受管服务，此处再用 stop 前采集
    的受管 PID 兜底，防止 stop 超时失败时端口清理误杀受管进程触发自动重启。
    """
    for _ in range(3):
        pids = find_port_pids(port, exclude=exclude)
        if not pids:
            return
        # 批量终止：端口被海量进程占用时（如数百 nginx worker），
        # 逐个 taskkill 会耗时数十秒，批量可秒级完成。
        taskkill_many(pids)
        time.sleep(0.5)


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
    except Exception:
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
        except Exception:
            continue
    return pids


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
    project = str(project_dir).lower()
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
            cmdline = ' '.join(proc.info.get('cmdline') or []).lower().replace('/', '\\')
            matched = project in cmdline
            if not matched:
                with contextlib.suppress(Exception):
                    matched = project in str(proc.cwd()).lower().replace('/', '\\')
            if matched:
                pids.append(pid)
        except Exception:
            continue
    return pids


def kill_residual_async(msg_queue, project_dir, managed_pids_fn):
    """清理本项目残留进程（P0-4：精确特征 + 受管进程豁免）。

    stop_all 是「紧急重置」，但不能以误杀 NSSM 受管进程为代价 —— 原实现按
    进程名把 python / node 全杀，杀掉 erp-prod 后 NSSM 5 秒拉起 → 死循环。
    """
    def _kill_worker():
        if not _IS_WINDOWS:
            return
        try:
            msg_queue.put(('log', {'text': "正在扫描残留进程..."}))
            managed = managed_pids_fn()
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
