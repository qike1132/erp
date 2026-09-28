"""
ERP 服务器管理器 GUI v5.5
功能:
  - 一键启动前后端：同时启动 FastAPI 后端 + Vue/Vite 前端 + Redis服务
  - 一键重启：停止所有进程和端口，然后重新启动服务
  - 全部停止：停止所有前后端进程、Redis服务，清理所有Python相关残留进程
  - 启动进度反馈：4步骤进度显示，实时状态更新
  - Redis状态监控：实时显示Redis运行状态，支持外部Redis进程管理
  - 单实例限制 — 同一时间只能运行一个管理器
  - 窗口居中显示 (无闪烁，小屏幕自适应)
  - 系统托盘集成 — 关闭按钮隐藏到托盘，最小化保留任务栏图标
  - 性能优化 — Font 度量缓存、批量日志写入、队列通信、主线程零阻塞
  - 彻底进程管理 — 完整进程树收集 + 递归 kill + 端口占用验证释放
  - 日志自动清理
  - 状态强制重置：遇到状态卡顿时，支持强制重置并重新启动
  - 高端暗色 UI — Linear/Vercel 风格配色 + 微交互动画
"""
import hashlib
import json
import locale
import logging
import math
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

_IS_WINDOWS = sys.platform == 'win32'

if _IS_WINDOWS:
    import io
    for stream in (sys.stdout, sys.stderr):
        if stream:
            try:
                stream.reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                if hasattr(stream, 'buffer'):
                    stream = io.TextIOWrapper(stream.buffer, encoding='utf-8', errors='replace', line_buffering=True)

import contextlib
import tkinter as tk
from tkinter import messagebox, ttk

_VERSION = 'v5.33'
_WINDOW_TITLE = f'ERP 服务器管理器 {_VERSION}'
_REDIS_PORT = 6379
_REDIS_EXE_PATHS = [Path(r'C:\Redis\redis-server.exe'), Path(r'C:\Program Files\Redis\redis-server.exe')]
_REDIS_CONF_PATHS = [Path(r'C:\Redis\redis.windows.conf'), Path(r'C:\Redis\redis.conf')]
# 生产模式：Windows 服务 (NSSM) 名称与 NSSM 常见安装位置
_SVC_API = 'erp-prod'
_SVC_ARQ = 'erp-arq'
# nginx 静态服务:prod_runner 已不再托管前端,由独立 NSSM 服务 erp-web 直管 nginx.exe。
# 无依赖(反代上游未起只 502,静态照常服务);与 erp-prod 启停解耦。
_SVC_WEB = 'erp-web'
# Redis 服务：缓存 6379 与 ARQ broker 6380 各一个实例。
#   ★ erp-arq 必须依赖 _SVC_REDIS_BROKER：没有 DependOnService 时，开机由 SCM
#     并行启动，erp-arq 会抢在 broker 之前连 6380 → 超时退出 → NSSM 5s 后重拉，
#     形成无限重启循环，cron/备份/报表全部静默不执行（2026-09-16 实测现场）。
_SVC_REDIS_CACHE = 'erp-redis'
_SVC_REDIS_BROKER = 'erp-redis-broker'
# erp-prod 依赖缓存实例（Redis 不可用时后端缓存层大面积降级）
_SVC_DEPENDS = {
    _SVC_API: [_SVC_REDIS_CACHE],
    _SVC_ARQ: [_SVC_REDIS_BROKER],
}
# ARQ broker 端口（与 config/redis-broker.conf 的 port 一致）
_REDIS_BROKER_PORT = 6380
_NSSM_CANDIDATES = [
    Path(r'C:\nssm\nssm.exe'),
    Path(r'C:\Program Files\nssm\nssm.exe'),
    Path(r'C:\Program Files (x86)\nssm\nssm.exe'),
    Path(r'C:\tools\nssm\nssm.exe'),
]
_PROD_STATUS_FILE = Path(r'logs\prod_runner.json')

_mutex_handle = None

def _ensure_single_instance():
    global _mutex_handle
    if not _IS_WINDOWS:
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetLastError(0)
        user_hash = hashlib.sha256(os.environ.get('USERPROFILE', str(Path.home())).encode()).hexdigest()[:8]
        handle = kernel32.CreateMutexW(None, False, f'ERP_Server_Manager_{user_hash}_v1')
        if ctypes.GetLastError() == 183:
            return False
        _mutex_handle = handle
        return True
    except Exception as e:
        logging.warning(f"互斥体创建异常: {e}")
        return True

def _activate_existing_window():
    if not _IS_WINDOWS:
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, _WINDOW_TITLE)
        if hwnd:
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass

def _get_project_dir():
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        if (exe_dir / 'fastapi_app').is_dir():
            return exe_dir
        path_cfg = exe_dir / 'erp_project_path.txt'
        if path_cfg.is_file():
            cfg_path = Path(path_cfg.read_text(encoding='utf-8').strip()).resolve()
            if cfg_path.is_dir() and (cfg_path / 'fastapi_app').is_dir():
                return cfg_path
        for candidate in [Path(r'd:\erp_system')]:
            if candidate.is_dir() and (candidate / 'fastapi_app').is_dir():
                with contextlib.suppress(Exception):
                    (exe_dir / 'erp_project_path.txt').write_text(str(candidate), encoding='utf-8')
                return candidate
        return exe_dir
    return Path(__file__).resolve().parent

def _validate_python_exe(python_exe):
    if not python_exe:
        return False
    try:
        result = subprocess.run([python_exe, '--version'], creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0, capture_output=True, text=True, timeout=5)
        return result.returncode == 0 and 'Python' in result.stdout
    except Exception:
        return False

_PROJECT_DIR = _get_project_dir()
_FRONTEND_DIR = _PROJECT_DIR / "frontend-vite"
_API_PORT = 5002
_WEB_PORT = 3000

# 本机探针必须绕开系统代理：prod_runner 曾因代理转发 127.0.0.1 探测导致间歇失败、
# 进而误判后端崩溃并重启（见 prod_runner 内 _OPENER_DIRECT 注释）。
_HTTP_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def _get_python_executable():
    if not getattr(sys, 'frozen', False):
        return sys.executable
    project_dir = _get_project_dir()
    venv_candidates = [
        project_dir / '.venv313' / 'Scripts' / 'python.exe',
        project_dir / '.venv' / 'Scripts' / 'python.exe',
        project_dir / 'venv' / 'Scripts' / 'python.exe',
    ]
    for venv_py in venv_candidates:
        if venv_py.is_file():
            return str(venv_py)
    py_exe = Path(os.environ.get('SYSTEMROOT', r'C:\Windows')) / 'py.exe'
    if py_exe.is_file():
        return str(py_exe)
    python_in_path = shutil.which('python')
    if python_in_path:
        return python_in_path
    for candidate in [Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Python' / 'Python313' / 'python.exe', Path(r'C:\Python313\python.exe'), Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Python' / 'Python312' / 'python.exe', Path(r'C:\Python312\python.exe')]:
        if candidate.is_file():
            return str(candidate)
    return None

_PYTHON_EXE = _get_python_executable()
if _PYTHON_EXE and not _validate_python_exe(_PYTHON_EXE):
    _PYTHON_EXE = None

_font_cache = {}

def _font_exists(name):
    if name in _font_cache:
        return _font_cache[name]
    try:
        import tkinter.font as tkfont
        root = tk._default_root or tk.Tk()
        result = name in tkfont.families(root)
    except Exception:
        result = False
    _font_cache[name] = result
    return result

def _shift_color(hex_c, amount):
    """颜色偏移 - 模块级公共函数"""
    r = max(0, min(255, int(hex_c[1:3], 16) + amount))
    g = max(0, min(255, int(hex_c[3:5], 16) + amount))
    b = max(0, min(255, int(hex_c[5:7], 16) + amount))
    return f'#{r:02x}{g:02x}{b:02x}'

def _lerp_color(c1, c2, t):
    """颜色线性插值 - 模块级公共函数"""
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    return f'#{int(r1+(r2-r1)*t):02x}{int(g1+(g2-g1)*t):02x}{int(b1+(b2-b1)*t):02x}'

# 按钮视觉变体调色板 - 与 ServerManagerApp._PALETTE 严格对齐
# solid    状态：fill=fill（实色）/hover=fill_h（加深）/fg=#ffffff
# outlined 状态：fill=#ffffff /hover=tint_h（淡染色）/fg=fill / 边框=fill
# subtle   状态：fill=tint（极浅色）/hover=tint_h /fg=fill / 边框=subtle_border
_BUTTON_VARIANT_PALETTE = {
    'accent': {
        'fill': '#007aff', 'fill_h': '#0064d1', 'tint': '#e8f1ff', 'tint_h': '#d5e8ff',
        'fg': '#ffffff', 'subtle_border': '#c8dcfb',
        'transparent_fill': '#ffffff',
    },
    'success': {
        'fill': '#34c759', 'fill_h': '#2ba847', 'tint': '#e6f9ec', 'tint_h': '#d3f3dc',
        'fg': '#ffffff', 'subtle_border': '#bbe6c5',
        'transparent_fill': '#ffffff',
    },
    'danger': {
        'fill': '#ff3b30', 'fill_h': '#d92d22', 'tint': '#ffece9', 'tint_h': '#ffdad3',
        'fg': '#ffffff', 'subtle_border': '#f5b8b1',
        'transparent_fill': '#ffffff',
    },
    'neutral': {
        'fill': '#f2f2f7', 'fill_h': '#e5e5ea', 'tint': '#f2f2f7', 'tint_h': '#e5e5ea',
        'fg': '#1d1d1f', 'subtle_border': '#e5e5ea',
        'transparent_fill': '#ffffff',
    },
}

def _taskkill(pid, force=True, tree=True):
    """统一的进程终止函数"""
    if not _IS_WINDOWS:
        return
    cmd = ['taskkill', '/F' if force else '', '/T' if tree else '', '/PID', str(pid)]
    cmd = [c for c in cmd if c]
    subprocess.run(cmd, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, timeout=10)

def _taskkill_many(pids, force=True, tree=True):
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

def _is_prod_runner_cmdline(cmdline):
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


def _kill_port_process(port, msg_queue=None):
    """终止占用指定端口的进程"""
    try:
        result = subprocess.run(['netstat', '-ano'], creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True, timeout=5)
        for line in result.stdout.split('\n'):
            if f':{port}' in line and 'LISTENING' in line:
                parts = line.split()
                if len(parts) >= 5 and parts[-1].isdigit():
                    _taskkill(int(parts[-1]))
                    if msg_queue:
                        msg_queue.put(('log', {'text': f"已终止端口{port}占用进程 (PID: {parts[-1]})"}))
                    return True
    except Exception:
        pass
    return False

def _get_port_occupier(port):
    """获取占用指定端口的进程信息列表 [(pid, name), ...]"""
    occupiers = []
    try:
        result = subprocess.run(['netstat', '-ano'], creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True, timeout=5)
        pids = set()
        for line in result.stdout.split('\n'):
            if f':{port}' in line and ('LISTENING' in line or 'ESTABLISHED' in line):
                parts = line.split()
                if len(parts) >= 5 and parts[-1].isdigit():
                    pids.add(parts[-1])
        for pid in pids:
            try:
                tasklist = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'], creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True, timeout=5)
                lines = [l.strip() for l in tasklist.stdout.split('\n') if l.strip()]
                if lines:
                    parts = lines[0].split('","')
                    if len(parts) >= 2:
                        name = parts[0].strip('"')
                        occupiers.append((pid, name))
            except Exception:
                occupiers.append((pid, '未知进程'))
    except Exception:
        pass
    return occupiers

# ===================== 动作闸门（P0-3 重构：单一持有者 / 自动释放 / 可协作取消） =====================
# 为什么要有这个类（2026-09-16 审计实测出的两个缺陷）：
#   ① 旧实现把「取锁 / 起线程 / 解锁」拆在三个方法里：任何一处异常（例如 UI 刷新报
#      TclError）就会永久持锁 → 所有动作按钮永久置灰、状态卡在 starting，只能重启进程。
#   ② 紧急停止绕过互斥，却没有任何取消机制：在飞行中的启动流程会继续把 Redis / 后端
#      拉起来（实测 UI 已显示 none 而后端进程真的在跑）。
# 本类的三条结构性约束：
#   1. 单一持有者 —— 只有 start() 一个入口，且它自己负责起线程；调用方拿不到
#      「只获取不释放」的用法；
#   2. 自动释放 —— worker 无论正常返回 / 抛异常 / 被取消，都由 try/finally 收尾，
#      另有看门狗兜底「worker 永不返回」；
#   3. 可协作取消 —— cancel() 置标志，worker 在步骤边界调 checkpoint() 立即中止，
#      不再产生后续副作用。
_OP_WATCHDOG_SEC = 600          # 单次动作上限（安装服务最坏 ≈ 400s，故取 600）
_EMERGENCY_JOIN_SEC = 8         # 紧急停止等待在飞行动作自行退出的上限


class _ActionCancelled(BaseException):
    """动作被取消的信号。

    ★ 刻意继承 BaseException 而非 Exception：本模块有 17 处 `except Exception: pass`，
    若继承 Exception，取消信号会在半路被吞掉、流程继续执行后续副作用 ——
    那正是「紧急停止后进程又被拉起来」的来路。
    """


class ActionGate:
    """动作闸门：一个不变量，一个主人，一条执行路径。"""

    def __init__(self, watchdog_seconds=_OP_WATCHDOG_SEC, on_event=None):
        self._lock = threading.Lock()
        self._owner = ''
        self._cancel = threading.Event()
        self._cancel_reason = ''      # 谁取消的（紧急停止 / 看门狗超时）—— 日志里必须能区分
        self._watchdog = None
        self._active_run = None
        self._run_seq = 0
        self._local = threading.local()   # 每个 worker 线程记录自己的 run_id（用于识别僵尸 worker）
        self._watchdog_seconds = watchdog_seconds
        self._on_event = on_event or (lambda kind, payload: None)

    # ---------- 只读状态（唯一的"占用"真相源就是这把锁） ----------
    @property
    def owner(self):
        return self._owner

    def busy(self):
        return self._lock.locked()

    def cancelled(self):
        return self._cancel.is_set()

    # ---------- 唯一入口 ----------
    def start(self, name, worker, *args):
        """开始一个动作；已有动作在执行则拒绝（不排队、不阻塞，由调用方决定提示）。"""
        if not self._lock.acquire(blocking=False):
            self._on_event('rejected', {'owner': self._owner, 'attempt': name})
            return False
        self._run_seq += 1
        run_id = self._run_seq
        self._active_run = run_id
        self._owner = name
        self._cancel.clear()
        self._cancel_reason = ''
        timer = threading.Timer(self._watchdog_seconds, self._watchdog_fire, args=(run_id, name))
        timer.daemon = True
        self._watchdog = timer
        timer.start()
        self._on_event('started', {'owner': name})
        threading.Thread(target=self._run, args=(run_id, name, worker, args), daemon=True).start()
        return True

    def cancel(self, reason='紧急停止'):
        """请求取消在飞行动作（紧急停止调用）。无动作时仅置标志，下一次 start 会清掉。

        ★ 空闲时不发事件：紧急停止在没动作在跑时也会调 cancel()，若照样上报，
        日志里会反复出现「正在取消动作：（空闲）…」这类噪音。
        """
        self._cancel.set()
        self._cancel_reason = reason or self._cancel_reason
        if self._active_run is not None:
            self._on_event('cancel-requested', {'owner': self._owner, 'reason': reason})

    def checkpoint(self):
        """worker 的步骤边界：已取消 / 所属动作已作废则抛 _ActionCancelled，阻断后续副作用。

        ★ 除了取消标志，还要看「这次运行是否还是当前运行」：看门狗强制释放后，旧 worker
        可能仍在跑，而下一个动作会 clear() 掉取消标志 —— 只查标志的话，僵尸 worker 会被
        「复活」并把进程拉起来。run_id 比对让它永久作废。
        非闸门线程（run_id 为 None）仍按取消标志判断，保持原有语义。
        """
        my_run = getattr(self._local, 'run_id', None)
        is_zombie = my_run is not None and my_run != self._active_run
        if is_zombie or self._cancel.is_set():
            raise _ActionCancelled()

    def wait_idle(self, timeout=_EMERGENCY_JOIN_SEC):
        """等待在飞行动作退出；False = 超时（调用方应继续强制清扫）。"""
        deadline = time.monotonic() + timeout
        while self._active_run is not None and time.monotonic() < deadline:
            time.sleep(0.1)
        return self._active_run is None

    # ---------- 内部：执行与收尾 ----------
    def _run(self, run_id, name, worker, args):
        self._local.run_id = run_id
        try:
            worker(*args)
        except _ActionCancelled:
            # 带上真实取消原因：看门狗超时不能用「紧急停止」四个字糊过去（审计实测到该歧义）
            self._on_event('cancelled', {'owner': name, 'reason': self._cancel_reason})
        except BaseException as e:      # noqa: BLE001 — 收尾责任在此，必须转成事件上报
            self._on_event('failed', {'owner': name, 'error': f'{type(e).__name__}: {e}'})
        finally:
            self._finish(run_id)

    def _watchdog_fire(self, run_id, name):
        if run_id != self._active_run:
            return
        self._on_event('watchdog', {'owner': name, 'seconds': self._watchdog_seconds})
        self._cancel_reason = f'看门狗超时 {self._watchdog_seconds}s'
        self._cancel.set()
        self._finish(run_id)

    def _finish(self, run_id):
        if run_id != self._active_run:
            return                      # 已被看门狗收尾，不重复释放
        self._active_run = None
        self._owner = ''
        timer, self._watchdog = self._watchdog, None
        if timer is not None:
            timer.cancel()
        self._lock.release()
        self._on_event('finished', {'owner': ''})


