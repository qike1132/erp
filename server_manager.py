"""
ERP 服务器管理器 GUI v3.4
功能:
  - 图形化管理调试模式 (run.py) 和生产模式 (start_production_optimized.py)
  - 单实例限制 — 同一时间只能运行一个管理器
  - 窗口居中显示 (无闪烁，小屏幕自适应)
  - 系统托盘集成 — 关闭按钮隐藏到托盘，最小化保留任务栏图标
  - 性能优化 — 批量日志写入、队列通信、主线程零阻塞
  - 日志自动清理
  - 现代简约 UI — Catppuccin Mocha 配色体系
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
from datetime import datetime
from pathlib import Path

# Windows平台特殊处理
if sys.platform == 'win32':
    import io
    if sys.stdout and hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    if sys.stderr and hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import tkinter as tk
from tkinter import ttk, messagebox


# ============================================================
# 全局常量
# ============================================================
_VERSION = 'v3.4'
_WINDOW_TITLE = f'ERP 服务器管理器 {_VERSION}'


# ============================================================
# 单实例限制 — Windows 命名互斥体
# ============================================================
_mutex_handle = None

def _ensure_single_instance():
    """确保只有一个实例运行。返回 True 表示当前是首个实例。"""
    global _mutex_handle
    if sys.platform != 'win32':
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # 基于用户目录生成互斥体名，避免硬编码可预测名称被 DoS
        user_hash = hashlib.sha256(os.environ.get('USERPROFILE', str(Path.home())).encode()).hexdigest()[:8]
        mutex_name = f'ERP_Server_Manager_{user_hash}_v1'
        handle = kernel32.CreateMutexW(None, False, mutex_name)
        last_err = ctypes.GetLastError()
        if last_err == 183:
            return False
        _mutex_handle = handle
        return True
    except Exception as e:
        logging.warning(f"互斥体创建异常: {e}")
        return True


def _activate_existing_window():
    """查找并激活已存在的管理器窗口"""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, _WINDOW_TITLE)
        if hwnd:
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
    except Exception as e:
        logging.debug(f"激活已有窗口失败: {e}")


# ============================================================
# 解析项目路径与 Python 解释器
# ============================================================
def _get_project_dir():
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        if (exe_dir / 'fastapi_app').is_dir():
            return exe_dir
        path_cfg = exe_dir / 'erp_project_path.txt'
        if path_cfg.is_file():
            cfg_text = path_cfg.read_text(encoding='utf-8').strip()
            if cfg_text:
                cfg_path = Path(cfg_text).resolve()
                if cfg_path.is_dir() and (cfg_path / 'fastapi_app').is_dir():
                    return cfg_path
        for candidate in [Path(r'd:\erp_system')]:
            if candidate.is_dir() and (candidate / 'fastapi_app').is_dir():
                return candidate
        return exe_dir
    return Path(__file__).resolve().parent

_PROJECT_DIR = _get_project_dir()


def _get_python_executable():
    project_dir = _PROJECT_DIR
    venv_python = project_dir / '.venv313' / 'Scripts' / 'python.exe'
    if sys.platform != 'win32':
        venv_python = project_dir / '.venv313' / 'bin' / 'python'
    if venv_python.is_file() and os.path.normpath(sys.executable) != os.path.normpath(str(venv_python)):
        return str(venv_python)
    if getattr(sys, 'frozen', False):
        py_exe = Path(os.environ.get('SYSTEMROOT', r'C:\Windows')) / 'py.exe'
        if py_exe.is_file():
            return str(py_exe)
        python_in_path = shutil.which('python')
        if python_in_path:
            return python_in_path
        return sys.executable
    return sys.executable

_PYTHON_EXE = _get_python_executable()


def _font_exists(name):
    """检测字体是否可用"""
    try:
        import tkinter.font as tkfont
        root = tk._default_root or tk.Tk()
        return name in tkfont.families(root)
    except Exception:
        return False


# ============================================================
# 圆角按钮组件 — 参考 CustomTkinter 风格
# ============================================================
class RoundedButton(tk.Canvas):
    """基于 Canvas 的圆角按钮 — 14px 大圆角，柔和阴影"""

    def __init__(self, parent, text='', fill='#89b4fa', fg='#1e1e2e',
                 hover_fill=None, command=None,
                 font=('Microsoft YaHei UI', 10),
                 padx=24, pady=8, radius=14,
                 state='normal', canvas_bg=None, **kw):
        tmp = tk.Label(parent, text=text, font=font)
        tmp.update_idletasks()
        tw, th = tmp.winfo_reqwidth(), tmp.winfo_reqheight()
        tmp.destroy()

        w, h = tw + padx * 2, th + pady * 2
        canvas_bg = canvas_bg or '#1e1e2e'

        super().__init__(parent, width=w, height=h,
                         highlightthickness=0, cursor='hand2',
                         bg=canvas_bg, **kw)

        self._text = text
        self._fill = fill
        self._fg = fg
        self._hover_fill = hover_fill or self._shift(fill, -20)
        self._font = font
        self._radius = radius
        self._command = command
        self._state = state
        self._hover = False

        self.bind('<Configure>', self._draw)
        self.bind('<Enter>', lambda e: self._hover_in())
        self.bind('<Leave>', lambda e: self._hover_out())
        self.bind('<ButtonRelease-1>', lambda e: self._click())

    @staticmethod
    def _shift(hex_c, amount):
        r = max(0, min(255, int(hex_c[1:3], 16) + amount))
        g = max(0, min(255, int(hex_c[3:5], 16) + amount))
        b = max(0, min(255, int(hex_c[5:7], 16) + amount))
        return f'#{r:02x}{g:02x}{b:02x}'

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1+r, y1, x2-r, y1, x2, y1,
               x2, y1+r, x2, y2-r, x2, y2,
               x2-r, y2, x1+r, y2, x1, y2,
               x1, y2-r, x1, y1+r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _draw(self, _=None):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        r = min(self._radius, w // 2, h // 2)

        if self._state == 'disabled':
            bg, fg = '#45475a', '#6c7086'
        elif self._hover:
            bg, fg = self._hover_fill, self._fg
        else:
            bg, fg = self._fill, self._fg

        self._round_rect(0, 0, w, h, r, fill=bg, outline='')
        self.create_text(w // 2, h // 2, text=self._text,
                         fill=fg, font=self._font)

    def _hover_in(self):
        if self._state == 'disabled':
            return
        self._hover = True
        self._draw()

    def _hover_out(self):
        self._hover = False
        self._draw()

    def _click(self):
        if self._state == 'normal' and self._command:
            self._command()

    def config(self, **kw):
        if 'state' in kw:
            self._state = kw.pop('state')
            kw['cursor'] = 'arrow' if self._state == 'disabled' else 'hand2'
        if 'text' in kw:
            self._text = kw.pop('text')
        super().config(**kw)
        self._draw()


# ============================================================
# 系统托盘支持
# ============================================================
def _create_tray_icon_image():
    """创建托盘图标 — Catppuccin Blue 圆点"""
    try:
        from PIL import Image, ImageDraw
        img = Image.new('RGBA', (16, 16), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, 14, 14], fill=(137, 180, 250, 255))  # Catppuccin Blue
        return img
    except Exception:
        return None


# ============================================================
# 主应用 — Catppuccin Mocha 配色体系
# 参考: CustomTkinter (现代圆角), Catppuccin (配色), ttkbootstrap (组件风格)
# ============================================================
class ServerManagerApp:
    """ERP 服务器管理器 — 调试/生产双模式"""

    # Catppuccin Mocha 完整调色板
    _PALETTE = {
        # 基础色
        'bg_main':      '#11111b',   # Crust — 最深背景
        'bg_card':      '#1e1e2e',   # Base  — 卡片/面板背景
        'bg_surface':   '#181825',   # Mantle — 中间层背景
        'bg_header':    '#11111b',   # Crust — 头部背景
        'bg_log':       '#11111b',   # Crust — 日志区背景
        'bg_input':     '#313244',   # Surface0 — 输入框/按钮区背景

        # 文字色
        'text_primary': '#cdd6f4',   # Text — 主文字
        'text_secondary':'#bac2de',  # Subtext1 — 副文字
        'text_dim':     '#6c7086',   # Overlay0 — 弱化文字

        # 边框与分割
        'border':       '#313244',   # Surface0

        # 语义色 — Catppuccin
        'accent':       '#89b4fa',   # Blue
        'accent_h':     '#74c7ec',   # Sapphire
        'success':      '#a6e3a1',   # Green
        'success_h':    '#94e2d5',   # Teal
        'danger':       '#f38ba8',   # Red
        'danger_h':     '#eba0ac',   # Maroon
        'warning':      '#fab387',   # Peach
        'info':         '#89dceb',   # Sky

        # 日志色 — Catppuccin
        'log_fg':       '#cdd6f4',   # Text
        'log_info':     '#89b4fa',   # Blue
        'log_error':    '#f38ba8',   # Red
        'log_warn':     '#fab387',   # Peach
    }

    MAX_LOG_LINES  = 500
    LOG_KEEP_LINES = 300
    LOG_CLEANUP_MS = 120000
    LOG_FLUSH_MS   = 150

    def __init__(self, root):
        self.root = root
        self.root.title(_WINDOW_TITLE)
        self.root.geometry("960x720")
        self.root.minsize(800, 600)
        self.root.resizable(True, True)

        # 先隐藏窗口，居中后再显示，避免闪烁
        self.root.withdraw()

        self._mode = 'none'
        self._process = None

        self._log_buffer = []
        self._flush_pending = False

        self._msg_queue = queue.Queue()

        self.setup_logging()
        self._build_ui()
        self._set_window_icon()

        self._center_window()
        self.root.deiconify()

        self._check_interval = 5000
        self._after_ids = {}  # 存储定时器回调 ID，退出时统一取消
        self.check_server_status()

        self._schedule_log_cleanup()
        self._schedule_log_flush()
        self._poll_queue()

        self._tray_icon = None
        self._init_tray()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self._ui_ready = True

        self.logger.info(f"服务器管理器已启动 ({_VERSION})")

    # ── 窗口居中 ──────────────────────────────────────────

    def _center_window(self):
        self.root.update_idletasks()
        geo = self.root.geometry()
        try:
            w_h = geo.split('+')[0]
            w, h = w_h.split('x')
            w, h = int(w), int(h)
        except (ValueError, IndexError):
            w, h = 960, 720
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        # 小屏幕自适应：窗口不超过屏幕 95%
        w = min(w, sw - 40)
        h = min(h, sh - 80)
        self.root.geometry(f'+{max(0,(sw-w)//2)}+{max(0,(sh-h)//2)}')

    # ── 系统托盘 ──────────────────────────────────────────

    def _init_tray(self):
        try:
            import pystray  # pystray 依赖 Pillow，局部导入兼容未安装环境
            icon_image = _create_tray_icon_image()
            if icon_image is None:
                return
            self._tray_image = icon_image  # 持有引用，防止 GC 回收图标图像
            menu = pystray.Menu(
                pystray.MenuItem('显示窗口', self._show_window, default=True),
                pystray.MenuItem('退出', self._quit_from_tray),
            )
            self._tray_icon = pystray.Icon(
                'ERP服务器管理器', icon_image, 'ERP 服务器管理器', menu)
            threading.Thread(target=self._tray_icon.run, daemon=True).start()
        except Exception as e:
            self.logger.info(f"托盘初始化跳过: {e}")

    def _set_window_icon(self):
        """设置窗口图标，确保任务栏显示自定义图标"""
        try:
            from PIL import ImageTk
            icon_image = _create_tray_icon_image()
            if icon_image:
                # 生成更大尺寸用于窗口图标（32x32 用于任务栏/DPI 适配）
                icon_image = icon_image.resize((32, 32))
                self._window_icon = ImageTk.PhotoImage(icon_image)
                self.root.iconphoto(True, self._window_icon)
        except Exception:
            pass

    def _show_window(self, icon=None, item=None):
        self.root.after(0, self._do_show_window)

    def _do_show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _quit_from_tray(self, icon=None, item=None):
        self.root.after(0, self._do_quit)

    def _do_quit(self):
        """从托盘退出 — 唯一退出入口"""
        if self._mode != 'none':
            self._stop_process()
            self._mode = 'none'
        self._kill_tray()
        # 取消所有定时器回调
        for aid in self._after_ids.values():
            try:
                self.root.after_cancel(aid)
            except Exception:
                pass
        self._after_ids.clear()
        # 释放互斥体句柄
        global _mutex_handle
        if _mutex_handle and sys.platform == 'win32':
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
                self.root.update()  # 确保 stop 消息被处理，防止托盘图标残留
            except Exception:
                pass

    # ── 日志 ──────────────────────────────────────────────

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
        entry = f"[{timestamp}] {level}: {message}\n"
        self._log_buffer.append((entry, level))
        fn = getattr(self.logger, level.lower(), None) or self.logger.warning
        if fn:
            fn(message)
        if not self._flush_pending:
            self._flush_pending = True
            self.root.after_idle(self._do_flush)

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
        filename = filedialog.asksaveasfilename(
            initialdir=log_dir,
            initialfile=f"server_log_{datetime.now():%Y%m%d_%H%M%S}.txt",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
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

    # ── 进程管理 ──────────────────────────────────────────

    def _stop_process(self):
        """安全终止当前管理的子进程（含进程树），不影响其他 Python 程序。
        注意: 不设置 _mode，由调用者决定模式状态。"""
        proc = self._process
        if proc and proc.poll() is None:
            pid = proc.pid
            self.log_message(f"正在终止进程 (PID: {pid})...")
            try:
                if sys.platform == 'win32':
                    result = subprocess.run(
                        ['taskkill', '/F', '/T', '/PID', str(pid)],
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        capture_output=True, timeout=10)
                    if result.returncode != 0:
                        self.log_message(f"taskkill 返回码: {result.returncode}", 'WARNING')
                else:
                    proc.terminate()
                    proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                self.log_message(f"进程 (PID: {pid}) 超时，已强制 kill", 'WARNING')
            except Exception as e:
                self.log_message(f"终止进程异常: {str(e)}", 'ERROR')
        self._process = None
        self._msg_queue.put(('ui_update', {}))

    def _start_server(self, script_name, mode_label):
        if self._mode != 'none':
            messagebox.showwarning("警告",
                f"当前已有 {self._mode_label()} 在运行，请先停止后再启动")
            return
        script = str(_PROJECT_DIR / script_name)
        if not Path(script).is_file():
            self.log_message(f"启动脚本不存在: {script}", 'ERROR')
            messagebox.showerror("错误", f"启动脚本不存在:\n{script}")
            return
        self.log_message(f"正在启动{mode_label}...")
        self.status_bar_label.config(text=f"正在启动{mode_label}...")
        self._mode = 'starting'
        self._update_all_ui()
        threading.Thread(target=self._start_thread,
                         args=(script, mode_label),
                         daemon=True).start()

    def _start_thread(self, script, mode_label):
        if self._mode not in ('starting', 'restarting'):  # 被 stop 取消，放弃启动
            return
        try:
            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'
            env['PYTHONIOENCODING'] = 'utf-8'
            env['PYTHONUTF8'] = '1'
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            self._process = subprocess.Popen(
                [_PYTHON_EXE, script],
                cwd=str(_PROJECT_DIR), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=creationflags,
                text=True, encoding='utf-8', errors='replace')
            self._msg_queue.put(('log', {'text': f"进程已启动 (PID: {self._process.pid})"}))
            threading.Thread(target=self._read_stdout,
                             args=(self._process,), daemon=True).start()
            # 轮询检测进程初始化状态，最多 3 秒
            alive = True
            for _ in range(6):
                if self._process.poll() is not None:
                    alive = False
                    break
                time.sleep(0.5)
            if alive:
                self._msg_queue.put(('started', {'label': mode_label}))
            else:
                self._msg_queue.put(('log', {'text': f"{mode_label}进程启动后立即退出", 'level': 'ERROR'}))
                self._msg_queue.put(('status', {'text': f"{mode_label}启动失败"}))
        except Exception as e:
            self._msg_queue.put(('log', {'text': f"启动异常: {str(e)}", 'level': 'ERROR'}))
            self._msg_queue.put(('status', {'text': f"{mode_label}启动失败"}))

    def _read_stdout(self, proc):
        try:
            if proc.stdout:
                try:
                    for line in proc.stdout:
                        line = line.strip()
                        if line:
                            self._msg_queue.put(('log', {'text': line}))
                finally:
                    proc.stdout.close()
        except Exception as e:
            self._msg_queue.put(('log', {'text': f"读取日志异常: {str(e)}", 'level': 'ERROR'}))

    def _on_started(self, mode_label):
        if not self._process or self._process.poll() is not None:
            self.log_message(f"{mode_label}启动后进程已退出", 'ERROR')
            self._mode = 'none'
            self._process = None
            self._update_all_ui()
            return
        self._mode = 'debug' if '调试' in mode_label else 'production'
        self._update_all_ui()
        self.status_bar_label.config(text=f"{mode_label}运行中")
        self.log_message(f"{mode_label}启动成功 — http://localhost:5002  http://localhost:5003")

    def _poll_queue(self):
        processed = 0
        while not self._msg_queue.empty() and processed < 30:
            try:
                msg_type, data = self._msg_queue.get_nowait()
            except queue.Empty:
                break
            if msg_type == 'log':
                self.log_message(data['text'], data.get('level', 'INFO'))
            elif msg_type == 'started':
                self._on_started(data['label'])
            elif msg_type == 'ui_update':
                self._update_all_ui()
            elif msg_type == 'status':
                self.status_bar_label.config(text=data['text'])
            processed += 1
        self._after_ids['poll'] = self.root.after(100, self._poll_queue)

    # ── 对外接口 ──

    def start_debug(self):
        self._start_server('run.py', '调试模式')

    def start_production(self):
        self._start_server('start_production_optimized.py', '生产模式')

    def stop_debug(self):
        self._stop_mode('debug', '调试模式')

    def stop_production(self):
        self._stop_mode('production', '生产模式')

    def _stop_mode(self, mode, label):
        if self._mode == mode:
            self._stop_process()
            self._mode = 'none'
            self.log_message(f"{label}已停止")
        else:
            self.log_message(f"{label}未运行")

    def stop_all(self):
        if self._mode != 'none':
            self._stop_process()
            self._mode = 'none'
            self.log_message("所有服务器已停止")

    def restart_debug(self):
        self.log_message("正在重启调试模式...")
        threading.Thread(target=self._restart_thread, args=('debug',), daemon=True).start()

    def restart_production(self):
        self.log_message("正在重启生产模式...")
        threading.Thread(target=self._restart_thread, args=('production',), daemon=True).start()

    def _restart_thread(self, mode):
        self._mode = 'restarting'
        self._msg_queue.put(('ui_update', {}))
        self._stop_process()
        self._mode = 'restarting'  # _stop_process 不设 mode，此处恢复 restarting
        time.sleep(1)  # 等待操作系统释放端口（taskkill /F 后通常 <500ms）
        if mode == 'debug':
            self._start_thread(str(_PROJECT_DIR / 'run.py'), '调试模式')
        else:
            self._start_thread(str(_PROJECT_DIR / 'start_production_optimized.py'), '生产模式')

    def _mode_label(self):
        return {'debug': '调试模式', 'production': '生产模式',
                'restarting': '重启中', 'starting': '启动中'}.get(self._mode, '')

    # ── UI 状态同步 ──

    def _update_all_ui(self):
        is_debug = self._mode == 'debug'
        is_prod  = self._mode == 'production'
        is_none  = self._mode == 'none'
        is_busy  = not is_none  # 运行中或重启中，禁止启动

        self._update_card_ui('debug', is_debug, is_none)
        self._update_card_ui('production', is_prod, is_none)

        self.stop_all_btn.config(state='normal' if is_busy else 'disabled')

        if is_none:
            self.status_bar_label.config(text="就绪")
        elif self._mode in ('restarting', 'starting'):
            self.status_bar_label.config(text=f"{self._mode_label()}...")

    def _update_card_ui(self, mode_key, is_active, is_none):
        """更新单个服务器卡片的 UI 状态"""
        status = getattr(self, f'{mode_key}_status')
        pid = getattr(self, f'{mode_key}_pid')
        start_btn = getattr(self, f'{mode_key}_start_btn')
        stop_btn = getattr(self, f'{mode_key}_stop_btn')
        restart_btn = getattr(self, f'{mode_key}_restart_btn')

        status.config(
            text="● 运行中" if is_active else "● 已停止",
            foreground=self._PALETTE['success'] if is_active else self._PALETTE['danger'])
        pid.config(
            text=f"PID: {self._process.pid}" if is_active and self._process else "PID: —")
        start_btn.config(state='normal' if is_none else 'disabled')
        stop_btn.config(state='normal' if is_active else 'disabled')
        restart_btn.config(state='normal' if is_active else 'disabled')

    def check_server_status(self):
        if self._process and self._process.poll() is not None:
            if self._mode not in ('none', 'restarting', 'starting'):
                code = self._process.poll()
                label = self._mode_label()  # 先保存，重置 _mode 后 _mode_label() 会返回空
                self.log_message(
                    f"{label}进程意外终止 (退出码: {code})", 'ERROR')
                self._mode = 'none'
                self._process = None
                self._update_all_ui()
                # 延迟弹窗避免阻塞消息队列处理
                self.root.after(100, lambda: messagebox.showwarning("警告",
                    f"{label}意外停止，请检查日志"))
        self._after_ids['status'] = self.root.after(self._check_interval, self.check_server_status)

    def on_closing(self):
        if self._tray_icon:
            self.root.withdraw()
        else:
            self._do_quit()

    # ================================================================
    #  UI 构建 — Catppuccin Mocha 暗色主题
    # ================================================================

    def _build_ui(self):
        self.root.configure(bg=self._PALETTE['bg_main'])

        # ── 标题栏 ──
        header = tk.Frame(self.root, bg=self._PALETTE['bg_header'], height=64)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        hdr_inner = tk.Frame(header, bg=self._PALETTE['bg_header'])
        hdr_inner.pack(fill=tk.X, padx=24, pady=(12, 0))

        tk.Label(hdr_inner, text='ERP 服务器管理器',
                 font=('Microsoft YaHei UI', 15, 'bold'),
                 fg=self._PALETTE['text_primary'],
                 bg=self._PALETTE['bg_header']).pack(side=tk.LEFT)

        tk.Label(hdr_inner, text=_VERSION,
                 font=('Microsoft YaHei UI', 10),
                 fg=self._PALETTE['text_dim'],
                 bg=self._PALETTE['bg_header']).pack(side=tk.LEFT, padx=(10, 0))

        tk.Label(hdr_inner,
                 text='FastAPI :5002  ·  Flask :5003',
                 font=('Microsoft YaHei UI', 9),
                 fg=self._PALETTE['text_dim'],
                 bg=self._PALETTE['bg_header']).pack(side=tk.RIGHT)

        # 分割线
        sep = tk.Frame(self.root, bg=self._PALETTE['border'], height=1)
        sep.pack(fill=tk.X)

        # ── 状态栏（先 pack 保证底部） ──
        self._build_status_bar()

        # ── 主内容 ──
        content = tk.Frame(self.root, bg=self._PALETTE['bg_main'])
        content.pack(fill=tk.BOTH, expand=True, padx=20, pady=(12, 12))
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(2, weight=1)

        self._build_server_card(content, 0, 0, '调试模式', 'run.py',
            'FastAPI + Flask (热重载) · 端口 5002 + 5003',
            'debug', self.start_debug, self.stop_debug, self.restart_debug)
        self._build_server_card(content, 0, 1, '生产模式', 'production',
            'FastAPI + Waitress (8线程) · 端口 5002 + 5003',
            'production', self.start_production, self.stop_production, self.restart_production)
        self._build_global_stop(content)
        self._build_log_section(content)

    # ── 服务器卡片（通用） ──

    def _card(self, parent, row, col):
        card = tk.Frame(parent, bg=self._PALETTE['bg_card'],
                        highlightbackground=self._PALETTE['border'],
                        highlightthickness=1)
        card.grid(row=row, column=col, sticky='nsew',
                  padx=(0, 10) if col == 0 else (0, 0))
        return card

    def _build_server_card(self, parent, row, col, title, script_label,
                            desc, mode_key, start_cmd, stop_cmd, restart_cmd):
        card = self._card(parent, row, col)

        hdr = tk.Frame(card, bg=self._PALETTE['bg_card'])
        hdr.pack(fill=tk.X, padx=20, pady=(18, 0))
        tk.Label(hdr, text=title,
                 font=('Microsoft YaHei UI', 13, 'bold'),
                 fg=self._PALETTE['text_primary'],
                 bg=self._PALETTE['bg_card']).pack(side=tk.LEFT)
        tk.Label(hdr, text=script_label,
                 font=('Consolas', 9),
                 fg=self._PALETTE['text_dim'],
                 bg=self._PALETTE['bg_card']).pack(side=tk.LEFT, padx=(12, 0))

        desc_frame = tk.Frame(card, bg=self._PALETTE['bg_card'])
        desc_frame.pack(fill=tk.X, padx=20, pady=(4, 0))
        tk.Label(desc_frame, text=desc,
                 font=('Microsoft YaHei UI', 9),
                 fg=self._PALETTE['text_dim'],
                 bg=self._PALETTE['bg_card']).pack(side=tk.LEFT)

        # 状态指示条
        st_frame = tk.Frame(card, bg=self._PALETTE['bg_input'], height=1)
        st_frame.pack(fill=tk.X, padx=20, pady=(12, 0))

        st = tk.Frame(card, bg=self._PALETTE['bg_card'])
        st.pack(fill=tk.X, padx=20, pady=(10, 0))
        status_label = tk.Label(st, text='● 已停止',
                                font=('Microsoft YaHei UI', 11),
                                fg=self._PALETTE['danger'],
                                bg=self._PALETTE['bg_card'])
        status_label.pack(side=tk.LEFT)
        pid_label = tk.Label(st, text='PID: —',
                             font=('Microsoft YaHei UI', 9),
                             fg=self._PALETTE['text_dim'],
                             bg=self._PALETTE['bg_card'])
        pid_label.pack(side=tk.LEFT, padx=(16, 0))

        # 按钮
        btns = tk.Frame(card, bg=self._PALETTE['bg_card'])
        btns.pack(fill=tk.X, padx=20, pady=(14, 18))

        start_btn = RoundedButton(
            btns, text='▶  启动', fill=self._PALETTE['success'],
            hover_fill=self._PALETTE['success_h'],
            fg='#1e1e2e',
            command=start_cmd, canvas_bg=self._PALETTE['bg_card'])
        start_btn.pack(side=tk.LEFT, padx=(0, 10))

        stop_btn = RoundedButton(
            btns, text='■  停止', fill=self._PALETTE['danger'],
            hover_fill=self._PALETTE['danger_h'],
            fg='#1e1e2e',
            command=stop_cmd, state='disabled',
            canvas_bg=self._PALETTE['bg_card'])
        stop_btn.pack(side=tk.LEFT, padx=(0, 10))

        restart_btn = RoundedButton(
            btns, text='↻  重启', fill=self._PALETTE['accent'],
            hover_fill=self._PALETTE['accent_h'],
            fg='#1e1e2e',
            command=restart_cmd, state='disabled',
            canvas_bg=self._PALETTE['bg_card'])
        restart_btn.pack(side=tk.LEFT)

        setattr(self, f'{mode_key}_status', status_label)
        setattr(self, f'{mode_key}_pid', pid_label)
        setattr(self, f'{mode_key}_start_btn', start_btn)
        setattr(self, f'{mode_key}_stop_btn', stop_btn)
        setattr(self, f'{mode_key}_restart_btn', restart_btn)

    def _build_global_stop(self, parent):
        frame = tk.Frame(parent, bg=self._PALETTE['bg_main'])
        frame.grid(row=1, column=0, columnspan=2, pady=(10, 10))

        self.stop_all_btn = RoundedButton(
            frame, text='■  全部停止', fill=self._PALETTE['danger'],
            hover_fill=self._PALETTE['danger_h'],
            fg='#1e1e2e',
            command=self.stop_all, state='disabled',
            canvas_bg=self._PALETTE['bg_main'], padx=36, pady=10)
        self.stop_all_btn.pack()

    # ── 日志区域 ──

    def _build_log_section(self, parent):
        log_card = tk.Frame(parent, bg=self._PALETTE['bg_card'],
                            highlightbackground=self._PALETTE['border'],
                            highlightthickness=1)
        log_card.grid(row=2, column=0, columnspan=2, sticky='nsew')
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(1, weight=1)

        # 标题栏
        log_hdr = tk.Frame(log_card, bg=self._PALETTE['bg_card'])
        log_hdr.grid(row=0, column=0, sticky='ew', padx=20, pady=(12, 0))

        tk.Label(log_hdr, text='实时日志',
                 font=('Microsoft YaHei UI', 11, 'bold'),
                 fg=self._PALETTE['text_primary'],
                 bg=self._PALETTE['bg_card']).pack(side=tk.LEFT)

        log_btns = tk.Frame(log_hdr, bg=self._PALETTE['bg_card'])
        log_btns.pack(side=tk.RIGHT)

        for txt, cmd in [('导出', self.export_log), ('清空', self.clear_log)]:
            tk.Button(log_btns, text=txt,
                      font=('Microsoft YaHei UI', 8),
                      fg=self._PALETTE['text_secondary'], bg=self._PALETTE['bg_input'],
                      activebackground=self._PALETTE['border'],
                      activeforeground=self._PALETTE['text_primary'],
                      relief=tk.FLAT, bd=0, cursor='hand2',
                      padx=12, pady=3,
                      command=cmd).pack(side=tk.RIGHT, padx=(6, 0))

        # 日志体
        log_body = tk.Frame(log_card, bg=self._PALETTE['bg_log'])
        log_body.grid(row=1, column=0, sticky='nsew', padx=12, pady=(8, 12))
        log_body.columnconfigure(0, weight=1)
        log_body.rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_body, bg=self._PALETTE['bg_log'], fg=self._PALETTE['log_fg'],
            insertbackground=self._PALETTE['log_fg'],
            selectbackground=self._PALETTE['bg_input'],
            font=('Cascadia Mono', 9) if _font_exists('Cascadia Mono') else ('Microsoft YaHei UI', 9),
            wrap=tk.WORD, state=tk.DISABLED, relief=tk.FLAT,
            padx=12, pady=10, cursor='arrow')
        self.log_text.grid(row=0, column=0, sticky='nsew')

        self.log_text.tag_configure('INFO',    foreground=self._PALETTE['log_info'])
        self.log_text.tag_configure('ERROR',   foreground=self._PALETTE['log_error'])
        self.log_text.tag_configure('WARNING', foreground=self._PALETTE['log_warn'])

        sb = ttk.Scrollbar(log_body, command=self.log_text.yview)
        sb.grid(row=0, column=1, sticky='ns')
        self.log_text.config(yscrollcommand=sb.set)

    # ── 状态栏 ──

    def _build_status_bar(self):
        bar = tk.Frame(self.root, bg=self._PALETTE['bg_surface'],
                       highlightbackground=self._PALETTE['border'],
                       highlightthickness=1)
        bar.pack(fill=tk.X, side=tk.BOTTOM)

        self.status_bar_label = tk.Label(
            bar, text='就绪',
            font=('Microsoft YaHei UI', 9),
            fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_surface'])
        self.status_bar_label.pack(side=tk.LEFT, padx=20, pady=7)

        tk.Label(bar, text='localhost:5002  ·  localhost:5003',
                 font=('Microsoft YaHei UI', 8),
                 fg=self._PALETTE['text_dim'],
                 bg=self._PALETTE['bg_surface']).pack(side=tk.RIGHT, padx=20, pady=7)


def main():
    if not _ensure_single_instance():
        _activate_existing_window()
        sys.exit(0)

    try:
        root = tk.Tk()
        ServerManagerApp(root)
        root.mainloop()
    except Exception as e:
        # console=False 时 print 不可见，写日志文件 + 弹窗
        import traceback
        tb_text = traceback.format_exc()
        log_dir = Path(_PROJECT_DIR) / 'logs'
        try:
            log_dir.mkdir(exist_ok=True)
            crash_file = log_dir / f'server_manager_crash_{datetime.now():%Y%m%d_%H%M%S}.log'
            crash_file.write_text(f"[CRASH] {datetime.now()}\n{tb_text}", encoding='utf-8')
        except Exception:
            crash_file = None
        try:
            messagebox.showerror("启动失败",
                f"服务器管理器启动失败:\n{str(e)}"
                + (f"\n\n日志: {crash_file}" if crash_file else ""))
        except Exception:
            pass
        sys.exit(1)


if __name__ == '__main__':
    main()
