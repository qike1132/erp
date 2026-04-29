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
import os
import sys
import subprocess
import threading
import time
import queue
import shutil
import hashlib
import logging
import locale
import socket
import urllib.request
from datetime import datetime
import math
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

import tkinter as tk
from tkinter import ttk, messagebox

_VERSION = 'v5.19'
_WINDOW_TITLE = f'ERP 服务器管理器 {_VERSION}'
_REDIS_PORT = 6379
_REDIS_EXE_PATHS = [Path(r'C:\Redis\redis-server.exe'), Path(r'C:\Program Files\Redis\redis-server.exe')]
_REDIS_CONF_PATHS = [Path(r'C:\Redis\redis.windows.conf'), Path(r'C:\Redis\redis.conf')]

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
                try:
                    (exe_dir / 'erp_project_path.txt').write_text(str(candidate), encoding='utf-8')
                except Exception:
                    pass
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

def _taskkill(pid, force=True, tree=True):
    """统一的进程终止函数"""
    if not _IS_WINDOWS:
        return
    cmd = ['taskkill', '/F' if force else '', '/T' if tree else '', '/PID', str(pid)]
    cmd = [c for c in cmd if c]
    subprocess.run(cmd, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, timeout=10)

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

class RoundedButton(tk.Canvas):
    """基于 Canvas 的圆角按钮 — 14px 大圆角，hover 动画过渡"""

    def __init__(self, parent, text='', fill='#89b4fa', fg='#1e1e2e',
                 hover_fill=None, command=None, font=('Microsoft YaHei UI', 10),
                 padx=24, pady=8, radius=14, state='normal', canvas_bg=None, **kw):
        import tkinter.font as tkfont
        f = tkfont.Font(font=font)
        w, h = f.measure(text) + padx * 2, f.metrics('linespace') + pady * 2
        canvas_bg = canvas_bg or '#141419'
        super().__init__(parent, width=w, height=h, highlightthickness=0, cursor='hand2', bg=canvas_bg, **kw)
        self._text, self._fill, self._fg = text, fill, fg
        self._hover_fill = hover_fill or _shift_color(fill, -20)
        self._font, self._radius, self._command = font, radius, command
        self._state, self._hover, self._press = state, False, False
        self._anim_after_id = None
        self.bind('<Configure>', self._draw)
        self.bind('<Enter>', lambda e: self._hover_in())
        self.bind('<Leave>', lambda e: self._hover_out())
        self.bind('<ButtonPress-1>', lambda e: self._press_in())
        self.bind('<ButtonRelease-1>', lambda e: self._press_out())

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2, x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _draw(self, _=None):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        r = min(self._radius, w // 2, h // 2)
        if self._state == 'disabled':
            bg, fg = '#2a2a35', '#4a4a58'
        elif self._press:
            bg, fg = _lerp_color(self._fill, self._hover_fill, 0.6), self._fg
        elif self._hover:
            bg, fg = self._hover_fill, self._fg
        else:
            bg, fg = self._fill, self._fg
        offset = 1 if self._press else 0
        self._round_rect(offset, offset, w - offset, h - offset, r, fill=bg, outline='')
        if self._hover and self._state != 'disabled':
            self._round_rect(2, h - 3, w - 2, h - 1, 1, fill=_shift_color(bg, 20), outline='')
        self.create_text(w // 2, h // 2, text=self._text, fill=fg, font=self._font)

    def _animate_hover(self, target_hover):
        if self._state == 'disabled':
            self._draw()
            return
        if self._anim_after_id:
            self.after_cancel(self._anim_after_id)
            self._anim_after_id = None
        start_color = self._fill if not target_hover else self._hover_fill
        end_color = self._hover_fill if target_hover else self._fill
        step_idx = [0]
        def step():
            step_idx[0] += 1
            t = step_idx[0] / 3
            if t >= 1.0:
                self._hover = target_hover
                self._draw()
                return
            self.delete('all')
            w, h = self.winfo_width(), self.winfo_height()
            if w < 4 or h < 4:
                return
            self._round_rect(0, 0, w, h, min(self._radius, w // 2, h // 2), fill=_lerp_color(start_color, end_color, t), outline='')
            self.create_text(w // 2, h // 2, text=self._text, fill=self._fg, font=self._font)
            self._anim_after_id = self.after(50, step)
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


class StatusDot(tk.Canvas):
    """带呼吸动画的状态指示灯"""

    def __init__(self, parent, size=12, color='#ff6b81', **kw):
        bg = kw.pop('canvas_bg', '#141419')
        super().__init__(parent, width=size, height=size, highlightthickness=0, bg=bg, **kw)
        self._size, self._color, self._bg = size, color, bg
        self._anim_after_id, self._is_active = None, False
        self._draw_dot()

    def set_color(self, color, active=False):
        self._color, self._is_active = color, active
        if self._anim_after_id:
            self.after_cancel(self._anim_after_id)
            self._anim_after_id = None
        if active:
            self._start_breathing()
        else:
            self._draw_dot()

    def _draw_dot(self, alpha=1.0):
        self.delete('all')
        s, r = self._size, self._size // 2 - 1
        if self._is_active and alpha < 1.0:
            glow_r = int(r + 2 * (1 - alpha))
            self.create_oval(s//2 - glow_r, s//2 - glow_r, s//2 + glow_r, s//2 + glow_r, fill=_shift_color(self._color, int(30 * (1 - alpha))), outline='')
        self.create_oval(s//2 - r, s//2 - r, s//2 + r, s//2 + r, fill=self._color, outline='')

    def _start_breathing(self):
        step = [0]
        def tick():
            step[0] = (step[0] + 1) % 60
            self._draw_dot(0.7 + 0.3 * math.sin(step[0] / 60.0 * 2 * math.pi))
            self._anim_after_id = self.after(200, tick)
        tick()

    def stop_animation(self):
        if self._anim_after_id:
            self.after_cancel(self._anim_after_id)
            self._anim_after_id = None
        self._draw_dot()


def _create_tray_icon_image():
    try:
        from PIL import Image, ImageDraw
        img = Image.new('RGBA', (16, 16), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse([2, 2, 14, 14], fill=(108, 142, 255, 255))
        return img
    except Exception:
        return None


class ServerManagerApp:
    """ERP 服务器管理器 — 调试/生产双模式"""

    _PALETTE = {
        'bg_main': '#f2f4f8', 'bg_card': '#ffffff', 'bg_surface': '#e9edf4', 'bg_header': '#f7f9fc', 'bg_log': '#fbfcfe', 'bg_input': '#edf1f7',
        'text_primary': '#1f2a3d', 'text_secondary': '#4f5f7a', 'text_dim': '#7b889f',
        'border': '#d7deea', 'border_card': '#dce3ef',
        'accent': '#3f7cff', 'accent_h': '#5d92ff', 'success': '#21b573', 'success_h': '#38c689',
        'danger': '#e3576d', 'danger_h': '#f06d83', 'warning': '#f0a542', 'info': '#36a8ce',
        'log_fg': '#25324a', 'log_info': '#3f7cff', 'log_error': '#e3576d', 'log_warn': '#f0a542', 'log_success': '#21b573',
    }
    MAX_LOG_LINES, LOG_KEEP_LINES, LOG_CLEANUP_MS, LOG_FLUSH_MS = 500, 300, 120000, 500

    def __init__(self, root):
        self.root = root
        self.root.title(_WINDOW_TITLE)
        self.root.geometry("960x720")
        self.root.minsize(800, 600)
        self.root.resizable(True, True)
        self.root.withdraw()
        self._mode, self._process, self._frontend_process, self._redis_process = 'none', None, None, None
        self._log_buffer, self._flush_pending = [], False
        self._msg_queue = queue.Queue()
        self._server_cards = []
        self._status_anim_after_id, self._status_pulse_step = None, 0
        self._startup_progress, self._startup_steps, self._startup_current_step, self._current_mode_key = 0, [], "", ""
        self.setup_logging()
        self._build_ui()
        self._set_window_icon()
        self._center_window()
        self.root.deiconify()
        self._fade_in()
        self._animate_cards_intro()
        self._check_interval, self._after_ids = 5000, {}
        self._redis_check_after_id = None
        self._run_env_checks()
        self.check_server_status()
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

    def _find_redis(self):
        """查找Redis可执行文件和配置文件"""
        redis_exe = next((str(p) for p in _REDIS_EXE_PATHS if p.is_file()), None)
        redis_conf = next((str(p) for p in _REDIS_CONF_PATHS if p.is_file()), None)
        return redis_exe, redis_conf

    def _is_redis_running(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                return sock.connect_ex(('127.0.0.1', _REDIS_PORT)) == 0
        except Exception:
            return False

    def _start_redis(self):
        """启动Redis服务"""
        if self._is_redis_running():
            self._msg_queue.put(('log', {'text': "Redis 已在运行"}))
            return True
        redis_exe, redis_conf = self._find_redis()
        if not redis_exe:
            self._msg_queue.put(('log', {'text': "Redis 未安装，请安装 Redis for Windows", 'level': 'WARNING'}))
            return False
        try:
            cmd = [redis_exe] + ([redis_conf] if redis_conf else [])
            self._msg_queue.put(('log', {'text': f"正在启动 Redis: {redis_exe}"}))
            self._redis_process = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=False)
            threading.Thread(target=self._read_stdout, args=(self._redis_process,), daemon=True).start()
            for _ in range(15):
                time.sleep(0.5)
                if self._is_redis_running():
                    self._msg_queue.put(('log', {'text': f"Redis 启动成功 (PID: {self._redis_process.pid})"}))
                    return True
                if self._redis_process.poll() is not None:
                    self._msg_queue.put(('log', {'text': f"Redis 进程意外退出 (退出码: {self._redis_process.returncode})", 'level': 'ERROR'}))
                    return False
            self._msg_queue.put(('log', {'text': "Redis 启动超时，请检查端口6379是否被占用", 'level': 'WARNING'}))
            return False
        except Exception as e:
            self._msg_queue.put(('log', {'text': f"Redis 启动失败: {str(e)}", 'level': 'ERROR'}))
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
                try:
                    card.configure(highlightbackground=base)
                except Exception:
                    pass
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
        if self._status_anim_after_id:
            try:
                self.root.after_cancel(self._status_anim_after_id)
            except Exception:
                pass
            self._status_anim_after_id = None
        if self._redis_check_after_id:
            try:
                self.root.after_cancel(self._redis_check_after_id)
            except Exception:
                pass
            self._redis_check_after_id = None
        for aid in self._after_ids.values():
            try:
                self.root.after_cancel(aid)
            except Exception:
                pass
        self._after_ids.clear()
        for attr in ('dual_dev_status_dot', 'dual_prod_status_dot'):
            dot = getattr(self, attr, None)
            if dot:
                dot.stop_animation()
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
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
            try:
                self.root.update()
            except Exception:
                pass

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
        proc = self._process
        self._process = None
        if proc and proc.poll() is None:
            pid = proc.pid
            self._msg_queue.put(('log', {'text': f"正在终止进程树 (根 PID: {pid})..."}))
            def _kill_worker():
                try:
                    if _IS_WINDOWS:
                        child_pids = self._collect_process_tree(pid)
                        self._msg_queue.put(('log', {'text': f"发现 {len(child_pids)+1} 个关联进程"}))
                        _taskkill(pid)
                        for cpid in child_pids:
                            try:
                                _taskkill(cpid)
                            except Exception:
                                pass
                        try:
                            proc.wait(timeout=3)
                        except Exception:
                            pass
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
            threading.Thread(target=_kill_worker, daemon=True).start()
        else:
            self._msg_queue.put(('ui_update', {}))

    def _collect_process_tree(self, root_pid):
        pids = []
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

    def _kill_port_sync(self, port):
        for _ in range(3):
            if not self._find_port_pids(port):
                return
            for opid in self._find_port_pids(port):
                try:
                    _taskkill(opid)
                except Exception:
                    pass
            time.sleep(0.5)

    def _find_port_pids(self, port):
        pids = set()
        try:
            output = subprocess.run(['netstat', '-ano'], creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True, timeout=10)
            for line in output.stdout.splitlines():
                if 'LISTENING' not in line and 'TIME_WAIT' not in line:
                    continue
                parts = line.split()
                if len(parts) >= 5 and ':' in parts[1] and parts[1].rsplit(':', 1)[-1] == str(port) and parts[-1].isdigit() and int(parts[-1]) > 0:
                    pids.add(parts[-1])
        except Exception:
            pass
        return list(pids)

    def _start_server(self, script_name, mode_label, mode_key='debug'):
        if not _PYTHON_EXE:
            self.log_message("无法启动: 未找到 Python 解释器，请安装 Python 并确保在 PATH 中", 'ERROR')
            messagebox.showerror("启动失败", "未找到可用的 Python 解释器！\n\n请安装 Python 3.12+ 并确保 python 在 PATH 中，\n或在项目目录下创建虚拟环境 (.venv313)")
            return
        script = str(_PROJECT_DIR / script_name)
        if not Path(script).is_file():
            self.log_message(f"启动脚本不存在: {script}", 'ERROR')
            messagebox.showerror("错误", f"启动脚本不存在:\n{script}")
            return
        self.log_message(f"正在启动{mode_label}...")
        self.status_bar_label.config(text=f"正在启动{mode_label}...")
        self._mode = 'starting'
        self._current_mode_key = mode_key
        self._update_all_ui()
        threading.Thread(target=self._start_thread, args=(script, mode_label, mode_key), daemon=True).start()

    def _start_thread(self, script, mode_label, mode_key):
        try:
            self._msg_queue.put(('log', {'text': '正在清理端口...'}))
            self._kill_port_sync(_API_PORT)
            
            env = os.environ.copy()
            env.update({'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1', 'PYTHONPATH': str(_PROJECT_DIR)})
            self._process = subprocess.Popen([_PYTHON_EXE, script], cwd=str(_PROJECT_DIR), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0, text=False)
            self._msg_queue.put(('log', {'text': f"进程已启动 (PID: {self._process.pid})"}))
            threading.Thread(target=self._read_stdout, args=(self._process,), daemon=True).start()
            time.sleep(2)
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
        processed = 0
        while not self._msg_queue.empty() and processed < 30:
            try:
                msg_type, data = self._msg_queue.get_nowait()
            except queue.Empty:
                break
            if msg_type == 'log':
                self.log_message(data['text'], data.get('level', 'INFO'))
            elif msg_type == 'log_batch':
                for line in data['lines']:
                    self.log_message(line, data.get('level', 'INFO'))
            elif msg_type == 'started':
                self._on_started(data['label'], data.get('mode_key', 'debug'))
            elif msg_type == 'dual_started':
                self._on_dual_started(data['mode'], data['label'])
            elif msg_type == 'dual_failed':
                self._on_dual_failed(data['mode'], data['label'], data.get('reason', ''))
            elif msg_type == 'ui_update':
                self._update_all_ui()
            elif msg_type == 'status':
                self.status_bar_label.config(text=data['text'])
            elif msg_type == 'startup_progress':
                self.status_bar_label.config(text=f"启动中: {data.get('step', '')} ({data.get('progress', 0)}/{data.get('total', 4)})")
                self._startup_current_step, self._startup_progress = data.get('step', ''), data.get('progress', 0)
            processed += 1
        self._after_ids['poll'] = self.root.after(200, self._poll_queue)

    def start_debug(self):
        self._start_server('run.py', '调试模式', mode_key='debug')

    def start_production(self):
        self._start_server('start_production_optimized.py', '生产模式', mode_key='production')

    def start_dual_dev(self):
        self._start_dual_server(mode='dev', label='开发模式（前后端）')

    def start_dual_prod(self):
        self._start_dual_server(mode='prod', label='生产模式（前后端）')

    def stop_debug(self):
        self._stop_mode('debug', '调试模式')

    def stop_production(self):
        self._stop_mode('production', '生产模式')

    def stop_dual_dev(self):
        self._stop_dual_mode_async('dual_dev', '开发模式')

    def stop_dual_prod(self):
        self._stop_dual_mode_async('dual_prod', '生产模式')

    def _stop_mode(self, mode, label):
        if self._mode == mode:
            self._stop_process()
            self._mode = 'none'
            self._update_all_ui()
            self.log_message(f"{label}已停止")
        else:
            self.log_message(f"{label}未运行")

    def stop_all(self):
        # 先在主线程立即重置状态（双重保险）
        self._mode = 'none'
        self._current_mode_key = ""
        self._update_all_ui()
        
        self.log_message("正在执行停止/重置操作...")
        self.status_bar_label.config(text="正在停止所有...")
        def _stop_all_worker():
            try:
                # 强制停止所有进程，不管状态
                for proc, name in [(self._frontend_process, '前端'), (self._process, '后端')]:
                    if proc and proc.poll() is None:
                        self._msg_queue.put(('log', {'text': f'正在终止{name}进程 (PID: {proc.pid})...'}))
                        self._kill_process_tree(proc.pid)
                self._frontend_process = None
                self._process = None
                
                self._stop_redis()
                self._kill_residual_async()
                self._kill_port_sync(_API_PORT)
                self._kill_port_sync(_WEB_PORT)
                self._kill_port_sync(_REDIS_PORT)
                self._msg_queue.put(('log', {'text': "已清理所有残留进程和端口"}))
                self._msg_queue.put(('ui_update', {}))
            except Exception as e:
                self._msg_queue.put(('log', {'text': f"停止过程出错: {str(e)}", 'level': 'ERROR'}))
        threading.Thread(target=_stop_all_worker, daemon=True).start()

    def _kill_residual_async(self):
        def _kill_worker():
            if not _IS_WINDOWS:
                return
            try:
                self._msg_queue.put(('log', {'text': "正在扫描残留进程..."}))
                try:
                    import psutil
                    pids_to_kill = [p.pid for p in psutil.process_iter(['pid', 'name', 'cmdline']) if p.pid != os.getpid() and ('python' in (p.info['name'] or '').lower() or 'uvicorn' in ' '.join(p.info['cmdline'] or []).lower() or 'next' in ' '.join(p.info['cmdline'] or []).lower() or 'node' in (p.info['name'] or '').lower())]
                    if pids_to_kill:
                        self._msg_queue.put(('log', {'text': f"发现 {len(pids_to_kill)} 个残留进程，正在终止..."}))
                        for pid in pids_to_kill:
                            try:
                                _taskkill(pid)
                            except Exception:
                                pass
                except ImportError:
                    self._msg_queue.put(('log', {'text': "缺少psutil库，跳过残留进程清理", 'level': 'WARNING'}))
            except Exception as e:
                self._msg_queue.put(('log', {'text': f"清理残留进程出错: {e}", 'level': 'WARNING'}))
        threading.Thread(target=_kill_worker, daemon=True).start()

    def restart_debug(self):
        self.log_message("正在重启调试模式...")
        threading.Thread(target=self._restart_thread, args=('debug',), daemon=True).start()

    def restart_production(self):
        self.log_message("正在重启生产模式...")
        threading.Thread(target=self._restart_thread, args=('production',), daemon=True).start()

    def restart_dual_dev(self):
        self.log_message("正在重启开发模式...")
        threading.Thread(target=self._restart_dual_thread, args=('dual_dev', 'dev'), daemon=True).start()

    def restart_dual_prod(self):
        self.log_message("正在重启生产模式...")
        threading.Thread(target=self._restart_dual_thread, args=('dual_prod', 'prod'), daemon=True).start()

    def _restart_thread(self, mode):
        self._mode = 'restarting'
        self._msg_queue.put(('ui_update', {}))
        proc = self._process
        self._process = None
        if proc and proc.poll() is None:
            self._msg_queue.put(('log', {'text': f"重启：终止进程树 (PID: {proc.pid})..."}))
            if _IS_WINDOWS:
                for cpid in self._collect_process_tree(proc.pid):
                    try:
                        _taskkill(cpid)
                    except Exception:
                        pass
                _taskkill(proc.pid)
                try:
                    proc.wait(timeout=3)
                except Exception:
                    pass
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
        self._kill_port_sync(_API_PORT)
        time.sleep(0.5)
        self._mode = 'restarting'
        self._start_thread(str(_PROJECT_DIR / ('run.py' if mode == 'debug' else 'start_production_optimized.py')), '调试模式' if mode == 'debug' else '生产模式', mode_key=mode)

    def _start_dual_server(self, mode, label):
        if not _PYTHON_EXE:
            self.log_message("无法启动: 未找到 Python 解释器，请安装 Python 并确保在 PATH 中", 'ERROR')
            messagebox.showerror("启动失败", "未找到可用的 Python 解释器！\n\n请安装 Python 3.12+ 并确保 python 在 PATH 中，\n或在项目目录下创建虚拟环境 (.venv313)")
            return
        if not _FRONTEND_DIR.exists():
            self.log_message(f"前端目录不存在: {_FRONTEND_DIR}", 'ERROR')
            messagebox.showerror("错误", f"前端目录不存在:\n{_FRONTEND_DIR}")
            return
        
        self._mode = 'starting'
        self._current_mode_key = 'dual_dev' if mode == 'dev' else 'dual_prod'
        self._startup_progress, self._startup_steps, self._startup_current_step = 0, ['检查Redis服务', '启动后端服务', '启动前端服务', '完成'], ''
        self._update_all_ui()
        self.log_message(f"正在启动{label}...")
        self.status_bar_label.config(text=f"正在启动{label}...")
        threading.Thread(target=self._start_dual_thread, args=(mode, label), daemon=True).start()

    def _start_dual_thread(self, mode, label):
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0
            
            self._msg_queue.put(('log', {'text': '正在清理端口...'}))
            self._kill_port_sync(_API_PORT)
            self._kill_port_sync(_WEB_PORT)
            
            self._startup_current_step, self._startup_progress = self._startup_steps[0], 1
            self._msg_queue.put(('startup_progress', {'step': self._startup_current_step, 'progress': self._startup_progress, 'total': len(self._startup_steps)}))
            if not self._start_redis():
                self._msg_queue.put(('log', {'text': '警告: Redis 未启动，部分功能可能不可用', 'level': 'WARNING'}))
            self._startup_current_step, self._startup_progress = self._startup_steps[1], 2
            self._msg_queue.put(('startup_progress', {'step': self._startup_current_step, 'progress': self._startup_progress, 'total': len(self._startup_steps)}))
            env = os.environ.copy()
            env.update({'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1', 'PYTHONPATH': str(_PROJECT_DIR)})
            backend_cmd = [_PYTHON_EXE, '-u', '-m', 'uvicorn', 'fastapi_app.main:app', '--host', '0.0.0.0', '--port', str(_API_PORT), '--log-level', 'info'] + (['--reload', '--reload-dir', 'fastapi_app'] if mode == 'dev' else [])
            self._process = subprocess.Popen(backend_cmd, cwd=str(_PROJECT_DIR), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creationflags, text=False)
            self._msg_queue.put(('log', {'text': f"后端进程已启动 (PID: {self._process.pid})"}))
            threading.Thread(target=self._read_stdout, args=(self._process,), daemon=True).start()
            backend_ready = False
            for _ in range(30):
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
                    try:
                        self._process.wait(timeout=3)
                    except Exception:
                        pass
                self._process = None
                self._msg_queue.put(('dual_failed', {'mode': 'dual_dev' if mode == 'dev' else 'dual_prod', 'label': label, 'reason': '后端未就绪'}))
                return
            self._startup_current_step, self._startup_progress = self._startup_steps[2], 3
            self._msg_queue.put(('startup_progress', {'step': self._startup_current_step, 'progress': self._startup_progress, 'total': len(self._startup_steps)}))
            npm_cmd = 'npm.cmd' if _IS_WINDOWS else 'npm'
            # 生产模式下：前端由 Nginx 直接服务静态文件，仅需确保构建产物存在
            if mode == 'prod':
                if not (_FRONTEND_DIR / 'dist').is_dir():
                    self._msg_queue.put(('log', {'text': '生产模式：未检测到 dist 构建产物，正在执行 vite build...', 'level': 'WARNING'}))
                    build_proc = subprocess.Popen([npm_cmd, 'run', 'build'], cwd=str(_FRONTEND_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creationflags, text=False)
                    build_output = []
                    while True:
                        line = build_proc.stdout.readline()
                        if not line:
                            break
                        text = line.decode('utf-8', errors='replace').rstrip('\n\r')
                        if text:
                            build_output.append(text)
                    build_proc.wait(timeout=300)
                    if build_proc.returncode != 0:
                        self._msg_queue.put(('log', {'text': 'vite build 失败', 'level': 'ERROR'}))
                    else:
                        self._msg_queue.put(('log', {'text': 'vite build 完成，前端将由 Nginx 提供服务'}))
                else:
                    self._msg_queue.put(('log', {'text': '前端构建产物已就绪，由 Nginx 提供服务'}))
                # 生产模式不需要启动前端进程，跳过健康检查
                self._startup_current_step, self._startup_progress = self._startup_steps[-1], len(self._startup_steps)
                self._msg_queue.put(('startup_progress', {'step': self._startup_current_step, 'progress': self._startup_progress, 'total': len(self._startup_steps)}))
                self._msg_queue.put(('dual_started', {'mode': 'dual_prod', 'label': label}))
                return
            # 开发模式：启动 Vite dev server
            self._frontend_process = subprocess.Popen([npm_cmd, 'run', 'dev', '--', '--port', str(_WEB_PORT)], cwd=str(_FRONTEND_DIR), env={**os.environ, 'BACKEND_INTERNAL_URL': f'http://127.0.0.1:{_API_PORT}'}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creationflags, text=False)
            self._msg_queue.put(('log', {'text': f"前端进程已启动 (PID: {self._frontend_process.pid})"}))
            threading.Thread(target=self._read_frontend_stdout, args=(self._frontend_process,), daemon=True).start()
            frontend_ready = False
            for _ in range(60):
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
                        try:
                            proc.wait(timeout=3)
                        except Exception:
                            pass
                self._process, self._frontend_process = None, None
                self._msg_queue.put(('dual_failed', {'mode': 'dual_dev' if mode == 'dev' else 'dual_prod', 'label': label, 'reason': '前端未就绪'}))
                return
            self._startup_current_step, self._startup_progress = self._startup_steps[3], 4
            self._msg_queue.put(('startup_progress', {'step': self._startup_current_step, 'progress': self._startup_progress, 'total': len(self._startup_steps)}))
            self._msg_queue.put(('dual_started', {'mode': 'dual_dev' if mode == 'dev' else 'dual_prod', 'label': label}))
        except Exception as e:
            self._process, self._frontend_process = None, None
            self._msg_queue.put(('dual_failed', {'mode': 'dual_dev' if mode == 'dev' else 'dual_prod', 'label': label, 'reason': f'异常: {str(e)}'}))

    def _read_frontend_stdout(self, proc):
        batch = []
        while True:
            try:
                line = proc.stdout.readline()
                if not line:
                    break
                text = line.decode('utf-8', errors='replace').rstrip('\n\r')
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

    def _stop_dual_mode_async(self, mode, label):
        self._msg_queue.put(('log', {'text': f"正在停止{label}..."}))
        def _stop_worker():
            frontend_proc, backend_proc = self._frontend_process, self._process
            self._frontend_process, self._process = None, None
            for proc, name in [(frontend_proc, '前端'), (backend_proc, '后端')]:
                if proc and proc.poll() is None:
                    self._msg_queue.put(('log', {'text': f'正在终止{name}进程树 (PID: {proc.pid})...'}))
                    if _IS_WINDOWS:
                        try:
                            _taskkill(proc.pid)
                        except Exception:
                            pass
                    else:
                        try:
                            proc.terminate()
                            proc.wait(timeout=5)
                        except Exception:
                            try:
                                proc.kill()
                            except Exception:
                                pass
                    self._msg_queue.put(('log', {'text': f'{name}进程已终止 (PID: {proc.pid})'}))
            self._stop_redis()
            self._kill_port_sync(_API_PORT)
            self._kill_port_sync(_WEB_PORT)
            self._mode = 'none'
            self._current_mode_key = ""
            self._msg_queue.put(('ui_update', {}))
            self._msg_queue.put(('log', {'text': f"{label}已停止，端口已释放"}))
        threading.Thread(target=_stop_worker, daemon=True).start()

    def _restart_dual_thread(self, mode_key, mode):
        self._mode, self._current_mode_key = 'restarting', mode_key
        self._msg_queue.put(('ui_update', {}))
        label = '开发模式' if mode == 'dev' else '生产模式'
        for proc, name in [(self._frontend_process, '前端'), (self._process, '后端')]:
            if proc and proc.poll() is None:
                self._msg_queue.put(('log', {'text': f"重启：终止{name}进程树 (PID: {proc.pid})..."}))
                if _IS_WINDOWS:
                    for cpid in self._collect_process_tree(proc.pid):
                        try:
                            _taskkill(cpid)
                        except Exception:
                            pass
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
        self._start_dual_thread(mode, label)

    def _on_dual_started(self, mode, label):
        backend_alive = self._process and self._process.poll() is None
        frontend_alive = self._frontend_process and self._frontend_process.poll() is None
        is_prod = mode == 'dual_prod'
        if not backend_alive:
            self.log_message(f"{label}启动后后端进程已退出", 'ERROR')
            if frontend_alive:
                self._kill_process_tree(self._frontend_process.pid)
            self._mode, self._process, self._frontend_process = 'none', None, None
            self._current_mode_key = ""
            self._update_all_ui()
            return
        if not is_prod and not frontend_alive:
            self.log_message(f"{label}启动后前端进程已退出，正在清理...", 'WARNING')
            if self._process and self._process.poll() is None:
                self._kill_process_tree(self._process.pid)
            self._mode, self._process, self._frontend_process = 'none', None, None
            self._current_mode_key = ""
            self._update_all_ui()
            self.status_bar_label.config(text="前端启动失败，已停止")
            return
        self._mode = mode
        self._update_all_ui()
        self.status_bar_label.config(text=f"{label}运行中")
        self.log_message(f"{label}启动成功")
        self.log_message(f"  → 后端: http://localhost:{_API_PORT}")
        if frontend_alive:
            self.log_message(f"  → 前端: http://localhost:{_WEB_PORT}")
        elif is_prod:
            self.log_message(f"  → 前端: 由 Nginx 提供服务 (dist/)")

    def _on_dual_failed(self, mode, label, reason):
        self.log_message(f"{label}启动失败: {reason}", 'ERROR')
        self._mode, self._process, self._frontend_process = 'none', None, None
        self._current_mode_key = ""
        self._update_all_ui()
        self.status_bar_label.config(text=f"{label}启动失败: {reason}")

    def _mode_label(self):
        return {'debug': '调试模式', 'production': '生产模式', 'dual_dev': '开发模式（前后端）', 'dual_prod': '生产模式（前后端）', 'restarting': '重启中', 'starting': '启动中', 'stopping': '停止中'}.get(self._mode, '')

    def _update_redis_status(self):
        if self._redis_check_after_id:
            try:
                self.root.after_cancel(self._redis_check_after_id)
            except Exception:
                pass
        def _check_and_update():
            try:
                is_running = self._is_redis_running()
                redis_exe, _ = self._find_redis()
                def _do_update():
                    try:
                        if is_running:
                            self._redis_status_label.config(text='Redis: 运行中', fg=self._PALETTE['success'])
                        elif redis_exe:
                            self._redis_status_label.config(text='Redis: 已停止', fg=self._PALETTE['danger'])
                        else:
                            self._redis_status_label.config(text='Redis: 未安装', fg=self._PALETTE['text_dim'])
                    except Exception:
                        pass
                    self._redis_check_after_id = None
                self.root.after(0, _do_update)
            except Exception:
                self._redis_check_after_id = None
        self._redis_check_after_id = self.root.after(500, lambda: threading.Thread(target=_check_and_update, daemon=True).start())

    def _update_all_ui(self):
        is_dual_dev, is_dual_prod = self._mode == 'dual_dev', self._mode == 'dual_prod'
        is_starting, is_restarting, is_stopping = self._mode == 'starting', self._mode == 'restarting', self._mode == 'stopping'
        is_none = self._mode == 'none'
        is_busy = not is_none
        current_mode_key = self._current_mode_key
        self._update_card_ui('dual_dev', is_dual_dev, is_none, is_starting and current_mode_key == 'dual_dev', is_restarting and current_mode_key == 'dual_dev')
        self._update_card_ui('dual_prod', is_dual_prod, is_none, is_starting and current_mode_key == 'dual_prod', is_restarting and current_mode_key == 'dual_prod')
        # stop_all总是可用，作为紧急重置
        self.stop_all_btn.config(state='normal')
        self._update_status_indicator(is_busy=is_busy, is_active=(is_dual_dev or is_dual_prod))
        self._update_redis_status()
        if is_none:
            self.status_bar_label.config(text="就绪")
        elif self._mode in ('restarting', 'starting', 'stopping'):
            self.status_bar_label.config(text=f"{self._mode_label()}...")

    def _update_card_ui(self, mode_key, is_active, is_none, is_starting=False, is_restarting=False):
        status = getattr(self, f'{mode_key}_status')
        pid = getattr(self, f'{mode_key}_pid')
        start_btn = getattr(self, f'{mode_key}_start_btn')
        restart_btn = getattr(self, f'{mode_key}_restart_btn')
        status_dot = getattr(self, f'{mode_key}_status_dot')
        state = 'starting' if is_starting else 'restarting' if is_restarting else 'active' if is_active else 'stopped'
        state_config = {'starting': ('启动中...', 'accent', True), 'restarting': ('重启中...', 'accent', True), 'active': ('运行中', 'success', True), 'stopped': ('已停止', 'danger', False)}
        status_text, color_key, dot_active = state_config[state]
        status_color = self._PALETTE[color_key]
        status.config(text=status_text, foreground=status_color)
        status_dot.set_color(status_color, active=dot_active)
        if is_active and mode_key in ('dual_dev', 'dual_prod'):
            backend_pid = self._process.pid if self._process else None
            frontend_pid = self._frontend_process.pid if self._frontend_process else None
            pid_text = f"B:{backend_pid} F:{frontend_pid}" if backend_pid and frontend_pid else f"B:{backend_pid}" if backend_pid else f"F:{frontend_pid}" if frontend_pid else "PID: —"
        elif is_active and self._process:
            pid_text = f"PID: {self._process.pid}"
        else:
            pid_text = "PID: —"
        pid.config(text=pid_text)
        start_btn.config(state='normal')  # 始终允许点击，给用户重置机会
        restart_btn.config(state='disabled' if (not is_active or is_starting or is_restarting) else 'normal')

    def check_server_status(self):
        if self._mode in ('none', 'restarting', 'starting'):
            self._after_ids['status'] = self.root.after(self._check_interval, self.check_server_status)
            return
        backend_crashed = self._process and self._process.poll() is not None
        frontend_crashed = self._mode in ('dual_dev', 'dual_prod') and self._frontend_process and self._frontend_process.poll() is not None
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
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except Exception:
                        pass
        except Exception:
            pass

    def on_closing(self):
        if self._tray_icon:
            self.root.withdraw()
        else:
            self._do_quit()

    def _build_ui(self):
        self.root.configure(bg=self._PALETTE['bg_main'])
        header = tk.Frame(self.root, bg=self._PALETTE['bg_header'], height=64)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        hdr_inner = tk.Frame(header, bg=self._PALETTE['bg_header'])
        hdr_inner.pack(fill=tk.X, padx=28, pady=(16, 0))
        brand = tk.Frame(hdr_inner, bg=self._PALETTE['bg_header'])
        brand.pack(side=tk.LEFT)
        tk.Label(brand, text='ERP', font=('Segoe UI', 16, 'bold'), fg=self._PALETTE['accent'], bg=self._PALETTE['bg_header']).pack(side=tk.LEFT)
        tk.Label(brand, text='Server Manager', font=('Segoe UI', 16), fg=self._PALETTE['text_primary'], bg=self._PALETTE['bg_header']).pack(side=tk.LEFT, padx=(6, 0))
        ver_frame = tk.Frame(hdr_inner, bg=self._PALETTE['bg_input'], highlightbackground=self._PALETTE['border'], highlightthickness=1)
        ver_frame.pack(side=tk.LEFT, padx=(12, 0))
        tk.Label(ver_frame, text=_VERSION, font=('Consolas', 8), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_input']).pack(padx=8, pady=1)
        port_frame = tk.Frame(hdr_inner, bg=self._PALETTE['bg_header'])
        port_frame.pack(side=tk.RIGHT)
        for label, port, color in [('API', _API_PORT, 'accent'), ('WEB', _WEB_PORT, 'success')]:
            tk.Label(port_frame, text=label, font=('Consolas', 8), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_header']).pack(side=tk.LEFT)
            tk.Label(port_frame, text=str(port), font=('Consolas', 11, 'bold'), fg=self._PALETTE[color], bg=self._PALETTE['bg_header']).pack(side=tk.LEFT, padx=(4, 8 if label == 'API' else 0))
        tk.Frame(self.root, bg=self._PALETTE['accent'], height=1).pack(fill=tk.X)
        tk.Frame(self.root, bg=self._PALETTE['border'], height=1).pack(fill=tk.X)
        self._build_status_bar()
        content = tk.Frame(self.root, bg=self._PALETTE['bg_main'])
        content.pack(fill=tk.BOTH, expand=True, padx=24, pady=(16, 12))
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=0)
        content.rowconfigure(1, weight=0)
        content.rowconfigure(2, weight=1)
        self._build_server_card(content, 0, 0, '开发模式（前后端）', 'dual_dev', 'FastAPI + Vue3/Vite · 后端 5002 · 前端 3000', 'dual_dev', self.start_dual_dev, self.stop_dual_dev, self.restart_dual_dev)
        self._build_server_card(content, 0, 1, '生产模式（前后端）', 'dual_prod', 'FastAPI + Uvicorn + Nginx/Vue3 · 后端 5002', 'dual_prod', self.start_dual_prod, self.stop_dual_prod, self.restart_dual_prod)
        self._build_global_stop(content)
        self._build_log_section(content)

    def _card(self, parent, row, col):
        card = tk.Frame(parent, bg=self._PALETTE['bg_card'], highlightbackground=self._PALETTE['border_card'], highlightthickness=1)
        card.grid(row=row, column=col, sticky='nsew', padx=(0, 12) if col == 0 else (0, 0))
        self._server_cards.append(card)
        return card

    def _build_server_card(self, parent, row, col, title, script_label, desc, mode_key, start_cmd, stop_cmd, restart_cmd):
        card = self._card(parent, row, col)
        mode_color = self._PALETTE['info']
        icon_text = 'FD' if mode_key in ('dual_dev', 'dual_prod') else 'D' if mode_key == 'debug' else 'P'
        tk.Frame(card, bg=mode_color, height=2).pack(fill=tk.X)
        hdr = tk.Frame(card, bg=self._PALETTE['bg_card'])
        hdr.pack(fill=tk.X, padx=22, pady=(14, 0))
        icon_frame = tk.Frame(hdr, bg=mode_color, width=28, height=28)
        icon_frame.pack(side=tk.LEFT, padx=(0, 10))
        icon_frame.pack_propagate(False)
        tk.Label(icon_frame, text=icon_text, font=('Consolas', 11, 'bold'), fg='#0a0a0f', bg=mode_color).place(relx=0.5, rely=0.5, anchor='center')
        title_col = tk.Frame(hdr, bg=self._PALETTE['bg_card'])
        title_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(title_col, text=title, font=('Microsoft YaHei UI', 13, 'bold'), fg=self._PALETTE['text_primary'], bg=self._PALETTE['bg_card'], anchor='w').pack(anchor='w')
        tk.Label(title_col, text=desc, font=('Microsoft YaHei UI', 8), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_card'], anchor='w').pack(anchor='w')
        tk.Label(hdr, text=script_label, font=('Consolas', 8), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_card']).pack(side=tk.RIGHT)
        tk.Frame(card, bg=self._PALETTE['border'], height=1).pack(fill=tk.X, padx=22, pady=(12, 0))
        st = tk.Frame(card, bg=self._PALETTE['bg_card'])
        st.pack(fill=tk.X, padx=22, pady=(10, 0))
        status_dot = StatusDot(st, size=10, color=self._PALETTE['danger'], canvas_bg=self._PALETTE['bg_card'])
        status_dot.pack(side=tk.LEFT, padx=(0, 8))
        status_label = tk.Label(st, text='已停止', font=('Microsoft YaHei UI', 10, 'bold'), fg=self._PALETTE['danger'], bg=self._PALETTE['bg_card'])
        status_label.pack(side=tk.LEFT)
        pid_label = tk.Label(st, text='PID: —', font=('Consolas', 9), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_card'])
        pid_label.pack(side=tk.RIGHT)
        btns = tk.Frame(card, bg=self._PALETTE['bg_card'])
        btns.pack(fill=tk.X, padx=22, pady=(14, 18))
        start_btn = RoundedButton(btns, text='  启动  ', fill=self._PALETTE['success'], hover_fill=self._PALETTE['success_h'], fg='#ffffff', command=start_cmd, canvas_bg=self._PALETTE['bg_card'], radius=8, pady=7)
        start_btn.pack(side=tk.LEFT, padx=(0, 8))
        restart_btn = RoundedButton(btns, text='  重启  ', fill=self._PALETTE['accent'], hover_fill=self._PALETTE['accent_h'], fg='#ffffff', command=restart_cmd, state='disabled', canvas_bg=self._PALETTE['bg_card'], radius=8, pady=7)
        restart_btn.pack(side=tk.LEFT)
        setattr(self, f'{mode_key}_status', status_label)
        setattr(self, f'{mode_key}_pid', pid_label)
        setattr(self, f'{mode_key}_start_btn', start_btn)
        setattr(self, f'{mode_key}_restart_btn', restart_btn)
        setattr(self, f'{mode_key}_status_dot', status_dot)

    def _build_global_stop(self, parent):
        frame = tk.Frame(parent, bg=self._PALETTE['bg_main'])
        frame.grid(row=1, column=0, columnspan=2, pady=(10, 6))
        self.stop_all_btn = RoundedButton(frame, text='  全部停止  ', fill=self._PALETTE['danger'], hover_fill=self._PALETTE['danger_h'], fg='#ffffff', command=self.stop_all, state='disabled', canvas_bg=self._PALETTE['bg_main'], padx=40, pady=9, radius=8, font=('Microsoft YaHei UI', 10, 'bold'))
        self.stop_all_btn.pack()

    def _build_log_section(self, parent):
        log_card = tk.Frame(parent, bg=self._PALETTE['bg_card'], highlightbackground=self._PALETTE['border_card'], highlightthickness=1)
        log_card.grid(row=2, column=0, columnspan=2, sticky='nsew', pady=(4, 0))
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(1, weight=1)
        log_hdr = tk.Frame(log_card, bg=self._PALETTE['bg_card'])
        log_hdr.grid(row=0, column=0, sticky='ew', padx=20, pady=(12, 0))
        tk.Label(log_hdr, text='控制台', font=('Microsoft YaHei UI', 11, 'bold'), fg=self._PALETTE['text_primary'], bg=self._PALETTE['bg_card']).pack(side=tk.LEFT)
        tk.Label(log_hdr, text='实时输出', font=('Microsoft YaHei UI', 8), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_card']).pack(side=tk.LEFT, padx=(8, 0))
        log_btns = tk.Frame(log_hdr, bg=self._PALETTE['bg_card'])
        log_btns.pack(side=tk.RIGHT)
        for txt, cmd in [('导出', self.export_log), ('清空', self.clear_log)]:
            tk.Button(log_btns, text=txt, font=('Microsoft YaHei UI', 8), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_input'], activebackground=self._PALETTE['border'], activeforeground=self._PALETTE['text_primary'], relief=tk.FLAT, bd=0, cursor='hand2', padx=10, pady=2, command=cmd).pack(side=tk.RIGHT, padx=(4, 0))
        log_body = tk.Frame(log_card, bg=self._PALETTE['bg_log'], highlightbackground=self._PALETTE['border'], highlightthickness=1)
        log_body.grid(row=1, column=0, sticky='nsew', padx=14, pady=(8, 14))
        log_body.columnconfigure(0, weight=1)
        log_body.rowconfigure(0, weight=1)
        log_font = ('Microsoft YaHei UI', 9)
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
        self._status_dot_bar = tk.Canvas(left, width=8, height=8, highlightthickness=0, bg=self._PALETTE['bg_surface'])
        self._status_dot_bar.pack(side=tk.LEFT, padx=(0, 6))
        self._status_dot_item = self._status_dot_bar.create_oval(1, 1, 7, 7, fill=self._PALETTE['success'], outline='')
        self.status_bar_label = tk.Label(left, text='就绪', font=('Microsoft YaHei UI', 9), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_surface'])
        self.status_bar_label.pack(side=tk.LEFT)
        right = tk.Frame(bar, bg=self._PALETTE['bg_surface'])
        right.pack(side=tk.RIGHT, padx=20, pady=5)
        self._redis_status_label = tk.Label(right, text='Redis: 检查中', font=('Consolas', 8), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_surface'])
        self._redis_status_label.pack(side=tk.RIGHT, padx=(8, 0))
        tk.Label(right, text=f'API:{_API_PORT} WEB:{_WEB_PORT}', font=('Consolas', 8), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_surface']).pack(side=tk.RIGHT)

    def _update_status_indicator(self, is_busy, is_active):
        color = self._PALETTE['success'] if is_active else self._PALETTE['warning'] if is_busy else self._PALETTE['info']
        if self._status_anim_after_id:
            try:
                self.root.after_cancel(self._status_anim_after_id)
            except Exception:
                pass
            self._status_anim_after_id = None
        self._status_pulse_step = 0
        try:
            self._status_dot_bar.coords(self._status_dot_item, 1, 1, 7, 7)
            self._status_dot_bar.itemconfig(self._status_dot_item, fill=color)
        except Exception:
            return
        if is_busy or is_active:
            speed_ms = 500 if is_active else 300
            def pulse():
                self._status_pulse_step = (self._status_pulse_step + 1) % 60
                inset = 1 + int((math.sin(self._status_pulse_step / 60.0 * 2 * math.pi) + 1) * 0.8)
                try:
                    self._status_dot_bar.coords(self._status_dot_item, inset, inset, 8 - inset, 8 - inset)
                    self._status_dot_bar.itemconfig(self._status_dot_item, fill=color)
                except Exception:
                    return
                self._status_anim_after_id = self.root.after(speed_ms, pulse)
            pulse()


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
        try:
            messagebox.showerror("启动失败", f"服务器管理器启动失败:\n{str(e)}" + (f"\n\n日志: {crash_file}" if crash_file else ""))
        except Exception:
            pass
        sys.exit(1)


if __name__ == '__main__':
    main()