class RoundedButton(tk.Canvas):
    """基于 Canvas 的圆角按钮 — 三种视觉变体：solid / outlined / subtle。

    设计规格（统一）：
        高度    36px (padx=16, pady=6 + font linespace ≈ 36)；mini 26px (pady=2)
        圆角    10px (mini 8px)
        字号    9pt bold (mini 8pt)
        间距    水平 8px（在调用方以 padx=(8,0) 实施）
        Hover   180ms 平滑过渡到 +12 加深色（solid） / 主色 12% 透明染（outlined / subtle）
        Press   立即下沉 1px、背景再加深 6%
        Disabled 背景 #f2f2f7 / 文字 #aeaeb2 / 边框 #e5e5ea / cursor not-allowed
    """

    _DISABLED_BG = '#f2f2f7'
    _DISABLED_FG = '#aeaeb2'
    _DISABLED_BORDER = '#e5e5ea'

    def __init__(self, parent, text='', variant='solid', tone='accent',
                 command=None, font=('Microsoft YaHei UI', 9, 'bold'),
                 padx=16, pady=6, radius=10, state='normal', canvas_bg=None,
                 hover_fill=None, fg=None, fill=None, **kw):
        """variant: 'solid'(实色填充) / 'outlined'(边框+透明) / 'subtle'(淡色填充)
        tone:    'accent' / 'success' / 'danger' / 'neutral'
        其余旧参数（fill/hover_fill/fg）保留向后兼容。"""
        # 兼容旧 API：若调用方显式给了 fill 但未给 variant/toner，按旧模式当 solid 处理
        legacy = fill is not None and variant == 'solid' and tone == 'accent'
        if fill is not None and (fg is not None or hover_fill is not None):
            legacy = True

        palette = _BUTTON_VARIANT_PALETTE
        if legacy:
            # 老路子：fill/hover_fill 直接用调用方传入的；fg 走调用方
            cfg_fill = fill
            cfg_hover = hover_fill or _shift_color(fill, 18)
            cfg_fg = fg or '#ffffff'
            cfg_outline = ''
            cfg_outline_hover = ''
            cfg_outline_w = 0
            eff_variant = 'solid-legacy'
        else:
            tone_cfg = palette.get(tone, palette['accent'])
            if variant == 'solid':
                cfg_fill = tone_cfg['fill']
                cfg_hover = tone_cfg['fill_h']
                cfg_fg = tone_cfg['fg']
                cfg_outline = ''
                cfg_outline_hover = ''
                cfg_outline_w = 0
                eff_variant = 'solid'
            elif variant == 'outlined':
                cfg_fill = tone_cfg.get('transparent_fill', '#ffffff')
                cfg_hover = tone_cfg['tint_h']
                cfg_fg = tone_cfg['fill']
                cfg_outline = tone_cfg['fill']
                cfg_outline_hover = tone_cfg['fill_h']
                cfg_outline_w = 1
                eff_variant = 'outlined'
            elif variant == 'subtle':
                cfg_fill = tone_cfg['tint']
                cfg_hover = tone_cfg['tint_h']
                cfg_fg = tone_cfg['fill']
                cfg_outline = tone_cfg.get('subtle_border', _shift_color(tone_cfg['tint'], -12))
                cfg_outline_hover = tone_cfg['fill']
                cfg_outline_w = 1
                eff_variant = 'subtle'
            else:
                cfg_fill = tone_cfg['fill']; cfg_hover = tone_cfg['fill_h']; cfg_fg = tone_cfg['fg']
                cfg_outline = ''; cfg_outline_hover = ''; cfg_outline_w = 0
                eff_variant = 'solid'

        import tkinter.font as tkfont
        f = tkfont.Font(font=font)
        text_w = f.measure(text)
        # 最小宽度 80：避免窄按钮在小屏上挤成"重启"二字团
        w = max(80, text_w + padx * 2 + cfg_outline_w * 2)
        h = f.metrics('linespace') + pady * 2
        canvas_bg = canvas_bg or '#ffffff'
        cursor = 'hand2' if state == 'normal' else 'arrow'
        super().__init__(parent, width=w, height=h, highlightthickness=0, cursor=cursor, bg=canvas_bg, **kw)
        self._text = text
        self._fill, self._hover_fill, self._fg = cfg_fill, cfg_hover, cfg_fg
        self._outline = cfg_outline
        self._outline_hover = cfg_outline_hover
        self._outline_w = cfg_outline_w
        self._variant = eff_variant
        self._font, self._radius, self._command = font, radius, command
        self._state, self._hover, self._press = state, False, False
        self._anim_after_id = None
        self.bind('<Configure>', self._draw)
        self.bind('<Enter>', lambda e: self._hover_in())
        self.bind('<Leave>', lambda e: self._hover_out())
        self.bind('<ButtonPress-1>', lambda e: self._press_in())
        self.bind('<ButtonRelease-1>', lambda e: self._press_out())
        # 初始立即绘制（不依赖 <Configure>），避免按钮首次显示为空白、鼠标移上才出现
        self._draw()

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2, x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _draw(self, _=None):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        # widget 尚未映射时 winfo_width/height 会返回 1，回退到显式请求的尺寸
        if w < 4:
            w = self.winfo_reqwidth()
        if h < 4:
            h = self.winfo_reqheight()
        if w < 4 or h < 4:
            return
        r = min(self._radius, w // 2, h // 2)
        if self._state == 'disabled':
            bg, fg = self._DISABLED_BG, self._DISABLED_FG
            outline, outline_w = self._DISABLED_BORDER, 1
        else:
            if self._press:
                bg = _lerp_color(self._fill, self._hover_fill, 0.7)
                outline = _lerp_color(self._outline, self._outline_hover, 0.7) if self._outline else ''
                fg = self._fg
            elif self._hover:
                bg = self._hover_fill
                outline = self._outline_hover if self._outline else ''
                fg = self._fg
            else:
                bg = self._fill
                outline = self._outline
                fg = self._fg
            outline_w = self._outline_w
        offset = 1 if self._press else 0
        if outline_w and outline:
            # 双层圆角矩形模拟边框：外层用 outline 色实心填圆角，内层缩小 outline_w 后填 bg 色
            self._round_rect(offset, offset, w - offset, h - offset, r, fill=outline, outline='')
            self._round_rect(offset + outline_w, offset + outline_w,
                             w - offset - outline_w, h - offset - outline_w,
                             max(0, r - outline_w), fill=bg, outline='')
        else:
            self._round_rect(offset, offset, w - offset, h - offset, r, fill=bg, outline='')
        self.create_text(w // 2, h // 2, text=self._text, fill=fg, font=self._font)

    def _animate_hover(self, target_hover):
        if self._state == 'disabled':
            self._draw()
            return
        if self._anim_after_id:
            self.after_cancel(self._anim_after_id)
            self._anim_after_id = None
        start_bg = self._fill if not target_hover else self._hover_fill
        end_bg = self._hover_fill if target_hover else self._fill
        start_outline = self._outline if not target_hover else self._outline_hover
        end_outline = self._outline_hover if target_hover else self._outline
        step_idx = [0]
        steps = 4
        def step():
            step_idx[0] += 1
            t = step_idx[0] / steps
            if t >= 1.0:
                self._hover = target_hover
                self._draw()
                return
            self.delete('all')
            w, h = self.winfo_width(), self.winfo_height()
            if w < 4 or h < 4:
                return
            r = min(self._radius, w // 2, h // 2)
            if self._outline_w and self._outline:
                self._round_rect(0, 0, w, h, r, fill=_lerp_color(start_outline, end_outline, t), outline='')
                bg = _lerp_color(start_bg, end_bg, t)
                self._round_rect(self._outline_w, self._outline_w, w - self._outline_w, h - self._outline_w,
                                 max(0, r - self._outline_w), fill=bg, outline='')
            else:
                self._round_rect(0, 0, w, h, r, fill=_lerp_color(start_bg, end_bg, t), outline='')
            self.create_text(w // 2, h // 2, text=self._text, fill=self._fg, font=self._font)
            self._anim_after_id = self.after(45, step)
        step()

    def _hover_in(self):
        if self._state != 'disabled':
            self._animate_hover(True)

    def _hover_out(self):
        if self._state != 'disabled':
            self._animate_hover(False)

    def _press_in(self):
        if self._state != 'disabled':
            self._press = True
            self._draw()

    def _press_out(self):
        was_pressed = self._press
        self._press = False
        self._draw()
        if was_pressed and self._state == 'normal' and self._command:
            self._command()

    def config(self, **kw):
        if 'state' in kw:
            self._state = kw.pop('state')
            kw['cursor'] = 'arrow' if self._state == 'disabled' else 'hand2'
        if 'text' in kw:
            self._text = kw.pop('text')
        super().config(**kw)
        self._draw()


# 状态徽章：统一状态枚举 → 文案/颜色/点样式/动画（大厂 Status Tag 设计规范）
_STATUS_META = {
    'running':       {'text': '运行中', 'color': 'success',     'tint': 'success_tint', 'dot': 'dot',   'anim': 'breath'},
    'stopped':       {'text': '已停止', 'color': 'text_dim',    'tint': 'bg_input',     'dot': 'ring',  'anim': None},
    'error':         {'text': '异常',   'color': 'danger',      'tint': 'danger_tint',  'dot': 'cross', 'anim': 'pulse'},
    'restarting':    {'text': '重启中', 'color': 'warning',     'tint': 'warning_tint', 'dot': 'dot',   'anim': 'blink'},
    'deploying':     {'text': '部署中', 'color': 'accent',      'tint': 'accent_tint',  'dot': 'arc',   'anim': 'spin'},
    'not_installed': {'text': '未安装', 'color': 'text_dim',    'tint': 'bg_input',     'dot': 'ring',  'anim': None},
    'unknown':       {'text': '状态未知', 'color': 'text_dim',  'tint': 'bg_input',     'dot': 'ring',  'anim': None},
}

_STATUS_SIZE = {
    'lg': {'padx': 10, 'pady': 4, 'dot': 8, 'gap': 6, 'font': ('Microsoft YaHei UI', 9, 'bold'), 'radius': 10},
    'md': {'padx': 8,  'pady': 3, 'dot': 7, 'gap': 5, 'font': ('Microsoft YaHei UI', 9, 'bold'), 'radius': 9},
    'sm': {'padx': 6,  'pady': 2, 'dot': 6, 'gap': 4, 'font': ('Microsoft YaHei UI', 8),         'radius': 7},
}


class StatusBadge(tk.Canvas):
    """圆角胶囊状态徽章：状态点 + 文字 + 语义色容器（大厂 Status Tag 风格）。

    与旧版"裸圆点 + 裸文字"的区别：统一状态枚举、彩色胶囊容器、
    四种点样式（实心/空心/叉/旋转弧）、四种动画（呼吸/闪烁/脉冲/旋转）。
    用于三种场景：状态栏(lg) / 卡片详情(md) / 监控面板组件(sm)。
    """

    def __init__(self, parent, state='stopped', text=None, size='md', palette=None, canvas_bg=None):
        self._palette = palette or {}
        self._size = size
        self._spec = _STATUS_SIZE[size]
        self._state = state
        self._custom_text = text
        self._anim_after_id = None
        self._phase = 0
        self._meta = _STATUS_META.get(state, _STATUS_META['stopped'])
        self._anim_kind = self._meta['anim']
        import tkinter.font as tkfont
        self._font_obj = tkfont.Font(font=self._spec['font'])
        w = self._calc_width()
        h = self._font_obj.metrics('linespace') + self._spec['pady'] * 2
        super().__init__(parent, width=w, height=h, highlightthickness=0, bg=canvas_bg or '#ffffff')
        self._draw()
        if self._anim_kind:
            self._tick()

    def _text(self):
        return self._custom_text if self._custom_text is not None else self._meta['text']

    def _calc_width(self):
        text_w = self._font_obj.measure(self._text())
        return self._spec['padx'] * 2 + self._spec['dot'] + self._spec['gap'] + text_w

    def set_state(self, state, text=None, color_key=None, tint_key=None):
        prev_state = self._state
        self._state = state
        if text is not None:
            self._custom_text = text
        elif state != prev_state:
            self._custom_text = None
        base = _STATUS_META.get(state, _STATUS_META['stopped'])
        self._meta = dict(base)
        if color_key is not None:
            self._meta['color'] = color_key
        if tint_key is not None:
            self._meta['tint'] = tint_key
        new_anim = self._meta['anim']
        if new_anim != self._anim_kind:
            self._anim_kind = new_anim
            if self._anim_after_id:
                self.after_cancel(self._anim_after_id)
                self._anim_after_id = None
            self._phase = 0
            if self._anim_kind:
                self._tick()
        self.configure(width=self._calc_width())
        self._draw()

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2, x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _colors(self):
        color = self._palette.get(self._meta['color'], '#8e8e93')
        tint = self._palette.get(self._meta['tint'], '#f2f2f7')
        if self._anim_kind == 'blink' and (self._phase // 90) % 2 == 0:
            color = tint
        return color, tint

    def _draw(self):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            w = self.winfo_reqwidth()
        if h < 4:
            h = self.winfo_reqheight()
        if w < 4 or h < 4:
            return
        color, tint = self._colors()
        # 胶囊容器（圆角 + 同色描边）
        self._round_rect(0, 0, w, h, self._spec['radius'], fill=tint, outline=color, width=1)
        # 状态点
        cy = h // 2
        dx = self._spec['padx'] + self._spec['dot'] // 2
        self._draw_dot(dx, cy, self._spec['dot'], color, self._meta['dot'])
        # 文字
        tx = self._spec['padx'] + self._spec['dot'] + self._spec['gap']
        self.create_text(tx, cy, text=self._text(), fill=color, font=self._spec['font'], anchor='w')

    def _draw_dot(self, cx, cy, d, color, style):
        r = max(2, d // 2)
        phase = self._phase
        if style == 'ring':
            self.create_oval(cx-r, cy-r, cx+r, cy+r, outline=color, width=1)
        elif style == 'cross':
            self.create_oval(cx-r, cy-r, cx+r, cy+r, fill=color, outline='')
            k = max(1, r - 1)
            self.create_line(cx-k, cy-k, cx+k, cy+k, fill='#ffffff', width=1)
            self.create_line(cx+k, cy-k, cx-k, cy+k, fill='#ffffff', width=1)
        elif style == 'arc':
            self.create_arc(cx-r, cy-r, cx+r, cy+r, start=phase % 360, extent=270, style='arc', outline=color, width=2)
        else:
            if self._anim_kind == 'breath':
                glow = int((math.sin(phase / 360.0 * 2 * math.pi) * 0.5 + 0.5) * (r // 2))
                if glow:
                    self.create_oval(cx-r-glow, cy-r-glow, cx+r+glow, cy+r+glow, fill=_shift_color(color, 40), outline='')
            elif self._anim_kind == 'pulse':
                ring_r = (phase % 60) / 60.0 * (r + 3)
                if ring_r > 0.5:
                    self.create_oval(cx-ring_r, cy-ring_r, cx+ring_r, cy+ring_r, outline=color, width=1)
            self.create_oval(cx-r, cy-r, cx+r, cy+r, fill=color, outline='')

    def _tick(self):
        self._phase = (self._phase + 6) % 360
        self._draw()
        delay = {'breath': 200, 'blink': 120, 'pulse': 150, 'spin': 80}.get(self._anim_kind, 200)
        self._anim_after_id = self.after(delay, self._tick)

    def stop_animation(self):
        if self._anim_after_id:
            self.after_cancel(self._anim_after_id)
            self._anim_after_id = None
        self._anim_kind = None
        self._phase = 0
        self._draw()


def _create_tray_icon_image():
    try:
        from PIL import Image, ImageDraw
        img = Image.new('RGBA', (16, 16), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse([2, 2, 14, 14], fill=(108, 142, 255, 255))
        return img
    except Exception:
        return None


class ServerManagerApp:
    """ERP 服务器管理器 — 开发/生产模式"""

    # Apple/iOS 风格设计令牌：浅色分组卡片 + 系统色板 + 克制留白
    _PALETTE = {
        'bg_main': '#f5f5f7', 'bg_card': '#ffffff', 'bg_surface': '#f2f2f7', 'bg_header': '#fbfbfd', 'bg_log': '#f9f9fb', 'bg_input': '#f2f2f7',
        'text_primary': '#1d1d1f', 'text_secondary': '#48484d', 'text_dim': '#8e8e93',
        'border': '#e5e5ea', 'border_card': '#e8e8ed',
        'accent': '#007aff', 'accent_h': '#2d96ff', 'accent_tint': '#e8f1ff',
        'success': '#34c759', 'success_h': '#4fd06a', 'success_tint': '#e6f9ec',
        'danger': '#ff3b30', 'danger_h': '#ff5548', 'danger_tint': '#ffece9',
        'warning': '#ff9500', 'warning_tint': '#fff4e0', 'info': '#30b0c7',
        'log_fg': '#1d1d1f', 'log_info': '#007aff', 'log_error': '#ff3b30', 'log_warn': '#ff9500', 'log_success': '#34c759',
    }
    MAX_LOG_LINES, LOG_KEEP_LINES, LOG_CLEANUP_MS, LOG_FLUSH_MS = 500, 300, 120000, 500
    # 生产模式状态刷新：prod_runner 每 3s 续写 logs/prod_runner.json，超过 HOSTING_STALE_SEC
    # 未更新即视为不可信（旧快照不得当现状展示）；收集线程超过 HOSTING_COLLECT_TIMEOUT_SEC
    # 未回报即认定刷新链卡死并重启（否则界面会永久停止更新）。
    HOSTING_STALE_SEC, HOSTING_COLLECT_TIMEOUT_SEC = 15, 20
    # 生产启动宽限：NSSM start 返回后，prod_runner 还要起 uvicorn / nginx 才写第一份快照，
    # 这段窗口里状态文件必然是**上一轮的旧快照**，不能据此判定 prod_runner 已退出。
    # 2026-09-16 实测：点「启动服务」3s 后就弹出「已 43s 未更新…可在服务管理里重启
    # erp-prod」——把正常启动过程说成故障，还给出了会白重启一次服务的建议。
    # 宽限期内改报「等待首份状态」（徽章显示启动中），超期才落回真实告警。
    HOSTING_START_GRACE_SEC = 60

    def __init__(self, root):
        self.root = root
        self.root.title(_WINDOW_TITLE)
        self.root.geometry("1080x760")
        self.root.minsize(960, 680)
        self.root.resizable(True, True)
        self.root.withdraw()
        self._mode, self._process, self._frontend_process, self._redis_process = 'none', None, None, None
        self._log_buffer, self._flush_pending = [], False
        self._msg_queue = queue.Queue()
        self._server_cards = []
        self._startup_progress, self._startup_steps, self._startup_current_step, self._current_mode_key = 0, [], "", ""
        self._prod_running = False
        self._prod_unknown = False      # 生产服务状态「未知」(sc query 失败) —— 仅供展示层，勿与 _prod_running 混用
        self._hosting_collecting, self._hosting_refresh_requested = False, False
        self._hosting_collect_started, self._hosting_last_warn = 0.0, ''
        # 最近一次「启动/重启生产服务」的时刻（0 表示本次会话还没启动过）。
        # 用于区分「刚启动、首份快照还没落盘」与「跑着跑着 prod_runner 掉了」。
        self._prod_start_ts = 0.0
        # 动作闸门（单一持有者 / 自动释放 / 可协作取消）+ 需置灰的操作按钮集合。
        # 闸门事件回调只往消息队列投递，绝不直接操作 Tk（回调在 worker 线程执行）。
        self._gate = ActionGate(on_event=self._on_gate_event)
        self._action_buttons = []
        self.setup_logging()
        self._build_ui()
        self._set_window_icon()
        self._center_window()
        self.root.deiconify()
        self._fade_in()
        self._animate_cards_intro()
        self._check_interval, self._after_ids = 5000, {}
        self._run_env_checks()
        self.check_server_status()
        self._refresh_hosting_status()
        self._schedule_log_cleanup()
        self._schedule_log_flush()
        self._poll_queue()
        self._tray_icon = None
        self._init_tray()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self._ui_ready = True
        self.logger.info(f"服务器管理器已启动 ({_VERSION})")

    def _run_env_checks(self):
        errors = []
        if not _PYTHON_EXE:
            errors.append("未找到 Python 解释器！请安装 Python 3.12+ 并确保 python 在 PATH 中，或在项目目录下创建虚拟环境 (.venv313)")
        elif not (_PROJECT_DIR / 'fastapi_app').is_dir():
            errors.append(f"项目目录无效: {_PROJECT_DIR}\n未找到 fastapi_app 目录，请检查 erp_project_path.txt 配置")
        if not (_PROJECT_DIR / '.env').is_file():
            errors.append(f"未找到 .env 配置文件: {_PROJECT_DIR / '.env'}\n服务器启动将因缺少 SECRET_KEY 而失败")
        if errors:
            self.root.after(500, lambda: messagebox.showwarning("环境检查警告", "\n\n".join(errors)))
            for err in errors:
                self.log_message(err, 'ERROR')

    def _get_env_value(self, key: str) -> str:
        """从项目 .env 文件读取指定键的值"""
        env_file = _PROJECT_DIR / '.env'
        if not env_file.is_file():
            return ''
        try:
            for line in env_file.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if line.startswith('#') or '=' not in line:
                    continue
                k, _, v = line.partition('=')
                if k.strip() == key:
                    return v.strip()
        except Exception:
            pass
        return ''

    def _find_redis(self):
        """查找Redis可执行文件和配置文件"""
        redis_exe = next((str(p) for p in _REDIS_EXE_PATHS if p.is_file()), None)
        redis_conf = next((str(p) for p in _REDIS_CONF_PATHS if p.is_file()), None)
        return redis_exe, redis_conf

    def _is_redis_running(self):
        """检测 Redis 是否真正可用：TCP 连通 + 认证通过

        仅做端口探测会误报（Redis 服务 Paused/停止或密码不匹配时，端口探测仍可能
        短暂通过）。这里通过 RESP 协议发送 PING：
        - 返回 +PONG ：无需密码，正常运行
        - 返回 -NOAUTH：需密码，先 AUTH（用 .env 的 REDIS_PASSWORD）再 PING
        - 其余情况：不可用
        """
        password = self._get_env_value('REDIS_PASSWORD')
        try:
            with socket.create_connection(('127.0.0.1', _REDIS_PORT), timeout=1) as sock:
                sock.sendall(b'*1\r\n$4\r\nPING\r\n')
                resp = sock.recv(64)
                if resp.startswith(b'+PONG'):
                    return True
                if resp.startswith(b'-NOAUTH'):
                    if not password:
                        return False
                    auth_cmd = (
                        f'*2\r\n$4\r\nAUTH\r\n${len(password)}\r\n{password}\r\n'
                    ).encode()
                    sock.sendall(auth_cmd)
                    auth_resp = sock.recv(64)
                    if not auth_resp.startswith(b'+OK'):
                        return False
                    sock.sendall(b'*1\r\n$4\r\nPING\r\n')
                    return sock.recv(64).startswith(b'+PONG')
            return False
        except Exception:
            return False

    def _redis_service_state(self, name):
        """查询 Redis 相关 Windows 服务的状态文本（空字符串=服务不存在）。"""
        code, out = self._run_capture(['sc', 'query', name], timeout=5)
        if code != 0:
            return ''
        for line in (out or '').splitlines():
            if 'STATE' in line.upper():
                return line.strip()
        return 'EXISTS'

    def _start_redis_via_service(self, name):
        """优先通过 Windows 服务启动 Redis（返回 True/False/None=服务不存在）。

        ★ 为什么不直接 Popen：直接拉起的 redis-server 与 erp-redis / erp-redis-broker
        服务没有父子关系，服务管理器会显示「服务存在但无子进程」，而实例的存活实际
        吊在管理器进程上——管理器一退、机器一重启，Redis 就没了，且不会自愈
        （2026-09-16 实测：6379 的监听者父进程链全是 ERP服务器管理器_v5.33.exe）。
        改走服务后，开机自启、崩溃重拉、依赖顺序全部由 SCM 保证。
        """
        state = self._redis_service_state(name)
        if not state:
            return None
        nssm = self._find_nssm()
        cmd = [nssm, 'start', name] if nssm else ['sc', 'start', name]
        self._run_capture(cmd, timeout=20)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            self._gate.checkpoint()
            state = self._redis_service_state(name)
            if 'RUNNING' in state.upper():
                return True
            time.sleep(0.5)
        self._msg_queue.put(('log', {'text': f'{name} 服务未在 20s 内进入 RUNNING（当前: {state or "未知"}）', 'level': 'WARNING'}))
        return False

    def _start_redis(self):
        """启动 Redis 缓存实例（6379）。

        顺序：已在运行 → 直接返回；否则先走 Windows 服务（自愈 + 开机自启），
        服务不存在时才回退到直接 Popen（未安装服务的开发场景）。
        """
        if self._is_redis_running():
            self._msg_queue.put(('log', {'text': "Redis 已在运行"}))
            return True
        via_svc = self._start_redis_via_service(_SVC_REDIS_CACHE)
        if via_svc is True:
            if self._is_redis_running():
                self._msg_queue.put(('log', {'text': f"Redis 已由服务 {_SVC_REDIS_CACHE} 启动"}))
                return True
            self._msg_queue.put(('log', {'text': f"{_SVC_REDIS_CACHE} 服务已 RUNNING，但 Redis 未通过 PING 校验", 'level': 'WARNING'}))
            return False
        if via_svc is False:
            self._msg_queue.put(('log', {'text': f"Redis 服务启动失败，回退为直接拉起进程", 'level': 'WARNING'}))
        else:
            self._msg_queue.put(('log', {'text': f"未安装 {_SVC_REDIS_CACHE} 服务，将直接拉起 Redis 进程（不随开机自启）", 'level': 'WARNING'}))
        return self._start_redis_process()

    def _start_redis_process(self):
        """回退路径：直接把 redis-server 作为本管理器子进程拉起。"""
        redis_exe, redis_conf = self._find_redis()
        if not redis_exe:
            self._msg_queue.put(('log', {'text': "Redis 未安装，请安装 Redis for Windows", 'level': 'WARNING'}))
            return False
        try:
            cmd = [redis_exe] + ([redis_conf] if redis_conf else [])
            redis_password = self._get_env_value('REDIS_PASSWORD')
            if redis_password:
                cmd += ['--requirepass', redis_password]
            self._msg_queue.put(('log', {'text': f"正在启动 Redis: {redis_exe}"}))
            # ★ 本地 proc 绑定：self._redis_process 会被并发的 _stop_redis() 置 None，
            # 原实现直接解引用 self._redis_process.pid/.poll() → 实测 AttributeError。
            proc = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=False)
            self._redis_process = proc
            threading.Thread(target=self._read_stdout, args=(proc,), daemon=True).start()
            for _ in range(15):
                time.sleep(0.5)
                self._gate.checkpoint()
                if self._is_redis_running():
                    self._msg_queue.put(('log', {'text': f"Redis 启动成功 (PID: {proc.pid})"}))
                    return True
                if proc.poll() is not None:
                    self._msg_queue.put(('log', {'text': f"Redis 进程意外退出 (退出码: {proc.returncode})", 'level': 'ERROR'}))
                    return False
            self._msg_queue.put(('log', {'text': "Redis 启动超时，请检查端口6379是否被占用", 'level': 'WARNING'}))
            return False
        except Exception as e:
            self._msg_queue.put(('log', {'text': f"Redis 启动失败: {str(e)}", 'level': 'ERROR'}))
            return False

    def _is_broker_running(self):
        """ARQ broker(6380) 是否真的可用：TCP 连通 + AUTH/PING（与缓存实例同款校验）。"""
        password = self._get_env_value('REDIS_PASSWORD')
        try:
            with socket.create_connection(('127.0.0.1', _REDIS_BROKER_PORT), timeout=1) as sock:
                sock.sendall(b'*1\r\n$4\r\nPING\r\n')
                resp = sock.recv(64)
                if resp.startswith(b'+PONG'):
                    return True
                if resp.startswith(b'-NOAUTH'):
                    if not password:
                        return False
                    auth_cmd = (f'*2\r\n$4\r\nAUTH\r\n${len(password)}\r\n{password}\r\n').encode()
                    sock.sendall(auth_cmd)
                    if not sock.recv(64).startswith(b'+OK'):
                        return False
                    sock.sendall(b'*1\r\n$4\r\nPING\r\n')
                    return sock.recv(64).startswith(b'+PONG')
            return False
        except Exception:
            return False

    def _ensure_redis_broker(self):
        """确保 ARQ broker(6380) 就绪——生产启动前调用，返回是否就绪。

        没有这一步，erp-arq 服务起来就直接连不上 6380 反复重启，而整套界面
        （服务状态、prod_runner 就绪徽章）全是绿的，用户完全无从察觉
        cron/备份/报表已经停了（2026-09-16 现场）。
        """
        if self._is_broker_running():
            return True
        self._msg_queue.put(('log', {'text': f'ARQ broker ({_REDIS_BROKER_PORT}) 未就绪，正在启动 {_SVC_REDIS_BROKER} 服务...'}))
        ok = self._start_redis_via_service(_SVC_REDIS_BROKER)
        if ok is None:
            self._msg_queue.put(('log', {
                'text': f'未安装 {_SVC_REDIS_BROKER} 服务，erp-arq 无法运行；'
                        f'请执行 scripts\\install_redis_services.ps1 注册 Redis 服务',
                'level': 'ERROR'}))
            return False
        for _ in range(20):
            time.sleep(0.5)
            self._gate.checkpoint()
            if self._is_broker_running():
                self._msg_queue.put(('log', {'text': f'ARQ broker 已就绪 ({_SVC_REDIS_BROKER})'}))
                return True
        self._msg_queue.put(('log', {'text': f'ARQ broker 启动后仍未通过 PING 校验，erp-arq 可能无法工作', 'level': 'ERROR'}))
        return False

    def _stop_redis(self):
        """停止Redis服务"""
        stopped = False
        if self._redis_process and self._redis_process.poll() is None:
            try:
                self._redis_process.terminate()
                self._redis_process.wait(timeout=3)
                stopped = True
            except Exception:
                try:
                    self._redis_process.kill()
                    stopped = True
                except Exception:
                    pass
        if self._is_redis_running():
            _kill_port_process(_REDIS_PORT, self._msg_queue)
        if stopped:
            self._msg_queue.put(('log', {'text': "Redis 已停止"}))
        self._redis_process = None

    def _fade_in(self):
        try:
            self.root.attributes('-alpha', 0.0)
            def step(i):
                if i > 10:
                    self.root.attributes('-alpha', 1.0)
                    return
                self.root.attributes('-alpha', i / 10)
                self.root.after(30, lambda: step(i + 1))
            step(0)
        except Exception:
            pass

    def _animate_cards_intro(self):
        try:
            for idx, card in enumerate(self._server_cards):
                self.root.after(80 * idx, lambda c=card: self._pulse_card_border(c))
        except Exception:
            pass

    def _pulse_card_border(self, card):
        base, accent = self._PALETTE['border_card'], self._PALETTE['accent_h']
        def tick(i):
            if i > 10:
                with contextlib.suppress(Exception):
                    card.configure(highlightbackground=base)
                return
            t = i / 10
            color = _lerp_color(base, accent, t * 2) if t <= 0.5 else _lerp_color(accent, base, (t - 0.5) * 2)
            try:
                card.configure(highlightbackground=color)
            except Exception:
                return
            self.root.after(30, lambda: tick(i + 1))
        tick(0)

    def _center_window(self):
        self.root.update_idletasks()
        try:
            w, h = map(int, self.root.geometry().split('+')[0].split('x'))
        except (ValueError, IndexError):
            w, h = 960, 720
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f'+{max(0,(min(w,sw-40)-w)//2)}+{max(0,(min(h,sh-80)-h)//2)}')

    def _init_tray(self):
        try:
            import pystray
            icon_image = _create_tray_icon_image()
            if icon_image is None:
                return
            self._tray_image = icon_image
            menu = pystray.Menu(pystray.MenuItem('显示窗口', self._show_window, default=True), pystray.MenuItem('退出', self._quit_from_tray))
            self._tray_icon = pystray.Icon('ERP服务器管理器', icon_image, 'ERP 服务器管理器', menu)
            threading.Thread(target=self._tray_icon.run, daemon=True).start()
        except Exception as e:
            self.logger.info(f"托盘初始化跳过: {e}")

    def _set_window_icon(self):
        try:
            from PIL import ImageTk
            icon_image = _create_tray_icon_image()
            if icon_image:
                self._window_icon = ImageTk.PhotoImage(icon_image.resize((32, 32)))
                self.root.iconphoto(True, self._window_icon)
        except Exception:
            pass

    def _show_window(self, icon=None, item=None):
        self.root.after(0, lambda: (self.root.deiconify(), self.root.lift(), self.root.focus_force()))

    def _quit_from_tray(self, icon=None, item=None):
        self.root.after(0, self._do_quit)

    def _do_quit(self):
        if self._mode != 'none':
            self._stop_process()
            self._mode = 'none'
        self._kill_tray()
        for aid in self._after_ids.values():
            with contextlib.suppress(Exception):
                self.root.after_cancel(aid)
        self._after_ids.clear()
        for attr in ('_mode_badge', 'dual_dev_status'):
            badge = getattr(self, attr, None)
            if badge is not None and hasattr(badge, 'stop_animation'):
                badge.stop_animation()
        global _mutex_handle
        if _mutex_handle and _IS_WINDOWS:
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(_mutex_handle)
            except Exception:
                pass
            _mutex_handle = None
        self.root.destroy()

    def _kill_tray(self):
        if self._tray_icon:
            with contextlib.suppress(Exception):
                self._tray_icon.stop()
            self._tray_icon = None
            with contextlib.suppress(Exception):
                self.root.update()

    def setup_logging(self):
        log_dir = _PROJECT_DIR / 'logs'
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f'server_manager_{datetime.now():%Y%m%d}.log'
        fmt = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s')
        self.logger = logging.getLogger('server_manager')
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            fh = logging.FileHandler(log_file, encoding='utf-8')
            fh.setFormatter(fmt)
            self.logger.addHandler(fh)
            if sys.stdout:
                console_handler = logging.StreamHandler(sys.stdout)
                console_handler.setFormatter(fmt)
                self.logger.addHandler(console_handler)

    def log_message(self, message, level='INFO'):
        timestamp = datetime.now().strftime('%H:%M:%S')
        self._log_buffer.append((f"[{timestamp}] {level}: {message}\n", level))
        fn = getattr(self.logger, level.lower(), None) or self.logger.warning
        if fn:
            fn(message)
        if not self._flush_pending:
            self._flush_pending = True
            try:
                self.root.after_idle(self._do_flush)
            except RuntimeError:
                self._flush_pending = False

    def _do_flush(self):
        self._flush_pending = False
        self._flush_log_buffer()

    def _flush_log_buffer(self):
        if not self._log_buffer:
            return
        buf = self._log_buffer[:]
        self._log_buffer.clear()
        self.log_text.config(state=tk.NORMAL)
        for entry, level in buf:
            self.log_text.insert(tk.END, entry, level)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _schedule_log_flush(self):
        if self._log_buffer:
            self._flush_log_buffer()
        self._after_ids['flush'] = self.root.after(self.LOG_FLUSH_MS, self._schedule_log_flush)

    def clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete('1.0', tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.log_message("日志已清空")

    def export_log(self):
        from tkinter import filedialog
        log_dir = _PROJECT_DIR / 'logs'
        log_dir.mkdir(exist_ok=True)
        filename = filedialog.asksaveasfilename(initialdir=log_dir, initialfile=f"server_log_{datetime.now():%Y%m%d_%H%M%S}.txt", defaultextension=".txt", filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.log_text.get('1.0', tk.END))
                self.log_message(f"日志已导出到: {filename}")
            except Exception as e:
                self.log_message(f"导出日志失败: {str(e)}", 'ERROR')

    def _schedule_log_cleanup(self):
        self._perform_log_cleanup()
        self._after_ids['cleanup'] = self.root.after(self.LOG_CLEANUP_MS, self._schedule_log_cleanup)

    def _perform_log_cleanup(self):
        try:
            total = int(self.log_text.index('end-1c').split('.')[0])
            if total > self.MAX_LOG_LINES:
                self.log_text.config(state=tk.NORMAL)
                self.log_text.delete('1.0', f'{total - self.LOG_KEEP_LINES}.0')
                self.log_text.config(state=tk.DISABLED)
        except (tk.TclError, ValueError):
            pass

    def _stop_process(self):
        """停止当前调试模式进程（经动作闸门串行；可被紧急停止取消）"""
        self._gate.start('停止服务', self._stop_process_flow)

    def _stop_process_flow(self):
        proc = self._process
        self._process = None
        if not (proc and proc.poll() is None):
            self._msg_queue.put(('ui_update', {}))
            return
        pid = proc.pid
        self._msg_queue.put(('log', {'text': f"正在终止进程树 (根 PID: {pid})..."}))
        try:
            if _IS_WINDOWS:
                child_pids = self._collect_process_tree(pid)
                self._msg_queue.put(('log', {'text': f"发现 {len(child_pids)+1} 个关联进程"}))
                _taskkill(pid)
                for cpid in child_pids:
                    with contextlib.suppress(Exception):
                        _taskkill(cpid)
                with contextlib.suppress(Exception):
                    proc.wait(timeout=3)
                self._kill_port_sync(_API_PORT)
            else:
                import signal
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except Exception:
                    proc.terminate()
                proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=3)
            except Exception:
                pass
            self._msg_queue.put(('log', {'text': f"进程 (PID: {pid}) 超时，已强制 kill", 'level': 'WARNING'}))
            self._kill_port_sync(_API_PORT)
        except Exception as e:
            self._msg_queue.put(('log', {'text': f"终止进程异常: {str(e)}", 'level': 'ERROR'}))
            self._kill_port_sync(_API_PORT)
        finally:
            self._msg_queue.put(('ui_update', {}))

    def _collect_process_tree(self, root_pid):
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
                    pids.extend(self._collect_process_tree(int(line)))
                    pids.append(int(line))
        except Exception:
            pass
        return pids

    def _kill_port_sync(self, port, exclude=None):
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
            pids = self._find_port_pids(port, exclude=exclude)
            if not pids:
                return
            # 批量终止：端口被海量进程占用时（如数百 nginx worker），
            # 逐个 taskkill 会耗时数十秒，批量可秒级完成。
            _taskkill_many(pids)
            time.sleep(0.5)

    def _find_port_pids(self, port, exclude=None):
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

    def _start_server(self, script_name, mode_label, mode_key='debug'):
        if self._mode != 'none':
            self.log_message(f"已有服务在运行或启动中，请先停止后再启动", 'WARNING')
            return
        if not _PYTHON_EXE:
            self.log_message("无法启动: 未找到 Python 解释器，请安装 Python 并确保在 PATH 中", 'ERROR')
            messagebox.showerror("启动失败", "未找到可用的 Python 解释器！\n\n请安装 Python 3.12+ 并确保 python 在 PATH 中，\n或在项目目录下创建虚拟环境 (.venv313)")
            return
        script = str(_PROJECT_DIR / script_name)
        if not Path(script).is_file():
            self.log_message(f"启动脚本不存在: {script}", 'ERROR')
            messagebox.showerror("错误", f"启动脚本不存在:\n{script}")
            return
        self._gate.start(f'启动{mode_label}', self._start_debug_flow, script, mode_label, mode_key)

    def _start_debug_flow(self, script, mode_label, mode_key):
        # 状态变更也放进 worker：入口侧不再存在「已取锁、还没起线程」的中间态，
        # 也就没有那个从审计中实测出来的“异常即永久持锁”窗口。
        self._mode = 'starting'
        self._current_mode_key = mode_key
        self._msg_queue.put(('log', {'text': f"正在启动{mode_label}..."}))
        self._msg_queue.put(('status', {'text': f"正在启动{mode_label}..."}))
        self._msg_queue.put(('ui_update', {}))
        self._start_thread(script, mode_label, mode_key)

    def _start_thread(self, script, mode_label, mode_key):
        try:
            self._gate.checkpoint()
            self._msg_queue.put(('log', {'text': '正在清理端口...'}))
            self._kill_port_sync(_API_PORT)

            env = os.environ.copy()
            env.update({'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1', 'PYTHONPATH': str(_PROJECT_DIR)})
            self._gate.checkpoint()      # 取消已请求时绝不产生新进程
            self._process = subprocess.Popen([_PYTHON_EXE, script], cwd=str(_PROJECT_DIR), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0, text=False)
            self._msg_queue.put(('log', {'text': f"进程已启动 (PID: {self._process.pid})"}))
            threading.Thread(target=self._read_stdout, args=(self._process,), daemon=True).start()
            time.sleep(2)
            self._gate.checkpoint()
            if self._process.poll() is None:
                self._msg_queue.put(('started', {'label': mode_label, 'mode_key': mode_key}))
            else:
                self._process = None
                self._mode = 'none'
                self._current_mode_key = ""
                self._msg_queue.put(('ui_update', {}))
                self._msg_queue.put(('log', {'text': f"{mode_label}进程启动后立即退出", 'level': 'ERROR'}))
                self._msg_queue.put(('status', {'text': f"{mode_label}启动失败"}))
        except Exception as e:
            self._process = None
            self._mode = 'none'
            self._current_mode_key = ""
            self._msg_queue.put(('ui_update', {}))
            self._msg_queue.put(('log', {'text': f"启动异常: {str(e)}", 'level': 'ERROR'}))
            self._msg_queue.put(('status', {'text': f"{mode_label}启动失败"}))

    def _read_stdout(self, proc):
        try:
            if proc.stdout:
                try:
                    # 按行读取（readline 迭代器）：读到 '\n' 即返回，不会像 read(4096) 那样
                    # 阻塞凑块导致 uvicorn 启动日志延迟显示；'\n' 是 ASCII 字节，UTF-8 中文
                    # 不会跨行被切断，_decode_line 的多编码回退已足够处理乱码。
                    batch = []
                    for raw_line in proc.stdout:
                        line = self._decode_line(raw_line) if isinstance(raw_line, bytes) else str(raw_line).strip()
                        if line:
                            batch.append(line)
                            if len(batch) >= 10:
                                self._msg_queue.put(('log_batch', {'lines': batch[:], 'level': 'INFO'}))
                                batch.clear()
                    if batch:
                        self._msg_queue.put(('log_batch', {'lines': batch, 'level': 'INFO'}))
                finally:
                    proc.stdout.close()
        except Exception as e:
            self._msg_queue.put(('log', {'text': f"读取日志异常: {str(e)}", 'level': 'ERROR'}))

    @staticmethod
    def _pick_log_font():
        """选择日志字体：优先 Microsoft YaHei Mono（等宽+CJK），回落到 Microsoft YaHei UI，
        最后落到系统默认。Consolas 不带 CJK 字形，会让中文渲染成方块。"""
        import tkinter.font as tkfont
        candidates = ('Microsoft YaHei Mono', 'Microsoft YaHei UI', 'NSimSun', 'SimSun', 'Consolas')
        for fam in candidates:
            try:
                f = tkfont.Font(family=fam, size=9, exists=False)
                # exists=False 不会抛错，用 families() 进一步确认系统接受了字体
                if fam.lower() in (x.lower() for x in tkfont.families()):
                    return (fam, 9)
            except Exception:
                continue
        return ('Microsoft YaHei UI', 9)

    @staticmethod
    def _decode_line(raw_line):
        if not raw_line:
            return ''
        preferred = locale.getpreferredencoding(False) or ''
        candidates = ['utf-8', 'utf-8-sig', 'gb18030', 'cp936'] + ([preferred] if preferred else [])
        tried = set()
        for enc in candidates:
            enc_norm = enc.lower()
            if enc_norm not in tried:
                tried.add(enc_norm)
                try:
                    return raw_line.decode(enc, errors='strict').strip()
                except Exception:
                    continue
        return raw_line.decode('utf-8', errors='replace').strip()

    def _on_started(self, mode_label, mode_key='debug'):
        if not self._process or self._process.poll() is not None:
            self.log_message(f"{mode_label}启动后进程已退出", 'ERROR')
            self._mode, self._process = 'none', None
            self._current_mode_key = ""
            self._update_all_ui()
            return
        self._mode = mode_key
        self._update_all_ui()
        self.status_bar_label.config(text=f"{mode_label}运行中")
        self.log_message(f"{mode_label}启动成功 — http://localhost:5002")

    def _poll_queue(self):
        try:
            self._process_pending_messages()
        finally:
            # poll 链是日志/徽章/状态栏等一切 UI 更新的主干：无论处理过程中发生什么，
            # 都必须续上下一轮，否则界面会永久停止更新。
            self._after_ids['poll'] = self.root.after(200, self._poll_queue)

    def _process_pending_messages(self):
        processed = 0
        while not self._msg_queue.empty() and processed < 30:
            try:
                msg_type, data = self._msg_queue.get_nowait()
            except queue.Empty:
                break
            try:
                if msg_type == 'log':
                    self.log_message(data['text'], data.get('level', 'INFO'))
                elif msg_type == 'log_batch':
                    for line in data['lines']:
                        self.log_message(line, data.get('level', 'INFO'))
                elif msg_type == 'started':
                    self._on_started(data['label'], data.get('mode_key', 'debug'))
                elif msg_type == 'dual_started':
                    self._on_dual_started(data['label'])
                elif msg_type == 'dual_failed':
                    self._on_dual_failed(data['label'], data.get('reason', ''))
                elif msg_type == 'ui_update':
                    self._update_all_ui()
                elif msg_type == 'status':
                    self.status_bar_label.config(text=data['text'])
                elif msg_type == 'startup_progress':
                    self.status_bar_label.config(text=f"启动中: {data.get('step', '')} ({data.get('progress', 0)}/{data.get('total', 4)})")
                    self._startup_current_step, self._startup_progress = data.get('step', ''), data.get('progress', 0)
                elif msg_type == 'hosting_refresh':
                    # 生产模式状态立即刷新（取消已排定的一轮，避免刷新链叠加）
                    try:
                        pending = self._after_ids.pop('hosting', None)
                        if pending:
                            self.root.after_cancel(pending)
                    except Exception:
                        pass
                    self._refresh_hosting_status()
                elif msg_type == 'hosting_apply':
                    # 后台收集完成 → 主线程应用（UI 更新）
                    self._apply_hosting_data(data['data'])
                elif msg_type == 'op_busy':
                    # P0-3：动作开始 → 在主线程置灰操作按钮（后台线程不碰 Tk）
                    self._set_actions_enabled(False)
                elif msg_type == 'op_done':
                    # 动作结束 → 先放开按钮，再由 _update_all_ui 算出真实可用态
                    self._set_actions_enabled(True)
                    self._update_all_ui()
                elif msg_type == 'op_aborted':
                    # 动作被取消/异常中止 → 清掉过渡态，避免 UI 卡在「启动中/重启中」
                    if self._mode in ('starting', 'restarting', 'stopping'):
                        self._mode, self._current_mode_key = 'none', ''
                    self._update_all_ui()
            except Exception:
                # 单条消息处理失败不能中断 poll 调度链，否则日志/状态更新全部停摆
                pass
            processed += 1

    # ===================== 动作闸门接入（P0-3） =====================
    #
    # 背景：v5.33 全模块 0 个锁，却有 21 个函数起线程；按钮回调直接起后台线程，
    # 彼此无任何互斥 —— 连点「启动」会产生多份 Popen 与多轮端口清理互相踩踏。
    #
    # 做法：所有动作只有一个入口 `self._gate.start(名称, worker, *args)`；
    # 锁的持有期 == 整个动作期（含所有阻塞等待），因为每个 worker 内部就是完整流程。
    # 闸门自己负责取锁/起线程/收尾/看门狗，因此“取了不释放”在结构上不可能。
    # 紧急停止 stop_all 故意不经闸门（它的职责是打断动作），但会先 cancel()：
    # worker 在步骤边界调 checkpoint() 即中止，不会再产生副作用。

    def _set_actions_enabled(self, enabled):
        """统一置灰/恢复操作按钮 —— 只在主线程调用，与状态机互斥双保险。"""
        state = 'normal' if enabled else 'disabled'
        for btn in self._action_buttons:
            with contextlib.suppress(Exception):
                btn.config(state=state)

    def _on_gate_event(self, kind, payload):
        """闸门事件 → 消息队列（可能在 worker 线程被调用，因此禁止直接操作 Tk）。

        这是闸门与 UI 之间唯一的接口：按钮置灰、过渡态复位、日志全部由这里派发。
        """
        owner = payload.get('owner') or ''
        if kind == 'started':
            self._msg_queue.put(('op_busy', {'name': owner}))
        elif kind == 'finished':
            self._msg_queue.put(('op_done', {'name': owner}))
        elif kind == 'rejected':
            self._msg_queue.put(('log', {'text': f'已有操作进行中（{owner or "未知动作"}），请等它完成后再试', 'level': 'WARNING'}))
        elif kind == 'cancel-requested':
            self._msg_queue.put(('log', {'text': f'正在取消动作：{owner or "（空闲）"}…', 'level': 'WARNING'}))
        elif kind == 'cancelled':
            reason = payload.get('reason') or '未知原因'
            self._msg_queue.put(('log', {'text': f'{owner}已中止（原因：{reason}）', 'level': 'WARNING'}))
            self._msg_queue.put(('op_aborted', {}))
        elif kind == 'failed':
            self._msg_queue.put(('log', {'text': f'{owner}执行异常: {payload.get("error")}', 'level': 'ERROR'}))
            self._msg_queue.put(('op_aborted', {}))
        elif kind == 'watchdog':
            self._msg_queue.put(('log', {'text': f'{owner}超过 {payload.get("seconds")}s 未结束，看门狗已强制释放动作闸门', 'level': 'ERROR'}))
            self._msg_queue.put(('op_aborted', {}))

    def start_debug(self):
        self._start_server('run.py', '调试模式', mode_key='debug')

    def start_dual_dev(self):
        self._start_dual_server('开发模式（前后端）')

    def stop_debug(self):
        self._stop_mode('debug', '调试模式')

    def stop_dual_dev(self):
        self._stop_dual_mode_async('开发模式')

    def _stop_mode(self, mode, label):
        if self._mode == mode:
            self._stop_process()
            self._mode = 'none'
            self._update_all_ui()
            self.log_message(f"{label}已停止")
        else:
            self.log_message(f"{label}未运行")

    def stop_all(self):
        # 紧急停止：不经闸门（它的职责就是打断正在进行的动作），但要先协作式取消：
        # 否则在飞行中的启动流程会在“停止”之后继续把 Redis / 后端拉起来（审计实测）。
        self._gate.cancel('紧急停止')

        # 先在主线程立即重置状态（双重保险）
        self._mode = 'none'
        self._current_mode_key = ""
        self._prod_running = False
        self._update_all_ui()

        self.log_message("正在执行停止/重置操作...")
        self.status_bar_label.config(text="正在停止所有...")
        def _stop_all_worker():
            try:
                # 先等被取消的 worker 退到边界再清扫，避免清扫之后又被它拉起来
                if not self._gate.wait_idle(_EMERGENCY_JOIN_SEC):
                    self._msg_queue.put(('log', {'text': '在飞行动作未在限期内退出，继续强制清扫', 'level': 'WARNING'}))
                # ★ 先正常停止 NSSM 受管服务（不带 checkpoint，因 cancel 已置位）。
                # 否则端口清理会强杀 erp-prod 监听 5002 的进程，被 AppExit=Default
                # Restart 判定为崩溃、5 秒后自动重启 ——「紧急停止变成重启」的根因。
                _, managed_pids = self._stop_managed_services()
                # 强制停止所有进程，不管状态
                for proc, name in [(self._frontend_process, '前端'), (self._process, '后端')]:
                    if proc and proc.poll() is None:
                        self._msg_queue.put(('log', {'text': f'正在终止{name}进程 (PID: {proc.pid})...'}))
                        self._kill_process_tree(proc.pid)
                self._frontend_process = None
                self._process = None

                self._stop_redis()
                self._kill_residual_async()
                # 端口清理时排除受管 PID：即使 nssm stop 超时失败，也绝不误杀受管进程触发自动重启
                self._kill_port_sync(_API_PORT, exclude=managed_pids)
                self._kill_port_sync(_WEB_PORT, exclude=managed_pids)
                self._kill_port_sync(_REDIS_PORT, exclude=managed_pids)
                self._msg_queue.put(('log', {'text': "已清理所有残留进程和端口"}))
                self._msg_queue.put(('ui_update', {}))
            except Exception as e:
                self._msg_queue.put(('log', {'text': f"停止过程出错: {str(e)}", 'level': 'ERROR'}))
        threading.Thread(target=_stop_all_worker, daemon=True).start()

    def _kill_residual_async(self):
        """清理本项目残留进程（P0-4：精确特征 + 受管进程豁免）。

        stop_all 是「紧急重置」，但不能以误杀 NSSM 受管进程为代价 —— 原实现按
        进程名把 python / node 全杀，杀掉 erp-prod 后 NSSM 5 秒拉起 → 死循环。
        """
        def _kill_worker():
            if not _IS_WINDOWS:
                return
            try:
                self._msg_queue.put(('log', {'text': "正在扫描残留进程..."}))
                managed = self._managed_service_pids()
                if managed:
                    self._msg_queue.put(('log', {'text': f'已识别 {len(managed)} 个 NSSM 受管进程，不在清理范围内'}))
                pids = self._find_project_residual_pids(exclude=managed)
                if not pids:
                    self._msg_queue.put(('log', {'text': '未发现本项目残留进程'}))
                    return
                self._msg_queue.put(('log', {'text': f"发现 {len(pids)} 个本项目残留进程，正在终止..."}))
                for pid in pids:
                    with contextlib.suppress(Exception):
                        _taskkill(pid)
            except Exception as e:
                self._msg_queue.put(('log', {'text': f"清理残留进程出错: {e}", 'level': 'WARNING'}))
        threading.Thread(target=_kill_worker, daemon=True).start()

    def restart_debug(self):
        self._gate.start('重启调试模式', self._restart_thread)

    def restart_dual_dev(self):
        self._gate.start('重启开发模式', self._restart_dual_thread)

    def _restart_thread(self):
        self._mode = 'restarting'
        self._msg_queue.put(('ui_update', {}))
        proc = self._process
        self._process = None
        if proc and proc.poll() is None:
            self._msg_queue.put(('log', {'text': f"重启：终止进程树 (PID: {proc.pid})..."}))
            if _IS_WINDOWS:
                for cpid in self._collect_process_tree(proc.pid):
                    with contextlib.suppress(Exception):
                        _taskkill(cpid)
                _taskkill(proc.pid)
                with contextlib.suppress(Exception):
                    proc.wait(timeout=3)
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
        self._kill_port_sync(_API_PORT)
        time.sleep(0.5)
        self._gate.checkpoint()
        self._mode = 'restarting'
        self._start_thread(str(_PROJECT_DIR / 'run.py'), '调试模式', mode_key='debug')

    def _start_dual_server(self, label):
        # 互斥守卫：开发模式正在启动/重启中则不操作
        if self._mode in ('starting', 'restarting'):
            self.log_message(f"开发模式正在启动/重启中，请稍候", 'WARNING')
            return
        if self._mode != 'none':
            self.log_message(f"已有服务在运行，请先停止后再启动", 'WARNING')
            return
        if not _PYTHON_EXE:
            self.log_message("无法启动: 未找到 Python 解释器，请安装 Python 并确保在 PATH 中", 'ERROR')
            messagebox.showerror("启动失败", "未找到可用的 Python 解释器！\n\n请安装 Python 3.12+ 并确保 python 在 PATH 中，\n或在项目目录下创建虚拟环境 (.venv313)")
            return
        if not _FRONTEND_DIR.exists():
            self.log_message(f"前端目录不存在: {_FRONTEND_DIR}", 'ERROR')
            messagebox.showerror("错误", f"前端目录不存在:\n{_FRONTEND_DIR}")
            return

        # 互斥切换（停生产+清端口）含子进程调用，必须放后台线程，否则阻塞 Tk 主线程导致 GUI 卡死
        self._gate.start(f'启动{label}', self._start_dual_flow, label)

    def _start_dual_flow(self, label):
        self._mode = 'starting'
        self._current_mode_key = 'dual_dev'
        self._startup_progress, self._startup_steps, self._startup_current_step = 0, ['停止生产模式', '检查Redis服务', '启动后端服务', '启动前端服务', '完成'], ''
        self._msg_queue.put(('log', {'text': f"正在启动{label}..."}))
        self._msg_queue.put(('status', {'text': f"正在启动{label}..."}))
        self._msg_queue.put(('ui_update', {}))
        self._start_dual_worker(label)

    def _start_dual_worker(self, label):
        """后台执行互斥切换（停生产 + 清端口），随后复用现有启动流程"""
        try:
            self._gate.checkpoint()
            self._msg_queue.put(('startup_progress', {'step': self._startup_steps[0], 'progress': 1, 'total': len(self._startup_steps)}))
            ok, reason, stopped_any = self._ensure_production_stopped()
            if not ok:
                self._msg_queue.put(('log', {'text': f"切换失败: {reason}", 'level': 'ERROR'}))
                self._msg_queue.put(('dual_failed', {'label': label, 'reason': reason}))
                return
            if stopped_any:
                self._msg_queue.put(('log', {'text': '已自动停止生产模式', 'level': 'INFO'}))
            self._release_ports()
            self._start_dual_thread(label)
        except Exception as e:
            # 后台线程无 try/except 会静默终止，导致启动流程卡在 'starting' 且无任何日志；
            # 这里兜底记录并重置状态，让用户能看到失败原因。
            self._msg_queue.put(('log', {'text': f"启动流程异常: {str(e)}", 'level': 'ERROR'}))
            self._msg_queue.put(('dual_failed', {'label': label, 'reason': str(e)}))

    def _start_dual_thread(self, label):
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0
            self._gate.checkpoint()

            self._msg_queue.put(('log', {'text': '正在清理端口...'}))
            self._kill_port_sync(_API_PORT)
            self._kill_port_sync(_WEB_PORT)

            self._startup_current_step, self._startup_progress = self._startup_steps[1], 2
            self._msg_queue.put(('startup_progress', {'step': self._startup_current_step, 'progress': self._startup_progress, 'total': len(self._startup_steps)}))
            self._gate.checkpoint()
            if not self._start_redis():
                self._msg_queue.put(('log', {'text': '警告: Redis 未启动，部分功能可能不可用', 'level': 'WARNING'}))
            self._startup_current_step, self._startup_progress = self._startup_steps[2], 3
            self._msg_queue.put(('startup_progress', {'step': self._startup_current_step, 'progress': self._startup_progress, 'total': len(self._startup_steps)}))
            env = os.environ.copy()
            env.update({'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1', 'PYTHONPATH': str(_PROJECT_DIR)})
            self._gate.checkpoint()
            backend_cmd = [_PYTHON_EXE, '-u', '-m', 'uvicorn', 'fastapi_app.main:app', '--host', '0.0.0.0', '--port', str(_API_PORT), '--log-level', 'info', '--reload', '--reload-dir', 'fastapi_app']
            self._process = subprocess.Popen(backend_cmd, cwd=str(_PROJECT_DIR), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creationflags, text=False)
            self._msg_queue.put(('log', {'text': f"后端进程已启动 (PID: {self._process.pid})"}))
            threading.Thread(target=self._read_stdout, args=(self._process,), daemon=True).start()
            backend_ready = False
            for _ in range(30):
                self._gate.checkpoint()
                try:
                    urllib.request.urlopen(f'http://127.0.0.1:{_API_PORT}/api/health', timeout=2)
                    backend_ready = True
                    break
                except Exception:
                    time.sleep(1)
            if not backend_ready:
                self._msg_queue.put(('log', {'text': '后端启动失败或健康检查未通过', 'level': 'ERROR'}))
                if self._process and self._process.poll() is None:
                    self._msg_queue.put(('log', {'text': f'正在终止未就绪的后端进程 (PID: {self._process.pid})...'}))
                    self._kill_process_tree(self._process.pid)
                    with contextlib.suppress(Exception):
                        self._process.wait(timeout=3)
                self._process = None
                self._msg_queue.put(('dual_failed', {'label': label, 'reason': '后端未就绪'}))
                return
            self._startup_current_step, self._startup_progress = self._startup_steps[3], 4
            self._msg_queue.put(('startup_progress', {'step': self._startup_current_step, 'progress': self._startup_progress, 'total': len(self._startup_steps)}))
            npm_cmd = 'npm.cmd' if _IS_WINDOWS else 'npm'
            # 启动 Vite dev server
            self._gate.checkpoint()
            self._frontend_process = subprocess.Popen([npm_cmd, 'run', 'dev', '--', '--port', str(_WEB_PORT)], cwd=str(_FRONTEND_DIR), env={**os.environ, 'BACKEND_INTERNAL_URL': f'http://127.0.0.1:{_API_PORT}'}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creationflags, text=False)
            self._msg_queue.put(('log', {'text': f"前端进程已启动 (PID: {self._frontend_process.pid})"}))
            threading.Thread(target=self._read_frontend_stdout, args=(self._frontend_process,), daemon=True).start()
            frontend_ready = False
            for _ in range(60):
                self._gate.checkpoint()
                try:
                    urllib.request.urlopen(f'http://127.0.0.1:{_WEB_PORT}/', timeout=2)
                    frontend_ready = True
                    break
                except Exception:
                    time.sleep(1)
            if not frontend_ready:
                self._msg_queue.put(('log', {'text': '前端启动失败或健康检查未通过', 'level': 'ERROR'}))
                for proc, name in [(self._frontend_process, '前端'), (self._process, '后端')]:
                    if proc and proc.poll() is None:
                        self._msg_queue.put(('log', {'text': f'正在终止未就绪的{name}进程 (PID: {proc.pid})...'}))
                        self._kill_process_tree(proc.pid)
                        with contextlib.suppress(Exception):
                            proc.wait(timeout=3)
                self._process, self._frontend_process = None, None
                self._msg_queue.put(('dual_failed', {'label': label, 'reason': '前端未就绪'}))
                return
            self._startup_current_step, self._startup_progress = self._startup_steps[4], 5
            self._msg_queue.put(('startup_progress', {'step': self._startup_current_step, 'progress': self._startup_progress, 'total': len(self._startup_steps)}))
            self._msg_queue.put(('dual_started', {'label': label}))
        except Exception as e:
            self._process, self._frontend_process = None, None
            self._msg_queue.put(('dual_failed', {'label': label, 'reason': f'异常: {str(e)}'}))

    def _read_frontend_stdout(self, proc):
        batch = []
        while True:
            try:
                line = proc.stdout.readline()
                if not line:
                    break
                text = self._decode_line(line)  # GBK/UTF-8 级联解码，修复中文 Windows 前端输出乱码
                if text:
                    level = 'ERROR' if any(k in text.lower() for k in ['error', 'exception', 'failed']) else 'INFO'
                    batch.append((f'[WEB] {text}', level))
                    if len(batch) >= 10:
                        for t, l in batch:
                            self._msg_queue.put(('log', {'text': t, 'level': l}))
                        batch.clear()
            except Exception:
                break
        if batch:
            for t, l in batch:
                self._msg_queue.put(('log', {'text': t, 'level': l}))

    def _stop_dual_mode_async(self, label):
        self._gate.start(f'停止{label}', self._stop_dual_flow, label)

    def _stop_dual_flow(self, label):
        self._msg_queue.put(('log', {'text': f"正在停止{label}..."}))
        frontend_proc, backend_proc = self._frontend_process, self._process
        self._frontend_process, self._process = None, None
        for proc, name in [(frontend_proc, '前端'), (backend_proc, '后端')]:
            if proc and proc.poll() is None:
                self._msg_queue.put(('log', {'text': f'正在终止{name}进程树 (PID: {proc.pid})...'}))
                if _IS_WINDOWS:
                    with contextlib.suppress(Exception):
                        _taskkill(proc.pid)
                else:
                    try:
                        proc.terminate()
                        proc.wait(timeout=5)
                    except Exception:
                        with contextlib.suppress(Exception):
                            proc.kill()
                self._msg_queue.put(('log', {'text': f'{name}进程已终止 (PID: {proc.pid})'}))
        self._stop_redis()
        self._kill_port_sync(_API_PORT)
        self._kill_port_sync(_WEB_PORT)
        self._mode = 'none'
        self._current_mode_key = ""
        self._msg_queue.put(('ui_update', {}))
        self._msg_queue.put(('log', {'text': f"{label}已停止，端口已释放"}))

    def _restart_dual_thread(self):
        self._mode, self._current_mode_key = 'restarting', 'dual_dev'
        self._startup_progress, self._startup_steps, self._startup_current_step = 0, ['停止生产模式', '检查Redis服务', '启动后端服务', '启动前端服务', '完成'], ''
        self._msg_queue.put(('ui_update', {}))
        label = '开发模式'
        for proc, name in [(self._frontend_process, '前端'), (self._process, '后端')]:
            if proc and proc.poll() is None:
                self._msg_queue.put(('log', {'text': f"重启：终止{name}进程树 (PID: {proc.pid})..."}))
                if _IS_WINDOWS:
                    for cpid in self._collect_process_tree(proc.pid):
                        with contextlib.suppress(Exception):
                            _taskkill(cpid)
                    _taskkill(proc.pid)
                else:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        proc.kill()
        self._frontend_process, self._process = None, None
        self._stop_redis()
        self._kill_port_sync(_API_PORT)
        self._kill_port_sync(_WEB_PORT)
        time.sleep(0.5)
        self._gate.checkpoint()
        self._start_dual_thread(label)

    def _on_dual_started(self, label):
        backend_alive = self._process and self._process.poll() is None
        frontend_alive = self._frontend_process and self._frontend_process.poll() is None
        if not backend_alive:
            self.log_message(f"{label}启动后后端进程已退出", 'ERROR')
            if frontend_alive:
                self._kill_process_tree(self._frontend_process.pid)
            self._mode, self._process, self._frontend_process = 'none', None, None
            self._current_mode_key = ""
            self._update_all_ui()
            return
        if not frontend_alive:
            self.log_message(f"{label}启动后前端进程已退出，正在清理...", 'WARNING')
            if self._process and self._process.poll() is None:
                self._kill_process_tree(self._process.pid)
            self._mode, self._process, self._frontend_process = 'none', None, None
            self._current_mode_key = ""
            self._update_all_ui()
            self.status_bar_label.config(text="前端启动失败，已停止")
            return
        self._mode = 'dual_dev'
        self._update_all_ui()
        self.status_bar_label.config(text=f"{label}运行中")
        self.log_message(f"{label}启动成功")
        self.log_message(f"  → 后端: http://localhost:{_API_PORT}")
        if frontend_alive:
            self.log_message(f"  → 前端: http://localhost:{_WEB_PORT}")

    def _on_dual_failed(self, label, reason):
        self.log_message(f"{label}启动失败: {reason}", 'ERROR')
        self._mode, self._process, self._frontend_process = 'none', None, None
        self._current_mode_key = ""
        self._update_all_ui()
        self.status_bar_label.config(text=f"{label}启动失败: {reason}")

    def _mode_label(self):
        return {'debug': '调试模式', 'dual_dev': '开发模式（前后端）', 'restarting': '重启中', 'starting': '启动中', 'stopping': '停止中'}.get(self._mode, '')

    def _update_all_ui(self):
        is_dual_dev = self._mode == 'dual_dev'
        is_starting, is_restarting, _is_stopping = self._mode == 'starting', self._mode == 'restarting', self._mode == 'stopping'
        is_none = self._mode == 'none'
        current_mode_key = self._current_mode_key
        self._update_card_ui('dual_dev', is_dual_dev, is_none, is_starting and current_mode_key == 'dual_dev', is_restarting and current_mode_key == 'dual_dev')
        # stop_all总是可用，作为紧急重置
        self.stop_all_btn.config(state='normal')
        self._update_mode_badge()
        if is_none:
            self.status_bar_label.config(text="就绪")
        elif self._mode in ('restarting', 'starting', 'stopping'):
            self.status_bar_label.config(text=f"{self._mode_label()}...")

    def _update_card_ui(self, mode_key, is_active, is_none, is_starting=False, is_restarting=False):
        status = getattr(self, f'{mode_key}_status')
        start_btn = getattr(self, f'{mode_key}_start_btn')
        restart_btn = getattr(self, f'{mode_key}_restart_btn')
        # 统一状态枚举：starting→部署中(蓝弧) / restarting→重启中(橙闪) / active→运行中(绿呼吸) / stopped→已停止(灰空心)
        state = 'deploying' if is_starting else 'restarting' if is_restarting else 'running' if is_active else 'stopped'
        state_text = '启动中' if is_starting else '重启中' if is_restarting else '运行中' if is_active else '已停止'
        status.set_state(state, state_text)
        start_btn.config(state='disabled' if (is_starting or is_restarting) else 'normal')
        restart_btn.config(state='disabled' if (not is_active or is_starting or is_restarting) else 'normal')

    def check_server_status(self):
        if self._mode in ('none', 'restarting', 'starting'):
            self._after_ids['status'] = self.root.after(self._check_interval, self.check_server_status)
            return
        backend_crashed = self._process and self._process.poll() is not None
        frontend_crashed = self._mode == 'dual_dev' and self._frontend_process and self._frontend_process.poll() is not None
        if backend_crashed or frontend_crashed:
            code = self._process.poll() if self._process else None
            label = self._mode_label()
            if backend_crashed and frontend_crashed:
                self.log_message(f"{label}前后端进程均已意外终止 (退出码: {code})", 'ERROR')
            elif backend_crashed:
                self.log_message(f"{label}后端进程意外终止 (退出码: {code})", 'ERROR')
            else:
                self.log_message(f"{label}前端进程意外终止", 'ERROR')
            if self._frontend_process and self._frontend_process.poll() is None:
                self._kill_process_tree(self._frontend_process.pid)
            if self._process and self._process.poll() is None:
                self._kill_process_tree(self._process.pid)
            self._mode, self._process, self._frontend_process = 'none', None, None
            self._current_mode_key = ""
            self._update_all_ui()
            self._after_ids['crash_warn'] = self.root.after(100, lambda: messagebox.showwarning("警告", f"{label}意外停止，请检查日志"))
        self._after_ids['status'] = self.root.after(self._check_interval, self.check_server_status)

    def _kill_process_tree(self, pid):
        if not pid:
            return
        try:
            if _IS_WINDOWS:
                _taskkill(pid)
            else:
                import signal
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except Exception:
                    with contextlib.suppress(Exception):
                        os.kill(pid, signal.SIGTERM)
        except Exception:
            pass

    def on_closing(self):
        if self._tray_icon:
            self.root.withdraw()
        else:
            self._do_quit()

    def _build_ui(self):
        self.root.configure(bg=self._PALETTE['bg_main'])
        # ---- 顶栏 ----
        header = tk.Frame(self.root, bg=self._PALETTE['bg_header'], height=58)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        hdr = tk.Frame(header, bg=self._PALETTE['bg_header'])
        hdr.pack(fill=tk.X, padx=24)
        logo = tk.Frame(hdr, bg=self._PALETTE['accent'], width=32, height=32)
        logo.pack(side=tk.LEFT, pady=(13, 0))
        logo.pack_propagate(False)
        tk.Label(logo, text='E', font=('Segoe UI', 15, 'bold'), fg='#ffffff', bg=self._PALETTE['accent']).place(relx=0.5, rely=0.5, anchor='center')
        brand = tk.Frame(hdr, bg=self._PALETTE['bg_header'])
        brand.pack(side=tk.LEFT, padx=(11, 0), pady=(11, 0))
        tk.Label(brand, text='ERP 服务器管理器', font=('Microsoft YaHei UI', 14, 'bold'), fg=self._PALETTE['text_primary'], bg=self._PALETTE['bg_header']).pack(anchor='w')
        tk.Label(brand, text='开发 / 生产一键切换 · 互斥托管', font=('Microsoft YaHei UI', 8), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_header']).pack(anchor='w')
        ver_frame = tk.Frame(hdr, bg=self._PALETTE['bg_input'], highlightbackground=self._PALETTE['border'], highlightthickness=1)
        ver_frame.pack(side=tk.LEFT, padx=(12, 0), pady=(22, 0))
        tk.Label(ver_frame, text=_VERSION, font=('Consolas', 8), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_input']).pack(padx=8, pady=1)
        ports = tk.Frame(hdr, bg=self._PALETTE['bg_header'])
        ports.pack(side=tk.RIGHT, pady=(18, 0))
        for label, port, tint, fg_c in [('API', _API_PORT, self._PALETTE['accent_tint'], self._PALETTE['accent']), ('WEB', _WEB_PORT, self._PALETTE['success_tint'], self._PALETTE['success'])]:
            pill = tk.Frame(ports, bg=tint)
            pill.pack(side=tk.LEFT, padx=(6, 0))
            tk.Label(pill, text=f'{label} {port}', font=('Consolas', 9, 'bold'), fg=fg_c, bg=tint).pack(padx=10, pady=3)
        tk.Frame(self.root, bg=self._PALETTE['border'], height=1).pack(fill=tk.X)
        self._build_status_bar()
        # ---- 内容区：开发/生产双卡并排 + 底部日志 ----
        content = tk.Frame(self.root, bg=self._PALETTE['bg_main'])
        content.pack(fill=tk.BOTH, expand=True, padx=20, pady=(14, 12))
        content.columnconfigure(0, weight=1, uniform='mode_cards')
        content.columnconfigure(1, weight=1, uniform='mode_cards')
        content.rowconfigure(0, weight=0)
        content.rowconfigure(1, weight=1)
        self._build_server_card(content, 0, 0, '开发模式', 'DEV', 'FastAPI + Vue3 / Vite · 热重载 · 自动切换', 'dual_dev', self.start_dual_dev, self.stop_dual_dev, self.restart_dual_dev)
        self._build_prod_card(content, 0, 1)
        self._build_log_section(content)

    def _card(self, parent, row, col, columnspan=1):
        card = tk.Frame(parent, bg=self._PALETTE['bg_card'], highlightbackground=self._PALETTE['border_card'], highlightthickness=1)
        card.grid(row=row, column=col, columnspan=columnspan, sticky='nsew', padx=(0, 10) if col == 0 else (10, 0))
        self._server_cards.append(card)
        return card

    def _card_head(self, card, icon_text, icon_tint, icon_fg, title, desc):
        """卡片统一头部：圆角图标 + 标题/副标题（iOS 分组列表风格）"""
        body = tk.Frame(card, bg=self._PALETTE['bg_card'])
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=(15, 16))
        head = tk.Frame(body, bg=self._PALETTE['bg_card'])
        head.pack(fill=tk.X)
        icon = tk.Frame(head, bg=icon_tint, width=34, height=34)
        icon.pack(side=tk.LEFT)
        icon.pack_propagate(False)
        tk.Label(icon, text=icon_text, font=('Segoe UI', 9, 'bold'), fg=icon_fg, bg=icon_tint).place(relx=0.5, rely=0.5, anchor='center')
        tcol = tk.Frame(head, bg=self._PALETTE['bg_card'])
        tcol.pack(side=tk.LEFT, padx=(10, 0), fill=tk.X, expand=True)
        tk.Label(tcol, text=title, font=('Microsoft YaHei UI', 13, 'bold'), fg=self._PALETTE['text_primary'], bg=self._PALETTE['bg_card'], anchor='w').pack(anchor='w')
        tk.Label(tcol, text=desc, font=('Microsoft YaHei UI', 8), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_card'], anchor='w').pack(anchor='w')
        tk.Frame(body, bg=self._PALETTE['border'], height=1).pack(fill=tk.X, pady=(13, 0))
        return body

    def _build_server_card(self, parent, row, col, title, script_label, desc, mode_key, start_cmd, stop_cmd, restart_cmd, columnspan=1):
        card = self._card(parent, row, col, columnspan=columnspan)
        body = self._card_head(card, 'DEV', self._PALETTE['success_tint'], self._PALETTE['success'], title, desc)
        # 状态行：胶囊状态徽章（详情页场景）
        st = tk.Frame(body, bg=self._PALETTE['bg_card'])
        st.pack(fill=tk.X, pady=(11, 0))
        status_badge = StatusBadge(st, state='stopped', text='已停止', size='md', palette=self._PALETTE, canvas_bg=self._PALETTE['bg_card'])
        status_badge.pack(side=tk.LEFT)
        # 操作按钮：主操作实心 + 次操作浅底
        btns = tk.Frame(body, bg=self._PALETTE['bg_card'])
        btns.pack(fill=tk.X, pady=(13, 0))
        start_btn = RoundedButton(btns, text='启动开发', variant='solid', tone='success', command=start_cmd, canvas_bg=self._PALETTE['bg_card'])
        self._action_buttons.append(start_btn)   # 参与「动作期间置灰」（紧急停止不登记）
        start_btn.pack(side=tk.LEFT)
        restart_btn = RoundedButton(btns, text='重启', variant='outlined', tone='accent', command=restart_cmd, state='disabled', canvas_bg=self._PALETTE['bg_card'])
        self._action_buttons.append(restart_btn)
        restart_btn.pack(side=tk.LEFT, padx=(8, 0))
        setattr(self, f'{mode_key}_status', status_badge)
        setattr(self, f'{mode_key}_start_btn', start_btn)
        setattr(self, f'{mode_key}_restart_btn', restart_btn)

    # ===================== 生产模式 (Windows 服务 + NSSM) =====================

    def _find_nssm(self):
        found = shutil.which('nssm')
        if found:
            return found
        for cand in _NSSM_CANDIDATES:
            if cand.is_file():
                return str(cand)
        return None

    @staticmethod
    def _decode_output(raw):
        """把子进程的原始字节流解码为文本（Windows 控制台程序编码并不统一）。

        · nssm 走宽字符 API，输出是 **UTF-16LE**：按 utf-8 解会得到
          "E r r o r   c r e a t i n g   s e r v i c e !" 这种隔字带空格的乱码，
          中文错误文本更是整段变成 U+FFFD。2026-09-16 实测：nssm 明明回了
          「指定的服务已存在。」，界面/日志里却只剩不可读字符，故障定位被直接堵死。
        · sc.exe 走 OEM 代码页（中文系统 cp936/GBK），偶尔夹杂 UTF-8。

        因此先按 BOM / NUL 密度判 UTF-16，再回落到多编码严格试探；
        任何一步都不抛异常——解码失败只降级为 replace，绝不因此吞掉真实返回码。
        """
        if not raw:
            return ''
        if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
            try:
                return raw.decode('utf-16', errors='replace').lstrip('\ufeff')
            except Exception:
                pass
        elif raw.count(b'\x00') * 4 > len(raw):
            # UTF-16LE 的 ASCII 段每个字符后跟一个 \x00，NUL 占比远高于任何 8bit 编码
            try:
                return raw.decode('utf-16-le', errors='replace')
            except Exception:
                pass
        preferred = locale.getpreferredencoding(False) or ''
        for enc in ('utf-8', 'gb18030', 'cp936', preferred):
            if not enc:
                continue
            try:
                return raw.decode(enc, errors='strict')
            except Exception:
                continue
        return raw.decode('utf-8', errors='replace')

    def _run_capture(self, args, timeout=20):
        try:
            result = subprocess.run(args, creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0,
                                    capture_output=True, timeout=timeout)
            return (result.returncode,
                    self._decode_output(result.stdout or b'') + self._decode_output(result.stderr or b''))
        except Exception as e:
            return -1, str(e)

    def _svc_state(self, name):
        """返回三态：'未安装' | '未知' | STATE 文本（如 '4 RUNNING' / '1 STOPPED'）。

        ★ 三态语义（勿回退）：只有 rc==1060（ERROR_SERVICE_DOES_NOT_EXIST）或输出
        明确含 1060 且【没有】STATE 行才判「未安装」；其它任何查询失败（5=拒绝访问、
        超时、被安全软件拦截、解码异常）一律判「未知」——绝不把「查不出来」当「不存在」，
        否则 _ensure_production_stopped 会静默跳过仍在运行的生产服务，开发模式随即
        抢占 5002/3000 与生产互杀。
        """
        code, out = self._run_capture(['sc', 'query', name], timeout=5)
        if code == 1060 or ('1060' in out and 'STATE' not in out):
            return '未安装'
        if code != 0 or 'SERVICE_NAME' not in out:
            return '未知'
        for line in out.splitlines():
            if 'STATE' in line:
                parts = line.split(':', 1)
                if len(parts) > 1:
                    return ' '.join(parts[1].split())[:28]
        return '未知'

    def _svc_pid(self, name):
        """查询 Windows 服务当前进程 PID（sc queryex），未运行返回 None"""
        code, out = self._run_capture(['sc', 'queryex', name], timeout=5)
        if code != 0:
            return None
        for line in out.splitlines():
            stripped = line.strip()
            if stripped.startswith('PID'):
                parts = stripped.split(':', 1)
                if len(parts) > 1 and parts[1].strip().isdigit():
                    return int(parts[1].strip())
        return None

    def _wait_service_stopped(self, name, timeout=45):
        """发出 nssm stop 后轮询服务状态直到 STOPPED；超时返回 False。

        NSSM stop 立即返回，服务进入 STOP_PENDING，优雅关闭需数秒。
        若在 STOP_PENDING 期间强杀被管进程，会被 AppExit Default Restart
        判定为崩溃而自动重启，与目标模式抢占端口。因此必须等待确认 STOPPED。
        """
        self._run_capture([self._find_nssm(), 'stop', name], timeout=15)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._gate.checkpoint()      # 取消时立即中止等待，不再空等 45s
            state = self._svc_state(name)
            if 'STOPPED' in state:
                return True
            time.sleep(1)
        return False

    def _managed_service_pids(self):
        """NSSM 受管进程集合（服务根 PID + 整棵子树）。

        ★ P0-4 的核心闸门：受管进程**绝不能被直接 kill** —— NSSM 的
        AppExit=Default Restart + AppRestartDelay=5000 会在 5 秒后把它拉起来，
        杀掉→复活→再杀就是「杀不死」死循环。受管进程只能经 `nssm stop` 停止。
        """
        managed = set()
        for name in (_SVC_API, _SVC_ARQ, _SVC_WEB):
            pid = self._svc_pid(name)
            if pid:
                managed.add(pid)
                managed.update(self._collect_process_tree(pid))
        return managed

    def _stop_managed_services(self):
        """正常停止 NSSM 受管服务（erp-prod / erp-arq / erp-web），返回受管 PID 集合供端口清理兜底。

        ★ 与 _service_cmd_sync('stop') 的关键区别：本方法【不带 checkpoint】——
        紧急停止 stop_all 已先 cancel() 置位取消标志，任何 checkpoint 都会抛
        _ActionCancelled 把「停服务」半路打断，于是服务根本没停、端口清理又误杀
        受管进程触发 NSSM 5 秒自动重启 —— 这正是「紧急停止变成重启」的根因。

        返回 (成功停止的服务数, 受管 PID 集合)。受管 PID 无论 stop 成败都要返回，
        供后续 _kill_port_sync 排除，避免 stop 超时失败时端口清理误杀受管进程。
        """
        nssm = self._find_nssm()
        managed = self._managed_service_pids()
        stopped = 0
        for name in (_SVC_API, _SVC_ARQ, _SVC_WEB):
            state = self._svc_state(name)
            if '未安装' in state or 'STOPPED' in state:
                continue
            self._msg_queue.put(('log', {'text': f'正在停止生产服务 {name}...'}))
            if nssm:
                self._run_capture([nssm, 'stop', name], timeout=30)
            else:
                self._run_capture(['sc', 'stop', name], timeout=30)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if 'STOPPED' in self._svc_state(name):
                    stopped += 1
                    self._msg_queue.put(('log', {'text': f'{name} 已停止'}))
                    break
                time.sleep(1)
            else:
                self._msg_queue.put(('log', {'text': f'{name} 在 45s 内未确认 STOPPED，将在端口清理时排除其受管进程以避免误杀触发重启', 'level': 'WARNING'}))
        return stopped, managed

    def _find_loose_prod_runner_pids(self, exclude=()):
        """精确定位「游离」的 prod_runner（不经 NSSM 托管的手工启动进程）。

        判据 = 命令行命中 _is_prod_runner_cmdline（模块式/脚本式精确匹配），
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
                if _is_prod_runner_cmdline(' '.join(proc.info.get('cmdline') or [])):
                    pids.append(pid)
            except Exception:
                continue
        return pids

    def _find_project_residual_pids(self, exclude=()):
        """扫描本项目的残留开发/调试进程（P0-4）。

        替代原先「凡名字带 python / node 一律杀」的宽特征扫描 —— 那会误杀 NSSM
        受管的生产进程，以及机器上任何无关的 Python / Node 程序。
        现判据：命令行或工作目录指向本项目，且不在排除集内。
        """
        exclude = set(exclude or ())
        exclude.add(os.getpid())
        with contextlib.suppress(Exception):
            exclude.add(os.getppid())  # PyInstaller onefile 的 bootloader 父进程
        project = str(_PROJECT_DIR).lower()
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

    def _ensure_production_stopped(self):
        """切换前停止生产模式：停 NSSM 服务 + 清游离的 prod_runner 进程树。

        ★ 返回契约固定为 3 元组 (ok, fail_reason, stopped_any)。
          P0-1：原实现在超时分支返回 2 元组，而调用方按 3 元组解包
                → ValueError → 「开发模式 100% 无法启动」。
          P0-2：原实现在 `except Exception: pass` 之后落到 `return True, None, ...`
                → 任何异常都被静默转成「成功」，调用方继续启动 → 双进程抢端口。
                现改为：失败必须带真实原因返回，不存在静默成功路径。
        """
        stopped_any = False
        nssm = self._find_nssm()
        if nssm:
            for name in (_SVC_API, _SVC_ARQ, _SVC_WEB):
                state = self._svc_state(name)
                if 'STOPPED' in state or '未安装' in state:
                    continue
                self._msg_queue.put(('log', {'text': f'正在停止生产服务 {name}...'}))
                if not self._wait_service_stopped(name):
                    return False, f'{name} 停止超时（STOP_PENDING 未确认），已中止切换', stopped_any
                stopped_any = True
        # 清理游离的 prod_runner（不受 NSSM 控制）；受管进程跳过，交给 nssm stop（P0-4）
        self._gate.checkpoint()
        try:
            managed = self._managed_service_pids()
            for pid in self._find_loose_prod_runner_pids(exclude=managed):
                self._kill_process_tree(pid)
                self._msg_queue.put(('log', {'text': f'已清理游离 prod_runner 进程 (PID: {pid})'}))
                stopped_any = True
            if managed:
                self._msg_queue.put(('log', {'text': f'已跳过 {len(managed)} 个 NSSM 受管进程（须经服务停止命令处理）'}))
        except Exception as e:
            # 失败如实返回：不允许「扫不到 / 扫描报错」等同于「没有残留」
            self._msg_queue.put(('log', {'text': f'残留 prod_runner 扫描失败: {e}', 'level': 'WARNING'}))
            return False, f'残留进程扫描失败: {e}', stopped_any
        return True, None, stopped_any

    def _ensure_development_stopped(self):
        """切换前停止开发模式：只停开发子进程，不动 Redis，重置 GUI 状态。

        与 _stop_dual_mode_async 的区别：不调用 _stop_redis()，保留共享基础设施。
        """
        stopped_any = False
        for proc, name in [(self._frontend_process, '前端'), (self._process, '后端')]:
            if proc and proc.poll() is None:
                self._msg_queue.put(('log', {'text': f'正在终止开发{name}进程树 (PID: {proc.pid})...'}))
                self._kill_process_tree(proc.pid)
                try:
                    proc.wait(timeout=5)
                except Exception:
                    with contextlib.suppress(Exception):
                        proc.kill()
                self._msg_queue.put(('log', {'text': f'开发{name}进程已终止 (PID: {proc.pid})'}))
                stopped_any = True
        self._process = None
        self._frontend_process = None
        self._mode = 'none'
        self._current_mode_key = ""
        self._msg_queue.put(('ui_update', {}))
        self._msg_queue.put(('hosting_refresh', {}))
        if stopped_any:
            self._msg_queue.put(('log', {'text': '开发模式已停止'}))
        return stopped_any

    def _release_ports(self):
        """清理 5002 与 3000 端口占用（复用 _kill_port_sync，其内部对多 PID 有 3 轮重试）。"""
        self._kill_port_sync(_API_PORT)
        self._kill_port_sync(_WEB_PORT)

    def _build_prod_card(self, parent, row, col):
        """生产模式卡片（与开发卡并排）— Windows 服务 (NSSM) 托管"""
        card = self._card(parent, row, col)
        body = self._card_head(card, 'PROD', self._PALETTE['accent_tint'], self._PALETTE['accent'], '生产模式', 'Windows 服务 (NSSM) · 开机自启 · 崩溃自愈')
        # 服务状态行：胶囊徽章(整体状态)
        st = tk.Frame(body, bg=self._PALETTE['bg_card'])
        st.pack(fill=tk.X, pady=(11, 0))
        self.hosting_svc_badge = StatusBadge(st, state='stopped', text='服务停止', size='md', palette=self._PALETTE, canvas_bg=self._PALETTE['bg_card'])
        self.hosting_svc_badge.pack(side=tk.LEFT, padx=(0, 8))
        # 组件状态网格：胶囊状态徽章（监控面板场景）
        grid = tk.Frame(body, bg=self._PALETTE['bg_input'])
        grid.pack(fill=tk.X, pady=(11, 0))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        self.hosting_backend_badge = StatusBadge(grid, state='stopped', text='后端', size='sm', palette=self._PALETTE, canvas_bg=self._PALETTE['bg_input'])
        self.hosting_backend_badge.grid(row=0, column=0, sticky='w', padx=(12, 6), pady=(8, 2))
        self.hosting_arq_badge = StatusBadge(grid, state='stopped', text='ARQ', size='sm', palette=self._PALETTE, canvas_bg=self._PALETTE['bg_input'])
        self.hosting_arq_badge.grid(row=0, column=1, sticky='w', padx=(6, 12), pady=(8, 2))
        self.hosting_frontend_badge = StatusBadge(grid, state='stopped', text='前端', size='sm', palette=self._PALETTE, canvas_bg=self._PALETTE['bg_input'])
        self.hosting_frontend_badge.grid(row=1, column=0, sticky='w', padx=(12, 6), pady=2)
        self.hosting_redis_badge = StatusBadge(grid, state='stopped', text='Redis', size='sm', palette=self._PALETTE, canvas_bg=self._PALETTE['bg_input'])
        self.hosting_redis_badge.grid(row=1, column=1, sticky='w', padx=(6, 12), pady=2)
        self.hosting_ready_badge = StatusBadge(grid, state='stopped', text='就绪', size='sm', palette=self._PALETTE, canvas_bg=self._PALETTE['bg_input'])
        self.hosting_ready_badge.grid(row=2, column=0, sticky='w', padx=(12, 6), pady=(2, 8))
        # 备份徽章：读 /api/health 的 backup 块（产物新鲜度 25h + ARQ 在线）
        self.hosting_backup_badge = StatusBadge(grid, state='stopped', text='备份', size='sm', palette=self._PALETTE, canvas_bg=self._PALETTE['bg_input'])
        self.hosting_backup_badge.grid(row=3, column=0, sticky='w', padx=(12, 6), pady=(0, 8))
        # Worker 数（安装服务时生效）
        wk = tk.Frame(grid, bg=self._PALETTE['bg_input'])
        wk.grid(row=2, column=1, sticky='e', padx=(6, 12), pady=(2, 8))
        tk.Label(wk, text='Worker', font=('Microsoft YaHei UI', 9), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_input']).pack(side=tk.LEFT, padx=(0, 4))
        self.hosting_workers_var = tk.StringVar(value=str(int(os.getenv('UVICORN_WORKERS', '4'))))
        ttk.Combobox(wk, textvariable=self.hosting_workers_var, values=('2', '4', '6', '8'), width=4, state='readonly', font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT)
        # 主操作行：启动(实心蓝) 停止(描边红) 重启(描边蓝) 刷新(描边蓝)  — 统一 36px / pady=6 / radius=10
        btns = tk.Frame(body, bg=self._PALETTE['bg_card'])
        btns.pack(fill=tk.X, pady=(13, 0))
        svc_start_btn = RoundedButton(btns, text='启动服务', variant='solid', tone='accent', command=self._start_services, canvas_bg=self._PALETTE['bg_card'])
        self._action_buttons.append(svc_start_btn)   # 变更类按钮置灰；刷新/打开日志为只读，始终可用
        svc_start_btn.pack(side=tk.LEFT)
        svc_stop_btn = RoundedButton(btns, text='停止', variant='outlined', tone='danger', command=self._stop_services, canvas_bg=self._PALETTE['bg_card'])
        self._action_buttons.append(svc_stop_btn)
        svc_stop_btn.pack(side=tk.LEFT, padx=(8, 0))
        svc_restart_btn = RoundedButton(btns, text='重启', variant='outlined', tone='accent', command=self._restart_services, canvas_bg=self._PALETTE['bg_card'])
        self._action_buttons.append(svc_restart_btn)
        svc_restart_btn.pack(side=tk.LEFT, padx=(8, 0))
        RoundedButton(btns, text='刷新', variant='outlined', tone='neutral', command=self._manual_refresh_hosting, canvas_bg=self._PALETTE['bg_card']).pack(side=tk.LEFT, padx=(8, 0))
        # 次操作行：安装(实心绿) 卸载(描边红) 日志(描边蓝)  — 同上规格，垂直间距 8px
        btns2 = tk.Frame(body, bg=self._PALETTE['bg_card'])
        btns2.pack(fill=tk.X, pady=(8, 0))
        install_btn = RoundedButton(btns2, text='安装服务', variant='solid', tone='success', command=self._install_services, canvas_bg=self._PALETTE['bg_card'])
        self._action_buttons.append(install_btn)
        install_btn.pack(side=tk.LEFT)
        uninstall_btn = RoundedButton(btns2, text='卸载', variant='outlined', tone='danger', command=self._uninstall_services, canvas_bg=self._PALETTE['bg_card'])
        self._action_buttons.append(uninstall_btn)
        uninstall_btn.pack(side=tk.LEFT, padx=(8, 0))
        RoundedButton(btns2, text='打开日志', variant='outlined', tone='neutral', command=self._open_logs_dir, canvas_bg=self._PALETTE['bg_card']).pack(side=tk.LEFT, padx=(8, 0))
    def _manual_refresh_hosting(self):
        """手动刷新生产模式状态（后台收集 + 主线程应用，不阻塞 UI）"""
        self._refresh_hosting_status()
        self.log_message('已手动刷新生产模式状态')

    def _warn_once(self, key, text):
        """同类警告只记一次，避免每 5s 刷屏把真实信号埋掉（状态好转时由调用方复位）。

        key 必须是稳定标识 —— 把「已 N 秒未更新」这类逐轮递增的量放进 key，
        去重就会失效，变成每 5s 刷一条。
        """
        if key != self._hosting_last_warn:
            self._hosting_last_warn = key
            self.log_message(f'[生产模式] {text}', 'WARNING')

    def _refresh_hosting_status(self):
        """调度后台线程收集生产模式状态，收集完成后经消息队列回主线程应用。

        sc query / 状态文件 IO / Redis 探测均为阻塞操作，绝不能在 Tk 主线程执行，
        否则周期刷新（5s）会让 GUI 持续卡顿。收集期间重复调用只标记待刷新。
        """
        now = time.time()
        if getattr(self, '_hosting_collecting', False):
            # 这个闸只在收集线程回报后才释放。线程若挂死（如 shutil.which 卡在失效的
            # PATH 项）或带 BaseException 退出，闸就永不释放、界面从此不再更新。
            # 超时即认定上一轮作废并重启刷新链。
            if now - getattr(self, '_hosting_collect_started', now) < self.HOSTING_COLLECT_TIMEOUT_SEC:
                self._hosting_refresh_requested = True
                return
            self._msg_queue.put(('log', {
                'text': f'[生产模式] 状态收集超过 {int(self.HOSTING_COLLECT_TIMEOUT_SEC)}s 未回报，'
                        f'已放弃该轮并重启刷新链',
                'level': 'WARNING'}))
        self._hosting_collecting = True
        self._hosting_collect_started = now

        def _collect():
            try:
                data = self._collect_hosting_data()
            except BaseException as e:   # 含 BaseException 派生（_ActionCancelled 等）
                data = {'collect_error': True, 'error': f'{type(e).__name__}: {e}'}
            self._msg_queue.put(('hosting_apply', {'data': data}))
        threading.Thread(target=_collect, daemon=True).start()

    def _collect_hosting_data(self):
        """纯数据收集（后台线程执行）——不触碰任何 UI 组件"""
        data = {
            'nssm': self._find_nssm(),
            'api_state': self._svc_state(_SVC_API),
            'arq_state': self._svc_state(_SVC_ARQ),
        }
        data['api_running'] = 'RUNNING' in data['api_state'].upper() if data['api_state'] else False
        data['api_unknown'] = data['api_state'] == '未知'
        data['arq_unknown'] = data['arq_state'] == '未知'
        data['redis_ok'] = self._is_redis_running()
        # broker 独立探测：它不在 prod_runner 的就绪判据里（ARQ 是独立服务），
        # 必须单独采集，否则「ARQ 已死」和「一切正常」在界面上长得一模一样。
        data['broker_ok'] = self._is_broker_running()
        data['redis_svc_state'] = self._redis_service_state(_SVC_REDIS_CACHE)
        data['broker_svc_state'] = self._redis_service_state(_SVC_REDIS_BROKER)
        status_file = _PROJECT_DIR / 'logs' / 'prod_runner.json'
        data['status_file'] = status_file
        data['status'], data['read_err'], data['mtime'], data['stale'], data['mtime_str'] = {}, None, 0, False, '—'
        if not data['api_running']:
            return data
        # 服务运行中：读取状态文件并校验新鲜度
        try:
            if status_file.is_file():
                data['status'] = json.loads(status_file.read_text(encoding='utf-8'))
            else:
                data['read_err'] = f'文件不存在: {status_file}'
        except Exception as e:
            data['read_err'] = f'读取失败: {type(e).__name__}: {e}'
        mtime = status_file.stat().st_mtime if status_file.is_file() else 0
        data['mtime'] = mtime
        data['stale'] = bool(status_file.is_file()) and (time.time() - mtime) > self.HOSTING_STALE_SEC
        data['mtime_str'] = datetime.fromtimestamp(mtime).strftime('%H:%M:%S') if mtime else '—'
        # ARQ 由独立 NSSM 服务托管时（--no-arq），从 erp-arq 服务查询真实 PID（IO 归入收集阶段）
        if data['status'].get('services', {}).get('arq', {}).get('status') == 'external':
            data['arq_svc_pid'] = self._svc_pid(_SVC_ARQ)
        else:
            data['arq_svc_pid'] = None
        # 备份可观测性：/api/health 的 backup 块（产物新鲜度 + ARQ 在线）。
        # 本机、10s 缓存、开销小；失败即空 dict，徽章显示「未上报」而非误报正常。
        data['backup'] = {}
        try:
            with _HTTP_DIRECT.open(f'http://127.0.0.1:{_API_PORT}/api/health', timeout=3) as resp:
                payload = json.loads(resp.read().decode('utf-8'))
            blk = payload.get('backup')
            if isinstance(blk, dict):
                data['backup'] = blk
        except Exception:
            pass
        return data

    def _apply_hosting_data(self, data):
        """主线程应用收集到的生产模式状态（仅 UI 更新，无阻塞 IO）"""
        try:
            self._prod_running = data.get('api_running', False)
            # ★ 三态语义贯通：sc query 失败(未知)必须独立记录，展示层据此显示「状态未知」，
            # 绝不能落成「已停止」——否则查不出来会被误当成生产已停、诱导误判。
            self._prod_unknown = data.get('api_unknown', False)
            if data.get('collect_error'):
                self._warn_once('collect-error',
                                f"状态收集失败（{data.get('error', '未知原因')}），界面本轮不更新")
                return

            def _detail(badge, state, text):
                badge.set_state(state, text)

            # 服务未运行：以 sc query 为权威，不读状态文件，避免残留旧数据
            if not data['api_running']:
                # ★ 查询失败(未知) ≠ 已停止：sc query 报「未知」时服务可能仍在运行，
                # 不得显示「服务停止」，须显式标「状态未知」并保留原状。
                api_unknown = data.get('api_unknown', False)
                if api_unknown:
                    self.hosting_svc_badge.set_state('unknown', '状态未知')
                    _detail(self.hosting_backend_badge, 'stopped', '后端 状态未知')
                    _detail(self.hosting_arq_badge, 'stopped', 'ARQ 状态未知')
                    _detail(self.hosting_frontend_badge, 'stopped', '前端 状态未知')
                    _detail(self.hosting_ready_badge, 'stopped', '就绪 状态未知')
                else:
                    self.hosting_svc_badge.set_state('stopped', '服务停止')
                    _detail(self.hosting_backend_badge, 'stopped', '后端 已停止')
                    _detail(self.hosting_arq_badge, 'stopped', 'ARQ 未运行')
                    _detail(self.hosting_frontend_badge, 'stopped', '前端 已停止')
                    _detail(self.hosting_ready_badge, 'stopped', '就绪 —')
                redis_ok = data['redis_ok']
                broker_ok = data.get('broker_ok', False)
                # 缓存与 broker 分开显示：broker 决定 ARQ（cron/备份/报表）能否工作，
                # 合并成一个「Redis 运行中」会把「缓存正常但队列已死」当健康上报。
                if redis_ok and broker_ok:
                    _detail(self.hosting_redis_badge, 'running', 'Redis 运行中')
                elif redis_ok:
                    _detail(self.hosting_redis_badge, 'error', f'broker({_REDIS_BROKER_PORT}) 未运行')
                else:
                    _detail(self.hosting_redis_badge, 'stopped', 'Redis 已停止')
                return

            read_err = data['read_err']
            stale = data.get('stale', False)
            mtime_str = data.get('mtime_str', '—')

            status = data['status']
            svcs = status.get('services', {})
            self.hosting_svc_badge.set_state('running', '服务运行')

            def _svc_detail(badge, label, svc, running, starting=()):
                """按 prod_runner 上报的 status 如实映射。

                关键：backend 的 running ≠ ready（进程已起、健康门未过）是「启动中」，
                不是「已停止」—— 把它显示成红色「已停止」正是用户点「启动服务」后
                看到的那条误导信息。
                """
                s = (svc or {}).get('status')
                if s in running:
                    _detail(badge, 'running', f'{label} 运行中')
                elif s in starting:
                    _detail(badge, 'deploying', f'{label} 启动中')
                elif s in ('failed', 'crashed'):
                    _detail(badge, 'error', f'{label} 异常({s})')
                elif s == 'stopped':
                    _detail(badge, 'stopped', f'{label} 已停止')
                else:
                    _detail(badge, 'stopped', f'{label} 未上报')

            # 状态文件不足信（陈旧/缺失/读失败）时绝不把旧快照当现状展示：
            # prod_runner 停写后，旧快照会永久冻在界面上，让人误判「已停止」
            # 而服务其实仍在 RUNNING —— 这正是「没有实时更新」的来路。
            if stale or read_err:
                # 但要先摘掉「启动窗口」这一段：刚发出启动/重启、且快照还早于那次启动时，
                # 陈旧是必然的（那是上一轮的快照），此时说「prod_runner 可能已退出、
                # 请重启服务」是假警报，照着做只会白重启一次服务。
                start_ts = getattr(self, '_prod_start_ts', 0.0)
                start_age = time.time() - start_ts if start_ts else None
                starting_up = (start_age is not None
                               and start_age < self.HOSTING_START_GRACE_SEC
                               and data['mtime'] < start_ts)
                if starting_up:
                    self._warn_once(f'starting:{data.get("mtime")}',
                                    f'生产服务 {int(start_age)}s 前刚启动，prod_runner 尚未写入首份状态'
                                    f'（状态文件最后更新 {mtime_str}）；界面暂按「启动中」显示')
                    for badge, label in ((self.hosting_backend_badge, '后端'),
                                         (self.hosting_frontend_badge, '前端'),
                                         (self.hosting_arq_badge, 'ARQ')):
                        _detail(badge, 'deploying', f'{label} 启动中')
                    _detail(self.hosting_ready_badge, 'deploying', '就绪 启动中')
                    return
                reason = (f"已 {int(time.time() - data['mtime'])}s 未更新，最后 {mtime_str}"
                          if stale else (read_err or '状态文件不可用'))
                self._warn_once(f'stale:{data.get("mtime")}',
                                f'状态文件不可信（{reason}），界面不再跟随服务状态；'
                                f'prod_runner 可能已退出，可在服务管理里重启 {_SVC_API}')
                for badge, label in ((self.hosting_backend_badge, '后端'),
                                     (self.hosting_frontend_badge, '前端'),
                                     (self.hosting_arq_badge, 'ARQ')):
                    _detail(badge, 'stopped', f'{label} 状态未知')
                _detail(self.hosting_ready_badge, 'stopped', f'就绪 无数据({mtime_str})')
                return
            self._hosting_last_warn = ''

            _svc_detail(self.hosting_backend_badge, '后端', svcs.get('backend'),
                        running=('ready',), starting=('running',))
            arq = svcs.get('arq') or {}
            if arq.get('status') == 'external':
                # ARQ 由独立 NSSM 服务托管：以 sc queryex 的真实 PID 为准。
                # ★ 但「服务在跑」不等于「ARQ 在干活」：broker 6380 不可达时 erp-arq
                # 进程仍是 RUNNING（Python 正在重试连接），徽章若只认 PID 就会
                # 把「死循环重启中」显示成「运行中」。broker 不健康时如实报异常。
                arq_pid = data.get('arq_svc_pid')
                if not arq_pid:
                    _detail(self.hosting_arq_badge, 'stopped', 'ARQ 未运行')
                elif not data.get('broker_ok', False):
                    _detail(self.hosting_arq_badge, 'error', f'ARQ 异常(broker 不可达)')
                else:
                    _detail(self.hosting_arq_badge, 'running', 'ARQ 运行中')
            else:
                _svc_detail(self.hosting_arq_badge, 'ARQ', arq, running=('running', 'ready'))
            # 前端:erp-web 为独立 NSSM 服务,status=external 时以服务状态为准,
            # prod_runner 的 frontend_ok 探针作交叉验证(探针区分 SPA fallback)。
            fe = svcs.get('frontend') or {}
            if fe.get('status') == 'external':
                web_state = self._svc_state(_SVC_WEB)
                if 'RUNNING' in web_state:
                    if status.get('frontend_ok'):
                        _detail(self.hosting_frontend_badge, 'running', '前端 运行中')
                    else:
                        _detail(self.hosting_frontend_badge, 'deploying', '前端 服务在跑但探针未过')
                elif 'STOPPED' in web_state:
                    _detail(self.hosting_frontend_badge, 'stopped', '前端 已停止')
                else:
                    _detail(self.hosting_frontend_badge, 'stopped', f'前端 {web_state}')
            else:
                _svc_detail(self.hosting_frontend_badge, '前端', svcs.get('frontend'),
                            running=('running', 'ready'))
            # 备份：采集阶段已从 /api/health 取到 backup 块（见 _collect_hosting_data）
            bk = data.get('backup') or {}
            if not bk:
                _detail(self.hosting_backup_badge, 'stopped', '备份 未上报')
            elif not bk.get('arq_ok', False):
                _detail(self.hosting_backup_badge, 'error', '备份 ARQ 掉线')
            elif bk.get('ok'):
                age = bk.get('age_hours')
                _detail(self.hosting_backup_badge, 'running',
                        f'备份 正常({age}h)' if age is not None else '备份 正常')
            else:
                age = bk.get('age_hours')
                _detail(self.hosting_backup_badge, 'error',
                        f'备份 陈旧({age}h)' if age is not None else '备份 无产物')
            redis_ok = data['redis_ok']
            broker_ok = data.get('broker_ok', False)
            if redis_ok and broker_ok:
                _detail(self.hosting_redis_badge, 'running', 'Redis 运行中')
            elif redis_ok:
                _detail(self.hosting_redis_badge, 'error', f'broker({_REDIS_BROKER_PORT}) 未运行')
            else:
                _detail(self.hosting_redis_badge, 'error', 'Redis 已停止')
            if status.get('ready'):
                # 「就绪」只在 ARQ 也健康时才算真的就绪，否则给一个可区分的文案
                if broker_ok:
                    _detail(self.hosting_ready_badge, 'running', '就绪 是')
                else:
                    _detail(self.hosting_ready_badge, 'error', '就绪 降级(broker 不可达)')
            elif ((svcs.get('backend') or {}).get('status') in ('failed', 'crashed')
                  or (svcs.get('frontend') or {}).get('status') in ('failed', 'crashed')):
                _detail(self.hosting_ready_badge, 'error', '就绪 启动失败')
            else:
                _detail(self.hosting_ready_badge, 'deploying', '就绪 启动中')
        finally:
            self._hosting_collecting = False
            self._update_mode_badge()
            # 收集期间有刷新请求 → 立即补一轮；否则按 5s 周期继续
            delay = 50 if self._hosting_refresh_requested else 5000
            self._hosting_refresh_requested = False
            self._after_ids['hosting'] = self.root.after(delay, self._refresh_hosting_status)

    def _svc_installed(self, name):
        """服务是否已注册到 SCM（供安装幂等判定使用）。

        与 `_svc_state` 的分工：这里只回答「在不在」，且**不把「查不出来」当成未安装**
        —— `sc query` 失败时返回 False，随后的 `nssm install` 会用自己的错误码报出
        真实原因（拒绝访问 / 找不到文件…），而不是被静默跳过。
        """
        code, out = self._run_capture(['sc', 'query', name], timeout=5)
        return code == 0 and 'SERVICE_NAME' in out

    @staticmethod
    def _looks_like_exists_error(out):
        """识别 nssm 的「服务已存在」失败（Windows 1073 ERROR_SERVICE_EXISTS）。

        兜底用：`sc query` 可能因权限/策略/瞬时故障查不到（此时 `_svc_installed`
        只能返回 False），此时只能靠 install 自己的错误文本判断，
        否则一个「重复注册」会被当成真失败，把整轮安装判死。
        """
        text = (out or '').lower()
        return any(marker in text for marker in ('已存在', 'already exists', '1073'))

    def _nssm_install(self, nssm, name, app, params, env_extra, depends=None):
        # Step 1: 创建服务（仅注册应用路径，不传参数，避免 NSSM 弹 GUI）
        #   已存在时**不能再 install**：CreateService 会以 1073「指定的服务已存在。」
        #   失败，整轮安装被判定为失败（2026-09-16 实测：erp-prod/erp-arq 早已注册，
        #   点『安装服务』必然报「注册失败」，且乱码后连原因都读不出来）。
        #   改为「跳过创建 + 覆盖配置」——「安装服务」可反复点击且结果幂等。
        existed = self._svc_installed(name)
        if existed:
            self.log_message(f'{name} 服务已存在，跳过创建，改为更新配置')
        else:
            code, out = self._run_capture([nssm, 'install', name, app], timeout=30)
            if code != 0:
                if self._looks_like_exists_error(out):
                    # 预判失败但服务其实在 → 同样按「已存在」处理，绝不因重复注册判死
                    existed = True
                    self.log_message(f'{name} 服务已存在（install 返回 1073），改为更新配置', 'WARNING')
                else:
                    self.log_message(f'{name} 注册失败: {out}', 'ERROR')
                    return False
        if existed and 'RUNNING' in self._svc_state(name):
            self.log_message(f'{name} 正在运行，配置变更将在下次启动生效（可点『重启』立即生效）', 'WARNING')
        # Step 2: 设置启动参数（NSSM AppParameters 接受空格分隔的完整命令行）
        if params:
            self._run_capture([nssm, 'set', name, 'AppParameters', ' '.join(params)], timeout=15)
        # Step 3: 设置其他属性
        #   Application 也一并写入：服务已存在时，这一步会把可执行文件路径纠正为当前值
        #   （换过 Python / 虚拟环境后，重新点『安装服务』即可修复指向）。
        settings = [
            ('Application', app),
            ('AppDirectory', str(_PROJECT_DIR)),
            ('AppStdout', str(_PROJECT_DIR / 'logs' / f'{name}.log')),
            ('AppStderr', str(_PROJECT_DIR / 'logs' / f'{name}.log')),
            ('AppRotateFiles', '1'),
            ('AppRotateBytes', '10485760'),
            ('AppExit', 'Default Restart'),
            ('AppRestartDelay', '5000'),
            ('Start', 'SERVICE_AUTO_START'),
            ('AppEnvironmentExtra', env_extra),
            ('AppNoConsole', '1'),
        ]
        for key, val in settings:
            code, out = self._run_capture([nssm, 'set', name, key, val], timeout=15)
            if code != 0:
                # 旧实现丢弃了全部返回码：某项没写进去也照样报「已注册」，无从判断。
                self.log_message(f'{name} 设置 {key} 失败: {out.strip() or f"退出码 {code}"}', 'WARNING')
        # Step 4: 依赖关系（开机由 SCM 串行保证启动顺序）
        #   只写已注册的依赖服务：依赖一个不存在的服务会让 SCM 直接拒绝启动本服务
        #   （错误 1068「依存服务或组无法启动」），比没有依赖更糟。
        self._apply_depends(name, depends)
        self.log_message(f'{name} {"已存在，配置已更新" if existed else "已注册为 Windows 服务"}（开机自启 + 崩溃自动重启）')
        return True

    def _apply_depends(self, name, depends):
        """设置服务的 SCM 依赖关系（DependOnService）。"""
        if not depends:
            return
        missing = [d for d in depends if not self._svc_installed(d)]
        if missing:
            self.log_message(
                f'{name} 跳过依赖设置：{", ".join(missing)} 服务不存在，'
                f'请先安装 Redis 服务（依赖不存在的服务会导致本服务无法启动）', 'WARNING')
            return
        nssm = self._find_nssm()
        if not nssm:
            return
        code, out = self._run_capture([nssm, 'set', name, 'DependOnService', ' '.join(depends)], timeout=15)
        if code != 0:
            # 旧版 NSSM 无该参数，回退直接写注册表（SCM 实际读取的位置）
            self._set_depends_registry(name, depends, out)
        else:
            self.log_message(f'{name} 依赖已设置: {", ".join(depends)}')

    def _set_depends_registry(self, name, depends, reason=''):
        """回退路径：直接写 HKLM\\SYSTEM\\...\\Services\\<name>\\DependOnService (REG_MULTI_SZ)。"""
        if not _IS_WINDOWS:
            return
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                rf'SYSTEM\CurrentControlSet\Services\{name}', 0, winreg.KEY_SET_VALUE)
            with key:
                winreg.SetValueEx(key, 'DependOnService', 0, winreg.REG_MULTI_SZ, list(depends))
            self.log_message(f'{name} 依赖已写入注册表: {", ".join(depends)}')
        except OSError as e:
            self.log_message(f'{name} 设置依赖失败（nssm: {reason.strip() or "非零退出"}）: {e}', 'WARNING')

    def _install_services(self):
        if self._mode not in ('none',):
            self.log_message('请先停止当前手动运行的服务，再安装 Windows 服务', 'WARNING')
            messagebox.showwarning('提示', '请先停止当前运行中的服务（开发/手动生产/调试），再安装 Windows 服务。')
            return
        nssm = self._find_nssm()
        if not nssm:
            self.log_message('未找到 NSSM，请下载 https://nssm.cc 解压到 C:\\nssm\\nssm.exe', 'ERROR')
            messagebox.showerror('缺少 NSSM', '未找到 NSSM。\n请从 https://nssm.cc/download 下载并解压到 C:\\nssm\\nssm.exe。')
            return
        if not _PYTHON_EXE:
            messagebox.showerror('缺少 Python', '未找到 Python 解释器，无法安装服务。')
            return
        workers = self.hosting_workers_var.get().strip() or '4'
        self._gate.start('安装生产服务', self._install_services_flow, nssm, workers)

    def _install_services_flow(self, nssm, workers):
        env_extra = ('APP_ENV=production FASTAPI_DEBUG=false PYTHONPATH=' + str(_PROJECT_DIR) +
                     ' PYTHONUTF8=1 PYTHONUNBUFFERED=1 UVICORN_WORKERS=' + workers)
        self._msg_queue.put(('log', {'text': f'正在安装生产服务 (worker={workers})...'}))
        # erp-prod 监督器 --no-arq：ARQ 由独立 erp-arq 服务托管，避免双跑定时任务
        self._gate.checkpoint()
        ok1 = self._nssm_install(nssm, _SVC_API, _PYTHON_EXE,
                                 ['-m', 'fastapi_app.core.prod_runner', '--no-arq'],
                                 env_extra, depends=_SVC_DEPENDS.get(_SVC_API))
        self._gate.checkpoint()
        ok2 = self._nssm_install(nssm, _SVC_ARQ, _PYTHON_EXE,
                                 ['-m', 'arq', 'fastapi_app.core.arq_app.WorkerSettings'],
                                 env_extra, depends=_SVC_DEPENDS.get(_SVC_ARQ))
        self._gate.checkpoint()
        # erp-web:nginx 静态服务,无 Python/env,无依赖(反代上游未起只 502)
        _nginx_exe = r'C:\nginx\nginx.exe'
        if Path(_nginx_exe).is_file():
            ok3 = self._nssm_install(nssm, _SVC_WEB, _nginx_exe,
                                     ['-p', str(_PROJECT_DIR),
                                      '-c', str(_PROJECT_DIR / 'config' / 'nginx-windows.conf'),
                                      '-e', str(_PROJECT_DIR / 'logs' / 'nginx-error.log')],
                                     '', depends=None)
        else:
            ok3 = False
            self._msg_queue.put(('log', {'text': f'未找到 {_nginx_exe}，{_SVC_WEB} 未安装（前端仍可由旧方式托管）', 'level': 'WARNING'}))
        if ok1 and ok2 and ok3:
            self._msg_queue.put(('log', {'text': '生产服务安装完成：erp-prod + erp-arq + erp-web（开机自启、按依赖顺序启动）'}))
        else:
            self._msg_queue.put(('log', {'text': '生产服务安装未完全成功，请查看上方日志', 'level': 'WARNING'}))
        self._msg_queue.put(('hosting_refresh', {}))

    def _service_cmd_sync(self, verb):
        """停止/重启生产服务：逐服务执行 + 轮询确认终态。

        NSSM 的 stop/restart 都是立即返回——不等终态就报「已执行」等于什么都没说
        （2026-09-16 用户实测：stop 打印完 5 秒后服务仍在 RUNNING）。
        """
        nssm = self._find_nssm()
        if verb == 'restart':
            # 重启同样会换掉 prod_runner 进程：旧快照在它写下第一份新快照前必然陈旧，
            # 与「启动服务」共用同一条宽限判据（否则重启后也会弹「可能已退出」）。
            self._prod_start_ts = time.time()
        for name in (_SVC_API, _SVC_ARQ, _SVC_WEB):
            self._gate.checkpoint()
            if verb == 'stop':
                self._msg_queue.put(('log', {'text': f'正在停止生产服务 {name}...'}))
                if self._wait_service_stopped(name, timeout=45):
                    self._msg_queue.put(('log', {'text': f'{name} 已停止 (state={self._svc_state(name)})'}))
                else:
                    self._msg_queue.put(('log', {'text': f'{name} 在 45s 内未确认 STOPPED（当前: {self._svc_state(name)}），请到服务管理器检查', 'level': 'WARNING'}))
            elif verb == 'restart':
                self._msg_queue.put(('log', {'text': f'正在重启生产服务 {name}...'}))
                if nssm:
                    self._run_capture([nssm, 'restart', name], timeout=30)
                else:
                    # sc 无 restart：先停后起，终态以轮询为准
                    self._run_capture(['sc', 'stop', name], timeout=30)
                    self._run_capture(['sc', 'start', name], timeout=30)
                self._wait_service_running(name, timeout=25)
        self._msg_queue.put(('hosting_refresh', {}))

    def _service_cmd(self, verb):
        self._gate.start(f'服务{verb}', self._service_cmd_sync, verb)

    def _start_services(self):
        # 互斥守卫：开发模式正在启动/重启中则拒绝（防 TOCTOU 双后端抢 5002）
        if self._mode in ('starting', 'restarting'):
            self.log_message('开发模式正在启动中，请稍候', 'WARNING')
            return
        self._gate.start('启动生产服务', self._start_services_flow)

    def _start_services_flow(self):
        # 互斥切换：停开发模式 + 清端口（含进程树终止等阻塞操作，在动作线程内完成）
        # ★ 日志对齐开发模式：原实现只有两行「erp-prod start 已执行」——NSSM start
        #   立即返回，不等待 RUNNING、不回灌服务日志，界面上一片安静像没反应。
        self._msg_queue.put(('log', {'text': '正在启动生产模式 (Windows 服务 NSSM)...'}))
        # 记下启动时刻：此后直到 prod_runner 写下第一份快照前，状态文件都还是上一轮的
        # 旧快照，界面必须按「启动中」对待，不能报「prod_runner 可能已退出」。
        self._prod_start_ts = time.time()
        if self._ensure_development_stopped():
            self._msg_queue.put(('log', {'text': '已自动停止开发模式', 'level': 'INFO'}))
        self._gate.checkpoint()
        self._msg_queue.put(('log', {'text': '正在清理端口...'}))
        self._release_ports()
        # Redis 基础设施工况：缓存实例直接拉起（走服务），broker 必须在 erp-arq
        # 之前就绪——否则 erp-arq 连不上 6380 会陷入重启循环，而界面依旧全绿。
        if not self._start_redis():
            self._msg_queue.put(('log', {'text': '警告: Redis 未启动，部分功能可能不可用', 'level': 'WARNING'}))
        self._gate.checkpoint()
        broker_ok = self._ensure_redis_broker()
        # NSSM 日志是追加写：先记下两个日志文件的当前大小，之后只回灌「本次启动
        # 之后新增的字节」——直接取文件尾会把上几次运行的旧输出（旧 PID、旧崩溃栈）
        # 当现状展示（2026-09-16 实机启动踩过）。
        offsets = {name: self._log_size(_PROJECT_DIR / 'logs' / f'{name}.log')
                   for name in (_SVC_API, _SVC_ARQ, _SVC_WEB)}
        ok_api, api_state, api_pid = self._start_one_service(_SVC_API)
        if not broker_ok:
            # broker 未就绪时 erp-arq 起不来；仍尝试一次（让日志自己说话），
            # 但最终结论必须按失败上报，不能再用「启动完成」把它盖过去。
            self._msg_queue.put(('log', {'text': f'ARQ broker 未就绪，{_SVC_ARQ} 预计无法工作', 'level': 'ERROR'}))
        ok_arq, arq_state, arq_pid = self._start_one_service(_SVC_ARQ)
        if ok_arq and not broker_ok:
            ok_arq = False
        # erp-web(nginx):与后端解耦,独立启动;失败只降级前端,不判整体失败
        ok_web, web_state, web_pid = self._start_one_service(_SVC_WEB)
        if not ok_web:
            self._msg_queue.put(('log', {'text': f'{_SVC_WEB} 启动未确认(当前: {web_state})，前端静态服务可能不可用', 'level': 'WARNING'}))
        # 服务 stdout/stderr 由 NSSM 重定向到 logs\{name}.log —— 回灌本次新增输出，
        # 对齐开发模式里 Redis/uvicorn 的实时输出。
        self._gate.checkpoint()
        for name in (_SVC_API, _SVC_ARQ, _SVC_WEB):
            fresh = self._read_log_lines(_PROJECT_DIR / 'logs' / f'{name}.log',
                                         start_offset=offsets[name], lines=30)
            if fresh:
                self._msg_queue.put(('log_batch', {'lines': [f'[{name}] {ln}' for ln in fresh], 'level': 'INFO'}))
            else:
                self._msg_queue.put(('log', {'text': f'[{name}] 本次启动暂无新日志（历史见 logs 下的 {name}.log）'}))
        if ok_api and ok_arq:
            self._msg_queue.put(('log', {'text': f'生产模式启动完成 → {_SVC_API}: {api_state} (PID: {api_pid}), '
                                         f'{_SVC_ARQ}: {arq_state} (PID: {arq_pid})'}))
        else:
            hint = (f'；{_SVC_ARQ} 因 ARQ broker(6380) 未就绪而不可用，'
                    f'请检查 {_SVC_REDIS_BROKER} 服务') if not broker_ok else ''
            self._msg_queue.put(('log', {'text': f'生产模式启动未完全成功{hint}，请查看上方日志与 logs 目录下的服务日志', 'level': 'WARNING'}))
        self._msg_queue.put(('hosting_refresh', {}))

    @staticmethod
    def _log_size(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    @staticmethod
    def _read_log_lines(path, start_offset=0, lines=15, max_bytes=65536):
        """读取日志文件自 start_offset 起新增内容的末尾 lines 行（有界读取）。

        NSSM 的 stdout/stderr 重定向是追加写：start 之前先记下文件大小，之后把
        「新增字节」的尾部回灌界面才是本次运行的输出；文件被轮转重开（大小小于
        offset）时按全新文件处理。历史日志绝不回灌。
        """
        try:
            with open(path, 'rb') as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                if start_offset > size:
                    # 文件被轮转重开（当前大小小于记录的 offset）：按全新文件处理
                    begin = max(0, size - max_bytes)
                else:
                    begin = max(start_offset, size - max_bytes, 0)
                f.seek(begin)
                raw = f.read().splitlines()
            return [ln.decode('utf-8', 'replace').strip() for ln in raw[-lines:] if ln.strip()]
        except OSError:
            return []

    def _wait_service_running(self, name, timeout=25):
        """轮询直到服务 RUNNING；返回 (ok, state, pid)，成功/超时都写日志。

        NSSM start/restart 立即返回，服务要经 START_PENDING 才到 RUNNING——
        不轮询就报「已执行」等于什么都没说。超时仍未 RUNNING 如实告警并指路日志文件。
        """
        deadline = time.monotonic() + timeout
        state = self._svc_state(name)
        while time.monotonic() < deadline:
            self._gate.checkpoint()
            state = self._svc_state(name)
            if 'RUNNING' in state.upper():
                pid = self._svc_pid(name)
                self._msg_queue.put(('log', {'text': f'{name} 启动成功 (state={state}, PID: {pid if pid is not None else "?"})'}))
                return True, state, pid
            time.sleep(1)
        self._msg_queue.put(('log', {'text': f'{name} 在 {timeout}s 内未进入 RUNNING（当前: {state}），请查看 logs\\{name}.log', 'level': 'WARNING'}))
        return False, state, None

    def _start_one_service(self, name, timeout=25):
        """发出启动命令并轮询确认 RUNNING；返回 (ok, state, pid)。"""
        nssm = self._find_nssm()
        self._msg_queue.put(('log', {'text': f'正在启动生产服务 {name}...'}))
        if nssm:
            code, out = self._run_capture([nssm, 'start', name], timeout=20)
        else:
            code, out = self._run_capture(['sc', 'start', name], timeout=20)
        if code != 0:
            out_l = (out or '').lower()
            if '1056' in out or 'already' in out_l:
                self._msg_queue.put(('log', {'text': f'{name} 已在运行中，跳过 start'}))
            elif '1053' not in out:
                # 1053/超时类错误不代表失败（服务可能仍在启动中），以轮询结果为准
                self._msg_queue.put(('log', {'text': f'{name} start 返回非零 (code={code}): {(out or "").strip()[:160]}', 'level': 'WARNING'}))
        return self._wait_service_running(name, timeout=timeout)

    def _stop_services(self):
        self._service_cmd('stop')

    def _restart_services(self):
        self._service_cmd('restart')

    def _uninstall_services(self):
        nssm = self._find_nssm()
        if not nssm:
            messagebox.showerror('缺少 NSSM', '未找到 NSSM，无法卸载服务。')
            return
        self._gate.start('卸载生产服务', self._uninstall_services_flow, nssm)

    def _uninstall_services_flow(self, nssm):
        for name in (_SVC_API, _SVC_ARQ, _SVC_WEB):
            self._gate.checkpoint()
            self._run_capture([nssm, 'stop', name], timeout=30)
            self._gate.checkpoint()
            code, out = self._run_capture([nssm, 'remove', name, 'confirm'], timeout=30)
            if code == 0:
                self._msg_queue.put(('log', {'text': f'{name} 已卸载'}))
            else:
                self._msg_queue.put(('log', {'text': f'{name} 卸载失败: {out}', 'level': 'WARNING'}))
        self._msg_queue.put(('hosting_refresh', {}))

    def _open_logs_dir(self):
        log_dir = _PROJECT_DIR / 'logs'
        log_dir.mkdir(exist_ok=True)
        try:
            os.startfile(str(log_dir))
        except Exception as e:
            self.log_message(f'打开日志目录失败: {e}', 'ERROR')

    def _build_log_section(self, parent):
        log_card = tk.Frame(parent, bg=self._PALETTE['bg_card'], highlightbackground=self._PALETTE['border_card'], highlightthickness=1)
        log_card.grid(row=1, column=0, columnspan=2, sticky='nsew', pady=(10, 0))
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(1, weight=1)
        log_hdr = tk.Frame(log_card, bg=self._PALETTE['bg_card'])
        log_hdr.grid(row=0, column=0, sticky='ew', padx=20, pady=(12, 0))
        tk.Label(log_hdr, text='运行日志', font=('Microsoft YaHei UI', 11, 'bold'), fg=self._PALETTE['text_primary'], bg=self._PALETTE['bg_card']).pack(side=tk.LEFT)
        tk.Label(log_hdr, text='实时输出', font=('Microsoft YaHei UI', 8), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_card']).pack(side=tk.LEFT, padx=(8, 0))
        log_btns = tk.Frame(log_hdr, bg=self._PALETTE['bg_card'])
        log_btns.pack(side=tk.RIGHT)
        for txt, cmd in [('导出', self.export_log), ('清空', self.clear_log)]:
            pill = tk.Frame(log_btns, bg=self._PALETTE['bg_card'], cursor='hand2', highlightbackground=self._PALETTE['border'], highlightthickness=1)
            pill.pack(side=tk.RIGHT, padx=(4, 0))
            tk.Label(pill, text=txt, font=('Microsoft YaHei UI', 8), fg=self._PALETTE['text_secondary'], bg=self._PALETTE['bg_card'], padx=12, pady=3, cursor='hand2').pack()
            for w in (pill, pill.winfo_children()[0]):
                w.bind('<Button-1>', lambda e, c=cmd: c())
                w.bind('<Enter>', lambda e, p=pill: p.config(bg=self._PALETTE['bg_input']))
                w.bind('<Leave>', lambda e, p=pill: p.config(bg=self._PALETTE['bg_card']))
                w.bind('<Enter>', lambda e, l=pill.winfo_children()[0]: l.config(bg=self._PALETTE['bg_input']), add='+')
                w.bind('<Leave>', lambda e, l=pill.winfo_children()[0]: l.config(bg=self._PALETTE['bg_card']), add='+')
        log_body = tk.Frame(log_card, bg=self._PALETTE['bg_input'], highlightbackground=self._PALETTE['border'], highlightthickness=1)
        log_body.grid(row=1, column=0, sticky='nsew', padx=14, pady=(8, 14))
        log_body.columnconfigure(0, weight=1)
        log_body.rowconfigure(0, weight=1)
        log_font = self._pick_log_font()
        self.log_text = tk.Text(log_body, bg=self._PALETTE['bg_log'], fg=self._PALETTE['log_fg'], insertbackground=self._PALETTE['log_fg'], selectbackground=self._PALETTE['bg_input'], font=log_font, wrap=tk.WORD, state=tk.DISABLED, relief=tk.FLAT, padx=14, pady=10, cursor='arrow')
        self.log_text.grid(row=0, column=0, sticky='nsew')
        self.log_text.tag_configure('INFO', foreground=self._PALETTE['log_info'])
        self.log_text.tag_configure('ERROR', foreground=self._PALETTE['log_error'])
        self.log_text.tag_configure('WARNING', foreground=self._PALETTE['log_warn'])
        sb = ttk.Scrollbar(log_body, command=self.log_text.yview)
        sb.grid(row=0, column=1, sticky='ns')
        self.log_text.config(yscrollcommand=sb.set)

    def _build_status_bar(self):
        bar = tk.Frame(self.root, bg=self._PALETTE['bg_surface'], highlightbackground=self._PALETTE['border'], highlightthickness=1)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        left = tk.Frame(bar, bg=self._PALETTE['bg_surface'])
        left.pack(side=tk.LEFT, padx=20, pady=5)
        # 运行模式徽章：一眼识别当前是开发模式 / 生产模式 / 未运行（大厂 Status Tag 风格）
        self._mode_badge = StatusBadge(left, state='stopped', text='未运行', size='lg', palette=self._PALETTE, canvas_bg=self._PALETTE['bg_surface'])
        self._mode_badge.pack(side=tk.LEFT, padx=(0, 10))
        self.status_bar_label = tk.Label(left, text='就绪', font=('Microsoft YaHei UI', 9), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_surface'])
        self.status_bar_label.pack(side=tk.LEFT)
        right = tk.Frame(bar, bg=self._PALETTE['bg_surface'])
        right.pack(side=tk.RIGHT, padx=20, pady=5)
        # 紧急停止（危险浅底）：强杀全部进程并释放端口
        self.stop_all_btn = RoundedButton(right, text='紧急停止', variant='subtle', tone='danger', command=self.stop_all, canvas_bg=self._PALETTE['bg_surface'], pady=2, radius=8, font=('Microsoft YaHei UI', 8, 'bold'))
        self.stop_all_btn.pack(side=tk.RIGHT, padx=(10, 0))

    def _update_mode_badge(self):
        """更新运行模式徽章：未运行 / 开发模式 / 生产模式（含过渡态）。"""
        try:
            mode = self._mode
            if mode == 'starting':
                self._mode_badge.set_state('deploying', f'开发模式 · {self._mode_label()}')
            elif mode in ('restarting', 'stopping'):
                self._mode_badge.set_state('restarting', f'开发模式 · {self._mode_label()}')
            elif mode == 'dual_dev':
                self._mode_badge.set_state('running', '开发模式')
            elif getattr(self, '_prod_running', False):
                # 生产模式用品牌蓝，与开发模式(绿)区分，体现环境语义
                self._mode_badge.set_state('running', '生产模式', color_key='accent', tint_key='accent_tint')
            elif getattr(self, '_prod_unknown', False):
                # ★ 三态语义贯通：生产状态「未知」不得显示「未运行」——否则误导现场
                # 判断生产是否在跑（sc query 查不出来 ≠ 服务已停止）。
                self._mode_badge.set_state('unknown', '生产模式 · 状态未知')
            else:
                self._mode_badge.set_state('stopped', '未运行')
        except Exception:
            pass


def main():
    if not _ensure_single_instance():
        _activate_existing_window()
        sys.exit(0)
    try:
        root = tk.Tk()
        ServerManagerApp(root)
        root.mainloop()
    except Exception as e:
        import traceback
        tb_text = traceback.format_exc()
        log_dir = Path(_PROJECT_DIR) / 'logs'
        crash_file = None
        try:
            log_dir.mkdir(exist_ok=True)
            crash_file = log_dir / f'server_manager_crash_{datetime.now():%Y%m%d_%H%M%S}.log'
            crash_file.write_text(f"[CRASH] {datetime.now()}\n{tb_text}", encoding='utf-8')
        except Exception:
            pass
        with contextlib.suppress(Exception):
            messagebox.showerror("启动失败", f"服务器管理器启动失败:\n{str(e)}" + (f"\n\n日志: {crash_file}" if crash_file else ""))
        sys.exit(1)


if __name__ == '__main__':
    main()
