"""
ERP 服务器管理器 GUI（版本号唯一真源见 server_manager.constants 的 _VERSION，当前 v5.40）
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
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from server_manager import git_guard, log_ops, windows_ops
from server_manager.action_gate import _EMERGENCY_JOIN_SEC, ActionGate
from server_manager.constants import (
    _API_PORT,
    _IS_WINDOWS,
    _REDIS_PORT,
    _SVC_API,
    _SVC_ARQ,
    _SVC_DEPENDS,
    _SVC_REDIS_BROKER,
    _SVC_UVICORN_WORKERS,
    _SVC_WEB,
    _VERSION,
    _WEB_PORT,
    _WINDOW_TITLE,
)
from server_manager.dev_mode import DevModeOps
from server_manager.hosting_view import HostingViewMixin
from server_manager.log_view import LogViewMixin
from server_manager.redis_ops import RedisOps
from server_manager.service_ops import ServiceOps
from server_manager.widgets import RoundedButton, StatusBadge

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
    return Path(__file__).resolve().parents[1]

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

def _create_tray_icon_image():
    try:
        from PIL import Image, ImageDraw
        img = Image.new('RGBA', (16, 16), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse([2, 2, 14, 14], fill=(108, 142, 255, 255))
        return img
    except Exception:
        return None

class ServerManagerApp(HostingViewMixin, LogViewMixin):
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
    # 运行日志面板相关的常量(缓冲上限/刷新与裁剪周期/生产日志回灌/文件清理周期)
    # 归 LogViewMixin(T8 抽出,见 server_manager/log_view.py)；本类经继承可见。
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
    # T7:hosting 视图层已抽到 server_manager/hosting_view.py(HostingViewMixin)。
    # 该层采集阶段要拼状态文件路径,需要项目根;它按 mixin 共享 self,故在此把本模块
    # 全局 _PROJECT_DIR 再暴露一份类属性供 self._PROJECT_DIR 读取(同一个 Path 对象)。
    # 注意:方法体内的**裸** _PROJECT_DIR 仍解析到模块全局(类属性不参与 LOAD_GLOBAL),
    # 故此处不影响本文件既有的其它引用点。
    _PROJECT_DIR = _PROJECT_DIR

    def __init__(self, root):
        self.root = root
        self.root.title(_WINDOW_TITLE)
        self.root.geometry("1080x760")
        self.root.minsize(960, 680)
        self.root.resizable(True, True)
        self.root.withdraw()
        # 注：redis_process 已归 RedisOps 自持(见下方 self.redis)，此处不再赋值。
        # 注：开发模式状态(mode/process/frontend_process/current_mode_key/startup_*)
        # 已归 DevModeOps 自持(见下方 self.dev)，一律经属性桥读写，此处不再赋值。
        self._init_log_view()
        self._msg_queue = queue.Queue()
        self._server_cards = []
        self._prod_running = False
        self._prod_unknown = False      # 生产服务状态「未知」(sc query 失败) —— 仅供展示层，勿与 _prod_running 混用
        self._hosting_collecting, self._hosting_refresh_requested = False, False
        self._hosting_collect_started, self._hosting_last_warn = 0.0, ''
        # 紧急停止进行中：清扫窗口内滞留的采集结果不得翻改 _prod_running、
        # 操作按钮保持置灰，由 stop_all 完成消息复位（M1/M3）。
        self._stopping_all = False
        # 最近一次「启动/重启生产服务」的时刻（0 表示本次会话还没启动过）。
        # 用于区分「刚启动、首份快照还没落盘」与「跑着跑着 prod_runner 掉了」。
        self._prod_start_ts = 0.0
        # 动作闸门（单一持有者 / 自动释放 / 可协作取消）+ 需置灰的操作按钮集合。
        # 闸门事件回调只往消息队列投递，绝不直接操作 Tk（回调在 worker 线程执行）。
        self._gate = ActionGate(on_event=self._on_gate_event)
        # 服务操作层(T4 包化)：NSSM/sc 查询、启停、安装、卸载。msg_queue/gate/
        # project_dir/log_message 一律注入;本模块不 import app,也不持有 app 状态
        # (nssm 搜索由 ServiceOps.find_nssm 自行完成,无外部注入)。
        self.svc = ServiceOps(self._msg_queue, self._gate, _PROJECT_DIR, self.log_message,
                              release_ports=self._release_ports)
        # Redis 探活/启停层(T3 包化)：RedisOps 自持 redis_process；服务层能力
        # (wait_service/svc_state/find_nssm/run_capture,T4 起归 service_ops)
        # 与 app 的 _read_stdout 一律注入,本类不 import app。
        self.redis = RedisOps(self._msg_queue, self._gate, _PROJECT_DIR,
                              wait_service=self.svc.wait_service, svc_state=self.svc.svc_state,
                              find_nssm=self.svc.find_nssm, run_capture=self.svc.run_capture,
                              read_stdout=self._read_stdout)
        # 开发模式层(T5 包化)：双进程(uvicorn + vite)的启停/重启 + 状态自持。
        # svc/redis 直接注入实例(兄弟 ops，不再包回调)；python_exe/frontend_dir 取
        # app 模块级值，release_ports 注入 app 的端口清理(它同时被不搬的生产路径
        # _start_services_flow 调用，故实现保留在 app)。
        self.dev = DevModeOps(self._msg_queue, self._gate, _PROJECT_DIR, self.svc, self.redis,
                              python_exe=_PYTHON_EXE, frontend_dir=_FRONTEND_DIR,
                              release_ports=self._release_ports)
        self._action_buttons = []
        self.setup_logging()
        self._build_ui()
        self._set_window_icon()
        self._center_window()
        self.root.deiconify()
        # 装饰动画已裁剪（2026-10-15 审计）：本机核显低配（i5-10400），
        # fade-in 11 帧 + 卡片脉冲 11 帧 × N 卡合计 ~24 次 after 重绘只拖慢首帧。
        self._check_interval, self._after_ids = 5000, {}
        self._run_env_checks()
        self.check_server_status()
        self._refresh_hosting_status()
        self._schedule_log_cleanup()
        self._schedule_log_file_cleanup()
        self._schedule_log_health()
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
            # deiconify 已完成，直接弹（原先 after(500) 与首帧 fade-in 叠加，告警被动画盖）
            messagebox.showwarning("环境检查警告", "\n\n".join(errors))
            for err in errors:
                self.log_message(err, 'ERROR')

    # ── Redis 探活/启停转发(T3 包化:实现已迁 server_manager/redis_ops.py) ──────
    # 保留同名瘦转发,既有调用点与静态断言不必改写。
    # （2026-10-15 审计：_get_env_value/_redis_ping/_redis_service_state/
    #   _start_redis_via_service/_start_redis_process/_find_redis 六个转发
    #   全仓 0 调用点，注释所称「静态断言」实测不存在 —— 已删。）

    def _is_redis_running(self):
        return self.redis.is_redis_running()

    def _is_broker_running(self):
        return self.redis.is_broker_running()

    def _ensure_redis_broker(self):
        return self.redis.ensure_redis_broker()

    def _start_redis(self):
        return self.redis.start_redis()

    def _stop_redis(self):
        return self.redis.stop_redis()

    # _fade_in / _animate_cards_intro / _pulse_card_border 为 v5.33 的装饰动画，
    # 已于 2026-10-15 从启动序列整体移除（低配机首帧拖累）。

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
        # ★ 同步终止开发进程（不经闸门、不依赖守护线程）：
        #   ① 旧实现走 _stop_process → gate.start 起的是守护线程，主线程随即
        #     root.destroy() → 解释器关闭 → 守护 worker 连同其中的 taskkill 一起
        #     被掐断，连后端都可能杀不完（竞态）。
        #   ② 旧实现只杀 self._process（后端），从不碰 _frontend_process —— 开发
        #     模式运行中退出会让 vite dev server 残留在 :3000（进程孤儿）。
        #   ③ 退出瞬间若有动作在飞，gate.start 会直接被拒（拒绝消息投进再也无人
        #     消费的队列），后端 + 前端 + 直接拉起的 Redis 全部孤儿。
        #   terminate_dev_processes 同步杀前后端两棵进程树（各至多等 5s），确定性
        #   换时间。同理同步收掉直接拉起的 Redis（服务托管的实例不归本进程管）。
        # ★ 先取消在飞行动作再杀（与 stop_all 同款两步）：若「启动开发模式」worker
        #   正卡在健康轮询里，不取消的话它会继续 Popen vite/uvicorn，解释器退出把
        #   守护 worker 掐断后，刚拉起的进程照样孤儿 —— 注释 ③ 竞态的另一半。
        #   wait_idle 上限取紧急停止同款 8s：到点未退就放弃等待继续杀（反正后面
        #   的进程树终止会兜住已拉起的部分）。
        self._gate.cancel('退出')
        self._gate.wait_idle(_EMERGENCY_JOIN_SEC)
        self._terminate_dev_processes('退出')
        self._stop_redis()
        self._mode = 'none'
        # 退出前收掉日志轮询线程：它是守护线程，但显式停能保证 join 后再销毁 Tk，
        # 不会出现「窗口没了、线程还在往已关闭的队列投消息」。
        self.prod_logs.stop()
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

    # 注：日志面板与日志运维(log_message / _build_log_section / 文件定时清理 /
    # 生产日志实时回灌)已整体抽到 LogViewMixin(T8，见 server_manager/log_view.py)，
    # 本类经继承使用；此处不再保留瘦转发。
    # 注：旧 _stop_process/_stop_process_flow（只杀后端、经守护线程、退出路径竞态）
    # 已随 2026-10-15 退出路径修复删除 —— 退出统一走 _terminate_dev_processes +
    # _stop_redis（见 _do_quit），开发停止走 dev.stop_dual_flow。

    def _kill_port_sync(self, port, exclude=None, managed_pids_fn=None):
        return windows_ops.kill_port_sync(port, exclude, managed_pids_fn)

    def _find_port_pids(self, port, exclude=None):
        return windows_ops.find_port_pids(port, exclude)


    def _read_stdout(self, proc):
        return self.dev.read_stdout(proc)

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
                elif msg_type == 'log_health':
                    # 巡检线程只投递结果，面板渲染与告警归口主线程（同 hosting_apply 的范式）
                    self._apply_log_health(data['report'])
                elif msg_type == 'log_flush':
                    # worker 线程直调 log_message 后经队列回主线程 flush（M4：
                    # 跨线程 after_idle 是间歇崩溃来源；此分支是唯一的 flush 触发器）
                    self._do_flush()
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
                    # 动作被取消/异常中止 → 清掉过渡态，避免 UI 卡在「启动中/重启中」。
                    # ★ 但不得越权复位「全停中」的过渡态：紧急停止打断一个在飞动作时，
                    #   被取消的 worker 退出时【必然】投 op_aborted，而此时清扫仍在后台跑
                    #   （5 服务各至多 45s + 端口 3 轮重试，数十秒）。若这里把
                    #   _mode 从 'stopping' 复位成 'none'，按钮立即恢复可点，用户点
                    #   「启动」会与清扫线程的 _kill_port_sync/nssm start 并发互踩。
                    #   清扫期间的过渡态只允许 stop_all_done 复位。
                    if not self._stopping_all and self._mode in ('starting', 'restarting', 'stopping'):
                        self._mode, self._current_mode_key = 'none', ''
                    self._update_all_ui()
                elif msg_type == 'stop_all_done':
                    # 紧急停止清扫完成 → 复位「全停中」与过渡态、放开按钮
                    self._stopping_all = False
                    if self._mode == 'stopping':
                        self._mode, self._current_mode_key = 'none', ''
                    self._set_actions_enabled(True)
                    self._update_all_ui()
                    # 全停窗口内丢弃过的采集结果在此补一轮（立即恢复真实状态显示）
                    self._refresh_hosting_status()
            except Exception:
                # 单条消息处理失败不能中断 poll 调度链，否则日志/状态更新全部停摆
                pass
            processed += 1
        # ★ 每轮 poll 结束时无条件 flush 一次（_do_flush 幂等且便宜）。
        # 只靠 'log_flush' 消息不够：worker 每秒可直调 log_message 数十次，
        # 会投出大量空 payload 的 log_flush，挤占上面 processed < 30 的配额，
        # 把真正的 log / log_batch 推到下一轮（200ms 后）——崩溃循环刷日志时
        # 运行面板的「最新输出」会明显滞后于实际日志，排障时看到的是假最新。
        self._do_flush()

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


    def start_dual_dev(self):
        self._start_dual_server('开发模式（前后端）')


    def stop_dual_dev(self):
        self._stop_dual_mode_async('开发模式')


    def stop_all(self):
        # 紧急停止：不经闸门（它的职责就是打断正在进行的动作），但要先协作式取消：
        # 否则在飞行中的启动流程会在“停止”之后继续把 Redis / 后端拉起来（审计实测）。
        self._gate.cancel('紧急停止')

        # 先在主线程立即重置状态（双重保险）
        # ★ 不直接置 'none'：清扫可持续数十秒（5 服务各至多 45s + 端口 3 轮重试），
        #   mode=none 会让开发卡/生产卡立刻回到「已停止、启动可点」—— 清扫窗口内
        #   点启动，gate.start 会把上面的取消标志 clear 掉，与清扫并发互踩。
        #   置 'stopping'（徽章显示「停止中」、_update_card_ui 全部置灰按钮），
        #   由清扫完成的 ui_update 消息收尾时经 _apply_hosting_data / op 事件复位。
        self._mode = 'stopping'
        self._current_mode_key = ""
        self._prod_running = False
        # ★ M1/M3：清扫期间停用全部操作按钮 + 置「全停中」标志（滞留的采集结果
        #   不得把 _prod_running 翻回 True / 重新点亮生产按钮）。
        self._stopping_all = True
        self._set_actions_enabled(False)
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
                _, managed_pids, srvc_failed = self._stop_managed_services()
                # 服务已停：实时回灌线程随之收工（否则旧日志会继续往面板里刷）
                self.prod_logs.stop()
                # 强制停止所有进程，不管状态
                self._terminate_dev_processes()

                self._stop_redis()
                self._kill_residual_async()
                # 端口清理时排除受管 PID：即使 nssm stop 超时失败，也绝不误杀受管进程触发自动重启。
                # ★ 同时传 managed_pids_fn：受管集合「不可知」（sc 通道故障）时由
                #   kill_port_sync 自行探测并 fail-safe 返回 'managed_unknown'，
                #   绝不按空集排除后照杀（那正是「紧急停止变成重启」的 fail-open 路径）。
                # ★ 每个端口的返回值都必须消费：'managed_unknown' = 已放弃清理、端口仍被占用，
                #   必须告警而不是假装清干净了。
                unresolved = []          # 未能确认清理干净的端口
                for port in (_API_PORT, _WEB_PORT, _REDIS_PORT):
                    try:
                        state = self._kill_port_sync(port, exclude=managed_pids,
                                                     managed_pids_fn=self._managed_service_pids)
                    except Exception as e:
                        self._msg_queue.put(('log', {'text': f'端口 {port} 清理异常: {e}', 'level': 'WARNING'}))
                        unresolved.append(port)
                        continue
                    if state == 'managed_unknown':
                        self._msg_queue.put(('log', {
                            'text': f'端口 {port} 未能清理：无法确认 NSSM 受管进程集合'
                                    f'（服务查询失败），已放弃清理以免误杀生产服务。',
                            'level': 'WARNING',
                        }))
                        unresolved.append(port)
                    elif state == 'all_exempted' and srvc_failed:
                        # 端口仍被受管进程占用。若 nssm stop 全部确认成功，该占用会随服务
                        # 退出而消失（属正常过渡）；仅在服务停止也失败时才算真正未落地。
                        unresolved.append(port)
                # ★ 汇总语必须与上面的告警**一致**：原实现在三个端口循环后**无条件**输出
                #   「已清理所有残留进程和端口」，于是当 managed_unknown（端口实际仍被占用）时，
                #   汇总语与紧邻的 WARNING 互相矛盾 —— 日志说「未能清理」，总结说「已清理」。
                if unresolved:
                    self._msg_queue.put(('log', {
                        'text': f'部分端口未能清理（{"、".join(str(p) for p in unresolved)}），'
                                f'详见上方告警。请稍后重试，或用「停止服务」后再启动。',
                        'level': 'WARNING',
                    }))
                elif srvc_failed:
                    self._msg_queue.put(('log', {
                        'text': f'端口已清理，但服务停止未全部成功（{"、".join(srvc_failed)}），详见上方告警。',
                        'level': 'WARNING',
                    }))
                else:
                    self._msg_queue.put(('log', {'text': "已清理所有残留进程和端口"}))
                # 清扫完成：解除「全停中」状态（stop_all 设置），经 ui_update 一起生效
                self._msg_queue.put(('stop_all_done', {}))
                self._msg_queue.put(('ui_update', {}))
            except Exception as e:
                self._msg_queue.put(('log', {'text': f"停止过程出错: {e!s}", 'level': 'ERROR'}))
                self._msg_queue.put(('stop_all_done', {}))
                self._msg_queue.put(('ui_update', {}))
        threading.Thread(target=_stop_all_worker, daemon=True).start()

    def _kill_residual_async(self):
        windows_ops.kill_residual_async(self._msg_queue, _PROJECT_DIR, self._managed_service_pids)


    def restart_dual_dev(self):
        self._gate.start('重启开发模式', self._restart_dual_thread)

    # ── 开发模式状态属性桥(T5 包化:DevModeOps 自持 7 个状态、此处桥接其中 6 个) ──
    # 读写都经此桥,使 app 内 ~50 处 self._mode / self._process / self._frontend_process /
    # self._current_mode_key / self._startup_* 的读写点不必改写。UI 判定与崩溃检测
    # (check_server_status / _update_all_ui / _apply_hosting_data / _update_mode_badge)
    # 全靠这些状态:缺 read 或 write 一侧都会让某处读到错值或写入 AttributeError,
    # 表现为「界面误判进程崩溃 / 误报启动中」——故这 6 个属性一律 @property + @setter。
    # (``startup_steps`` 由 DevModeOps 内部使用,app 侧无读写点,其桥已随 T6 一并删除。)
    @property
    def _mode(self):
        return self.dev.mode

    @_mode.setter
    def _mode(self, value):
        self.dev.mode = value

    @property
    def _process(self):
        return self.dev.process

    @_process.setter
    def _process(self, value):
        self.dev.process = value

    @property
    def _frontend_process(self):
        return self.dev.frontend_process

    @_frontend_process.setter
    def _frontend_process(self, value):
        self.dev.frontend_process = value

    @property
    def _current_mode_key(self):
        return self.dev.current_mode_key

    @_current_mode_key.setter
    def _current_mode_key(self, value):
        self.dev.current_mode_key = value

    @property
    def _startup_progress(self):
        return self.dev.startup_progress

    @_startup_progress.setter
    def _startup_progress(self, value):
        self.dev.startup_progress = value

    @property
    def _startup_current_step(self):
        return self.dev.startup_current_step

    @_startup_current_step.setter
    def _startup_current_step(self, value):
        self.dev.startup_current_step = value

    # ── 开发模式层转发(T5 包化:实现已迁 server_manager/dev_mode.py) ──────────
    # 保留同名瘦转发,既有调用点与静态断言不必改写。
    # 注:UI 胶水 _start_dual_server / _on_dual_started / _on_dual_failed 刻意留在
    # app(碰 messagebox / status_bar_label / _update_all_ui,不得进无 Tk 的 ops 模块)。

    def _start_dual_server(self, label):
        # 互斥守卫：开发模式正在启动/重启中则不操作
        if self._mode in ('starting', 'restarting'):
            self.log_message("开发模式正在启动/重启中，请稍候", 'WARNING')
            return
        if self._mode != 'none':
            self.log_message("已有服务在运行，请先停止后再启动", 'WARNING')
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
        return self.dev.start_dual_flow(label)

    def _stop_dual_mode_async(self, label):
        return self.dev.stop_dual_mode_async(label)

    def _restart_dual_thread(self):
        return self.dev.restart_dual_thread()

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
        # 生产卡按钮随权威状态(sc query→_prod_running)联动：已停止时「停止/重启」
        # 置灰、点不到（原先恒可点，虽闸门兜底无害但语义误导）。状态未知(_prod_unknown)
        # 时全部保持可点 —— 「查不出来」不能当成「已停止」。
        prod_active = self._prod_running
        prod_buttons = (('svc_stop_btn', prod_active), ('svc_restart_btn', prod_active))
        for attr, enabled in prod_buttons:
            btn = getattr(self, attr, None)
            if btn is not None:
                with contextlib.suppress(Exception):
                    btn.config(state='normal' if (enabled or self._prod_unknown) else 'disabled')
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
        stop_btn = getattr(self, f'{mode_key}_stop_btn')
        restart_btn = getattr(self, f'{mode_key}_restart_btn')
        # 统一状态枚举：starting→部署中(蓝弧) / restarting→重启中(橙闪) / active→运行中(绿呼吸) / stopped→已停止(灰空心)
        state = 'deploying' if is_starting else 'restarting' if is_restarting else 'running' if is_active else 'stopped'
        state_text = '启动中' if is_starting else '重启中' if is_restarting else '运行中' if is_active else '已停止'
        status.set_state(state, state_text)
        in_transition = is_starting or is_restarting
        start_btn.config(state='disabled' if in_transition else 'normal')
        # 停止/重启只在运行中可用；「停止中」由闸门 op_busy 全量置灰兜底
        stop_btn.config(state='normal' if is_active else 'disabled')
        restart_btn.config(state='disabled' if (not is_active or in_transition) else 'normal')

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
        return windows_ops.kill_process_tree(pid)

    def _terminate_dev_processes(self, reason='', *, wait=True):
        return self.dev.terminate_dev_processes(reason, wait=wait)

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
        self._build_server_card(content, 0, 0, '开发模式', 'FastAPI + Vue3 / Vite · 热重载 · 自动切换', 'dual_dev', self.start_dual_dev, self.stop_dual_dev, self.restart_dual_dev)
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

    def _build_server_card(self, parent, row, col, title, desc, mode_key, start_cmd, stop_cmd, restart_cmd, columnspan=1):
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
        # 只停开发模式（不动 Redis / 不做全量清扫）：2026-10-15 前该能力存在
        # （stop_dual_dev）但按钮在 v5.33 卡片改版时被丢掉，成了 UI 不可达的死方法 ——
        # 当时只能靠「紧急停止」（连 Redis 一起停）或「启动生产服务」间接停开发。
        stop_btn = RoundedButton(btns, text='停止', variant='outlined', tone='danger', command=stop_cmd, state='disabled', canvas_bg=self._PALETTE['bg_card'])
        self._action_buttons.append(stop_btn)
        stop_btn.pack(side=tk.LEFT, padx=(8, 0))
        restart_btn = RoundedButton(btns, text='重启', variant='outlined', tone='accent', command=restart_cmd, state='disabled', canvas_bg=self._PALETTE['bg_card'])
        self._action_buttons.append(restart_btn)
        restart_btn.pack(side=tk.LEFT, padx=(8, 0))
        setattr(self, f'{mode_key}_status', status_badge)
        setattr(self, f'{mode_key}_start_btn', start_btn)
        setattr(self, f'{mode_key}_stop_btn', stop_btn)
        setattr(self, f'{mode_key}_restart_btn', restart_btn)

    # ===================== 生产模式 (Windows 服务 + NSSM) =====================

    # ── 服务操作层转发(T4 包化:实现已迁 server_manager/service_ops.py) ─────────
    # 保留同名瘦转发,既有调用点与静态断言不必改写。

    def _find_nssm(self):
        return self.svc.find_nssm()

    def _svc_state(self, name):
        return self.svc.svc_state(name)

    def _svc_pid(self, name):
        return self.svc.svc_pid(name)

    def _managed_service_pids(self):
        return self.svc.managed_service_pids()

    def _stop_managed_services(self):
        return self.svc.stop_managed_services()

    def _ensure_production_stopped(self):
        return self.svc.ensure_production_stopped()

    def _ensure_development_stopped(self):
        return self.dev.ensure_development_stopped()

    def _release_ports(self):
        """清理 5002 与 3000 端口占用（复用 _kill_port_sync，其内部对多 PID 有 3 轮重试）。

        ★ 必须排除受管 PID：生产已在运行时点「启动服务」若做无差别清理，
        会 taskkill 掉 erp-prod 的 uvicorn 与 erp-web 的 nginx —— 全站 3000 立即
        502、在途请求全丢，随后 NSSM 5 秒拉起并与本流程的 nssm start 竞态
        （2026-09-28 评审确认；stop_all 的同类调用本就带 exclude，此处曾漏）。

        ★ 必须消费 `_kill_port_sync` 的返回值：'managed_unknown' 意味着
        「受管集合不可知、已 fail-safe 放弃清理」，此时端口**仍被占用**。
        若不判返回值，调用方就会在「端口没清干净」的前提下继续启动新进程
        → 新进程绑不上端口 → 起不来又查不出原因（静默失败）。
        """
        managed = self._managed_service_pids()
        for port in (_API_PORT, _WEB_PORT):
            try:
                state = self._kill_port_sync(port, exclude=managed,
                                             managed_pids_fn=self._managed_service_pids)
            except Exception as e:
                self.log_message(f'端口 {port} 清理异常: {e}', 'WARNING')
                continue
            if state == 'managed_unknown':
                self.log_message(
                    f'端口 {port} 未能清理：无法确认 NSSM 受管进程集合（服务查询失败），'
                    f'已放弃清理以免误杀生产服务。请稍后重试，或用「停止服务」后再启动。',
                    'WARNING',
                )

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
        # Worker 数：初始值读 NSSM 里**已配置**的值，不是本进程环境变量 ——
        # 后者会显示 4 而生产实际跑 8，点「安装服务」就把 8 静默降回 4（2026-09-29 实测）。
        # 「应用」= 写入 NSSM + 只重启 erp-prod（uvicorn worker 数是启动时固定的）。
        # 旁边「生效 N」来自 prod_runner 快照；与已配置值不一致时标「待重启」。
        wk = tk.Frame(grid, bg=self._PALETTE['bg_input'])
        wk.grid(row=2, column=1, sticky='e', padx=(6, 12), pady=(2, 8))
        tk.Label(wk, text='Worker', font=('Microsoft YaHei UI', 9), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_input']).pack(side=tk.LEFT, padx=(0, 4))
        self.hosting_workers_var = tk.StringVar(value=self._configured_workers())
        ttk.Combobox(wk, textvariable=self.hosting_workers_var, values=('2', '4', '6', '8'), width=4, state='readonly', font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT)
        workers_apply_btn = RoundedButton(wk, text='应用', variant='subtle', tone='accent', padx=10, pady=2, radius=8, command=self._apply_workers, canvas_bg=self._PALETTE['bg_input'])
        self._action_buttons.append(workers_apply_btn)   # 变更类按钮，与其它变更按钮一同置灰
        workers_apply_btn.pack(side=tk.LEFT, padx=(4, 0))
        self.hosting_workers_effective = tk.Label(wk, text='', font=('Microsoft YaHei UI', 8), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_input'])
        self.hosting_workers_effective.pack(side=tk.LEFT, padx=(6, 0))
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

    def _nssm_install(self, nssm, name, app, params, env_extra, depends=None):
        return self.svc.nssm_install(nssm, name, app, params, env_extra, depends)

    # ---------- Worker 数：读真值 / 应用并只重启 erp-prod ----------

    def _configured_workers(self) -> str:
        """NSSM 里 erp-prod 已配置的 worker 数；读不到时退回本进程环境变量（默认 4）。

        必须读 NSSM 真值：``os.getenv`` 取的是 server_manager 自身环境，与生产
        实际生效值无关 —— 旧实现因此显示 4 而生产跑 8，点「安装服务」就把它降回 4。

        ★ 限 3s 超时：本方法在 _build_prod_card 里**主线程**执行，run_capture 默认
        20s —— nssm 一卡整个首帧就冻住 20s。读不到只损失「初值显示」，不值得赌。
        """
        try:
            nssm = self._find_nssm()
            if nssm:
                value = self.svc.get_env_extra_key(nssm, _SVC_API, 'UVICORN_WORKERS',
                                                    read_timeout=3)
                if value and value.isdigit():
                    return value
        except Exception:  # defensive: 读 NSSM 失败不得阻断界面构建
            self.log_message('读取 NSSM 中的 Worker 数失败，退回本机环境变量', 'WARNING')
        return str(int(os.getenv('UVICORN_WORKERS', '4')))

    def _read_workers_current(self, nssm) -> str | None:
        """带 3s 超时读 NSSM 里已配置的 Worker 数；失败/超时返回 None（供 _apply_workers
        做主线程读现状，不默认 20s 冻界面）。"""
        try:
            return self.svc.get_env_extra_key(nssm, _SVC_API, 'UVICORN_WORKERS',
                                              read_timeout=3)
        except Exception:
            return None

    def _apply_workers(self):
        """主线程：读现状 + 弹窗确认 + 交给闸门。（tkinter 不许跨线程，弹窗必须在这里）"""
        nssm = self._find_nssm()
        if not nssm:
            messagebox.showerror('缺少 NSSM', '未找到 NSSM，无法修改服务配置。')
            return
        target = (self.hosting_workers_var.get() or '').strip()
        if not target:
            return
        current = self._read_workers_current(nssm)
        if current == target:
            self.log_message(f'Worker 已是 {target}，无需变更')
            return
        # 读不到现状（超时/失败）时仍允许变更：写侧 set_env_extra_key 会回读校验，
        # 拿不到「旧值」只损失确认弹窗里的一行展示，不应阻断操作。
        needs_restart = 'RUNNING' in self._svc_state(_SVC_API)
        if needs_restart and not messagebox.askyesno(
            '确认重启 erp-prod',
            f'Worker {current or "（未设置）"} → {target}\n\n'
            f'worker 数改动必须重启 {_SVC_API} 才生效，期间 :5002 会中断数秒。继续？',
        ):
            self.log_message('已取消 Worker 变更')
            return
        self._gate.start('应用 Worker 数', self._apply_workers_flow, nssm, target, needs_restart)

    def _apply_workers_flow(self, nssm, target, needs_restart):
        """后台线程：只写配置 + 重启 + 经消息队列汇报，绝不可触碰 Tk。

        uvicorn 的 worker 数是启动时一次性 spawn 的进程数，运行中无法增减 ——
        所以「生效」必然包含一次重启（是否重启由主线程确认后以 needs_restart 传入）。
        """
        # 两个服务都写（_SVC_UVICORN_WORKERS）：erp-arq 不读该变量，但保持两者
        # AppEnvironmentExtra 一致，免得日后「安装生产服务」用其中一个的值覆盖出分歧。
        for name in _SVC_UVICORN_WORKERS:
            self._gate.checkpoint()
            ok, msg = self.svc.set_env_extra_key(nssm, name, 'UVICORN_WORKERS', target)
            self._msg_queue.put(('log', {'text': msg, 'level': 'INFO' if ok else 'ERROR'}))
            if not ok:
                return
        if needs_restart:
            self._gate.checkpoint()
            self._msg_queue.put(('log', {'text': f'重启 {_SVC_API} 使 Worker={target} 生效...'}))
            self.svc.restart_one_service(_SVC_API)
        self._msg_queue.put(('hosting_refresh', {}))

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

    def _verify_installed_service_paths(self):
        """安装后回读注册表，校验服务实际加载的模块与当前源码同源（P0-6）。

        ★ 为什么必须有：2026-09-16 的部署漂移事故 —— 源码已修，线上服务却跑旧版
        约 10 小时无人发现，因为「安装成功」只证明命令返回 0，不证明**下次启动**
        会加载哪份代码。

        ⚠️ **必须读 `Parameters\\Application`，不能读顶层 `ImagePath`**：
        `ImagePath` 永远是 `C:\\nssm\\nssm.exe`（NSSM 自己是宿主进程），真正被拉起的
        解释器存在 `<service>\\Parameters\\Application`。实测（本机真实注册表）
        只看 `ImagePath` 会对 erp-prod / erp-arq **双双误报**「解释器不一致」，
        把一个正确配置报成故障 —— 校验器自己成了噪声源。
        """
        if not _IS_WINDOWS:
            return
        if not _PYTHON_EXE:
            self.log_message('未定位到可用的 Python 解释器，跳过安装后指向校验', 'WARNING')
            return
        try:
            import winreg
        except ImportError:
            self.log_message('无法校验服务指向（winreg 不可用），请手工核对服务参数', 'WARNING')
            return
        expected_app = str(_PYTHON_EXE)
        expected_dir = str(_PROJECT_DIR)
        for name in (_SVC_API, _SVC_ARQ):
            actual_app, actual_params, actual_dir = None, None, None
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                    rf'SYSTEM\CurrentControlSet\Services\{name}', 0, winreg.KEY_READ) as key:
                    with winreg.OpenKey(key, 'Parameters', 0, winreg.KEY_READ) as pk:
                        with contextlib.suppress(OSError):
                            actual_app = winreg.QueryValueEx(pk, 'Application')[0]
                        with contextlib.suppress(OSError):
                            actual_params = winreg.QueryValueEx(pk, 'AppParameters')[0]
                        with contextlib.suppress(OSError):
                            actual_dir = winreg.QueryValueEx(pk, 'AppDirectory')[0]
            except OSError as e:
                self.log_message(f'{name} 指向校验失败（读注册表出错）: {e}', 'WARNING')
                continue
            problems = []
            if not actual_app:
                problems.append(r'Parameters\Application 缺失（服务未正确配置）')
            elif expected_app.lower() not in str(actual_app).lower():
                problems.append(f'解释器={actual_app} 期望含 {expected_app}')
            if actual_dir and str(actual_dir).lower() != expected_dir.lower():
                problems.append(f'工作目录={actual_dir} 期望 {expected_dir}')
            if problems:
                self.log_message(
                    f'{name} 安装后校验不一致，服务可能加载非当前源码：' + '；'.join(problems),
                    'WARNING')
            else:
                self.log_message(
                    f'{name} 指向校验通过（app={Path(actual_app).name if actual_app else "?"}，'
                    f'params={(actual_params or "")[:80]}）')

    def _install_services_flow(self, nssm, workers):
        # 逐项列表(不是空格拼接的整串)：_nssm_install 会把它作为多个 argv 元素传给
        # `nssm set ... AppEnvironmentExtra`，NSSM 才会逐项注入；拼成一串只有第一项生效。
        env_extra = [
            'APP_ENV=production',
            'FASTAPI_DEBUG=false',
            f'PYTHONPATH={_PROJECT_DIR}',
            'PYTHONUTF8=1',
            'PYTHONUNBUFFERED=1',
            f'UVICORN_WORKERS={workers}',
        ]
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
                                     [], depends=None)
        else:
            ok3 = False
            self._msg_queue.put(('log', {'text': f'未找到 {_nginx_exe}，{_SVC_WEB} 未安装（前端仍可由旧方式托管）', 'level': 'WARNING'}))
        if ok1 and ok2 and ok3:
            self._msg_queue.put(('log', {'text': '生产服务安装完成：erp-prod + erp-arq + erp-web（开机自启、按依赖顺序启动）'}))
        else:
            self._msg_queue.put(('log', {'text': '生产服务安装未完全成功，请查看上方日志', 'level': 'WARNING'}))
        # ★ 安装成功 ≠ 下次启动会加载当前这份源码。回读注册表核实指向（P0-6）；
        #   不一致只报 WARNING（安装动作本身已完成，问题是「生效目标」可能不是你以为的那份）。
        self._verify_installed_service_paths()
        self._msg_queue.put(('hosting_refresh', {}))

    def _service_cmd_sync(self, verb):
        return self.svc.service_cmd_sync(verb)

    def _service_cmd(self, verb):
        # 重启会换掉 prod_runner 进程：旧快照在它写下第一份新快照前必然陈旧，
        # 与「启动服务」共用同一条宽限判据（否则重启后也会弹「可能已退出」）。
        # ★ _prod_start_ts 是 app 的托管状态(与 _start_services_flow 共用),ServiceOps 不得触碰。
        # ★ 必须等闸门【放行之后】才记时:gate.start 会拒绝(已有动作在飞),若提前刷新时间戳,
        #   随后 HOSTING_START_GRACE_SEC(60s) 内陈旧的状态文件会被误显示为「启动中」,
        #   而不是按真实情况告警。
        if self._gate.start(f'服务{verb}', self._service_cmd_sync, verb) and verb == 'restart':
            self._prod_start_ts = time.time()

    def _start_services(self):
        # 互斥守卫：开发模式正在启动/重启中则拒绝（防 TOCTOU 双后端抢 5002）
        if self._mode in ('starting', 'restarting'):
            self.log_message('开发模式正在启动中，请稍候', 'WARNING')
            return
        self._gate.start('启动生产服务', self._start_services_flow)

    def _start_services_flow(self):
        # 2026-10-17 审计 AUD-28：生产启动前先过 git 分支闸门
        # （NSSM AppDirectory = 本仓库工作区，非 main 分支会被直接跑进生产）
        ok, guard_msg = git_guard.check_production_branch()
        if not ok:
            self._msg_queue.put(('log', {'text': f'拒绝启动：{guard_msg}', 'level': 'ERROR'}))
            return
        if guard_msg.startswith('警告') or '覆盖' in guard_msg:
            self._msg_queue.put(('log', {'text': guard_msg, 'level': 'WARNING'}))
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
        # （_log_size/_read_log_lines 已收编 log_ops（T9）：纯文件 IO 住 ops 层。）
        offsets = {name: log_ops.log_file_size(_PROJECT_DIR / 'logs' / f'{name}.log')
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
            fresh = log_ops.read_log_tail_lines(_PROJECT_DIR / 'logs' / f'{name}.log',
                                               start_offset=offsets[name], lines=30)
            if fresh:
                self._msg_queue.put(('log_batch', {'lines': [f'[{name}] {ln}' for ln in fresh], 'level': 'INFO'}))
            else:
                self._msg_queue.put(('log', {'text': f'[{name}] 本次启动暂无新日志（历史见 logs 下的 {name}.log）'}))
        # ★ 上面的回灌只是「本次启动到此刻」的一次性快照；此后必须由 ProdLogTailer
        #   持续跟踪这三个日志文件的增量，否则界面在启动窗口之后再无输出 ——
        #   用户实测的「生产模式打开后运行日志不是实时输出」就是这段断层。
        self.prod_logs.ensure_started()
        if ok_api and ok_arq:
            self._msg_queue.put(('log', {'text': f'生产模式启动完成 → {_SVC_API}: {api_state} (PID: {api_pid}), '
                                         f'{_SVC_ARQ}: {arq_state} (PID: {arq_pid})'}))
        else:
            hint = (f'；{_SVC_ARQ} 因 ARQ broker(6380) 未就绪而不可用，'
                    f'请检查 {_SVC_REDIS_BROKER} 服务') if not broker_ok else ''
            self._msg_queue.put(('log', {'text': f'生产模式启动未完全成功{hint}，请查看上方日志与 logs 目录下的服务日志', 'level': 'WARNING'}))
        self._msg_queue.put(('hosting_refresh', {}))

    def _start_one_service(self, name, timeout=25):
        return self.svc.start_one_service(name, timeout)

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
        return self.svc.uninstall_services_flow(nssm)

    def _open_logs_dir(self):
        log_dir = _PROJECT_DIR / 'logs'
        log_dir.mkdir(exist_ok=True)
        try:
            os.startfile(str(log_dir))
        except Exception as e:
            self.log_message(f'打开日志目录失败: {e}', 'ERROR')

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
            messagebox.showerror("启动失败", f"服务器管理器启动失败:\n{e!s}" + (f"\n\n日志: {crash_file}" if crash_file else ""))
        sys.exit(1)


if __name__ == '__main__':
    main()
