"""
ERP 服务器管理器 GUI v4.0
功能:
  - 图形化管理调试模式 (run.py) 和生产模式 (start_production_optimized.py)
  - 单实例限制 — 同一时间只能运行一个管理器
  - 窗口居中显示 (无闪烁，小屏幕自适应)
  - 系统托盘集成 — 关闭按钮隐藏到托盘，最小化保留任务栏图标
  - 性能优化 — Font 度量缓存、批量日志写入、队列通信、主线程零阻塞
  - 彻底进程管理 — 完整进程树收集 + 递归 kill + 端口占用验证释放
  - 日志自动清理
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
from datetime import datetime
import math
from pathlib import Path

# Windows平台特殊处理
if sys.platform == 'win32':
    import io
    if sys.stdout:
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            if hasattr(sys.stdout, 'buffer'):
                sys.stdout = io.TextIOWrapper(
                    sys.stdout.buffer,
                    encoding='utf-8',
                    errors='replace',
                    line_buffering=True,
                )
    if sys.stderr:
        try:
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            if hasattr(sys.stderr, 'buffer'):
                sys.stderr = io.TextIOWrapper(
                    sys.stderr.buffer,
                    encoding='utf-8',
                    errors='replace',
                    line_buffering=True,
                )

import tkinter as tk
from tkinter import ttk, messagebox


# ============================================================
# 全局常量
# ============================================================
_VERSION = 'v4.1'
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
    # 非 frozen 环境：直接使用当前解释器
    if not getattr(sys, 'frozen', False):
        return sys.executable
    # frozen 环境（PyInstaller exe）：需要定位系统 Python
    # 1. 尝试 py launcher
    py_exe = Path(os.environ.get('SYSTEMROOT', r'C:\Windows')) / 'py.exe'
    if py_exe.is_file():
        return str(py_exe)
    # 2. 尝试 PATH 中的 python
    python_in_path = shutil.which('python')
    if python_in_path:
        return python_in_path
    # 3. 尝试已知安装路径
    for candidate in [
        Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Python' / 'Python313' / 'python.exe',
        Path(r'C:\Python313\python.exe'),
        Path(r'C:\Program Files\Python313\python.exe'),
    ]:
        if candidate.is_file():
            return str(candidate)
    # 4. 最终回退（可能是 exe 自身，会失败）
    return sys.executable

_PYTHON_EXE = _get_python_executable()


# ============================================================
# 字体检测（缓存结果，避免重复创建临时 Tk root）
# ============================================================
_font_cache = {}

def _font_exists(name):
    """检测字体是否可用（带缓存）"""
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


# ============================================================
# 圆角按钮组件 — 带动画与绘图缓存
# ============================================================
class RoundedButton(tk.Canvas):
    """基于 Canvas 的圆角按钮 — 14px 大圆角，hover 动画过渡"""

    def __init__(self, parent, text='', fill='#89b4fa', fg='#1e1e2e',
                 hover_fill=None, command=None,
                 font=('Microsoft YaHei UI', 10),
                 padx=24, pady=8, radius=14,
                 state='normal', canvas_bg=None, **kw):
        import tkinter.font as tkfont
        f = tkfont.Font(font=font)
        tw = f.measure(text)
        th = f.metrics('linespace')

        w, h = tw + padx * 2, th + pady * 2
        canvas_bg = canvas_bg or '#141419'

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
        self._press = False  # 按下动画状态

        # 动画参数
        self._anim_step = 0
        self._anim_total = 6  # 动画帧数
        self._anim_after_id = None

        self.bind('<Configure>', self._draw)
        self.bind('<Enter>', lambda e: self._hover_in())
        self.bind('<Leave>', lambda e: self._hover_out())
        self.bind('<ButtonPress-1>', lambda e: self._press_in())
        self.bind('<ButtonRelease-1>', lambda e: self._press_out())

    @staticmethod
    def _shift(hex_c, amount):
        r = max(0, min(255, int(hex_c[1:3], 16) + amount))
        g = max(0, min(255, int(hex_c[3:5], 16) + amount))
        b = max(0, min(255, int(hex_c[5:7], 16) + amount))
        return f'#{r:02x}{g:02x}{b:02x}'

    @staticmethod
    def _lerp_color(c1, c2, t):
        """线性插值两个颜色，t: 0→1"""
        r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
        r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
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
            bg, fg = '#2a2a35', '#4a4a58'
        elif self._press:
            # 按下态：颜色更深，轻微缩放效果
            bg = self._lerp_color(self._fill, self._hover_fill, 0.6)
            fg = self._fg
        elif self._hover:
            bg, fg = self._hover_fill, self._fg
        else:
            bg, fg = self._fill, self._fg

        # 按下时缩小 1px 的视觉反馈
        offset = 1 if self._press else 0
        self._round_rect(offset, offset, w - offset, h - offset, r, fill=bg, outline='')

        # hover 时底部微光效果
        if self._hover and self._state != 'disabled':
            glow_color = self._shift(bg, 20)
            self._round_rect(2, h - 3, w - 2, h - 1, 1, fill=glow_color, outline='')

        self.create_text(w // 2, h // 2, text=self._text,
                         fill=fg, font=self._font)

    def _animate_hover(self, target_hover):
        """平滑过渡 hover 动画"""
        if self._anim_after_id:
            self.after_cancel(self._anim_after_id)
            self._anim_after_id = None

        self._anim_step = 0
        start_color = self._fill if not target_hover else self._hover_fill
        end_color = self._hover_fill if target_hover else self._fill

        def step():
            self._anim_step += 1
            t = self._anim_step / self._anim_total
            if t >= 1.0:
                self._hover = target_hover
                self._draw()
                return
            self.delete('all')
            w, h = self.winfo_width(), self.winfo_height()
            if w < 4 or h < 4:
                return
            r = min(self._radius, w // 2, h // 2)
            current_bg = self._lerp_color(start_color, end_color, t)
            self._round_rect(0, 0, w, h, r, fill=current_bg, outline='')
            self.create_text(w // 2, h // 2, text=self._text,
                             fill=self._fg, font=self._font)
            self._anim_after_id = self.after(16, step)  # ~60fps

        step()

    def _hover_in(self):
        if self._state == 'disabled':
            return
        self._animate_hover(True)

    def _hover_out(self):
        self._animate_hover(False)

    def _press_in(self):
        if self._state == 'disabled':
            return
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


# ============================================================
# 状态指示灯动画组件
# ============================================================
class StatusDot(tk.Canvas):
    """带呼吸动画的状态指示灯"""

    def __init__(self, parent, size=12, color='#ff6b81', **kw):
        bg = kw.pop('canvas_bg', '#141419')
        super().__init__(parent, width=size, height=size,
                         highlightthickness=0, bg=bg, **kw)
        self._size = size
        self._color = color
        self._bg = bg
        self._anim_after_id = None
        self._anim_step = 0
        self._is_active = False
        self._draw_dot()

    @staticmethod
    def _shift(hex_c, amount):
        r = max(0, min(255, int(hex_c[1:3], 16) + amount))
        g = max(0, min(255, int(hex_c[3:5], 16) + amount))
        b = max(0, min(255, int(hex_c[5:7], 16) + amount))
        return f'#{r:02x}{g:02x}{b:02x}'

    def set_color(self, color, active=False):
        self._color = color
        self._is_active = active
        if self._anim_after_id:
            self.after_cancel(self._anim_after_id)
            self._anim_after_id = None
        if active:
            self._start_breathing()
        else:
            self._draw_dot()

    def _draw_dot(self, alpha=1.0):
        self.delete('all')
        s = self._size
        r = s // 2 - 1

        if self._is_active and alpha < 1.0:
            # 呼吸光晕
            glow_r = int(r + 2 * (1 - alpha))
            glow_color = self._shift(self._color, int(30 * (1 - alpha)))
            self.create_oval(s//2 - glow_r, s//2 - glow_r,
                             s//2 + glow_r, s//2 + glow_r,
                             fill=glow_color, outline='')

        self.create_oval(s//2 - r, s//2 - r, s//2 + r, s//2 + r,
                         fill=self._color, outline='')

    def _start_breathing(self):
        self._anim_step = 0

        def step():
            self._anim_step = (self._anim_step + 1) % 60
            # sin 波呼吸：0.7 ~ 1.0 之间
            t = self._anim_step / 60.0
            alpha = 0.7 + 0.3 * math.sin(t * 2 * math.pi)
            self._draw_dot(alpha)
            self._anim_after_id = self.after(33, step)  # ~30fps

        step()

    def stop_animation(self):
        if self._anim_after_id:
            self.after_cancel(self._anim_after_id)
            self._anim_after_id = None
        self._draw_dot()


# ============================================================
# 系统托盘支持
# ============================================================
def _create_tray_icon_image():
    """创建托盘图标 — Catppuccin Blue 圆点"""
    try:
        from PIL import Image, ImageDraw
        img = Image.new('RGBA', (16, 16), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, 14, 14], fill=(108, 142, 255, 255))
        return img
    except Exception:
        return None


# ============================================================
# 主应用 — 高端暗色主题 + 微交互动画
# ============================================================
class ServerManagerApp:
    """ERP 服务器管理器 — 调试/生产双模式"""

    # 中性企业风调色板（非纯黑）
    _PALETTE = {
        'bg_main':      '#f2f4f8',
        'bg_card':      '#ffffff',
        'bg_surface':   '#e9edf4',
        'bg_header':    '#f7f9fc',
        'bg_log':       '#fbfcfe',
        'bg_input':     '#edf1f7',

        'text_primary': '#1f2a3d',
        'text_secondary':'#4f5f7a',
        'text_dim':     '#7b889f',

        'border':       '#d7deea',
        'border_card':  '#dce3ef',

        'accent':       '#3f7cff',
        'accent_h':     '#5d92ff',
        'success':      '#21b573',
        'success_h':    '#38c689',
        'danger':       '#e3576d',
        'danger_h':     '#f06d83',
        'warning':      '#f0a542',
        'info':         '#36a8ce',

        'log_fg':       '#25324a',
        'log_info':     '#3f7cff',
        'log_error':    '#e3576d',
        'log_warn':     '#f0a542',
        'log_success':  '#21b573',
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
        self._server_cards = []
        self._status_anim_after_id = None
        self._status_pulse_step = 0

        self.setup_logging()
        self._build_ui()
        self._set_window_icon()

        self._center_window()
        self.root.deiconify()
        # 淡入动画
        self._fade_in()
        self._animate_cards_intro()

        self._check_interval = 5000
        self._after_ids = {}
        self.check_server_status()

        self._schedule_log_cleanup()
        self._schedule_log_flush()
        self._poll_queue()

        self._tray_icon = None
        self._init_tray()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self._ui_ready = True

        # 异步清理残留端口（不阻塞 UI）
        self._kill_port_occupants_async(5002)

        self.logger.info(f"服务器管理器已启动 ({_VERSION})")

    # ── 窗口动画 ──────────────────────────────────────────

    def _fade_in(self):
        """窗口淡入动画"""
        try:
            self.root.attributes('-alpha', 0.0)
            steps = 10
            delay = 20

            def step(i):
                if i > steps:
                    self.root.attributes('-alpha', 1.0)
                    self._after_ids.pop('fade_in', None)
                    return
                alpha = i / steps
                self.root.attributes('-alpha', alpha)
                self._after_ids['fade_in'] = self.root.after(delay, lambda: step(i + 1))

            step(0)
        except Exception:
            pass

    def _animate_cards_intro(self):
        """卡片入场边框渐变动画（轻量，不影响布局性能）"""
        try:
            for idx, card in enumerate(self._server_cards):
                self.root.after(80 * idx, lambda c=card: self._pulse_card_border(c))
        except Exception:
            pass

    def _pulse_card_border(self, card):
        base = self._PALETTE['border_card']
        accent = self._PALETTE['accent_h']
        steps = 10

        def tick(i):
            if i > steps:
                try:
                    card.configure(highlightbackground=base)
                except Exception:
                    pass
                return
            t = i / steps
            if t <= 0.5:
                color = RoundedButton._lerp_color(base, accent, t * 2)
            else:
                color = RoundedButton._lerp_color(accent, base, (t - 0.5) * 2)
            try:
                card.configure(highlightbackground=color)
            except Exception:
                return
            self.root.after(30, lambda: tick(i + 1))

        tick(0)

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
        w = min(w, sw - 40)
        h = min(h, sh - 80)
        self.root.geometry(f'+{max(0,(sw-w)//2)}+{max(0,(sh-h)//2)}')

    # ── 系统托盘 ──────────────────────────────────────────

    def _init_tray(self):
        try:
            import pystray
            icon_image = _create_tray_icon_image()
            if icon_image is None:
                return
            self._tray_image = icon_image
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
        for aid in self._after_ids.values():
            try:
                self.root.after_cancel(aid)
            except Exception:
                pass
        self._after_ids.clear()
        # 停止所有状态灯动画
        for attr in ('debug_status_dot', 'production_status_dot'):
            dot = getattr(self, attr, None)
            if dot:
                dot.stop_animation()
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
            self._tray_icon = None
            try:
                self.root.update()
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
            try:
                self.root.after_idle(self._do_flush)
            except RuntimeError:
                # 主线程已销毁，忽略
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
        """安全终止当前管理的子进程（含完整进程树），并确保端口彻底释放。
        所有阻塞操作在后台线程执行，主线程零阻塞。"""
        proc = self._process
        self._process = None  # 立即置空，防止重复调用
        if proc and proc.poll() is None:
            pid = proc.pid
            self._msg_queue.put(('log', {'text': f"正在终止进程树 (根 PID: {pid})..."}))

            def _kill_worker():
                try:
                    if sys.platform == 'win32':
                        # 第一步：收集完整进程树 PID
                        child_pids = self._collect_process_tree(pid)
                        all_pids = child_pids + [pid]  # 子进程优先，根进程最后
                        self._msg_queue.put(('log', {
                            'text': f"发现 {len(all_pids)} 个关联进程: {all_pids}"}))

                        # 第二步：taskkill /T 先尝试整棵树
                        subprocess.run(
                            ['taskkill', '/F', '/T', '/PID', str(pid)],
                            creationflags=subprocess.CREATE_NO_WINDOW,
                            capture_output=True, timeout=10)

                        # 第三步：逐个确认并补杀残留
                        for cpid in all_pids:
                            try:
                                check = subprocess.run(
                                    ['tasklist', '/FI', f'PID eq {cpid}', '/NH'],
                                    creationflags=subprocess.CREATE_NO_WINDOW,
                                    capture_output=True, text=True, timeout=5)
                                if str(cpid) in check.stdout:
                                    subprocess.run(
                                        ['taskkill', '/F', '/PID', str(cpid)],
                                        creationflags=subprocess.CREATE_NO_WINDOW,
                                        capture_output=True, timeout=5)
                                    self._msg_queue.put(('log', {
                                        'text': f"补杀残留进程 PID: {cpid}",
                                        'level': 'WARNING'}))
                            except Exception:
                                pass

                        # 第四步：回收 Popen 对象
                        try:
                            proc.wait(timeout=3)
                        except Exception:
                            pass

                        # 第五步：彻底清理端口占用（同步等待确认）
                        self._kill_port_occupants_sync(5002)
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
                    except Exception:
                        pass
                    try:
                        proc.wait(timeout=3)
                    except Exception:
                        pass
                    self._msg_queue.put(('log', {
                        'text': f"进程 (PID: {pid}) 超时，已强制 kill",
                        'level': 'WARNING'}))
                    self._kill_port_occupants_sync(5002)
                except Exception as e:
                    self._msg_queue.put(('log', {
                        'text': f"终止进程异常: {str(e)}",
                        'level': 'ERROR'}))
                    self._kill_port_occupants_sync(5002)
                finally:
                    self._msg_queue.put(('ui_update', {}))

            threading.Thread(target=_kill_worker, daemon=True).start()
        else:
            self._msg_queue.put(('ui_update', {}))

    def _collect_process_tree(self, root_pid):
        """递归收集进程树所有子 PID（使用 wmic）"""
        pids = []
        try:
            result = subprocess.run(
                ['wmic', 'process', 'where',
                 f'(ParentProcessId={root_pid})',
                 'get', 'ProcessId'],
                creationflags=subprocess.CREATE_NO_WINDOW,
                capture_output=True, text=True, timeout=5)
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    child_pid = int(line)
                    if child_pid != root_pid:
                        # 递归收集孙进程
                        pids.extend(self._collect_process_tree(child_pid))
                        pids.append(child_pid)
        except Exception:
            pass
        return pids

    def _kill_port_occupants_sync(self, port):
        """同步清理端口占用，带重试验证确保端口彻底释放"""
        for attempt in range(3):
            occupied_pids = self._find_port_pids(port)
            if not occupied_pids:
                if attempt > 0:
                    self._msg_queue.put(('log', {
                        'text': f"端口 {port} 已完全释放",
                        'level': 'INFO'}))
                return
            for opid in occupied_pids:
                try:
                    self._msg_queue.put(('log', {
                        'text': f"终止占用端口 {port} 的进程 PID: {opid}",
                        'level': 'INFO'}))
                    subprocess.run(
                        ['taskkill', '/F', '/T', '/PID', str(opid)],
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        capture_output=True, timeout=5)
                except Exception:
                    pass
            time.sleep(0.5)  # 等待端口释放
        # 最终验证
        remaining = self._find_port_pids(port)
        if remaining:
            self._msg_queue.put(('log', {
                'text': f"警告：端口 {port} 仍被占用 (PIDs: {remaining})，可能需手动处理",
                'level': 'WARNING'}))

    def _find_port_pids(self, port):
        """查找占用指定端口的所有 PID"""
        pids = set()
        try:
            output = subprocess.run(
                ['netstat', '-ano'],
                creationflags=subprocess.CREATE_NO_WINDOW,
                capture_output=True, text=True, timeout=10)
            for line in output.stdout.splitlines():
                if 'LISTENING' not in line and 'TIME_WAIT' not in line:
                    continue
                parts = line.split()
                if len(parts) < 5:
                    continue
                local_addr = parts[1]
                if ':' in local_addr and local_addr.rsplit(':', 1)[-1] == str(port):
                    pid_str = parts[-1]
                    if pid_str.isdigit() and int(pid_str) > 0:
                        pids.add(pid_str)
        except Exception:
            pass
        return list(pids)

    def _kill_port_occupants_async(self, port):
        """异步扫描并清理端口占用 — 不阻塞 UI 线程"""
        def _worker():
            try:
                output = subprocess.run(
                    ['netstat', '-ano'],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    capture_output=True, text=True, timeout=10)
                for line in output.stdout.splitlines():
                    if 'LISTENING' not in line:
                        continue
                    parts = line.split()
                    if len(parts) < 5:
                        continue
                    local_addr = parts[1]
                    if ':' in local_addr and local_addr.rsplit(':', 1)[-1] == str(port):
                        occupant_pid = parts[-1]
                        if occupant_pid.isdigit():
                            try:
                                proc_check = subprocess.run(
                                    ['tasklist', '/FI', f'PID eq {occupant_pid}', '/FO', 'CSV', '/NH'],
                                    creationflags=subprocess.CREATE_NO_WINDOW,
                                    capture_output=True, text=True, timeout=5)
                                if 'python' in proc_check.stdout.lower():
                                    self._msg_queue.put(('log', {
                                        'text': f"发现残留 Python 进程占用端口 {port} (PID: {occupant_pid})，正在终止...",
                                        'level': 'INFO'
                                    }))
                                    subprocess.run(
                                        ['taskkill', '/F', '/PID', occupant_pid],
                                        creationflags=subprocess.CREATE_NO_WINDOW,
                                        capture_output=True, timeout=5)
                            except Exception as e:
                                self._msg_queue.put(('log', {
                                    'text': f"清理端口占用异常: {e}",
                                    'level': 'WARNING'
                                }))
            except Exception as e:
                self._msg_queue.put(('log', {
                    'text': f"端口扫描异常: {e}",
                    'level': 'WARNING'
                }))
        threading.Thread(target=_worker, daemon=True).start()

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
        # 异步清理端口（不阻塞 UI）
        self.log_message(f"正在启动{mode_label}...")
        self.status_bar_label.config(text=f"正在启动{mode_label}...")
        self._mode = 'starting'
        self._update_all_ui()

        def _prepare_and_start():
            self._kill_port_occupants_async(5002)
            # 短暂等待异步清理完成（比同步快得多）
            time.sleep(0.3)
            self._start_thread(script, mode_label)

        threading.Thread(target=_prepare_and_start, daemon=True).start()

    def _start_thread(self, script, mode_label):
        if self._mode not in ('starting', 'restarting'):
            return
        try:
            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'
            env['PYTHONIOENCODING'] = 'utf-8'
            env['PYTHONUTF8'] = '1'
            env['PYTHONPATH'] = str(_PROJECT_DIR)
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            self._process = subprocess.Popen(
                [_PYTHON_EXE, script],
                cwd=str(_PROJECT_DIR), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=creationflags,
                text=False)
            self._msg_queue.put(('log', {'text': f"进程已启动 (PID: {self._process.pid})"}))
            threading.Thread(target=self._read_stdout,
                             args=(self._process,), daemon=True).start()
            alive = True
            for _ in range(6):
                if self._process.poll() is not None:
                    alive = False
                    break
                time.sleep(0.5)
            if alive:
                self._msg_queue.put(('started', {'label': mode_label}))
            else:
                self._process = None
                self._msg_queue.put(('log', {'text': f"{mode_label}进程启动后立即退出", 'level': 'ERROR'}))
                self._msg_queue.put(('status', {'text': f"{mode_label}启动失败"}))
        except Exception as e:
            self._process = None
            self._msg_queue.put(('log', {'text': f"启动异常: {str(e)}", 'level': 'ERROR'}))
            self._msg_queue.put(('status', {'text': f"{mode_label}启动失败"}))

    def _read_stdout(self, proc):
        try:
            if proc.stdout:
                try:
                    for raw_line in proc.stdout:
                        if isinstance(raw_line, bytes):
                            line = self._decode_subprocess_line(raw_line)
                        else:
                            line = str(raw_line).strip()
                        if line:
                            self._msg_queue.put(('log', {'text': line}))
                finally:
                    proc.stdout.close()
        except Exception as e:
            self._msg_queue.put(('log', {'text': f"读取日志异常: {str(e)}", 'level': 'ERROR'}))

    @staticmethod
    def _decode_subprocess_line(raw_line):
        """鲁棒解码子进程输出，兼容 UTF-8/GBK，避免中文乱码。"""
        if not raw_line:
            return ''

        preferred = locale.getpreferredencoding(False) or ''
        candidates = ['utf-8', 'utf-8-sig', 'gb18030', 'cp936']
        if preferred:
            candidates.append(preferred)

        tried = set()
        for enc in candidates:
            enc_norm = enc.lower()
            if enc_norm in tried:
                continue
            tried.add(enc_norm)
            try:
                return raw_line.decode(enc, errors='strict').strip()
            except Exception:
                continue

        return raw_line.decode('utf-8', errors='replace').strip()

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
            self._update_all_ui()
            self.log_message(f"{label}已停止")
        else:
            self.log_message(f"{label}未运行")

    def stop_all(self):
        if self._mode != 'none':
            self._stop_process()
            self._mode = 'none'
            self._update_all_ui()
            self.log_message("所有服务器已停止")
        else:
            # 即使无管理的进程，也清理端口残留
            self._kill_port_occupants_async(5002)
            self.log_message("已触发端口清理")

    def restart_debug(self):
        self.log_message("正在重启调试模式...")
        threading.Thread(target=self._restart_thread, args=('debug',), daemon=True).start()

    def restart_production(self):
        self.log_message("正在重启生产模式...")
        threading.Thread(target=self._restart_thread, args=('production',), daemon=True).start()

    def _restart_thread(self, mode):
        self._mode = 'restarting'
        self._msg_queue.put(('ui_update', {}))

        # 停止当前进程
        proc = self._process
        self._process = None
        if proc and proc.poll() is None:
            pid = proc.pid
            self._msg_queue.put(('log', {'text': f"重启：终止进程树 (PID: {pid})..."}))
            if sys.platform == 'win32':
                child_pids = self._collect_process_tree(pid)
                subprocess.run(
                    ['taskkill', '/F', '/T', '/PID', str(pid)],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    capture_output=True, timeout=10)
                for cpid in child_pids:
                    try:
                        subprocess.run(
                            ['taskkill', '/F', '/PID', str(cpid)],
                            creationflags=subprocess.CREATE_NO_WINDOW,
                            capture_output=True, timeout=3)
                    except Exception:
                        pass
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

        # 同步等待端口彻底释放（最多重试 3 次，每次 0.5s）
        self._kill_port_occupants_sync(5002)
        # 额外等待确保 OS 层面完全释放
        time.sleep(0.5)

        self._mode = 'restarting'
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
        is_busy  = not is_none

        self._update_card_ui('debug', is_debug, is_none)
        self._update_card_ui('production', is_prod, is_none)

        self.stop_all_btn.config(state='normal' if is_busy else 'disabled')
        self._update_status_indicator(is_busy=is_busy, is_active=(is_debug or is_prod))

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
        status_dot = getattr(self, f'{mode_key}_status_dot')

        status.config(
            text="运行中" if is_active else "已停止",
            foreground=self._PALETTE['success'] if is_active else self._PALETTE['danger'])
        status_dot.set_color(
            self._PALETTE['success'] if is_active else self._PALETTE['danger'],
            active=is_active)
        pid.config(
            text=f"PID: {self._process.pid}" if is_active and self._process else "PID: —")
        start_btn.config(state='normal' if is_none else 'disabled')
        stop_btn.config(state='normal' if is_active else 'disabled')
        restart_btn.config(state='normal' if is_active else 'disabled')

    def check_server_status(self):
        if self._process and self._process.poll() is not None:
            if self._mode not in ('none', 'restarting', 'starting'):
                code = self._process.poll()
                label = self._mode_label()
                self.log_message(
                    f"{label}进程意外终止 (退出码: {code})", 'ERROR')
                self._mode = 'none'
                self._process = None
                self._update_all_ui()
                self._after_ids['crash_warn'] = self.root.after(100, lambda: messagebox.showwarning("警告",
                    f"{label}意外停止，请检查日志"))
        self._after_ids['status'] = self.root.after(self._check_interval, self.check_server_status)

    def on_closing(self):
        if self._tray_icon:
            self.root.withdraw()
        else:
            self._do_quit()

    # ================================================================
    #  UI 构建 — 高端暗色主题 + 动画
    # ================================================================

    def _build_ui(self):
        self.root.configure(bg=self._PALETTE['bg_main'])

        # ── 标题栏 ──
        header = tk.Frame(self.root, bg=self._PALETTE['bg_header'], height=64)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        hdr_inner = tk.Frame(header, bg=self._PALETTE['bg_header'])
        hdr_inner.pack(fill=tk.X, padx=28, pady=(16, 0))

        # 品牌标识区
        brand = tk.Frame(hdr_inner, bg=self._PALETTE['bg_header'])
        brand.pack(side=tk.LEFT)

        tk.Label(brand, text='ERP',
                 font=('Segoe UI', 16, 'bold'),
                 fg=self._PALETTE['accent'],
                 bg=self._PALETTE['bg_header']).pack(side=tk.LEFT)
        tk.Label(brand, text='Server Manager',
                 font=('Segoe UI', 16),
                 fg=self._PALETTE['text_primary'],
                 bg=self._PALETTE['bg_header']).pack(side=tk.LEFT, padx=(6, 0))

        # 版本标签 — 圆角标签样式
        ver_frame = tk.Frame(hdr_inner, bg=self._PALETTE['bg_input'],
                             highlightbackground=self._PALETTE['border'],
                             highlightthickness=1)
        ver_frame.pack(side=tk.LEFT, padx=(12, 0))
        tk.Label(ver_frame, text=_VERSION,
                 font=('Consolas', 8),
                 fg=self._PALETTE['text_dim'],
                 bg=self._PALETTE['bg_input']).pack(padx=8, pady=1)

        # 右侧端口信息
        port_frame = tk.Frame(hdr_inner, bg=self._PALETTE['bg_header'])
        port_frame.pack(side=tk.RIGHT)
        tk.Label(port_frame, text='PORT',
                 font=('Consolas', 8),
                 fg=self._PALETTE['text_dim'],
                 bg=self._PALETTE['bg_header']).pack(side=tk.LEFT)
        tk.Label(port_frame, text='5002',
                 font=('Consolas', 11, 'bold'),
                 fg=self._PALETTE['accent'],
                 bg=self._PALETTE['bg_header']).pack(side=tk.LEFT, padx=(4, 0))

        # 强调分割线 — 渐变效果用纯色近似
        accent_sep = tk.Frame(self.root, bg=self._PALETTE['accent'], height=1)
        accent_sep.pack(fill=tk.X)
        sep = tk.Frame(self.root, bg=self._PALETTE['border'], height=1)
        sep.pack(fill=tk.X)

        # ── 状态栏（先 pack 保证底部） ──
        self._build_status_bar()

        # ── 主内容 ──
        content = tk.Frame(self.root, bg=self._PALETTE['bg_main'])
        content.pack(fill=tk.BOTH, expand=True, padx=24, pady=(16, 12))
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(2, weight=1)

        self._build_server_card(content, 0, 0, '调试模式', 'run.py',
            'FastAPI (热重载) · 端口 5002',
            'debug', self.start_debug, self.stop_debug, self.restart_debug)
        self._build_server_card(content, 0, 1, '生产模式', 'production',
            'FastAPI + Uvicorn (多Worker) · 端口 5002',
            'production', self.start_production, self.stop_production, self.restart_production)
        self._build_global_stop(content)
        self._build_log_section(content)

    # ── 服务器卡片（通用） ──

    def _card(self, parent, row, col):
        card = tk.Frame(parent, bg=self._PALETTE['bg_card'],
                        highlightbackground=self._PALETTE['border_card'],
                        highlightthickness=1)
        card.grid(row=row, column=col, sticky='nsew',
                  padx=(0, 12) if col == 0 else (0, 0))
        self._server_cards.append(card)
        return card

    def _build_server_card(self, parent, row, col, title, script_label,
                            desc, mode_key, start_cmd, stop_cmd, restart_cmd):
        card = self._card(parent, row, col)

        # 卡片内顶部色条
        mode_color = self._PALETTE['accent'] if mode_key == 'debug' else self._PALETTE['success']
        accent_bar = tk.Frame(card, bg=mode_color, height=2)
        accent_bar.pack(fill=tk.X)

        # 标题行
        hdr = tk.Frame(card, bg=self._PALETTE['bg_card'])
        hdr.pack(fill=tk.X, padx=22, pady=(14, 0))

        # 模式图标
        icon_text = 'D' if mode_key == 'debug' else 'P'
        icon_frame = tk.Frame(hdr, bg=mode_color, width=28, height=28)
        icon_frame.pack(side=tk.LEFT, padx=(0, 10))
        icon_frame.pack_propagate(False)
        tk.Label(icon_frame, text=icon_text,
                 font=('Consolas', 11, 'bold'),
                 fg='#0a0a0f', bg=mode_color).place(relx=0.5, rely=0.5, anchor='center')

        title_col = tk.Frame(hdr, bg=self._PALETTE['bg_card'])
        title_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(title_col, text=title,
                 font=('Microsoft YaHei UI', 13, 'bold'),
                 fg=self._PALETTE['text_primary'],
                 bg=self._PALETTE['bg_card'], anchor='w').pack(anchor='w')
        tk.Label(title_col, text=desc,
                 font=('Microsoft YaHei UI', 8),
                 fg=self._PALETTE['text_dim'],
                 bg=self._PALETTE['bg_card'], anchor='w').pack(anchor='w')

        tk.Label(hdr, text=script_label,
                 font=('Consolas', 8),
                 fg=self._PALETTE['text_dim'],
                 bg=self._PALETTE['bg_card']).pack(side=tk.RIGHT)

        # 分割线
        sep = tk.Frame(card, bg=self._PALETTE['border'], height=1)
        sep.pack(fill=tk.X, padx=22, pady=(12, 0))

        # 状态行：指示灯 + 文字 + PID
        st = tk.Frame(card, bg=self._PALETTE['bg_card'])
        st.pack(fill=tk.X, padx=22, pady=(10, 0))

        status_dot = StatusDot(st, size=10, color=self._PALETTE['danger'],
                               canvas_bg=self._PALETTE['bg_card'])
        status_dot.pack(side=tk.LEFT, padx=(0, 8))

        status_label = tk.Label(st, text='已停止',
                                font=('Microsoft YaHei UI', 10, 'bold'),
                                fg=self._PALETTE['danger'],
                                bg=self._PALETTE['bg_card'])
        status_label.pack(side=tk.LEFT)

        pid_label = tk.Label(st, text='PID: —',
                             font=('Consolas', 9),
                             fg=self._PALETTE['text_dim'],
                             bg=self._PALETTE['bg_card'])
        pid_label.pack(side=tk.RIGHT)

        # 按钮区
        btns = tk.Frame(card, bg=self._PALETTE['bg_card'])
        btns.pack(fill=tk.X, padx=22, pady=(14, 18))

        start_btn = RoundedButton(
            btns, text='  启动  ', fill=self._PALETTE['success'],
            hover_fill=self._PALETTE['success_h'],
            fg='#ffffff',
            command=start_cmd, canvas_bg=self._PALETTE['bg_card'],
            radius=8, pady=7)
        start_btn.pack(side=tk.LEFT, padx=(0, 8))

        stop_btn = RoundedButton(
            btns, text='  停止  ', fill=self._PALETTE['danger'],
            hover_fill=self._PALETTE['danger_h'],
            fg='#ffffff',
            command=stop_cmd, state='disabled',
            canvas_bg=self._PALETTE['bg_card'],
            radius=8, pady=7)
        stop_btn.pack(side=tk.LEFT, padx=(0, 8))

        restart_btn = RoundedButton(
            btns, text='  重启  ', fill=self._PALETTE['accent'],
            hover_fill=self._PALETTE['accent_h'],
            fg='#ffffff',
            command=restart_cmd, state='disabled',
            canvas_bg=self._PALETTE['bg_card'],
            radius=8, pady=7)
        restart_btn.pack(side=tk.LEFT)

        setattr(self, f'{mode_key}_status', status_label)
        setattr(self, f'{mode_key}_pid', pid_label)
        setattr(self, f'{mode_key}_start_btn', start_btn)
        setattr(self, f'{mode_key}_stop_btn', stop_btn)
        setattr(self, f'{mode_key}_restart_btn', restart_btn)
        setattr(self, f'{mode_key}_status_dot', status_dot)

    def _build_global_stop(self, parent):
        frame = tk.Frame(parent, bg=self._PALETTE['bg_main'])
        frame.grid(row=1, column=0, columnspan=2, pady=(10, 6))

        self.stop_all_btn = RoundedButton(
            frame, text='  全部停止  ', fill=self._PALETTE['danger'],
            hover_fill=self._PALETTE['danger_h'],
            fg='#ffffff',
            command=self.stop_all, state='disabled',
            canvas_bg=self._PALETTE['bg_main'], padx=40, pady=9,
            radius=8, font=('Microsoft YaHei UI', 10, 'bold'))
        self.stop_all_btn.pack()

    # ── 日志区域 ──

    def _build_log_section(self, parent):
        log_card = tk.Frame(parent, bg=self._PALETTE['bg_card'],
                            highlightbackground=self._PALETTE['border_card'],
                            highlightthickness=1)
        log_card.grid(row=2, column=0, columnspan=2, sticky='nsew', pady=(4, 0))
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(1, weight=1)

        # 标题栏
        log_hdr = tk.Frame(log_card, bg=self._PALETTE['bg_card'])
        log_hdr.grid(row=0, column=0, sticky='ew', padx=20, pady=(12, 0))

        tk.Label(log_hdr, text='控制台',
                 font=('Microsoft YaHei UI', 11, 'bold'),
                 fg=self._PALETTE['text_primary'],
                 bg=self._PALETTE['bg_card']).pack(side=tk.LEFT)

        tk.Label(log_hdr, text='实时输出',
                 font=('Microsoft YaHei UI', 8),
                 fg=self._PALETTE['text_dim'],
                 bg=self._PALETTE['bg_card']).pack(side=tk.LEFT, padx=(8, 0))

        log_btns = tk.Frame(log_hdr, bg=self._PALETTE['bg_card'])
        log_btns.pack(side=tk.RIGHT)

        for txt, cmd in [('导出', self.export_log), ('清空', self.clear_log)]:
            btn = tk.Button(log_btns, text=txt,
                      font=('Microsoft YaHei UI', 8),
                      fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_input'],
                      activebackground=self._PALETTE['border'],
                      activeforeground=self._PALETTE['text_primary'],
                      relief=tk.FLAT, bd=0, cursor='hand2',
                      padx=10, pady=2,
                      command=cmd)
            btn.pack(side=tk.RIGHT, padx=(4, 0))

        # 日志体
        log_body = tk.Frame(log_card, bg=self._PALETTE['bg_log'],
                            highlightbackground=self._PALETTE['border'],
                            highlightthickness=1)
        log_body.grid(row=1, column=0, sticky='nsew', padx=14, pady=(8, 14))
        log_body.columnconfigure(0, weight=1)
        log_body.rowconfigure(0, weight=1)

        log_font = ('Microsoft YaHei UI', 9)
        self.log_text = tk.Text(
            log_body, bg=self._PALETTE['bg_log'], fg=self._PALETTE['log_fg'],
            insertbackground=self._PALETTE['log_fg'],
            selectbackground=self._PALETTE['bg_input'],
            font=log_font,
            wrap=tk.WORD, state=tk.DISABLED, relief=tk.FLAT,
            padx=14, pady=10, cursor='arrow')
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

        # 左侧状态
        left = tk.Frame(bar, bg=self._PALETTE['bg_surface'])
        left.pack(side=tk.LEFT, padx=20, pady=5)

        self._status_dot_bar = tk.Canvas(left, width=8, height=8,
                                          highlightthickness=0,
                                          bg=self._PALETTE['bg_surface'])
        self._status_dot_bar.pack(side=tk.LEFT, padx=(0, 6))
        self._status_dot_item = self._status_dot_bar.create_oval(
            1, 1, 7, 7, fill=self._PALETTE['success'], outline='')

        self.status_bar_label = tk.Label(
            left, text='就绪',
            font=('Microsoft YaHei UI', 9),
            fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_surface'])
        self.status_bar_label.pack(side=tk.LEFT)

        # 右侧信息
        right = tk.Frame(bar, bg=self._PALETTE['bg_surface'])
        right.pack(side=tk.RIGHT, padx=20, pady=5)
        tk.Label(right, text='localhost:5002',
                 font=('Consolas', 8),
                 fg=self._PALETTE['text_dim'],
                 bg=self._PALETTE['bg_surface']).pack(side=tk.RIGHT)

    def _update_status_indicator(self, is_busy, is_active):
        """状态栏指示灯统一动效：运行中呼吸、忙碌时加速。"""
        color = self._PALETTE['success'] if is_active else self._PALETTE['warning'] if is_busy else self._PALETTE['info']
        speed_ms = 26 if is_busy else 42

        if self._status_anim_after_id:
            try:
                self.root.after_cancel(self._status_anim_after_id)
            except Exception:
                pass
            self._status_anim_after_id = None

        self._status_pulse_step = 0

        def pulse():
            self._status_pulse_step = (self._status_pulse_step + 1) % 60
            t = self._status_pulse_step / 60.0
            inset = 1 + int((math.sin(t * 2 * math.pi) + 1) * 0.8)
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
