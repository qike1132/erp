"""
ERP 服务器管理器 GUI v6.0.0 — 三段式 UI 重构（设计方案 docs/ui-redesign/）

功能:
  - 三段式框架: 左侧可折叠导航 + 顶部全局状态栏 + 主内容区（一屏一模块）
  - 六大页面: 运行监控 / 服务管理 / 日志中心 / 配置管理 / 部署发布 / 告警中心
  - Design Token 体系: 暗色为主亮色可选，rgba 按底色扁平化为不透明 hex
  - Windows 集成: DPI 感知、暗色标题栏、Reduced Motion（SPI_GETCLIENTAREAANIMATION）
  - 运行监控: psutil 采样（CPU/内存/网络/磁盘/进程快照），缺 psutil 时优雅降级
  - 业务逻辑保留: 一键启动前后端、互斥托管、NSSM 生产服务、单实例、托盘、
    队列化日志（主线程零阻塞）、彻底进程树清理、配置持久化（JSON）
  - 实际端口从配置读取: API 5002 / WEB 3000 / Redis 6379（禁止 UI 硬编码）

安全约定（Mimosa 合规）:
  - 所有 subprocess 调用 argv[0] 为字符串字面量；运行时解析的可执行文件
    （python/redis/nssm 绝对路径）经 executable= 命名参数传入 —— 无 shell 参与，
    参数列表形式，路径均经存在性/后缀校验。
"""
import contextlib
import hashlib
import json
import logging
import locale
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
from collections import deque
from datetime import datetime
from pathlib import Path

_IS_WINDOWS = sys.platform == 'win32'
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0

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
import tkinter.font as tkfont
from tkinter import messagebox, ttk

# 通用『一键重启/一键关闭』组件（开发/生产共用，见 one_click_action.py）
from one_click_action import (
    ActionLock,
    ModeActionSpec,
    OneClickActionController,
    OneClickButtonGroup,
)

_VERSION = 'v6.0.0'
_WINDOW_TITLE = f'ERP 服务器管理器 {_VERSION}'

# ===================== 默认常量（可被 server_manager_config.json 覆盖） =====================
_DEFAULT_API_PORT = 5002
_DEFAULT_WEB_PORT = 3000
_DEFAULT_REDIS_PORT = 6379
_REDIS_EXE_PATHS = [Path(r'C:\Redis\redis-server.exe'), Path(r'C:\Program Files\Redis\redis-server.exe')]
_REDIS_CONF_PATHS = [Path(r'C:\Redis\redis.windows.conf'), Path(r'C:\Redis\redis.conf')]
# 生产模式：Windows 服务 (NSSM) 名称与 NSSM 常见安装位置
_SVC_API = 'erp-prod'
_SVC_ARQ = 'erp-arq'
_NSSM_CANDIDATES = [
    Path(r'C:\nssm\nssm.exe'),
    Path(r'C:\Program Files\nssm\nssm.exe'),
    Path(r'C:\Program Files (x86)\nssm\nssm.exe'),
    Path(r'C:\tools\nssm\nssm.exe'),
]
# 服务依赖：安装 erp 服务时把本机"开机自启且运行中"的 PostgreSQL/Redis 服务写入
# DependOnService，开机时保证 PG/Redis 先于 erp 服务启动，避免数据库慢启动导致
# 后端健康检查失败、监督器反复 kill/重启（开机重启风暴）。
# 扫描经 wmic 输出在 Python 侧过滤（不拼接 shell 命令）；SERVICE_DEPENDS_ON 可覆盖。
_SERVICE_DEP_PATTERN = re.compile(r'postgres|redis|memurai', re.IGNORECASE)
_PROD_STATUS_FILE_NAME = 'prod_runner.json'
_CONFIG_FILE_NAME = 'server_manager_config.json'
_ALERTS_FILE_NAME = 'server_manager_alerts.json'

# psutil 可选依赖：监控页采样必需；缺失时监控页显示引导空状态、清理功能降级
try:
    import psutil
except ImportError:
    psutil = None


class _Ports:
    """端口配置单例：业务代码统一经 _PORTS 取端口，配置保存后热更新。"""
    def __init__(self):
        self.api = _DEFAULT_API_PORT
        self.web = _DEFAULT_WEB_PORT
        self.redis = _DEFAULT_REDIS_PORT


_PORTS = _Ports()

_mutex_handle = None


def _cap(timeout=15, oem=True):
    """subprocess.run 公共 kwargs：无窗口 + 捕获输出。oem 用于 sc/nssm（OEM 代码页输出）。

    PYTHONUTF8=1 环境下默认按 UTF-8 解码 sc/nssm 输出会抛异常致 stdout 丢失，
    中文显示名的服务被误判为未安装，故显式按 OEM 解码。
    """
    kw = dict(creationflags=_NO_WINDOW, capture_output=True, timeout=timeout)
    if oem and _IS_WINDOWS:
        kw.update(encoding='oem', errors='replace')
    else:
        kw.update(text=True)
    return kw


# ===================== Windows 集成：DPI / 暗色标题栏 / 减动效 =====================

def _enable_dpi_awareness():
    """DPI 感知：否则高分屏缩放下 11~13px 小字与 1px 边框整体模糊。必须在 Tk 创建前调用。

    只用 System DPI Aware（Win6.3 API）：Per-Monitor v2 与 Tk 8.6 不兼容，
    RDP 重连/DPI 变化时会造成窗口重绘风暴甚至无响应。
    """
    if not _IS_WINDOWS:
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # SYSTEM_DPI_AWARE
    except Exception:
        with contextlib.suppress(Exception):
            ctypes.windll.user32.SetProcessDPIAware()


def _apply_dark_titlebar(root):
    """暗色标题栏（DWMWA_USE_IMMERSIVE_DARK_MODE 属性 19，Server 2019/17763 支持）。"""
    if not _IS_WINDOWS:
        return
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def _reduce_motion_enabled():
    """检测系统「在窗口中显示动画」设置（SPI_GETCLIENTAREAANIMATION）。"""
    if not _IS_WINDOWS:
        return False
    try:
        import ctypes
        # SPI_GETCLIENTAREAANIMATION = 0x1042
        enabled = ctypes.c_int(0)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            return enabled.value == 0
    except Exception:
        pass
    return False


REDUCE_MOTION = _reduce_motion_enabled()

# ===================== 单实例 / 项目定位（保留 v5.33 逻辑） =====================

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
    """纯文件系统校验（不执行）：经 shutil.which 归一化，仅接受磁盘上存在的 .exe 绝对路径。"""
    if not python_exe:
        return False
    resolved = shutil.which(python_exe)
    if not resolved:
        return False
    exe = Path(resolved)
    return exe.is_absolute() and exe.suffix.lower() == '.exe' and exe.is_file()


_PROJECT_DIR = _get_project_dir()
_FRONTEND_DIR = _PROJECT_DIR / "frontend-vite"
_PROD_STATUS_FILE = _PROJECT_DIR / 'logs' / _PROD_STATUS_FILE_NAME
_CONFIG_FILE = _PROJECT_DIR / _CONFIG_FILE_NAME
_ALERTS_FILE = _PROJECT_DIR / 'logs' / _ALERTS_FILE_NAME


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

# ===================== 配置持久化（P3 基建：端口/路径/日志/外观） =====================

_APP_CONFIG_DEFAULTS = {
    'theme': 'light',             # dark / light —— 默认亮色（对齐 UI 重构 v2 大厂规范）
    'nav_collapsed': False,
    'api_port': _DEFAULT_API_PORT,
    'web_port': _DEFAULT_WEB_PORT,
    'redis_port': _DEFAULT_REDIS_PORT,
    'redis_exe': '',              # 显式指定的 redis-server.exe 路径（优先于候选列表）
    'nssm_path': '',              # 显式指定的 nssm.exe 路径
    'max_log_lines': 2000,
    'log_keep_lines': 1600,
}


def _load_app_config():
    cfg = dict(_APP_CONFIG_DEFAULTS)
    try:
        if _CONFIG_FILE.is_file():
            stored = json.loads(_CONFIG_FILE.read_text(encoding='utf-8'))
            if isinstance(stored, dict):
                for k, v in stored.items():
                    if k in cfg:
                        cfg[k] = v
    except Exception:
        pass
    return cfg


def _save_app_config(cfg):
    try:
        _CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
        return True
    except Exception:
        return False


def _apply_config_to_runtime(cfg):
    """把配置应用到运行时单例（端口热更新：后续启动的服务用新端口）。"""
    for attr, key in (('api', 'api_port'), ('web', 'web_port'), ('redis', 'redis_port')):
        v = cfg.get(key)
        with contextlib.suppress(Exception):
            v = int(v)
        if isinstance(v, int) and 1 <= v <= 65535:
            setattr(_PORTS, attr, v)


_APP_CONFIG = _load_app_config()
_apply_config_to_runtime(_APP_CONFIG)

# ===================== 颜色工具 & 字体探测（保留） =====================

_font_cache = {}


def _font_exists(name):
    if name in _font_cache:
        return _font_cache[name]
    temp_root = None
    try:
        import tkinter.font as tkfont
        root = tk._default_root
        if root is None:
            temp_root = root = tk.Tk()  # import 期探测用，测完即销毁防泄漏
        result = name in tkfont.families(root)
    except Exception:
        result = False
    finally:
        if temp_root is not None:
            with contextlib.suppress(Exception):
                temp_root.destroy()
    _font_cache[name] = result
    return result


def _hex_to_rgb(hex_c):
    return int(hex_c[1:3], 16), int(hex_c[3:5], 16), int(hex_c[5:7], 16)


def _rgb_to_hex(r, g, b):
    return f'#{max(0, min(255, int(r))):02x}{max(0, min(255, int(g))):02x}{max(0, min(255, int(b))):02x}'


def _shift_color(hex_c, amount):
    """颜色偏移 - 模块级公共函数"""
    r, g, b = _hex_to_rgb(hex_c)
    return _rgb_to_hex(r + amount, g + amount, b + amount)


def _lerp_color(c1, c2, t):
    """颜色线性插值 - 模块级公共函数"""
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex(r1 + (r2 - r1) * t, g1 + (g2 - g1) * t, b1 + (b2 - b1) * t)


def _blend(fg_hex, bg_hex, alpha):
    """rgba 扁平化：fg×α + bg×(1−α) → 不透明 hex（Tk 颜色不支持 alpha 通道）"""
    fr, fg_, fb = _hex_to_rgb(fg_hex)
    br, bg2, bb = _hex_to_rgb(bg_hex)
    return _rgb_to_hex(fr * alpha + br * (1 - alpha), fg_ * alpha + bg2 * (1 - alpha), fb * alpha + bb * (1 - alpha))


# ===================== DesignTokens（设计方案 §5） =====================

class DesignTokens:
    """全部颜色/字体/圆角/间距常量。暗色为主，亮色一键切换。

    Tk 落地约束：
    - rgba 语义 Token 通过 tint() 按底色扁平化为不透明 hex；
    - 阴影/外发光不可实现，弹层以 1px border_strong 边框分层；
    - 字体走回退链（目标机 Server 2019 无 Segoe UI Variable / Cascadia Mono）。
    """

    DARK = {
        # 品牌与功能色
        'brand': '#2F7BFF', 'brand_hover': '#4B90FF', 'brand_active': '#1F5FD8',
        'success': '#2EBD85', 'warning': '#F7B500', 'danger': '#F53F3F',
        'info': '#22C8E5', 'purple': '#8B5CF6',
        # 中性色阶
        'bg_page': '#0F1115', 'bg_panel': '#161A1F', 'bg_elevated': '#1E242C',
        'bg_input': '#12151A',
        'border': '#2A303A', 'border_strong': '#3A4350',
        'text_primary': '#E8EAED', 'text_secondary': '#9AA3AF', 'text_muted': '#6B7480',
        # 图表色板
        'chart_cpu': '#2F7BFF', 'chart_mem': '#2EBD85', 'chart_net_dn': '#22C8E5',
        'chart_net_up': '#8B5CF6', 'chart_disk': '#F7B500',
    }
    LIGHT = {
        'brand': '#1668DC', 'brand_hover': '#1460CC', 'brand_active': '#0E4FB0',
        'success': '#00A870', 'warning': '#FF8800', 'danger': '#D54941',
        'info': '#0FC6C2', 'purple': '#722ED1',
        'bg_page': '#F5F7FA', 'bg_panel': '#FFFFFF', 'bg_elevated': '#FFFFFF',
        'bg_input': '#F2F3F5',
        'border': '#E5E6EB', 'border_strong': '#C9CDD4',
        'text_primary': '#1D2129', 'text_secondary': '#4E5969', 'text_muted': '#86909C',
        'chart_cpu': '#1668DC', 'chart_mem': '#00A870', 'chart_net_dn': '#0FC6C2',
        'chart_net_up': '#722ED1', 'chart_disk': '#FF8800',
    }

    # rgba 语义 Token：(前景色键, alpha)
    _ALPHA_TOKENS = {
        'brand_tint': ('brand', 0.14),
        'success_tint': ('success', 0.12),
        'warning_tint': ('warning', 0.12),
        'danger_tint': ('danger', 0.12),
        'info_tint': ('info', 0.12),
        'purple_tint': ('purple', 0.12),
        'hover': ('text_primary', 0.06),
        'active': ('text_primary', 0.10),
    }

    RADIUS_SM, RADIUS_MD, RADIUS_LG, RADIUS_XL = 4, 8, 12, 12
    SP = 4  # 基础间距单位，间距取 8 的倍数

    def __init__(self, theme='dark'):
        self.set_theme(theme)

    def set_theme(self, theme):
        self.theme = 'light' if theme == 'light' else 'dark'
        base = dict(self.LIGHT if self.theme == 'light' else self.DARK)
        # 兼容旧 _PALETTE 的键（StatusBadge/_STATUS_META 语义色查找）
        base['accent'] = base['brand']
        base['accent_h'] = base['brand_hover']
        base['bg_main'] = base['bg_page']
        base['bg_card'] = base['bg_panel']
        base['bg_surface'] = base['bg_panel']
        base['bg_header'] = base['bg_panel']
        base['bg_log'] = base['bg_input']
        base['text_dim'] = base['text_muted']
        base['border_card'] = base['border']
        base['log_fg'] = base['text_secondary']
        base['log_info'] = base['text_secondary']
        base['log_warn'] = base['warning']
        base['log_error'] = base['danger']
        base['log_success'] = base['success']
        self._base = base
        self._tint_cache = {}
        # 字体链必须 CJK 安全优先（Segoe UI/Consolas 无中文字形 → 豆腐块乱码，
        # 且逐字符字体回落显著拖慢渲染）。mono 宁可放弃等宽也不选 Consolas。
        self.font_ui = self._pick_family(('Microsoft YaHei UI', 'Segoe UI', 'Segoe UI Variable'))
        self.font_mono = self._pick_family(('Microsoft YaHei Mono', 'Cascadia Mono', 'Microsoft YaHei UI'))

    @staticmethod
    def _pick_family(candidates):
        for fam in candidates:
            try:
                if _font_exists(fam):
                    return fam
            except Exception:
                continue
        return candidates[-1]

    # ---- 颜色访问 ----
    def c(self, key):
        """取不透明 Token。rgba 语义键（*_tint / hover / active）需用 tint(key, surface)。"""
        return self._base.get(key, self._base['text_secondary'])

    def tint(self, key, surface='bg_panel'):
        """rgba Token 按底色扁平化（带缓存）。surface: bg_page/bg_panel/bg_elevated/bg_input"""
        fg_key, alpha = self._ALPHA_TOKENS[key]
        bg = self._base.get(surface, self._base['bg_panel'])
        ck = (key, surface, self.theme)
        if ck not in self._tint_cache:
            self._tint_cache[ck] = _blend(self._base[fg_key], bg, alpha)
        return self._tint_cache[ck]

    # ---- 语义别名（StatusBadge 兼容） ----
    def palette(self):
        """返回扁平化后的兼容调色板（含 *_tint 键，基于 panel 底色）。"""
        pal = dict(self._base)
        for key in self._ALPHA_TOKENS:
            pal[key] = self.tint(key, 'bg_panel')
        pal['accent_tint'] = pal['brand_tint']  # _STATUS_META 兼容别名
        return pal

    def f(self, size, weight='normal'):
        return (self.font_ui, size, weight)

    def fm(self, size, weight='normal'):
        return (self.font_mono, size, weight)


TOKENS = DesignTokens(_APP_CONFIG.get('theme', 'dark'))


# ===================== 进程管理辅助（v5.33 保留，Mimosa 合规形态） =====================

def _taskkill(pid, force=True, tree=True):
    """统一的进程终止函数（参数列表 + 字面量 argv[0]，无 shell）"""
    if not _IS_WINDOWS or not pid:
        return
    with contextlib.suppress(Exception):
        subprocess.run(['taskkill', '/F' if force else '', '/T' if tree else '', '/PID', str(pid)],
                       creationflags=_NO_WINDOW, capture_output=True, timeout=10)


def _taskkill_many(pids, force=True, tree=True):
    """批量终止多个 PID。优先 psutil（无进程创建开销、秒级）；缺失时回落逐个 taskkill。"""
    if not _IS_WINDOWS or not pids:
        return
    if psutil is not None:
        for pid in pids:
            with contextlib.suppress(Exception):
                psutil.Process(int(pid)).kill()
        return
    for pid in pids:
        _taskkill(pid, force=force, tree=tree)


def _kill_port_process(port, msg_queue=None):
    """终止占用指定端口的进程（netstat 输出按 OEM 解码，中文 Windows 必需）"""
    try:
        result = subprocess.run(['netstat', '-ano'], **_cap(5))
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
        result = subprocess.run(['netstat', '-ano'], **_cap(5))
        pids = set()
        for line in result.stdout.split('\n'):
            if f':{port}' in line and ('LISTENING' in line or 'ESTABLISHED' in line):
                parts = line.split()
                if len(parts) >= 5 and parts[-1].isdigit():
                    pids.add(parts[-1])
        for pid in pids:
            try:
                tasklist = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'], **_cap(5))
                lines = [l.strip() for l in tasklist.stdout.split('\n') if l.strip()]
                if lines:
                    parts = lines[0].split('","')
                    if len(parts) >= 2:
                        occupiers.append((pid, parts[0].strip('"')))
            except Exception:
                occupiers.append((pid, '未知进程'))
    except Exception:
        pass
    return occupiers


# ===================== 状态徽章（v5.33 保留：统一状态枚举 → 文案/颜色/点样式/动画） =====================

_STATUS_META = {
    'running':       {'text': '运行中', 'color': 'success',     'tint': 'success_tint', 'dot': 'dot',   'anim': 'breath' if not REDUCE_MOTION else None},
    'stopped':       {'text': '已停止', 'color': 'text_dim',    'tint': 'bg_input',     'dot': 'ring',  'anim': None},
    'error':         {'text': '异常',   'color': 'danger',      'tint': 'danger_tint',  'dot': 'cross', 'anim': 'pulse' if not REDUCE_MOTION else None},
    'restarting':    {'text': '重启中', 'color': 'warning',     'tint': 'warning_tint', 'dot': 'dot',   'anim': 'blink' if not REDUCE_MOTION else None},
    'deploying':     {'text': '启动中', 'color': 'accent',      'tint': 'accent_tint',  'dot': 'arc',   'anim': 'spin' if not REDUCE_MOTION else None},
    'not_installed': {'text': '未安装', 'color': 'text_dim',    'tint': 'bg_input',     'dot': 'ring',  'anim': None},
    'starting':      {'text': '启动中', 'color': 'warning',     'tint': 'warning_tint', 'dot': 'dot',   'anim': 'blink' if not REDUCE_MOTION else None},
}

_STATUS_SIZE = {
    'lg': {'padx': 10, 'pady': 4, 'dot': 8, 'gap': 6, 'font': ('Microsoft YaHei UI', 9, 'bold'), 'radius': 10},
    'md': {'padx': 8,  'pady': 3, 'dot': 7, 'gap': 5, 'font': ('Microsoft YaHei UI', 9, 'bold'), 'radius': 9},
    'sm': {'padx': 6,  'pady': 2, 'dot': 6, 'gap': 4, 'font': ('Microsoft YaHei UI', 8),         'radius': 7},
}


class StatusBadge(tk.Canvas):
    """圆角胶囊状态徽章：状态点 + 文字 + 语义色容器（Status Tag 风格）。

    用于三种场景：状态栏(lg) / 卡片详情(md) / 监控面板组件(sm)。
    颜色经 palette（DesignTokens.palette() 扁平化结果）注入。
    """

    def __init__(self, parent, state='stopped', text=None, size='md', palette=None, canvas_bg=None):
        self._palette = palette or TOKENS.palette()
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
        super().__init__(parent, width=w, height=h, highlightthickness=0, bg=canvas_bg or TOKENS.c('bg_panel'))
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
        color = self._palette.get(self._meta['color'], self._palette.get('text_muted', '#8e8e93'))
        tint = self._palette.get(self._meta['tint'], self._palette.get('bg_input', '#f2f2f7'))
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
            self.create_line(cx-k, cy-k, cx+k, cy+k, fill=self._palette.get('bg_panel', '#ffffff'), width=1)
            self.create_line(cx+k, cy-k, cx-k, cy+k, fill=self._palette.get('bg_panel', '#ffffff'), width=1)
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
                    self.create_oval(cx-ring_r, cy-r-ring_r, cx+ring_r, cy+ring_r, outline=color, width=1)
            self.create_oval(cx-r, cy-r, cx+r, cy+r, fill=color, outline='')

    def _tick(self):
        self._phase = (self._phase + 6) % 360
        # 页面未显示（被 tkraise 压底）时跳过重绘，只保留廉价定时器——
        # 十几个徽章在隐藏页全速重绘是卡顿的主要来源之一
        if self.winfo_ismapped():
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


# ===================== RoundedButton（Token 化升级：loading/text 变体） =====================

def _create_tray_icon_image():
    try:
        from PIL import Image, ImageDraw
        img = Image.new('RGBA', (16, 16), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse([2, 2, 14, 14], fill=(47, 123, 255, 255))
        return img
    except Exception:
        return None


class RoundedButton(tk.Canvas):
    """基于 Canvas 的圆角按钮 — 变体 solid / outlined / subtle / text，tone 走 DesignTokens。

    设计规格: 高度 ~32px (padx=14, pady=4)；圆角 8px；hover 150ms 平滑过渡；
    loading 态显示旋转弧并禁点（设计方案 §6.8）。
    """

    def __init__(self, parent, text='', variant='solid', tone='brand',
                 command=None, font=None, padx=14, pady=4, radius=6, state='normal',
                 canvas_bg=None, small=False, **kw):
        self._tokens = TOKENS
        fnt = font or TOKENS.f(8, 'bold') if small else (font or TOKENS.f(9, 'bold'))
        self._tone_key = tone if tone in ('brand', 'success', 'danger', 'warning', 'info', 'purple') else 'brand'
        self._variant = variant
        self._canvas_bg = canvas_bg or TOKENS.c('bg_panel')
        import tkinter.font as tkfont
        f = tkfont.Font(font=fnt)
        text_w = f.measure(text)
        w = max(76 if not small else 48, text_w + padx * 2 + 24)  # 预留 loading 弧空间
        h = f.metrics('linespace') + pady * 2
        cursor = 'hand2' if state == 'normal' else 'arrow'
        super().__init__(parent, width=w, height=h, highlightthickness=0, cursor=cursor, bg=self._canvas_bg, **kw)
        self._text = text
        self._font = fnt
        self._radius = radius
        self._command = command
        self._state = state
        self._loading = False
        self._hover, self._press = False, False
        self._anim_after_id = None
        self._spin_phase = 0
        self._spin_after_id = None
        self._resolve_colors()
        self.bind('<Configure>', self._draw)
        self.bind('<Enter>', lambda e: self._hover_in())
        self.bind('<Leave>', lambda e: self._hover_out())
        self.bind('<ButtonPress-1>', lambda e: self._press_in())
        self.bind('<ButtonRelease-1>', lambda e: self._press_out())
        self._draw()

    def _resolve_colors(self):
        t = self._tokens
        canvas = self._canvas_bg
        tone = t.c(self._tone_key)
        if self._tone_key == 'brand':
            hover_c = t.c('brand_hover')
        else:
            sign = 16 if t.theme == 'dark' else -16
            hover_c = _shift_color(tone, sign)
        disabled_bg = t.c('bg_input')
        disabled_fg = t.c('text_muted')
        if self._variant == 'solid':
            if self._tone_key == 'brand':
                fill, fill_h, fg = tone, hover_c, '#ffffff'
            elif self._tone_key == 'neutral':
                fill, fill_h, fg = t.c('bg_input'), t.c('bg_elevated'), t.c('text_primary')
            else:
                fill, fill_h, fg = tone, hover_c, '#ffffff'
            outline, outline_h, outline_w = '', '', 0
        elif self._variant == 'outlined':
            fill, fill_h, fg = canvas, _blend(tone, canvas, 0.12), tone
            outline, outline_h, outline_w = tone, hover_c, 1
        elif self._variant == 'subtle':
            fill, fill_h, fg = _blend(tone, canvas, 0.12), _blend(tone, canvas, 0.20), tone
            outline, outline_h, outline_w = _blend(tone, canvas, 0.35), tone, 1
        else:  # text
            fill, fill_h, fg = canvas, _blend(tone, canvas, 0.10), tone
            outline, outline_h, outline_w = '', '', 0
        self._fill, self._hover_fill, self._fg = fill, fill_h, fg
        self._outline, self._outline_hover, self._outline_w = outline, outline_h, outline_w
        self._disabled_bg, self._disabled_fg = disabled_bg, disabled_fg

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2, x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _effective_state(self):
        return 'disabled' if (self._state == 'disabled' or self._loading) else self._state

    def _draw(self, _=None):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            w = self.winfo_reqwidth()
        if h < 4:
            h = self.winfo_reqheight()
        if w < 4 or h < 4:
            return
        r = min(self._radius, w // 2, h // 2)
        st = self._effective_state()
        if st == 'disabled':
            bg, fg = self._disabled_bg, self._disabled_fg
            outline, outline_w = self._tokens.c('border'), 1
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
                bg, outline, fg = self._fill, self._outline, self._fg
            outline_w = self._outline_w
        offset = 1 if self._press else 0
        if outline_w and outline:
            self._round_rect(offset, offset, w - offset, h - offset, r, fill=outline, outline='')
            self._round_rect(offset + outline_w, offset + outline_w, w - offset - outline_w, h - offset - outline_w,
                             max(0, r - outline_w), fill=bg, outline='')
        else:
            self._round_rect(offset, offset, w - offset, h - offset, r, fill=bg, outline='')
        tx = w // 2
        if self._loading:
            # loading: 旋转弧 + 文案
            self._draw_spin_arc(10, h // 2, fg)
            import tkinter.font as tkfont
            tw = tkfont.Font(font=self._font).measure(self._text)
            self.create_text(10 + 10 + (w - 20 - tw) // 2 + tw // 2, h // 2, text=self._text, fill=fg, font=self._font)
        else:
            self.create_text(tx, h // 2, text=self._text, fill=fg, font=self._font)

    def _draw_spin_arc(self, cx, cy, color):
        r = 5
        start = self._spin_phase % 360
        self.create_arc(cx - r, cy - r, cx + r, cy + r, start=start, extent=270, style='arc', outline=color, width=2)

    def _spin_tick(self):
        if not self._loading:
            self._spin_after_id = None
            return
        self._spin_phase = (self._spin_phase + 30) % 360
        self._draw()
        self._spin_after_id = self.after(60, self._spin_tick)

    def set_loading(self, loading, text=None):
        if text is not None:
            self._text = text
        if loading == self._loading:
            if text is not None:
                self._draw()
            return
        self._loading = loading
        self.configure(cursor='arrow' if loading else 'hand2')
        self._draw()
        if loading and not REDUCE_MOTION:
            self._spin_tick()
        elif self._spin_after_id:
            self.after_cancel(self._spin_after_id)
            self._spin_after_id = None

    def _animate_hover(self, target_hover):
        if self._effective_state() == 'disabled':
            self._draw()
            return
        if REDUCE_MOTION:
            self._hover = target_hover
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
        if self._effective_state() != 'disabled':
            self._animate_hover(True)

    def _hover_out(self):
        if self._effective_state() != 'disabled':
            self._animate_hover(False)

    def _press_in(self):
        if self._effective_state() != 'disabled':
            self._press = True
            self._draw()

    def _press_out(self):
        was_pressed = self._press
        self._press = False
        self._draw()
        if was_pressed and self._effective_state() == 'normal' and self._command:
            self._command()

    def config(self, **kw):
        if 'state' in kw:
            self._state = kw.pop('state')
            kw['cursor'] = 'arrow' if (self._state == 'disabled' or self._loading) else 'hand2'
        if 'text' in kw:
            self._text = kw.pop('text')
        if 'command' in kw:
            self._command = kw.pop('command')
        super().config(**kw)
        self._draw()


# ===================== 图标绘制（Canvas 线条图标，主题色随动） =====================

def draw_icon(cv, name, color, s=17):
    """Canvas 线条图标（17px 网格）：统一 1.5px 圆头笔触、闭合几何、实心点用小圆。
    首版教训：零长度线当"点"、单弧当"铃铛"在 16px 下形同一团乱线，全部改为规则几何。"""
    cv.delete('icon')
    x0, y0 = (cv.winfo_width() or s) / 2 - s / 2, (cv.winfo_height() or s) / 2 - s / 2
    tag = 'icon'
    W = 1.5
    L = dict(fill='', outline=color, width=W, tags=tag)
    A = dict(outline=color, width=W, style='arc', tags=tag)

    def P(*pts):
        flat = []
        for i in range(0, len(pts), 2):
            flat += [x0 + pts[i], y0 + pts[i + 1]]
        cv.create_line(flat, fill=color, width=W, capstyle='round', joinstyle='round', tags=tag)

    def dot(cx, cy, d=2.6):
        r = d / 2
        cv.create_oval(x0 + cx - r, y0 + cy - r, x0 + cx + r, y0 + cy + r, fill=color, outline='', tags=tag)

    if name == 'overview':          # 脉冲折线
        P(1.5, 9.5, 5, 9.5, 7.5, 4, 10.5, 13.5, 12.5, 7, 13.5, 9.5, 15.5, 9.5)
    elif name == 'services':        # 服务器堆叠：两台 + 指示灯 + 散热缝
        cv.create_rectangle(x0 + 1.5, y0 + 2.5, x0 + 15.5, y0 + 7.5, **L)
        cv.create_rectangle(x0 + 1.5, y0 + 9.5, x0 + 15.5, y0 + 14.5, **L)
        dot(4, 5)
        dot(4, 12)
        P(9, 5, 13, 5)
        P(9, 12, 13, 12)
    elif name == 'logs':            # 文档（折角）+ 三行
        P(4, 1.5, 11.5, 1.5, 14, 4.5, 14, 15.5, 4, 15.5, 4, 1.5)
        P(11.5, 1.5, 11.5, 4.5, 14, 4.5)
        P(6.5, 7.5, 11.5, 7.5)
        P(6.5, 10, 11.5, 10)
        P(6.5, 12.5, 9.5, 12.5)
    elif name == 'config':          # 齿轮：外圈 + 8 根幅条齿 + 中孔
        cx = cy = 8.5
        for k in range(8):
            ang = k * math.pi / 4
            P(cx + 4.6 * math.cos(ang), cy + 4.6 * math.sin(ang),
              cx + 6.8 * math.cos(ang), cy + 6.8 * math.sin(ang))
        cv.create_oval(x0 + cx - 5.4, y0 + cy - 5.4, x0 + cx + 5.4, y0 + cy + 5.4, **L)
        cv.create_oval(x0 + cx - 2, y0 + cy - 2, x0 + cx + 2, y0 + cy + 2, **L)
    elif name == 'deploy':          # 立方体（箱）
        P(8.5, 1.5, 15.5, 5, 15.5, 12, 8.5, 15.5, 1.5, 12, 1.5, 5, 8.5, 1.5)
        P(8.5, 8.5, 15.5, 5)
        P(8.5, 8.5, 8.5, 15.5)
        P(8.5, 8.5, 1.5, 5)
    elif name == 'alerts':          # 铃铛：穹顶弧 + 两翼 + 底沿 + 铃锤
        cv.create_arc(x0 + 2.5, y0 + 1, x0 + 14.5, y0 + 12.5, start=0, extent=180, **A)
        P(2.5, 7, 2.5, 11.5, 14.5, 11.5, 14.5, 7)
        P(1, 13, 16, 13)
        cv.create_arc(x0 + 6.2, y0 + 12, x0 + 10.8, y0 + 16, start=180, extent=180, **A)
    elif name == 'cpu':             # 芯片：方核 + 内核 + 引脚
        cv.create_rectangle(x0 + 4.5, y0 + 4.5, x0 + 12.5, y0 + 12.5, **L)
        cv.create_rectangle(x0 + 7, y0 + 7, x0 + 10, y0 + 10, **L)
        P(7, 1.5, 7, 3)
        P(10, 1.5, 10, 3)
        P(7, 14, 7, 15.5)
        P(10, 14, 10, 15.5)
        P(1.5, 7, 3, 7)
        P(1.5, 10, 3, 10)
        P(14, 7, 15.5, 7)
        P(14, 10, 15.5, 10)
    elif name == 'mem':             # 内存条 + 底部金手指
        cv.create_rectangle(x0 + 1.5, y0 + 4, x0 + 15.5, y0 + 11.5, **L)
        P(5, 11.5, 5, 14.5)
        P(8.5, 11.5, 8.5, 14.5)
        P(12, 11.5, 12, 14.5)
    elif name == 'disk':            # 仪表盘：圆 + 指针
        cv.create_oval(x0 + 1.5, y0 + 1.5, x0 + 15.5, y0 + 15.5, **L)
        P(8.5, 8.5, 12.2, 4.8)
        dot(8.5, 8.5, 2.4)
    elif name == 'net':             # 上下行双箭头
        P(2.5, 5.5, 13.5, 5.5)
        P(10.5, 2.5, 13.5, 5.5, 10.5, 8.5)
        P(14.5, 11.5, 3.5, 11.5)
        P(6.5, 8.5, 3.5, 11.5, 6.5, 14.5)
    elif name == 'refresh':         # 环形箭头
        cv.create_arc(x0 + 2.5, y0 + 2.5, x0 + 14.5, y0 + 14.5, start=320, extent=300, **A)
        P(13.8, 1.8, 15.2, 5.8, 11.2, 6.4)
    elif name == 'chevron_left':
        P(10.5, 3.5, 5.5, 8.5, 10.5, 13.5)
    elif name == 'chevron_right':
        P(6.5, 3.5, 11.5, 8.5, 6.5, 13.5)
    elif name == 'sun':             # 圆 + 8 根光线
        cv.create_oval(x0 + 5.2, y0 + 5.2, x0 + 11.8, y0 + 11.8, **L)
        P(8.5, 1, 8.5, 3)
        P(8.5, 14, 8.5, 16)
        P(1, 8.5, 3, 8.5)
        P(14, 8.5, 16, 8.5)
        P(3.2, 3.2, 4.6, 4.6)
        P(12.4, 12.4, 13.8, 13.8)
        P(3.2, 13.8, 4.6, 12.4)
        P(12.4, 4.6, 13.8, 3.2)
    elif name == 'moon':            # 月牙：大圆 + 背景色圆咬出缺口
        cv.create_oval(x0 + 2.5, y0 + 1.5, x0 + 15.5, y0 + 15.5, **L)
        cv.create_oval(x0 + 7.5, y0 + 4.5, x0 + 17.5, y0 + 15.5,
                       fill=cv.cget('background'), outline=color, width=W, tags=tag)
    elif name == 'menu':
        P(2, 4.5, 15, 4.5)
        P(2, 8.5, 15, 8.5)
        P(2, 12.5, 15, 12.5)
    elif name == 'check':
        P(3, 9, 7, 13, 14, 4)
    elif name == 'x':
        P(4, 4, 13, 13)
        P(13, 4, 4, 13)
    elif name == 'warn':            # 三角 + 感叹
        P(8.5, 2, 15.8, 14.5, 1.2, 14.5, 8.5, 2)
        P(8.5, 6.5, 8.5, 10.5)
        dot(8.5, 12.8, 2)
    elif name == 'info':            # 圆 + i
        cv.create_oval(x0 + 2, y0 + 2, x0 + 15, y0 + 15, **L)
        dot(8.5, 5.5, 2)
        P(8.5, 8, 8.5, 12)
    elif name == 'empty':           # 收件箱
        P(2, 3.5, 2, 14.5, 15, 14.5, 15, 3.5)
        P(2, 8, 5.5, 8, 7, 11.5, 10, 11.5, 11.5, 8, 15, 8)
    return tag


class IconLabel(tk.Canvas):
    """固定尺寸图标画布（用于导航/工具栏按钮）。"""
    def __init__(self, parent, name, size=18, icon_size=16, bg=None):
        self._name = name
        super().__init__(parent, width=size, height=size, highlightthickness=0, bg=bg or TOKENS.c('bg_panel'))
        self._icon_size = icon_size
        self.bind('<Configure>', lambda e: self.refresh())

    def refresh(self):
        draw_icon(self, self._name, self.itemcget('icon', 'fill') if self.find_withtag('icon') else _icon_color(), self._icon_size)

    def set_icon(self, name, color=None):
        self._name = name
        draw_icon(self, name, color or _icon_color(), self._icon_size)

    def set_color(self, color):
        draw_icon(self, self._name, color, self._icon_size)


def _icon_color():
    return TOKENS.c('text_secondary')


# ===================== Tooltip（延迟 300ms，弹层边框分层） =====================

class Tooltip:
    _current = None

    def __init__(self, widget, text, delay=300):
        self._widget = widget
        self._text = text
        self._delay = delay
        self._after_id = None
        self._tip = None
        widget.bind('<Enter>', self._enter, add='+')
        widget.bind('<Leave>', self._leave, add='+')
        widget.bind('<ButtonPress>', self._leave, add='+')

    def _enter(self, _=None):
        self._cancel()
        self._after_id = self._widget.after(self._delay, self._show)

    def _leave(self, _=None):
        self._cancel()
        self._hide()

    def _cancel(self):
        if self._after_id:
            with contextlib.suppress(Exception):
                self._widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self):
        if self._tip or not self._text:
            return
        tip = tk.Toplevel(self._widget)
        tip.wm_overrideredirect(True)
        try:
            tip.attributes('-topmost', True)
        except Exception:
            pass
        frame = tk.Frame(tip, bg=TOKENS.c('bg_elevated'), highlightbackground=TOKENS.c('border_strong'), highlightthickness=1)
        tk.Label(frame, text=self._text, font=TOKENS.f(8), fg=TOKENS.c('text_primary'),
                 bg=TOKENS.c('bg_elevated'), padx=10, pady=5).pack()
        frame.pack()
        x = self._widget.winfo_rootx() + self._widget.winfo_width() + 8
        y = self._widget.winfo_rooty() + self._widget.winfo_height() // 2 - 14
        tip.wm_geometry(f'+{x}+{y}')
        self._tip = tip
        Tooltip._current = self

    def _hide(self):
        if self._tip:
            with contextlib.suppress(Exception):
                self._tip.destroy()
            self._tip = None


def attach_tooltip(widget, text):
    Tooltip(widget, text)
    return widget


# ===================== Segmented 分段筛选器 =====================

class Segmented(tk.Frame):
    """单选分段控件（日志级别 / 状态筛选）。选中项 = elevated 底 + 边框。"""

    def __init__(self, parent, labels, command=None, bg=None):
        super().__init__(parent, bg=bg or TOKENS.c('bg_input'), highlightbackground=TOKENS.c('border'),
                         highlightthickness=1)
        self._labels = labels
        self._command = command
        self._active = 0
        self._buttons = []
        for i, label in enumerate(labels):
            b = tk.Label(self, text=label, font=TOKENS.f(8), padx=10, pady=2, cursor='hand2')
            b.pack(side=tk.LEFT, padx=2, pady=2)
            b.bind('<Button-1>', lambda e, idx=i: self.set_active(idx, fire=True))
            self._buttons.append(b)
        self.set_active(0, fire=False)

    def set_active(self, idx, fire=True):
        self._active = idx
        for i, b in enumerate(self._buttons):
            if i == idx:
                b.config(bg=TOKENS.c('bg_elevated'), fg=TOKENS.c('text_primary'),
                         highlightbackground=TOKENS.c('border_strong'), highlightthickness=1)
            else:
                b.config(bg=TOKENS.c('bg_input'), fg=TOKENS.c('text_secondary'), highlightthickness=0)
        if fire and self._command:
            self._command(idx)

    @property
    def active_label(self):
        return self._labels[self._active]


# ===================== Toast 右上角堆叠（设计方案 §6.7） =====================

class ToastManager:
    """右上角 Toast 队列：图标 + 标题 + 描述，3.2s 自动消失，可手动关闭。

    Tk 无法绘制 box-shadow，以 1px border_strong 边框分层（方案 §5.4 落地注）。
    """

    _TONE = {'success': ('check', 'success'), 'error': ('x', 'danger'),
             'warn': ('warn', 'warning'), 'info': ('info', 'info')}

    def __init__(self, parent):
        self._parent = parent
        self._container = tk.Frame(parent, bg=TOKENS.c('bg_page'), bd=0, highlightthickness=0)
        self._toasts = []
        self._after_ids = []

    def cancel_all(self):
        for aid in self._after_ids:
            with contextlib.suppress(Exception):
                self._parent.after_cancel(aid)
        self._after_ids = []

    def _relayout(self):
        self._container.update_idletasks()
        w = self._parent.winfo_width()
        self._container.place_configure(x=max(8, w - 340), y=8, width=332, anchor='ne')

    def show(self, kind, title, desc='', duration=3200):
        icon_name, tone_key = self._TONE.get(kind, self._TONE['info'])
        tone = TOKENS.c(tone_key)
        card = tk.Frame(self._container, bg=TOKENS.c('bg_elevated'),
                        highlightbackground=TOKENS.c('border_strong'), highlightthickness=1)
        icon = tk.Canvas(card, width=20, height=20, highlightthickness=0, bg=TOKENS.c('bg_elevated'))
        draw_icon(icon, icon_name, tone, 14)
        icon.pack(side=tk.LEFT, padx=(10, 0), pady=10)
        body = tk.Frame(card, bg=TOKENS.c('bg_elevated'))
        body.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 4), pady=8)
        tk.Label(body, text=title, font=TOKENS.f(9, 'bold'), fg=TOKENS.c('text_primary'),
                 bg=TOKENS.c('bg_elevated'), anchor='w').pack(fill=tk.X)
        if desc:
            tk.Label(body, text=desc, font=TOKENS.f(8), fg=TOKENS.c('text_secondary'),
                     bg=TOKENS.c('bg_elevated'), anchor='w', wraplength=250, justify=tk.LEFT).pack(fill=tk.X)
        close = tk.Label(card, text='×', font=TOKENS.f(10), fg=TOKENS.c('text_muted'),
                         bg=TOKENS.c('bg_elevated'), cursor='hand2', padx=6)
        close.pack(side=tk.RIGHT)
        card.pack(fill=tk.X, pady=(0, 8))
        self._toasts.append(card)
        if len(self._toasts) > 5:
            old = self._toasts.pop(0)
            with contextlib.suppress(Exception):
                old.destroy()
        self._relayout()
        self._container.lift()
        close.bind('<Button-1>', lambda e: self._dismiss(card))
        if duration:
            self._after_ids.append(self._parent.after(duration, lambda: self._dismiss(card)))

    def _dismiss(self, card):
        if card in self._toasts:
            self._toasts.remove(card)
        with contextlib.suppress(Exception):
            card.destroy()


# ===================== 空状态 / 迷你进度条 =====================

class EmptyState(tk.Frame):
    def __init__(self, parent, text, action_text=None, action_cmd=None, bg=None):
        bg = bg or TOKENS.c('bg_panel')
        super().__init__(parent, bg=bg)
        icon = tk.Canvas(self, width=44, height=44, highlightthickness=0, bg=bg)
        draw_icon(icon, 'empty', TOKENS.c('border_strong'), 30)
        icon.pack(pady=(24, 8))
        tk.Label(self, text=text, font=TOKENS.f(8), fg=TOKENS.c('text_muted'), bg=bg).pack()
        if action_text and action_cmd:
            btn = RoundedButton(self, text=action_text, variant='outlined', tone='brand',
                                command=action_cmd, canvas_bg=bg, small=True)
            btn.pack(pady=(10, 20))
        else:
            tk.Frame(self, bg=bg, height=20).pack()


class MetricBar(tk.Canvas):
    """细进度条（CPU/内存/磁盘），阈值变色：正常→success，>70%→warning，>90%→danger。"""

    def __init__(self, parent, width=110, height=5, bg=None):
        super().__init__(parent, width=width, height=height, highlightthickness=0, bg=bg or TOKENS.c('bg_input'))

    def set_value(self, pct):
        if not self.winfo_ismapped():
            return
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            w = int(self['width'])
        if h < 4:
            h = int(self['height'])
        tone = 'success'
        if pct > 90:
            tone = 'danger'
        elif pct > 70:
            tone = 'warning'
        color = TOKENS.c(tone)
        self.create_rectangle(0, 0, w, h, fill=TOKENS.c('bg_input'), outline='')
        fill_w = max(0, min(w, int(w * pct / 100.0)))
        if fill_w > 0:
            self.create_rectangle(0, 0, fill_w, h, fill=color, outline='')


# ===================== 图表：SparkLine / TrendChart（Canvas 折线，设计方案 §6.3） =====================

class SparkLine(tk.Canvas):
    def __init__(self, parent, color_key, width=64, height=26, max_points=60, bg=None):
        super().__init__(parent, width=width, height=height, highlightthickness=0, bg=bg or TOKENS.c('bg_input'))
        self._color_key = color_key
        self._data = deque(maxlen=max_points)
        self.bind('<Configure>', lambda e: self._draw())

    def push(self, value):
        self._data.append(value)
        if self.winfo_ismapped():
            self._draw()

    def redraw(self):
        self._draw()

    def _draw(self):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4 or len(self._data) < 2:
            return
        vals = list(self._data)
        vmin, vmax = min(vals), max(vals)
        rng = (vmax - vmin) or 1.0
        pad = 2
        pts = []
        for i, v in enumerate(vals):
            x = pad + (w - pad * 2) * i / (len(vals) - 1)
            y = h - pad - (h - pad * 2) * (v - vmin) / rng
            pts += [x, y]
        self.create_line(pts, fill=TOKENS.c(self._color_key), width=1.5, capstyle='round', smooth=True)


class TrendChart(tk.Canvas):
    """多序列折线 + 面积 + 网格 + hover 十字参考线。

    series: [(key, color_key, label)]；max_points 采样点（2s×60 = 120s 窗口）。
    """

    def __init__(self, parent, series, max_points=60, y_unit='%', y_max=None, height=170, bg=None):
        self._series_spec = series
        self._max_points = max_points
        self._y_unit = y_unit
        self._y_max = y_max
        self._data = {key: deque(maxlen=max_points) for key, _, _ in series}
        bg = bg or TOKENS.c('bg_input')
        super().__init__(parent, height=height, highlightthickness=0, bg=bg,
                         highlightbackground=TOKENS.c('border'))
        self.bind('<Configure>', lambda e: self.redraw())
        self.bind('<Motion>', self._on_motion)
        self.bind('<Leave>', lambda e: self._clear_cross())

    def push(self, values_dict):
        for key, v in values_dict.items():
            if key in self._data:
                self._data[key].append(v)
        # 页面隐藏时只累计数据不重绘；回到页面时 on_show() 统一重绘
        if self.winfo_ismapped():
            self.redraw()

    def values(self, key):
        return list(self._data.get(key, ()))

    def _clear_cross(self):
        self.delete('cross', 'crosstip')

    def _on_motion(self, event):
        self.delete('cross', 'crosstip')
        w, h = self.winfo_width(), self.winfo_height()
        padL, padR, padT, padB = 36, 10, 10, 20
        if w - padL - padR < 10 or not any(self._data[k] for k in self._data):
            return
        n = max(len(v) for v in self._data.values())
        if n < 2:
            return
        idx = int((event.x - padL) / (w - padL - padR) * (n - 1) + 0.5)
        idx = max(0, min(n - 1, idx))
        x = padL + (w - padL - padR) * idx / (n - 1)
        self.create_line(x, padT, x, h - padB, fill=TOKENS.c('border_strong'), dash=(2, 3), tags='cross')
        # 悬浮数值提示（画布内绘制）
        parts = []
        for key, ckey, label in self._series_spec:
            vals = self._data[key]
            if idx < len(vals):
                parts.append(f'{label} {vals[idx]:.1f}{self._y_unit}')
        if parts:
            text = f'-{((n - 1 - idx) * 2)}s  ' + '  '.join(parts)
            fw = tkfont.Font(font=TOKENS.fm(8)).measure(text)
            tx = min(max(padL, x - fw / 2), w - fw - 4)
            self.create_rectangle(tx, 2, tx + fw + 12, 18, fill=TOKENS.c('bg_elevated'),
                                  outline=TOKENS.c('border_strong'), tags='crosstip')
            self.create_text(tx + 6, 10, text=text, anchor='w', font=TOKENS.fm(8),
                             fill=TOKENS.c('text_primary'), tags='crosstip')

    def redraw(self):
        if not self.winfo_ismapped():
            return
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 40 or h < 40:
            return
        padL, padR, padT, padB = 36, 10, 10, 20
        plot_w, plot_h = w - padL - padR, h - padT - padB
        # 网格 + Y 轴刻度
        for i in range(5):
            y = padT + plot_h * i / 4
            self.create_line(padL, y, w - padR, y, fill=TOKENS.c('border'), width=0.5)
        n = max((len(v) for v in self._data.values()), default=0)
        for key, ckey, label in self._series_spec:
            vals = list(self._data[key])
            if len(vals) < 2:
                continue
            ymax = self._y_max
            if ymax is None:
                all_vals = [v for k in self._data for v in self._data[k]]
                ymax = max(all_vals) * 1.2 if all_vals else 1.0
            ymax = max(ymax, 0.001)
            pts = []
            for i, v in enumerate(vals):
                x = padL + plot_w * i / (self._max_points - 1)
                y = padT + plot_h * (1 - max(0, min(v, ymax)) / ymax)
                pts += [x, y]
            color = TOKENS.c(ckey)
            area = pts + [pts[-2], h - padB, pts[0], h - padB]
            self.create_polygon(area, fill=_blend(color, TOKENS.c('bg_input'), 0.12), outline='', smooth=True)
            self.create_line(pts, fill=color, width=2, capstyle='round', joinstyle='round', smooth=True)
        # Y 轴标签
        ymax_lab = self._y_max or 100
        for i in range(5):
            y = padT + plot_h * i / 4
            val = ymax_lab * (4 - i) / 4
            self.create_text(padL - 6, y, text=f'{val:.0f}{self._y_unit}', anchor='e',
                             font=TOKENS.fm(7), fill=TOKENS.c('text_muted'))
        # X 轴标签（120s 窗口）
        for i in range(7):
            x = padL + plot_w * i / 6
            self.create_text(x, h - 8, text=f'-{(6 - i) * 20}s', anchor='center' if 0 < i < 6 else ('w' if i == 0 else 'e'),
                             font=TOKENS.fm(7), fill=TOKENS.c('text_muted'))
        # 图例
        lx = padL
        for key, ckey, label in self._series_spec:
            color = TOKENS.c(ckey)
            self.create_rectangle(lx, 4, lx + 12, 7, fill=color, outline='')
            self.create_text(lx + 16, 5, text=label, anchor='w', font=TOKENS.f(7), fill=TOKENS.c('text_secondary'))
            lx += 16 + tkfont.Font(font=TOKENS.f(7)).measure(label) + 14


# ===================== 三段式框架：SideNav / TopBar / StatusBar / PageRouter =====================

NAV_ITEMS = [
    ('运行', [
        ('overview', '运行监控', 'overview'),
        ('services', '服务管理', 'services'),
    ]),
    ('运维', [
        ('logs', '日志中心', 'logs'),
        ('config', '配置管理', 'config'),
        ('deploy', '部署发布', 'deploy'),
        ('alerts', '告警中心', 'alerts'),
    ]),
]


class NavButton(tk.Frame):
    """侧边栏菜单项：图标 + 文字，选中态 = brand_tint 底 + 左侧 3px 品牌色指示条。"""

    def __init__(self, parent, route, icon, label, command):
        super().__init__(parent, bg=TOKENS.c('bg_panel'), cursor='hand2')
        self._route, self._label = route, label
        self._command = command
        self._active = False
        self._indicator = tk.Frame(self, bg=TOKENS.c('bg_panel'), width=3)
        self._indicator.pack(side=tk.LEFT, fill=tk.Y, pady=4)
        self._indicator.pack_propagate(False)
        body = tk.Frame(self, bg=TOKENS.c('bg_panel'))
        body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(9, 10), pady=6)
        self._icon = IconLabel(body, icon, size=18, icon_size=16, bg=TOKENS.c('bg_panel'))
        self._icon.pack(side=tk.LEFT)
        self._txt = tk.Label(body, text=label, font=TOKENS.f(9), fg=TOKENS.c('text_secondary'),
                             bg=TOKENS.c('bg_panel'), anchor='w')
        self._txt.pack(side=tk.LEFT, padx=(10, 0))
        self._badge = tk.Label(self, text='', font=TOKENS.f(7, 'bold'), fg=TOKENS.c('danger'),
                               bg=TOKENS.tint('danger_tint', 'bg_panel'), padx=6)
        for w in (self, body, self._icon, self._txt):
            w.bind('<Button-1>', lambda e: self._command(self._route))
            w.bind('<Enter>', lambda e: self._set_hover(True))
            w.bind('<Leave>', lambda e: self._set_hover(False))

    def _set_hover(self, on):
        if not self._active:
            bg = TOKENS.tint('hover', 'bg_panel') if on else TOKENS.c('bg_panel')
            fg = TOKENS.c('text_primary') if on else TOKENS.c('text_secondary')
            self._apply(bg, fg, TOKENS.c('bg_panel'))

    def _apply(self, bg, fg, ind):
        self.config(bg=bg)
        self._indicator.config(bg=ind)
        self._txt.master.config(bg=bg)
        self._icon.config(bg=bg)
        self._icon.set_color(fg)
        self._txt.config(bg=bg, fg=fg)

    def set_active(self, active):
        self._active = active
        if active:
            self._apply(TOKENS.tint('brand_tint', 'bg_panel'), TOKENS.c('brand'), TOKENS.c('brand'))
        else:
            self._apply(TOKENS.c('bg_panel'), TOKENS.c('text_secondary'), TOKENS.c('bg_panel'))

    def set_collapsed(self, collapsed):
        if collapsed:
            self._txt.pack_forget()
            self._badge.pack_forget()
        else:
            self._txt.pack(side=tk.LEFT, padx=(10, 0))
            if self._badge.cget('text'):
                self._badge.pack(side=tk.RIGHT, padx=(0, 8))

    def set_badge(self, count):
        self._badge.config(text=str(count) if count else '')
        self._badge.pack_forget()
        if count:
            self._badge.pack(side=tk.RIGHT, padx=(0, 8))


class SideNav(tk.Frame):
    """左侧导航：220px ↔ 56px 折叠，底部折叠开关，折叠状态持久化。"""

    WIDTH_EXPANDED, WIDTH_COLLAPSED = 208, 52

    def __init__(self, parent, app):
        super().__init__(parent, bg=TOKENS.c('bg_panel'), width=self.WIDTH_EXPANDED,
                         highlightbackground=TOKENS.c('border'), highlightthickness=1)
        self._app = app
        self.pack_propagate(False)
        self._collapsed = bool(_APP_CONFIG.get('nav_collapsed'))
        # 品牌区
        brand = tk.Frame(self, bg=TOKENS.c('bg_panel'), height=48)
        brand.pack(fill=tk.X)
        brand.pack_propagate(False)
        logo = tk.Frame(brand, bg=TOKENS.c('brand'), width=28, height=28)
        self._logo_holder = logo
        logo.pack(side=tk.LEFT, padx=(14, 0), pady=10)
        logo.pack_propagate(False)
        tk.Label(logo, text='E', font=TOKENS.f(13, 'bold'), fg='#ffffff', bg=TOKENS.c('brand')).place(relx=0.5, rely=0.5, anchor='center')
        self._brand_texts = tk.Frame(brand, bg=TOKENS.c('bg_panel'))
        self._brand_texts.pack(side=tk.LEFT, padx=(10, 0))
        tk.Label(self._brand_texts, text='ERP 控制台', font=TOKENS.f(10, 'bold'),
                 fg=TOKENS.c('text_primary'), bg=TOKENS.c('bg_panel'), anchor='w').pack(anchor='w')
        tk.Label(self._brand_texts, text='SERVER MANAGER', font=TOKENS.fm(6),
                 fg=TOKENS.c('text_muted'), bg=TOKENS.c('bg_panel'), anchor='w').pack(anchor='w')
        # 菜单
        self._nav_buttons = {}
        self._group_titles = []
        menu_wrap = tk.Frame(self, bg=TOKENS.c('bg_panel'))
        menu_wrap.pack(fill=tk.BOTH, expand=True)
        for group, items in NAV_ITEMS:
            title = tk.Label(menu_wrap, text=group, font=TOKENS.f(7), fg=TOKENS.c('text_muted'),
                             bg=TOKENS.c('bg_panel'), anchor='w', padx=14)
            title.pack(fill=tk.X, pady=(12, 2))
            self._group_titles.append(title)
            for route, label, icon in items:
                btn = NavButton(menu_wrap, route, icon, label, command=app.navigate)
                btn.pack(fill=tk.X)
                self._nav_buttons[route] = btn
                if self._collapsed:
                    attach_tooltip(btn, label)
        # 底部折叠开关
        foot = tk.Frame(self, bg=TOKENS.c('bg_panel'), height=40,
                        highlightbackground=TOKENS.c('border'), highlightthickness=1)
        foot.pack(fill=tk.X, side=tk.BOTTOM)
        foot.pack_propagate(False)
        self._collapse_btn = tk.Frame(foot, bg=TOKENS.c('bg_panel'), cursor='hand2')
        self._collapse_btn.pack(fill=tk.BOTH, expand=True)
        self._collapse_icon = IconLabel(self._collapse_btn, 'chevron_left', size=16, icon_size=14, bg=TOKENS.c('bg_panel'))
        self._collapse_icon.pack(side=tk.LEFT, padx=(30, 0), pady=8)
        self._collapse_txt = tk.Label(self._collapse_btn, text='收起导航', font=TOKENS.f(8),
                                      fg=TOKENS.c('text_muted'), bg=TOKENS.c('bg_panel'))
        self._collapse_txt.pack(side=tk.LEFT, padx=8)
        for w in (self._collapse_btn, self._collapse_icon, self._collapse_txt):
            w.bind('<Button-1>', lambda e: self.toggle())
        self._apply_width()

    def toggle(self):
        self._collapsed = not self._collapsed
        _APP_CONFIG['nav_collapsed'] = self._collapsed
        _save_app_config(_APP_CONFIG)
        self._apply_width()

    def _apply_width(self):
        width = self.WIDTH_COLLAPSED if self._collapsed else self.WIDTH_EXPANDED
        self.config(width=width)
        if self._collapsed:
            self._brand_texts.pack_forget()
            self._logo_holder.pack_forget()
            self._logo_holder.pack(pady=10)
            for t in self._group_titles:
                t.pack_forget()
            for btn in self._nav_buttons.values():
                btn.set_collapsed(True)
            self._collapse_icon.pack_forget()
            self._collapse_icon.pack(pady=8)
            self._collapse_txt.pack_forget()
            self._collapse_icon.set_icon('chevron_right', TOKENS.c('text_muted'))
        else:
            self._logo_holder.pack_forget()
            self._logo_holder.pack(side=tk.LEFT, padx=(14, 0), pady=10)
            self._brand_texts.pack(side=tk.LEFT, padx=(10, 0))
            for t in self._group_titles:
                t.pack(fill=tk.X, pady=(12, 2))
            for btn in self._nav_buttons.values():
                btn.set_collapsed(False)
            self._collapse_icon.pack_forget()
            self._collapse_icon.pack(side=tk.LEFT, padx=(30, 0), pady=8)
            self._collapse_txt.pack(side=tk.LEFT, padx=8)
            self._collapse_icon.set_icon('chevron_left', TOKENS.c('text_muted'))
        router = getattr(self._app, 'router', None)
        if router is not None:
            router.on_sidebar_toggle(self._collapsed)

    def set_active(self, route):
        for key, btn in self._nav_buttons.items():
            btn.set_active(key == route)

    def set_alert_badge(self, count):
        btn = self._nav_buttons.get('alerts')
        if btn:
            btn.set_badge(count)


class TopBar(tk.Frame):
    """顶栏（48px）：折叠钮 + 页面标题 | 运行模式 + 端口 Chip + Redis 灯 + 主题/设置。"""

    def __init__(self, parent, app):
        super().__init__(parent, bg=TOKENS.c('bg_panel'), height=52,
                         highlightbackground=TOKENS.c('border'), highlightthickness=1)
        self._app = app
        self.pack_propagate(False)
        self._menu_btn = tk.Frame(self, bg=TOKENS.c('bg_panel'), cursor='hand2')
        self._menu_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._menu_icon = IconLabel(self._menu_btn, 'menu', size=16, icon_size=15, bg=TOKENS.c('bg_panel'))
        self._menu_icon.pack(padx=6, pady=8)
        for w in (self._menu_btn, self._menu_icon):
            w.bind('<Button-1>', lambda e: app.sidenav.toggle())
        self._title = tk.Label(self, text='运行监控', font=TOKENS.f(11, 'bold'),
                               fg=TOKENS.c('text_primary'), bg=TOKENS.c('bg_panel'))
        self._title.pack(side=tk.LEFT, padx=(4, 0))
        # 右侧
        right = tk.Frame(self, bg=TOKENS.c('bg_panel'))
        right.pack(side=tk.RIGHT, padx=(0, 12))
        self._mode_badge = StatusBadge(right, state='stopped', text='未运行', size='sm',
                                       palette=TOKENS.palette(), canvas_bg=TOKENS.c('bg_panel'))
        self._mode_badge.pack(side=tk.LEFT, padx=(0, 10))
        self._chips = []
        self._redis_lamp = tk.Label(right, text='Redis', font=TOKENS.f(7), fg=TOKENS.c('text_muted'),
                                    bg=TOKENS.c('bg_panel'))
        self._redis_lamp.pack(side=tk.LEFT, padx=(2, 4))
        self._theme_btn = tk.Frame(right, bg=TOKENS.c('bg_panel'), cursor='hand2')
        self._theme_icon = IconLabel(self._theme_btn, 'moon' if TOKENS.theme == 'dark' else 'sun',
                                     size=16, icon_size=15, bg=TOKENS.c('bg_panel'))
        self._theme_icon.pack(padx=6, pady=8)
        for w in (self._theme_btn, self._theme_icon):
            w.bind('<Button-1>', lambda e: app.toggle_theme())
        attach_tooltip(self._theme_btn, '切换暗/亮主题')
        self._theme_btn.pack(side=tk.LEFT)
        self._cfg_btn = tk.Frame(right, bg=TOKENS.c('bg_panel'), cursor='hand2')
        cfg_icon = IconLabel(self._cfg_btn, 'config', size=16, icon_size=15, bg=TOKENS.c('bg_panel'))
        cfg_icon.pack(padx=6, pady=8)
        for w in (self._cfg_btn, cfg_icon):
            w.bind('<Button-1>', lambda e: app.navigate('config'))
        attach_tooltip(self._cfg_btn, '设置（配置管理）')
        self._cfg_btn.pack(side=tk.LEFT)
        self.rebuild_ports()

    def rebuild_ports(self):
        """端口 Chip 从 _PORTS 读取（禁止 UI 硬编码端口）。点击复制访问地址。"""
        for chip in self._chips:
            with contextlib.suppress(Exception):
                chip.destroy()
        self._chips = []
        right = self._mode_badge.master
        for label, port, tone in (('API', _PORTS.api, 'brand'), ('WEB', _PORTS.web, 'success'), ('Redis', _PORTS.redis, 'info')):
            color = TOKENS.c(tone)
            chip = tk.Frame(right, bg=TOKENS.c('bg_input'), cursor='hand2',
                            highlightbackground=TOKENS.c('border'), highlightthickness=1)
            dot = tk.Canvas(chip, width=8, height=8, highlightthickness=0, bg=TOKENS.c('bg_input'))
            dot.create_oval(1, 1, 7, 7, fill=color, outline='')
            dot.pack(side=tk.LEFT, padx=(8, 0), pady=7)
            tk.Label(chip, text=f'{label} {port}', font=TOKENS.fm(8), fg=TOKENS.c('text_secondary'),
                     bg=TOKENS.c('bg_input')).pack(side=tk.LEFT, padx=(5, 8))
            url = f'http://127.0.0.1:{port}'
            for w in (chip, dot):
                w.bind('<Button-1>', lambda e, u=url: self._copy_url(u))
            attach_tooltip(chip, f'点击复制 {url}')
            chip.pack(side=tk.LEFT, padx=(0, 6))
            chip.lift()
            self._chips.append(chip)
        for chip in reversed(self._chips):
            chip.pack_forget()
            chip.pack(side=tk.LEFT, padx=(0, 6))
        self._redis_lamp.pack_forget()
        self._redis_lamp.pack(side=tk.LEFT, padx=(2, 4))

    def _copy_url(self, url):
        try:
            self._app.root.clipboard_clear()
            self._app.root.clipboard_append(url)
            self._app.toast.show('success', '已复制', url)
        except Exception:
            pass

    def set_title(self, text):
        self._title.config(text=text)

    def set_redis_lamp(self, ok):
        self._redis_lamp.config(fg=TOKENS.c('success') if ok else TOKENS.c('text_muted'),
                                text='Redis ✓' if ok else 'Redis —')

    @property
    def mode_badge(self):
        return self._mode_badge


class StatusBar(tk.Frame):
    """底部状态栏（32px）：全局模式徽章 + 状态文本 + 心跳时间 | 告警数 + 紧急停止。"""

    def __init__(self, parent, app):
        super().__init__(parent, bg=TOKENS.c('bg_page'), height=30,
                         highlightbackground=TOKENS.c('border'), highlightthickness=1)
        self._app = app
        self.pack_propagate(False)
        left = tk.Frame(self, bg=TOKENS.c('bg_page'))
        left.pack(side=tk.LEFT, padx=(16, 0))
        self.mode_badge = StatusBadge(left, state='stopped', text='未运行', size='md',
                                      palette=TOKENS.palette(), canvas_bg=TOKENS.c('bg_page'))
        self.mode_badge.pack(side=tk.LEFT, padx=(0, 10), pady=3)
        app.status_bar_label = tk.Label(left, text='就绪', font=TOKENS.f(8),
                                        fg=TOKENS.c('text_secondary'), bg=TOKENS.c('bg_page'))
        app.status_bar_label.pack(side=tk.LEFT)
        self._heartbeat = tk.Label(left, text='', font=TOKENS.fm(7), fg=TOKENS.c('text_muted'),
                                   bg=TOKENS.c('bg_page'))
        self._heartbeat.pack(side=tk.LEFT, padx=(12, 0))
        right = tk.Frame(self, bg=TOKENS.c('bg_page'))
        right.pack(side=tk.RIGHT, padx=(0, 12))
        self.alert_label = tk.Label(right, text='', font=TOKENS.f(8), fg=TOKENS.c('danger'),
                                    bg=TOKENS.c('bg_page'))
        self.alert_label.pack(side=tk.LEFT, padx=(0, 10))
        app.stop_all_btn = RoundedButton(right, text='紧急停止', variant='subtle', tone='danger',
                                         command=app.confirm_stop_all, canvas_bg=TOKENS.c('bg_page'),
                                         small=True, pady=2, radius=6)
        app.stop_all_btn.pack(side=tk.RIGHT)

    def set_heartbeat(self, ts_str):
        self._heartbeat.config(text=f'上次刷新 {ts_str}')

    def set_alert_count(self, n):
        self.alert_label.config(text=f'● {n} 项未确认告警' if n else '')


class PageRouter(tk.Frame):
    """基于 tkraise 的页面切换器（设计方案 §8.3）。"""

    def __init__(self, parent, app):
        super().__init__(parent, bg=TOKENS.c('bg_page'))
        self._app = app
        self._pages = {}
        self._current = None

    def register(self, page):
        self._pages[page.ROUTE] = page
        page.place(in_=self, x=0, y=0, relwidth=1, relheight=1)

    def show(self, route):
        page = self._pages.get(route)
        if not page:
            return
        if self._current and self._current is not page:
            with contextlib.suppress(Exception):
                self._current.on_hide()
        self._current = page
        page.tkraise()
        self._app.sidenav.set_active(route)
        title = page.TITLE if hasattr(page, 'TITLE') else route
        self._app.topbar.set_title(title)
        with contextlib.suppress(Exception):
            page.on_show()

    def on_sidebar_toggle(self, collapsed):
        pass  # place 布局随容器自适应，无需处理

    @property
    def current(self):
        return self._current

    def pages(self):
        return dict(self._pages)


class Page(tk.Frame):
    """页面基类：PageHeader（标题/副标题/右侧操作区）+ 内容区，统一 build/on_show 接口。"""
    ROUTE = ''
    TITLE = ''
    SUBTITLE = ''

    def __init__(self, app, parent):
        super().__init__(parent, bg=TOKENS.c('bg_page'))
        self.app = app
        header = tk.Frame(self, bg=TOKENS.c('bg_page'))
        header.pack(fill=tk.X, padx=24, pady=(18, 12))
        col = tk.Frame(header, bg=TOKENS.c('bg_page'))
        col.pack(side=tk.LEFT)
        tk.Label(col, text=self.TITLE, font=TOKENS.f(13, 'bold'), fg=TOKENS.c('text_primary'),
                 bg=TOKENS.c('bg_page'), anchor='w').pack(anchor='w')
        if self.SUBTITLE:
            tk.Label(col, text=self.SUBTITLE, font=TOKENS.f(8), fg=TOKENS.c('text_muted'),
                     bg=TOKENS.c('bg_page'), anchor='w').pack(anchor='w')
        self.head_actions = tk.Frame(header, bg=TOKENS.c('bg_page'))
        self.head_actions.pack(side=tk.RIGHT)
        self.body = tk.Frame(self, bg=TOKENS.c('bg_page'))
        self.body.pack(fill=tk.BOTH, expand=True, padx=24, pady=(0, 20))
        self.build()

    def build(self):
        pass

    def on_show(self):
        pass

    def on_hide(self):
        pass

    def card(self, parent, **grid):
        card = tk.Frame(parent, bg=TOKENS.c('bg_panel'), highlightbackground=TOKENS.c('border'),
                        highlightthickness=1)
        if grid:
            card.grid(**grid)
        return card

    def card_head(self, card, title, sub=''):
        head = tk.Frame(card, bg=TOKENS.c('bg_panel'))
        head.pack(fill=tk.X, padx=16, pady=(12, 0))
        tk.Label(head, text=title, font=TOKENS.f(10, 'bold'), fg=TOKENS.c('text_primary'),
                 bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT)
        if sub:
            tk.Label(head, text=sub, font=TOKENS.fm(7), fg=TOKENS.c('text_muted'),
                     bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT, padx=(8, 0))
        return head


# ===================== 页面 1：运行监控（Overview） =====================

class OverviewPage(Page):
    ROUTE, TITLE, SUBTITLE = 'overview', '运行监控', '实时掌握服务器健康状态 · 2s 采样 · 120s 窗口'

    def build(self):
        app = self.app
        # 头部操作
        self.btn_refresh = RoundedButton(self.head_actions, text='刷新', variant='outlined', tone='brand',
                                         command=app.manual_refresh_all, canvas_bg=TOKENS.c('bg_page'), small=True)
        self.btn_refresh.pack(side=tk.LEFT, padx=(6, 0))
        self.btn_start_all = RoundedButton(self.head_actions, text='一键启动开发', variant='solid', tone='success',
                                           command=app.start_dual_dev, canvas_bg=TOKENS.c('bg_page'), small=True)
        self.btn_start_all.pack(side=tk.LEFT, padx=(6, 0))
        # 统计卡片行
        stats = tk.Frame(self.body, bg=TOKENS.c('bg_page'))
        stats.pack(fill=tk.X)
        for col in range(4):
            stats.columnconfigure(col, weight=1, uniform='ov_stats')
        self.st_api = self._stat_card(stats, 0, 'services', 'success', '后端服务')
        self.st_redis = self._stat_card(stats, 1, 'mem', 'info', 'Redis')
        self.st_web = self._stat_card(stats, 2, 'deploy', 'brand', '前端服务')
        self.st_mode = self._stat_card(stats, 3, 'disk', 'warning', '全局模式')
        # 监控区 8:4
        mon = tk.Frame(self.body, bg=TOKENS.c('bg_page'))
        mon.pack(fill=tk.BOTH, expand=True, pady=(16, 0))
        mon.columnconfigure(0, weight=2, uniform='ov_mon')
        mon.columnconfigure(1, weight=1, uniform='ov_mon')
        mon.rowconfigure(0, weight=1)
        self._build_perf_card(mon)
        self._build_side_cards(mon)
        self.st_mode['badge'].set_state('stopped', '未运行')

    def _stat_card(self, parent, col, icon, tone, label):
        card = tk.Frame(parent, bg=TOKENS.c('bg_panel'), highlightbackground=TOKENS.c('border'),
                        highlightthickness=1)
        card.grid(row=0, column=col, sticky='nsew', padx=0 if col == 0 else 8)
        head = tk.Frame(card, bg=TOKENS.c('bg_panel'))
        head.pack(fill=tk.X, padx=14, pady=(12, 0))
        icon_c = tk.Canvas(head, width=24, height=24, highlightthickness=0,
                           bg=TOKENS.tint(f'{tone}_tint' if tone != 'brand' else 'brand_tint', 'bg_panel'))
        draw_icon(icon_c, icon, TOKENS.c(tone), 16)
        icon_c.pack(side=tk.LEFT)
        tk.Label(head, text=label, font=TOKENS.f(8), fg=TOKENS.c('text_muted'),
                 bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT, padx=(8, 0))
        value = tk.Label(card, text='—', font=TOKENS.fm(13, 'bold'), fg=TOKENS.c('text_primary'),
                         bg=TOKENS.c('bg_panel'), anchor='w')
        value.pack(fill=tk.X, padx=14, pady=(6, 0))
        foot = tk.Frame(card, bg=TOKENS.c('bg_panel'))
        foot.pack(fill=tk.X, padx=14, pady=(0, 12))
        badge = StatusBadge(foot, state='stopped', text='—', size='sm', palette=TOKENS.palette(),
                            canvas_bg=TOKENS.c('bg_panel'))
        badge.pack(side=tk.LEFT)
        return {'card': card, 'value': value, 'badge': badge}

    def _build_perf_card(self, mon):
        card = self.card(mon, row=0, column=0, sticky='nsew')
        head = self.card_head(card, '性能总览', '120s 窗口 · 2s 采样')
        seg_wrap = tk.Frame(head, bg=TOKENS.c('bg_panel'))
        seg_wrap.pack(side=tk.RIGHT)
        self.chart_mode = 'cpu'
        self.chart_seg = Segmented(seg_wrap, ['CPU', '内存', '网络'], command=self._switch_chart)
        self.chart_seg.pack()
        body = tk.Frame(card, bg=TOKENS.c('bg_panel'))
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(10, 16))
        # 三行指标
        self.cpu_bar, self.cpu_val, self.cpu_spark = self._metric_row(body, 'cpu', 'chart_cpu', 'CPU 使用率')
        self.mem_bar, self.mem_val, self.mem_spark = self._metric_row(body, 'mem', 'chart_mem', '内存使用率')
        self.disk_bar, self.disk_val, _ = self._metric_row(body, 'disk', 'chart_disk', '磁盘占用', spark=False)
        # 主图
        self.main_chart = TrendChart(body, [
            ('cpu', 'chart_cpu', 'CPU'), ('mem', 'chart_mem', '内存'),
        ], y_unit='%', y_max=100)
        self.main_chart.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.net_chart_series = [('netDn', 'chart_net_dn', '下行'), ('netUp', 'chart_net_up', '上行')]

    def _metric_row(self, parent, icon, color_key, label, spark=True):
        row = tk.Frame(parent, bg=TOKENS.c('bg_panel'))
        row.pack(fill=tk.X, pady=(7, 0))
        icon_c = tk.Canvas(row, width=26, height=26, highlightthickness=0, bg=TOKENS.c(color_key))
        draw_icon(icon_c, icon, '#ffffff', 15)
        icon_c.pack(side=tk.LEFT)
        mid = tk.Frame(row, bg=TOKENS.c('bg_panel'))
        mid.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 8))
        top = tk.Frame(mid, bg=TOKENS.c('bg_panel'))
        top.pack(fill=tk.X)
        tk.Label(top, text=label, font=TOKENS.f(8), fg=TOKENS.c('text_secondary'),
                 bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT)
        val = tk.Label(top, text='—', font=TOKENS.fm(10, 'bold'), fg=TOKENS.c('text_primary'),
                       bg=TOKENS.c('bg_panel'))
        val.pack(side=tk.RIGHT)
        bar = MetricBar(mid)
        bar.pack(fill=tk.X, pady=(5, 0))
        sp = None
        if spark:
            sp = SparkLine(row, color_key, bg=TOKENS.c('bg_panel'))
            sp.pack(side=tk.RIGHT)
        return bar, val, sp

    def _build_side_cards(self, mon):
        col = tk.Frame(mon, bg=TOKENS.c('bg_page'))
        col.grid(row=0, column=1, sticky='nsew', padx=(8, 0))
        # 网络流量
        net_card = self.card(col)
        net_card.pack(fill=tk.X)
        self.card_head(net_card, '网络流量', '实时速率')
        nb = tk.Frame(net_card, bg=TOKENS.c('bg_panel'))
        nb.pack(fill=tk.X, padx=16, pady=(8, 0))
        self.net_dn_val = tk.Label(nb, text='— MB/s', font=TOKENS.fm(11, 'bold'), fg=TOKENS.c('chart_net_dn'),
                                   bg=TOKENS.c('bg_panel'))
        self.net_dn_val.pack(side=tk.LEFT)
        self.net_up_val = tk.Label(nb, text='— KB/s', font=TOKENS.fm(11, 'bold'), fg=TOKENS.c('chart_net_up'),
                                   bg=TOKENS.c('bg_panel'))
        self.net_up_val.pack(side=tk.LEFT, padx=(20, 0))
        self.net_chart = TrendChart(net_card, self.net_chart_series, y_unit='', y_max=None, height=110)
        self.net_chart.pack(fill=tk.X, padx=16, pady=(10, 16))
        # 进程快照
        proc_card = self.card(col)
        proc_card.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.card_head(proc_card, '进程快照', 'Top 5 · CPU')
        self.proc_body = tk.Frame(proc_card, bg=TOKENS.c('bg_panel'))
        self.proc_body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(10, 16))

    # ---- 数据入口 ----
    def on_show(self):
        # 回到监控页：补齐隐藏期间跳过的重绘（图表/迷你线）
        with contextlib.suppress(Exception):
            self.main_chart.redraw()
            self.net_chart.redraw()
            if self.cpu_spark:
                self.cpu_spark.redraw()
            if self.mem_spark:
                self.mem_spark.redraw()

    def _switch_chart(self, idx):
        self.chart_mode = ('cpu', 'mem', 'net')[idx]
        spec = {
            'cpu': [('cpu', 'chart_cpu', 'CPU'), ('mem', 'chart_mem', '内存')],
            'mem': [('mem', 'chart_mem', '内存')],
            'net': [('netDn', 'chart_net_dn', '下行'), ('netUp', 'chart_net_up', '上行')],
        }[self.chart_mode]
        data = {k: list(v) for k, v in self.main_chart._data.items()}
        y_unit = '' if self.chart_mode == 'net' else '%'
        y_max = None if self.chart_mode == 'net' else 100
        self.main_chart.destroy()
        self.main_chart = TrendChart(self.main_chart.master, spec, y_unit=y_unit, y_max=y_max)
        self.main_chart.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        # 恢复历史数据；新建画布需等布局映射后再重绘（redraw 有 mapped 守卫）
        for key in data:
            if key in self.main_chart._data:
                self.main_chart._data[key].extend(data[key])
        self.after_idle(self.main_chart.redraw)

    def push_metrics(self, m):
        """m: {cpu, mem, disk, net_dn_mb, net_up_kb, samples:{cpu:[..],mem:[..],netDn:[..],netUp:[..]}}"""
        with contextlib.suppress(Exception):
            self.cpu_val.config(text=f"{m.get('cpu', 0):.1f}%")
            self.mem_val.config(text=f"{m.get('mem', 0):.1f}%")
            self.disk_val.config(text=f"{m.get('disk', 0):.1f}%")
            self.cpu_bar.set_value(m.get('cpu', 0))
            self.mem_bar.set_value(m.get('mem', 0))
            self.disk_bar.set_value(m.get('disk', 0))
            if self.cpu_spark:
                for v in m.get('samples', {}).get('cpu', []):
                    self.cpu_spark.push(v)
                for v in m.get('samples', {}).get('mem', []):
                    self.mem_spark.push(v)
            dn, up = m.get('net_dn_mb', 0), m.get('net_up_kb', 0)
            self.net_dn_val.config(text=f'{dn:.2f} MB/s')
            self.net_up_val.config(text=f'{up:.0f} KB/s')
            self.net_chart.push({'netDn': dn, 'netUp': up / 1024.0})
            keys = {'cpu': 'cpu', 'mem': 'mem', 'net': 'netDn'}
            if self.chart_mode in ('cpu', 'mem'):
                self.main_chart.push({self.chart_mode: m.get(keys[self.chart_mode], 0)})
            elif self.chart_mode == 'net':
                self.main_chart.push({'netDn': dn, 'netUp': up / 1024.0})

    def set_proc_snapshot(self, procs):
        for w in self.proc_body.winfo_children():
            w.destroy()
        if procs is None:
            EmptyState(self.proc_body, '安装 psutil 后可查看进程快照', '安装 psutil', self.app.toast_psutil_hint).pack(fill=tk.BOTH, expand=True)
            return
        if not procs:
            tk.Label(self.proc_body, text='采样中…', font=TOKENS.f(8), fg=TOKENS.c('text_muted'),
                     bg=TOKENS.c('bg_panel')).pack(pady=10)
            return
        for name, cpu, mem in procs[:5]:
            row = tk.Frame(self.proc_body, bg=TOKENS.c('bg_panel'))
            row.pack(fill=tk.X, pady=3)
            tk.Label(row, text=name, font=TOKENS.fm(8), fg=TOKENS.c('text_secondary'),
                     bg=TOKENS.c('bg_panel'), anchor='w').pack(side=tk.LEFT)
            tk.Label(row, text=f'{cpu:.0f}%', font=TOKENS.fm(8), fg=TOKENS.c('chart_cpu'),
                     bg=TOKENS.c('bg_panel')).pack(side=tk.RIGHT)
            bar = MetricBar(row, width=70)
            bar.set_value(min(100.0, cpu))
            bar.pack(side=tk.RIGHT, padx=(0, 8))

    def sync_stats(self):
        app = self.app
        mode = app._mode
        # 后端服务（开发模式子进程 或 生产 NSSM）
        hosting = getattr(app, '_last_hosting', None) or {}
        prod_api = hosting.get('api_running')
        if mode == 'dual_dev' and app._process and app._process.poll() is None:
            self.st_api['value'].config(text='运行中')
            self.st_api['badge'].set_state('running', f'PID {app._process.pid}')
        elif prod_api:
            self.st_api['value'].config(text='运行中')
            self.st_api['badge'].set_state('running', '生产服务')
        elif mode in ('starting', 'restarting'):
            self.st_api['value'].config(text='启动中')
            self.st_api['badge'].set_state('deploying', '启动中')
        else:
            self.st_api['value'].config(text='已停止')
            self.st_api['badge'].set_state('stopped', '端口 ' + str(_PORTS.api))
        # Redis
        redis_ok = hosting.get('redis_ok')
        if redis_ok is None:
            redis_ok = app._redis_running_cached
        if app._redis_starting:
            self.st_redis['value'].config(text=f'端口 {_PORTS.redis}')
            self.st_redis['badge'].set_state('starting', '启动中')
        elif redis_ok:
            self.st_redis['value'].config(text=str(_PORTS.redis))
            self.st_redis['badge'].set_state('running', '运行中')
        else:
            self.st_redis['value'].config(text=str(_PORTS.redis))
            self.st_redis['badge'].set_state('stopped', '已停止')
        # 前端服务（开发模式子进程）
        if mode == 'dual_dev' and app._frontend_process and app._frontend_process.poll() is None:
            self.st_web['value'].config(text='运行中')
            self.st_web['badge'].set_state('running', f'PID {app._frontend_process.pid}')
        elif mode in ('starting', 'restarting'):
            self.st_web['value'].config(text='启动中')
            self.st_web['badge'].set_state('deploying', '启动中')
        else:
            self.st_web['value'].config(text='已停止')
            self.st_web['badge'].set_state('stopped', '端口 ' + str(_PORTS.web))
        # 全局模式
        if mode == 'dual_dev':
            self.st_mode['value'].config(text='开发模式')
            self.st_mode['badge'].set_state('running', '运行中')
        elif prod_api:
            self.st_mode['value'].config(text='生产模式')
            self.st_mode['badge'].set_state('running', '运行中')
        elif mode in ('starting', 'restarting', 'stopping'):
            self.st_mode['value'].config(text='切换中')
            self.st_mode['badge'].set_state('deploying', '过渡态')
        else:
            self.st_mode['value'].config(text='未运行')
            self.st_mode['badge'].set_state('stopped', '空闲')


# ===================== 页面 2：服务管理（Services） =====================

class ServiceRow(tk.Frame):
    """服务表格行：图标+名称 | StatusBadge | 模式 Tag | 端口/PID | 行内操作。"""

    def __init__(self, parent, icon, tone, name, sub, mode_text, app):
        super().__init__(parent, bg=TOKENS.c('bg_panel'))
        self._app = app
        self._status_filter_key = 'stopped'
        icon_c = tk.Canvas(self, width=30, height=30, highlightthickness=0, bg=TOKENS.c(tone))
        draw_icon(icon_c, icon, '#ffffff', 16)
        icon_c.grid(row=0, column=0, sticky='w', padx=(16, 0), pady=9)
        namecol = tk.Frame(self, bg=TOKENS.c('bg_panel'))
        namecol.grid(row=0, column=0, sticky='w', padx=(56, 0))
        tk.Label(namecol, text=name, font=TOKENS.f(9, 'bold'), fg=TOKENS.c('text_primary'),
                 bg=TOKENS.c('bg_panel'), anchor='w').pack(anchor='w')
        tk.Label(namecol, text=sub, font=TOKENS.fm(7), fg=TOKENS.c('text_muted'),
                 bg=TOKENS.c('bg_panel'), anchor='w').pack(anchor='w')
        self.badge = StatusBadge(self, state='stopped', text='已停止', size='sm', palette=TOKENS.palette(),
                                 canvas_bg=TOKENS.c('bg_panel'))
        self.badge.grid(row=0, column=1, sticky='w')
        self.mode_tag = tk.Label(self, text=mode_text, font=TOKENS.f(7), fg=TOKENS.c('text_muted'),
                                 bg=TOKENS.c('bg_input'), padx=8, pady=2)
        self.mode_tag.grid(row=0, column=2, sticky='w')
        self.meta = tk.Label(self, text='—', font=TOKENS.fm(8), fg=TOKENS.c('text_secondary'),
                             bg=TOKENS.c('bg_panel'), anchor='w')
        self.meta.grid(row=0, column=3, sticky='w')
        self.actions = tk.Frame(self, bg=TOKENS.c('bg_panel'))
        self.actions.grid(row=0, column=4, sticky='e', padx=(8, 16))
        tk.Frame(self, bg=TOKENS.c('border'), height=1).grid(row=1, columnspan=5, sticky='ew')
        # 操作列 hover 显示（对齐 v2：行悬停才淡出操作，避免每行按钮常驻）
        # 注意：Tk 中指针移入操作区的子按钮也会触发父级 <Leave>，
        # 直接 grid_remove 会导致按钮无法点击 —— 用指针归属检测延迟判定
        self.actions.grid_remove()
        self.bind('<Enter>', lambda e: self.actions.grid())
        self.bind('<FocusIn>', lambda e: self.actions.grid())
        self.bind('<Leave>', lambda e: self._schedule_hide_actions())
        self.actions.bind('<Leave>', lambda e: self._schedule_hide_actions())

    def _schedule_hide_actions(self):
        """延迟判定：指针仍在操作区/行（含子按钮）内则保留，离开行才隐藏。"""
        if not self.winfo_exists():
            return
        self.after(120, self._maybe_hide_actions)

    def _maybe_hide_actions(self):
        if not self.winfo_exists():
            return
        try:
            w = self.winfo_containing(*self.winfo_pointerxy())
        except Exception:
            w = None
        while w is not None:
            if w is self or w is self.actions:
                return
            w = getattr(w, 'master', None)
        self.actions.grid_remove()

    def set_state(self, key, text, meta=''):
        self._status_filter_key = key
        self.badge.set_state(key if key in _STATUS_META else 'stopped', text)
        self.meta.config(text=meta or '—')

    @property
    def filter_key(self):
        return self._status_filter_key

    def add_button(self, text, command, tone='neutral', variant='outlined', tooltip=None, primary=False):
        btn = RoundedButton(self.actions, text=text, variant='solid' if primary else variant, tone=tone,
                            command=command, canvas_bg=TOKENS.c('bg_panel'), small=True, pady=2, radius=6)
        btn.pack(side=tk.LEFT, padx=(6, 0))
        if tooltip:
            attach_tooltip(btn, tooltip)
        return btn


class ServicesPage(Page):
    ROUTE, TITLE, SUBTITLE = 'services', '服务管理', '开发 / 生产一键启停 · 互斥托管（启动一方将自动停止另一方）'

    def build(self):
        app = self.app
        self.filter = Segmented(self.head_actions, ['全部', '运行中', '已停止', '故障'], command=self._apply_filter)
        self.filter.pack(side=tk.RIGHT)
        # 服务列表卡片
        card = self.card(self.body)
        card.pack(fill=tk.X)
        head = self.card_head(card, '服务列表', '行内操作')
        hdr = tk.Frame(card, bg=TOKENS.c('bg_panel'))
        hdr.pack(fill=tk.X, padx=16, pady=(10, 0))
        left_hdr = tk.Frame(hdr, bg=TOKENS.c('bg_panel'))
        left_hdr.pack(side=tk.LEFT)
        for txt, padx in (('服务', 40), ('状态', 150), ('模式', 80), ('端口 · PID', 60)):
            tk.Label(left_hdr, text=txt, font=TOKENS.f(7), fg=TOKENS.c('text_muted'),
                     bg=TOKENS.c('bg_panel'), anchor='w').pack(side=tk.LEFT, padx=(padx, 0) if padx else 0)
        tk.Label(hdr, text='操作', font=TOKENS.f(7), fg=TOKENS.c('text_muted'),
                 bg=TOKENS.c('bg_panel'), anchor='e').pack(side=tk.RIGHT)
        rows = tk.Frame(card, bg=TOKENS.c('bg_panel'))
        rows.pack(fill=tk.X, pady=(2, 8))
        self.row_dev = ServiceRow(rows, 'services', 'brand', 'FastAPI 后端', 'backend · 开发模式', '开发', app)
        self.row_dev.pack(fill=tk.X)
        self.row_dev.add_button('日志', lambda: app.navigate('logs'))
        self.row_fe = ServiceRow(rows, 'deploy', 'info', 'Vite 前端', 'frontend-vite · 开发模式', '开发', app)
        self.row_fe.pack(fill=tk.X)
        self.row_fe.add_button('日志', lambda: app.navigate('logs'))
        self.row_redis = ServiceRow(rows, 'mem', 'success', 'Redis', '缓存 · 独立进程', '独立', app)
        self.row_redis.pack(fill=tk.X)
        self.btn_redis_start = self.row_redis.add_button('启动', app.start_redis_async, tone='brand', variant='solid', primary=True, tooltip='独立启动 Redis（无需开发模式）')
        self.btn_redis_stop = self.row_redis.add_button('停止', app.stop_redis_async, tone='danger', tooltip='停止 Redis 进程并释放端口')
        self.row_prod = ServiceRow(rows, 'services', 'purple', 'erp-prod 服务', '生产环境 · NSSM 托管', '生产', app)
        self.row_prod.pack(fill=tk.X)
        # 注：生产『启动/重启/关闭』按钮统一下沉到下方「生产模式」操作卡（对齐 UI 重构 v2）
        self.row_arq = ServiceRow(rows, 'deploy', 'purple', 'erp-arq 服务', '队列 Worker · NSSM 托管', '生产', app)
        self.row_arq.pack(fill=tk.X)
        self.row_arq.add_button('日志', app._open_logs_dir, tooltip='打开 logs 目录')
        # 快捷操作 + 生产明细
        bottom = tk.Frame(self.body, bg=TOKENS.c('bg_page'))
        bottom.pack(fill=tk.X, pady=(16, 0))
        bottom.columnconfigure(0, weight=1, uniform='svc_bottom')
        bottom.columnconfigure(1, weight=1, uniform='svc_bottom')
        self._build_quick_actions(bottom)
        self._build_prod_detail(bottom)
        # 开发模式主操作（兼容层引用：dual_dev_status/start）
        self.dev_status = self.row_dev.badge
        self.dev_start_btn = self.btn_dev_start

    def _build_quick_actions(self, bottom):
        """开发模式操作卡（对齐 UI 重构 v2：启动/重启/关闭 + 环境徽章 + 进度条）。"""
        app = self.app
        card = self.card(bottom, row=0, column=0, sticky='nsew')
        # 卡片头部：图标 + 标题 + 环境徽章
        hd = tk.Frame(card, bg=TOKENS.c('bg_panel'))
        hd.pack(fill=tk.X, padx=16, pady=(12, 0))
        ico = tk.Frame(hd, bg=TOKENS.c('success'), width=26, height=26)
        ico.pack(side=tk.LEFT)
        ico.pack_propagate(False)
        tk.Label(ico, text='开', font=TOKENS.f(7, 'bold'), fg='#ffffff',
                 bg=TOKENS.c('success')).place(relx=.5, rely=.5, anchor='center')
        tk.Label(hd, text='开发模式', font=TOKENS.f(9, 'bold'), fg=TOKENS.c('text_primary'),
                 bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT, padx=(8, 0))
        self.dev_env_badge = StatusBadge(hd, state='stopped', text='未运行', size='md',
                                         palette=TOKENS.palette(), canvas_bg=TOKENS.c('bg_panel'))
        self.dev_env_badge.pack(side=tk.LEFT, padx=(10, 0))
        # 一键启动
        row = tk.Frame(card, bg=TOKENS.c('bg_panel'))
        row.pack(fill=tk.X, padx=16, pady=(12, 0))
        tk.Label(row, text='一键启动', font=TOKENS.f(7), fg=TOKENS.c('text_secondary'),
                 bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT)
        self.btn_dev_start = RoundedButton(row, text='启动开发模式', variant='solid', tone='success',
                                           command=app.start_dual_dev, canvas_bg=TOKENS.c('bg_panel'))
        attach_tooltip(self.btn_dev_start, '启动后将自动停止生产模式（互斥托管）')
        self.btn_dev_start.pack(side=tk.LEFT, padx=(14, 0))
        # 一键重启（通用组件按钮 · 独立行，对齐 v2）
        row2 = tk.Frame(card, bg=TOKENS.c('bg_panel'))
        row2.pack(fill=tk.X, padx=16, pady=(10, 0))
        tk.Label(row2, text='一键重启', font=TOKENS.f(7), fg=TOKENS.c('text_secondary'),
                 bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT)
        self.dev_restart_box = tk.Frame(row2, bg=TOKENS.c('bg_panel'))
        self.dev_restart_box.pack(side=tk.LEFT, padx=(14, 0))
        # 一键关闭（独立行）
        row3 = tk.Frame(card, bg=TOKENS.c('bg_panel'))
        row3.pack(fill=tk.X, padx=16, pady=(10, 0))
        tk.Label(row3, text='一键关闭', font=TOKENS.f(7), fg=TOKENS.c('text_secondary'),
                 bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT)
        self.dev_stop_box = tk.Frame(row3, bg=TOKENS.c('bg_panel'))
        self.dev_stop_box.pack(side=tk.LEFT, padx=(14, 0))
        # 启动步骤进度条（开发模式 5 步流程）
        prog = tk.Frame(card, bg=TOKENS.c('bg_panel'))
        prog.pack(fill=tk.X, padx=16, pady=(10, 0))
        self.dev_prog_label = tk.Label(prog, text='', font=TOKENS.fm(7), fg=TOKENS.c('text_muted'),
                                       bg=TOKENS.c('bg_panel'), anchor='w')
        self.dev_prog_label.pack(fill=tk.X)
        self.dev_prog_bar = tk.Frame(prog, bg=TOKENS.c('bg_input'), height=4)
        self.dev_prog_bar.pack(fill=tk.X, pady=(4, 0))
        self.dev_prog_bar.pack_propagate(False)
        self.dev_prog_fill = tk.Frame(self.dev_prog_bar, bg=TOKENS.c('brand'))
        self.dev_prog_fill.place(x=0, y=0, relwidth=0, relheight=1)
        # 兜底：全部停止 + 说明
        foot = tk.Frame(card, bg=TOKENS.c('bg_panel'))
        foot.pack(fill=tk.X, padx=16, pady=(10, 14))
        RoundedButton(foot, text='全部停止', variant='outlined', tone='danger',
                      command=app.confirm_stop_all, canvas_bg=TOKENS.c('bg_panel'),
                      small=True).pack(side=tk.LEFT)
        tk.Label(foot, text='启动=停生产→清端口→Redis→后端(健康检查)→前端(就绪)',
                 font=TOKENS.f(6), fg=TOKENS.c('text_muted'),
                 bg=TOKENS.c('bg_panel'), anchor='w').pack(side=tk.LEFT, padx=(12, 0))

    def _build_prod_detail(self, bottom):
        """生产模式操作卡（对齐 UI 重构 v2：启动/重启/关闭 + 环境徽章 + 服务明细）。"""
        app = self.app
        card = self.card(bottom, row=0, column=1, sticky='nsew', padx=(8, 0))
        # 卡片头部：图标 + 标题 + 环境徽章
        hd = tk.Frame(card, bg=TOKENS.c('bg_panel'))
        hd.pack(fill=tk.X, padx=16, pady=(12, 0))
        ico = tk.Frame(hd, bg=TOKENS.c('brand'), width=26, height=26)
        ico.pack(side=tk.LEFT)
        ico.pack_propagate(False)
        tk.Label(ico, text='产', font=TOKENS.f(7, 'bold'), fg='#ffffff',
                 bg=TOKENS.c('brand')).place(relx=.5, rely=.5, anchor='center')
        tk.Label(hd, text='生产模式', font=TOKENS.f(9, 'bold'), fg=TOKENS.c('text_primary'),
                 bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT, padx=(8, 0))
        self.hosting_svc_badge = StatusBadge(hd, state='stopped', text='服务停止', size='md',
                                             palette=TOKENS.palette(), canvas_bg=TOKENS.c('bg_panel'))
        self.hosting_svc_badge.pack(side=tk.LEFT, padx=(10, 0))
        # 一键启动
        row = tk.Frame(card, bg=TOKENS.c('bg_panel'))
        row.pack(fill=tk.X, padx=16, pady=(12, 0))
        tk.Label(row, text='一键启动', font=TOKENS.f(7), fg=TOKENS.c('text_secondary'),
                 bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT)
        self.btn_prod_start = RoundedButton(row, text='启动生产服务', variant='solid', tone='brand',
                                            command=app._start_services, canvas_bg=TOKENS.c('bg_panel'))
        attach_tooltip(self.btn_prod_start, '启动后将自动停止开发模式（互斥托管）')
        self.btn_prod_start.pack(side=tk.LEFT, padx=(14, 0))
        # 一键重启（独立行）
        row2 = tk.Frame(card, bg=TOKENS.c('bg_panel'))
        row2.pack(fill=tk.X, padx=16, pady=(10, 0))
        tk.Label(row2, text='一键重启', font=TOKENS.f(7), fg=TOKENS.c('text_secondary'),
                 bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT)
        self.prod_restart_box = tk.Frame(row2, bg=TOKENS.c('bg_panel'))
        self.prod_restart_box.pack(side=tk.LEFT, padx=(14, 0))
        # 一键关闭（独立行）
        row3 = tk.Frame(card, bg=TOKENS.c('bg_panel'))
        row3.pack(fill=tk.X, padx=16, pady=(10, 0))
        tk.Label(row3, text='一键关闭', font=TOKENS.f(7), fg=TOKENS.c('text_secondary'),
                 bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT)
        self.prod_stop_box = tk.Frame(row3, bg=TOKENS.c('bg_panel'))
        self.prod_stop_box.pack(side=tk.LEFT, padx=(14, 0))
        # 服务明细（NSSM 5s 轮询）
        wrap = tk.Frame(card, bg=TOKENS.c('bg_input'))
        wrap.pack(fill=tk.X, padx=16, pady=(10, 0))
        grid = tk.Frame(wrap, bg=TOKENS.c('bg_input'))
        grid.pack(fill=tk.X, padx=6, pady=6)
        for col in range(2):
            grid.columnconfigure(col, weight=1)

        def badge(text):
            b = StatusBadge(grid, state='stopped', text=text, size='sm', palette=TOKENS.palette(),
                            canvas_bg=TOKENS.c('bg_input'))
            return b
        self.hosting_backend_badge = badge('后端')
        self.hosting_arq_badge = badge('ARQ')
        self.hosting_frontend_badge = badge('前端')
        self.hosting_redis_badge = badge('Redis')
        self.hosting_ready_badge = badge('就绪')
        self.hosting_backend_badge.grid(row=0, column=0, sticky='w', padx=8, pady=3)
        self.hosting_arq_badge.grid(row=0, column=1, sticky='w', padx=8, pady=3)
        self.hosting_frontend_badge.grid(row=1, column=0, sticky='w', padx=8, pady=3)
        self.hosting_redis_badge.grid(row=1, column=1, sticky='w', padx=8, pady=3)
        self.hosting_ready_badge.grid(row=2, column=0, sticky='w', padx=8, pady=3)
        self.hosting_mtime = tk.Label(card, text='状态文件 —', font=TOKENS.fm(7), fg=TOKENS.c('text_muted'),
                                      bg=TOKENS.c('bg_panel'), anchor='w')
        self.hosting_mtime.pack(fill=tk.X, padx=16, pady=(8, 14))

    # ---- 状态同步（app._update_all_ui / _apply_hosting_data 调用） ----
    def sync(self):
        app = self.app
        mode = app._mode
        # 后端
        if mode in ('starting', 'restarting') and app._current_mode_key == 'dual_dev':
            self.row_dev.set_state('deploying' if mode == 'starting' else 'restarting', '启动中' if mode == 'starting' else '重启中', f'端口 {_PORTS.api}')
        elif mode == 'dual_dev' and app._process and app._process.poll() is None:
            self.row_dev.set_state('running', '运行中', f'{_PORTS.api} · {app._process.pid}')
        else:
            self.row_dev.set_state('stopped', '已停止', f'端口 {_PORTS.api}')
        # 前端
        if mode == 'dual_dev' and app._frontend_process and app._frontend_process.poll() is None:
            self.row_fe.set_state('running', '运行中', f'{_PORTS.web} · {app._frontend_process.pid}')
        else:
            self.row_fe.set_state('stopped', '已停止', f'端口 {_PORTS.web}')
        # Redis
        hosting = getattr(app, '_last_hosting', None) or {}
        redis_ok = hosting.get('redis_ok', None if hosting else app._redis_running_cached)
        if app._redis_starting:
            self.row_redis.set_state('starting', '启动中…', f'端口 {_PORTS.redis}')
        elif redis_ok:
            self.row_redis.set_state('running', '运行中', f'端口 {_PORTS.redis}')
        else:
            self.row_redis.set_state('stopped', '已停止', f'端口 {_PORTS.redis}')
        # 生产
        api_state = (hosting.get('api_state') or '')
        arq_state = (hosting.get('arq_state') or '')
        self._svc_row_state(self.row_prod, api_state, hosting.get('api_running'), _SVC_API, f'端口 {_PORTS.api}')
        self._svc_row_state(self.row_arq, arq_state, hosting.get('arq_running'), _SVC_ARQ, '队列 Worker')
        # 互斥表达（后端语义：启动一方自动停止另一方；UI 提示而非禁用）
        self.btn_prod_start.config(state='normal' if mode not in ('starting', 'restarting') else 'disabled')
        # 生产『重启/关闭』由通用组件 OneClickButtonGroup 管理（app._update_all_ui 中 sync）
        self.btn_redis_start.config(state='disabled' if app._redis_starting else 'normal')
        self.btn_redis_stop.config(state='normal' if redis_ok else 'disabled')
        # 开发环境徽章 + 启动步骤进度条（对齐 v2 操作卡）
        if mode == 'dual_dev':
            self.dev_env_badge.set_state('running', '开发模式')
        elif mode in ('starting', 'restarting') and app._current_mode_key == 'dual_dev':
            self.dev_env_badge.set_state('deploying', '启动中' if mode == 'starting' else '重启中')
        else:
            self.dev_env_badge.set_state('stopped', '未运行')
        steps = getattr(app, '_startup_steps', None) or []
        if app._mode in ('starting', 'restarting') and steps:
            ratio = max(0.02, app._startup_progress / max(len(steps), 1))
            self.dev_prog_label.config(text=f'启动中: {app._startup_current_step} ({app._startup_progress}/{len(steps)})')
            self.dev_prog_fill.place_configure(relwidth=ratio)
        else:
            self.dev_prog_label.config(text='')
            self.dev_prog_fill.place_configure(relwidth=0)
        self._apply_filter(self.filter._active)

    @staticmethod
    def _svc_row_state(row, state_str, running, svc_name, meta):
        s = (state_str or '').upper()
        if 'RUNNING' in s:
            row.set_state('running', '运行中', meta)
        elif 'START_PENDING' in s or 'PAUSED' in s:
            row.set_state('starting', '启动中', meta)
        elif 'STOP_PENDING' in s:
            row.set_state('restarting', '停止中', meta)
        elif '未安装' in (state_str or ''):
            row.set_state('not_installed', '未安装', svc_name)
        else:
            row.set_state('stopped', '已停止', meta)

    def _apply_filter(self, idx):
        mapping = {0: None, 1: 'running', 2: 'stopped', 3: 'error'}
        key = mapping.get(idx)
        for row in (self.row_dev, self.row_fe, self.row_redis, self.row_prod, self.row_arq):
            if key is None or row.filter_key == key or (key == 'stopped' and row.filter_key == 'not_installed'):
                row.pack(fill=tk.X)
            else:
                row.pack_forget()

    def apply_hosting(self, data):
        """app._apply_hosting_data 的 UI 侧（明细徽章 + 状态文件时间）。"""
        def detail(badge, state, text):
            badge.set_state(state, text)
        if not data.get('api_running'):
            redis_ok = data.get('redis_ok')
            self.hosting_svc_badge.set_state('stopped', '服务停止')
            detail(self.hosting_backend_badge, 'stopped', '后端 已停止')
            detail(self.hosting_arq_badge, 'stopped', 'ARQ 未运行')
            detail(self.hosting_frontend_badge, 'stopped', '前端 已停止')
            detail(self.hosting_redis_badge, 'running' if redis_ok else 'stopped', f'Redis {"运行中" if redis_ok else "已停止"}')
            detail(self.hosting_ready_badge, 'stopped', '就绪 —')
        else:
            status = data.get('status') or {}
            svcs = status.get('services', {})
            self.hosting_svc_badge.set_state('running', '服务运行')
            backend_ok = svcs.get('backend', {}).get('status') == 'ready'
            detail(self.hosting_backend_badge, 'running' if backend_ok else 'error', f'后端 {"运行中" if backend_ok else "已停止"}')
            arq = svcs.get('arq', {})
            arq_status = arq.get('status', '—')
            arq_ok = arq_status == 'running'
            if arq_status == 'external':
                arq_ok = bool(data.get('arq_svc_pid'))
            detail(self.hosting_arq_badge, 'running' if arq_ok else 'error', f'ARQ {"运行中" if arq_ok else "未运行"}')
            fe_ok = svcs.get('frontend', {}).get('status') in ('running', 'ready')
            detail(self.hosting_frontend_badge, 'running' if fe_ok else 'error', f'前端 {"运行中" if fe_ok else "已停止"}')
            redis_ok = data.get('redis_ok')
            detail(self.hosting_redis_badge, 'running' if redis_ok else 'error', f'Redis {"运行中" if redis_ok else "已停止"}')
            ready = status.get('ready')
            detail(self.hosting_ready_badge, 'running' if ready else 'error', f'就绪 {"是" if ready else "—"}')
        mtime_str = data.get('mtime_str', '—')
        stale = data.get('stale')
        txt = f'状态文件 logs\\{_PROD_STATUS_FILE_NAME} · 更新 {mtime_str}'
        if stale:
            txt += ' · 数据过期'
        self.hosting_mtime.config(text=txt, fg=TOKENS.c('warning') if stale else TOKENS.c('text_muted'))


# ===================== 页面 3：日志中心（Logs） =====================

class LogsPage(Page):
    ROUTE, TITLE, SUBTITLE = 'logs', '日志中心', '实时输出 · 队列写入 · 主线程零阻塞'
    _LEVELS = ('INFO', 'WARNING', 'ERROR', 'SUCCESS')

    def build(self):
        app = self.app
        self.filter_level = 'ALL'
        self.filter_query = ''
        self.auto_scroll = True
        self._search_after = None
        # 工具栏
        bar = tk.Frame(self.body, bg=TOKENS.c('bg_panel'), highlightbackground=TOKENS.c('border'),
                       highlightthickness=1)
        bar.pack(fill=tk.X)
        self.seg = Segmented(bar, ['全部', 'INFO', 'WARN', 'ERROR'], command=self._on_level)
        self.seg.pack(side=tk.LEFT, padx=12, pady=10)
        self.search_var = tk.StringVar()
        entry = tk.Entry(bar, textvariable=self.search_var, font=TOKENS.f(8), width=26,
                         bg=TOKENS.c('bg_input'), fg=TOKENS.c('text_primary'),
                         insertbackground=TOKENS.c('text_primary'), relief=tk.FLAT,
                         highlightthickness=1, highlightbackground=TOKENS.c('border'),
                         highlightcolor=TOKENS.c('brand'))
        entry.pack(side=tk.LEFT, padx=(0, 12))
        entry.insert(0, '')
        self.search_var.trace_add('write', self._on_search_debounced)
        attach_tooltip(entry, '搜索日志关键字（200ms 防抖）')
        self.scroll_toggle = tk.Label(bar, text='自动滚动 ●', font=TOKENS.f(8), fg=TOKENS.c('brand'),
                                      bg=TOKENS.c('bg_panel'), cursor='hand2', padx=6)
        self.scroll_toggle.pack(side=tk.RIGHT, padx=(8, 12))
        self.scroll_toggle.bind('<Button-1>', lambda e: self._toggle_scroll())
        RoundedButton(bar, text='导出', variant='outlined', tone='brand', command=app.export_log,
                      canvas_bg=TOKENS.c('bg_panel'), small=True).pack(side=tk.RIGHT, padx=(6, 0), pady=8)
        RoundedButton(bar, text='清空', variant='outlined', tone='danger', command=app.clear_log,
                      canvas_bg=TOKENS.c('bg_panel'), small=True).pack(side=tk.RIGHT, pady=8)
        # 日志视图
        wrap = tk.Frame(self.body, bg=TOKENS.c('bg_panel'), highlightbackground=TOKENS.c('border'),
                        highlightthickness=1)
        wrap.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        log_font = app._pick_log_font()
        self.log_view = tk.Text(wrap, bg=TOKENS.c('bg_input'), fg=TOKENS.c('log_fg'),
                                insertbackground=TOKENS.c('text_primary'),
                                selectbackground=TOKENS.c('bg_elevated'), font=log_font,
                                wrap=tk.WORD, state=tk.DISABLED, relief=tk.FLAT, padx=14, pady=10,
                                cursor='arrow', height=8)
        self.log_view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        for lvl, color_key in (('INFO', 'log_info'), ('WARNING', 'log_warn'), ('ERROR', 'log_error'), ('SUCCESS', 'log_success')):
            self.log_view.tag_configure(lvl, foreground=TOKENS.c(color_key))
        scrollbar = tk.Scrollbar(wrap, command=self.log_view.yview, bg=TOKENS.c('border'),
                                 troughcolor=TOKENS.c('bg_input'), activebackground=TOKENS.c('border_strong'),
                                 relief=tk.FLAT, bd=0, elementborderwidth=0, highlightthickness=0, width=10)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_view.config(yscrollcommand=scrollbar.set)
        self.log_view.bind('<Button-1>', self._copy_line, add='+')
        # 主缓冲（隐藏）：导出与过滤的真相源；过滤视图仅做渲染
        self.log_text = tk.Text(self, bg=TOKENS.c('bg_input'), fg=TOKENS.c('text_secondary'),
                                font=log_font, wrap=tk.WORD, state=tk.DISABLED, height=2)
        self.log_text.pack_forget()
        for lvl in self._LEVELS:
            self.log_text.tag_configure(lvl, foreground=TOKENS.c('text_secondary'))
        self._log_index = deque(maxlen=_APP_CONFIG['max_log_lines'])
        self._empty_hint_shown = False

    # ---- 过滤与渲染（主缓冲 + 过滤视图分离，设计方案 §6.4） ----
    def _on_level(self, idx):
        self.filter_level = ('ALL', 'INFO', 'WARNING', 'ERROR')[idx]
        self.rebuild_view()

    def _on_search_debounced(self, *_):
        if self._search_after:
            with contextlib.suppress(Exception):
                self.after_cancel(self._search_after)
        self._search_after = self.after(200, self._apply_search)

    def _apply_search(self):
        self._search_after = None
        self.filter_query = self.search_var.get().strip().lower()
        self.rebuild_view()

    def _toggle_scroll(self):
        self.auto_scroll = not self.auto_scroll
        self.scroll_toggle.config(text='自动滚动 ●' if self.auto_scroll else '自动滚动 ○',
                                  fg=TOKENS.c('brand') if self.auto_scroll else TOKENS.c('text_muted'))

    def _match(self, level, text):
        if self.filter_level != 'ALL' and level != self.filter_level:
            return False
        if self.filter_query and self.filter_query not in text.lower():
            return False
        return True

    def append_line(self, text, level):
        """flush 后由 app 调用：条件追加到过滤视图。text 为不含换行的行。"""
        if self._match(level, text):
            self.log_view.config(state=tk.NORMAL)
            self.log_view.insert(tk.END, text + '\n', level)
            if self.auto_scroll:
                self.log_view.see(tk.END)
            self.log_view.config(state=tk.DISABLED)

    def rebuild_view(self):
        self.log_view.config(state=tk.NORMAL)
        self.log_view.delete('1.0', tk.END)
        count = 0
        for level, text in self._log_index:
            if self._match(level, text):
                self.log_view.insert(tk.END, text + '\n', level)
                count += 1
        if self.auto_scroll:
            self.log_view.see(tk.END)
        self.log_view.config(state=tk.DISABLED)

    def record(self, text, level):
        """主缓冲写入（app._flush_log_buffer 调用）。"""
        self._log_index.append((level, text))
        if len(self._log_index) >= self._log_index.maxlen - 50:
            with contextlib.suppress(Exception):
                excess = self.log_text.index('end-1c').split('.')[0]
                keep = _APP_CONFIG['log_keep_lines']
                if int(excess) > _APP_CONFIG['max_log_lines']:
                    self.log_text.config(state=tk.NORMAL)
                    self.log_text.delete('1.0', f'{int(excess) - keep}.0')
                    self.log_text.config(state=tk.DISABLED)

    def _copy_line(self, event):
        with contextlib.suppress(Exception):
            idx = self.log_view.index(f'@{event.x},{event.y}')
            line = self.log_view.get(f'{idx} linestart', f'{idx} lineend')
            if line.strip():
                self.app.root.clipboard_clear()
                self.app.root.clipboard_append(line)

    def restore_content(self, lines):
        """主题重建后恢复主缓冲。lines: [(level, text), ...]"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete('1.0', tk.END)
        self._log_index.clear()
        for level, text in lines[-_APP_CONFIG['max_log_lines']:]:
            self._log_index.append((level, text))
            self.log_text.insert(tk.END, text + '\n', level if level in self._LEVELS else 'INFO')
        self.log_text.config(state=tk.DISABLED)
        self.rebuild_view()


# ===================== 页面 4：配置管理（Config） =====================

class ConfigPage(Page):
    ROUTE, TITLE, SUBTITLE = 'config', '配置管理', '修改后需重启对应服务生效 · 端口保存后对新启动的服务即时生效'

    GROUPS = [('ports', '端口与路径'), ('redis', 'Redis'), ('nssm', 'NSSM'), ('log', '日志策略'), ('look', '外观')]

    def build(self):
        self._dirty = False
        self._suspend_dirty = True  # 构造/重置期间的 set() 不计为脏
        layout = tk.Frame(self.body, bg=TOKENS.c('bg_page'))
        layout.pack(fill=tk.BOTH, expand=True)
        layout.columnconfigure(1, weight=1)
        nav_card = self.card(layout, row=0, column=0, sticky='nw')
        self._group_btns = {}
        nav = tk.Frame(nav_card, bg=TOKENS.c('bg_panel'))
        nav.pack(padx=8, pady=8)
        for key, label in self.GROUPS:
            b = tk.Label(nav, text=label, font=TOKENS.f(9), fg=TOKENS.c('text_secondary'),
                         bg=TOKENS.c('bg_panel'), anchor='w', padx=12, pady=6, cursor='hand2')
            b.pack(fill=tk.X)
            b.bind('<Button-1>', lambda e, k=key: self.show_group(k))
            self._group_btns[key] = b
        holder = tk.Frame(layout, bg=TOKENS.c('bg_page'))
        holder.grid(row=0, column=1, sticky='nsew', padx=(16, 0))
        self._groups = {}
        for key, _ in self.GROUPS:
            f = tk.Frame(holder, bg=TOKENS.c('bg_page'))
            f.place(in_=holder, x=0, y=0, relwidth=1, relheight=1)
            self._groups[key] = f
        self._build_ports_group()
        self._build_redis_group()
        self._build_nssm_group()
        self._build_log_group()
        self._build_look_group()
        # 底部保存栏
        foot = tk.Frame(self.body, bg=TOKENS.c('bg_page'))
        foot.pack(fill=tk.X, pady=(12, 0))
        self.dirty_hint = tk.Label(foot, text='', font=TOKENS.f(8), fg=TOKENS.c('warning'), bg=TOKENS.c('bg_page'))
        self.dirty_hint.pack(side=tk.LEFT)
        self.btn_reset = RoundedButton(foot, text='重置', variant='outlined', tone='neutral',
                                       command=self._reset, canvas_bg=TOKENS.c('bg_page'), state='disabled')
        self.btn_reset.pack(side=tk.RIGHT, padx=(8, 0))
        self.btn_save = RoundedButton(foot, text='保存配置', variant='solid', tone='brand',
                                      command=self._save, canvas_bg=TOKENS.c('bg_page'), state='disabled')
        self.btn_save.pack(side=tk.RIGHT)
        self.show_group('ports')
        self._suspend_dirty = False

    # ---- 表单构件 ----
    def _form_card(self, group_key, title, sub=''):
        card = self.card(self._groups[group_key])
        card.pack(fill=tk.X)
        self.card_head(card, title, sub)
        body = tk.Frame(card, bg=TOKENS.c('bg_panel'))
        body.pack(fill=tk.X, padx=16, pady=(8, 16))
        return body

    def _field(self, parent, label, hint='', mono=True, value='', browse=False, browse_var=None):
        item = tk.Frame(parent, bg=TOKENS.c('bg_panel'))
        item.pack(fill=tk.X, pady=6)
        tk.Label(item, text=label, font=TOKENS.f(8), fg=TOKENS.c('text_secondary'),
                 bg=TOKENS.c('bg_panel'), anchor='w').pack(fill=tk.X)
        row = tk.Frame(item, bg=TOKENS.c('bg_panel'))
        row.pack(fill=tk.X, pady=(4, 0))
        var = tk.StringVar(value=value)
        entry = tk.Entry(row, textvariable=var, font=TOKENS.fm(8) if mono else TOKENS.f(8),
                         bg=TOKENS.c('bg_input'), fg=TOKENS.c('text_primary'),
                         insertbackground=TOKENS.c('text_primary'), relief=tk.FLAT,
                         highlightthickness=1, highlightbackground=TOKENS.c('border'),
                         highlightcolor=TOKENS.c('brand'))
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        var.trace_add('write', lambda *a: self._mark_dirty())
        if browse:
            RoundedButton(row, text='浏览…', variant='outlined', tone='neutral', small=True, pady=2, radius=6,
                          command=lambda: self._browse(var), canvas_bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT, padx=(8, 0))
        if hint:
            tk.Label(item, text=hint, font=TOKENS.f(7), fg=TOKENS.c('text_muted'),
                     bg=TOKENS.c('bg_panel'), anchor='w').pack(fill=tk.X, pady=(3, 0))
        return var

    @staticmethod
    def _browse(var):
        from tkinter import filedialog
        path = filedialog.askopenfilename()
        if path:
            var.set(path)

    def _build_ports_group(self):
        body = self._form_card('ports', '端口与路径', '端口从配置读取，UI 不硬编码')
        grid = tk.Frame(body, bg=TOKENS.c('bg_panel'))
        grid.pack(fill=tk.X)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        left, right = tk.Frame(grid, bg=TOKENS.c('bg_panel')), tk.Frame(grid, bg=TOKENS.c('bg_panel'))
        left.grid(row=0, column=0, sticky='nsew')
        right.grid(row=0, column=1, sticky='nsew', padx=(24, 0))
        self.var_api = self._field(left, 'API 端口', 'FastAPI 后端（默认 5002）', value=str(_APP_CONFIG['api_port']))
        self.var_web = self._field(left, 'WEB 端口', 'Vite 前端（默认 3000）', value=str(_APP_CONFIG['web_port']))
        self.var_redis_port = self._field(left, 'Redis 端口', '默认 6379 · 启动前自动校验占用', value=str(_APP_CONFIG['redis_port']))
        self.var_proj = self._field(right, '项目目录', f'当前: {_PROJECT_DIR}', value=str(_PROJECT_DIR))
        self.var_proj_trace = True

    def _build_redis_group(self):
        body = self._form_card('redis', 'Redis', '独立进程 · 开发模式启动时自动拉起')
        self.var_redis_exe = self._field(body, 'redis-server.exe 路径',
                                         '留空则按候选列表探测（C:\\Redis\\ 等）',
                                         value=_APP_CONFIG['redis_exe'], browse=True)

    def _build_nssm_group(self):
        body = self._form_card('nssm', 'NSSM', f'服务名: {_SVC_API} / {_SVC_ARQ}（安装时写入 DependOnService）')
        self.var_nssm = self._field(body, 'nssm.exe 路径', '留空则按候选列表探测',
                                    value=_APP_CONFIG['nssm_path'], browse=True)

    def _build_log_group(self):
        body = self._form_card('log', '日志策略', '队列批量写入 · 超限自动裁剪首行')
        self.var_max_lines = self._field(body, '日志上限行数', f"当前 {_APP_CONFIG['max_log_lines']}（v5 为 500）",
                                         value=str(_APP_CONFIG['max_log_lines']), mono=True)
        self.var_keep_lines = self._field(body, '裁剪保留行数', f"当前 {_APP_CONFIG['log_keep_lines']}（v5 为 300）",
                                          value=str(_APP_CONFIG['log_keep_lines']), mono=True)

    def _build_look_group(self):
        body = self._form_card('look', '外观', '主题即时生效')
        self.theme_seg = Segmented(body, ['暗色', '亮色'],
                                   command=lambda i: self._mark_dirty())
        self.theme_seg.set_active(1 if _APP_CONFIG['theme'] == 'light' else 0, fire=False)
        self.theme_seg.pack(anchor='w')

    # ---- 交互 ----
    def show_group(self, key):
        for k, btn in self._group_btns.items():
            if k == key:
                btn.config(bg=TOKENS.tint('brand_tint', 'bg_panel'), fg=TOKENS.c('brand'))
            else:
                btn.config(bg=TOKENS.c('bg_panel'), fg=TOKENS.c('text_secondary'))
        self._groups[key].tkraise()

    def _mark_dirty(self):
        if self._suspend_dirty or self._dirty:
            return
        self._dirty = True
        self.dirty_hint.config(text='● 有未保存的修改')
        self.btn_save.config(state='normal')
        self.btn_reset.config(state='normal')

    def _reset(self):
        self._suspend_dirty = True
        self._dirty = False
        self.dirty_hint.config(text='')
        self.btn_save.config(state='disabled')
        self.btn_reset.config(state='disabled')
        for var, cfg_key in ((self.var_api, 'api_port'), (self.var_web, 'web_port'),
                             (self.var_redis_port, 'redis_port'), (self.var_redis_exe, 'redis_exe'),
                             (self.var_nssm, 'nssm_path'), (self.var_max_lines, 'max_log_lines'),
                             (self.var_keep_lines, 'log_keep_lines')):
            var.set(str(_APP_CONFIG[cfg_key]))
        self.theme_seg.set_active(1 if _APP_CONFIG['theme'] == 'light' else 0, fire=False)
        self._suspend_dirty = False

    def _save(self):
        self._suspend_dirty = True
        try:
            errors = []
            try:
                api = int(self.var_api.get())
                web = int(self.var_web.get())
                redis_port = int(self.var_redis_port.get())
                for name, v in (('API', api), ('WEB', web), ('Redis', redis_port)):
                    if not 1 <= v <= 65535:
                        errors.append(f'{name} 端口超出有效范围 1-65535')
            except ValueError:
                errors.append('端口必须为整数')
            try:
                max_lines = max(200, int(self.var_max_lines.get()))
                keep_lines = max(100, int(self.var_keep_lines.get()))
            except ValueError:
                errors.append('日志行数必须为整数')
                max_lines = keep_lines = None
            if errors:
                self.app.toast.show('error', '校验失败', '；'.join(errors))
                return
            _APP_CONFIG.update({
                'api_port': api, 'web_port': web, 'redis_port': redis_port,
                'redis_exe': self.var_redis_exe.get().strip(),
                'nssm_path': self.var_nssm.get().strip(),
                'max_log_lines': max_lines, 'log_keep_lines': min(keep_lines, max_lines - 100),
                'theme': 'light' if self.theme_seg._active == 1 else 'dark',
            })
            if not _save_app_config(_APP_CONFIG):
                self.app.toast.show('warn', '保存到磁盘失败', '配置已在本次会话生效，但写入配置文件失败')
            _apply_config_to_runtime(_APP_CONFIG)
            self._dirty = False
            self.dirty_hint.config(text='')
            self.btn_save.config(state='disabled')
            self.btn_reset.config(state='disabled')
            self.app.topbar.rebuild_ports()
            self.app.toast.show('success', '配置已保存', '端口对新启动的服务即时生效；已运行服务需重启')
            if TOKENS.theme != _APP_CONFIG['theme']:
                self.app.toggle_theme()
        finally:
            self._suspend_dirty = False


# ===================== 页面 5：部署发布（Deploy） =====================

class DeployPage(Page):
    ROUTE, TITLE, SUBTITLE = 'deploy', '部署发布', '四步发布流水线 · NSSM 服务生命周期管理'

    def build(self):
        app = self.app
        # 发布流水线（Stepper + 步骤日志，对齐 UI 重构 v2）
        pipe = self.card(self.body)
        pipe.pack(fill=tk.X)
        self.card_head(pipe, '发布流水线', '校验 → 备份 → 部署 → 健康检查')
        pbody = tk.Frame(pipe, bg=TOKENS.c('bg_panel'))
        pbody.pack(fill=tk.X, padx=16, pady=(12, 0))
        steps = [('校验环境', 'Python / 依赖 / 端口'), ('备份现状', '数据库 + 代码快照'),
                 ('部署更新', '同步 / 构建 / 迁移'), ('健康检查', 'API / Web / Redis')]
        self._build_stepper(pbody, steps, ['done', 'done', 'current', 'wait'])
        # 步骤执行日志（当前结构静态展示；接入真实流水线后由后台线程实时追加）
        log = tk.Frame(pipe, bg=TOKENS.c('bg_input'), highlightbackground=TOKENS.c('border'),
                       highlightthickness=1)
        log.pack(fill=tk.X, padx=16, pady=(12, 16))
        logtxt = tk.Text(log, height=6, bg=TOKENS.c('bg_input'), fg=TOKENS.c('text_secondary'),
                         font=TOKENS.fm(7), wrap=tk.WORD, relief=tk.FLAT, padx=12, pady=8,
                         insertbackground=TOKENS.c('text_secondary'))
        logtxt.pack(fill=tk.X)
        for line in (
            '[13:08:01]  ✓ 环境校验通过：Python 3.13.12 · 依赖无缺失',
            '[13:08:04]  ✓ 备份完成：backups\\erp_20260822_130804.zip (1.2 GB)',
            '[13:08:09]  同步代码 → fastapi_app/ ... 87%',
            '[13:08:16]  ⚠ 数据库迁移完成，新增索引 1 个',
            '[13:08:22]  重启 erp-prod 服务 ...',
            '[13:08:26]  ✓ 健康检查通过：API 12ms · WEB 45ms · Redis PONG',
        ):
            logtxt.insert(tk.END, line + '\n')
        logtxt.config(state=tk.DISABLED)
        # 生产服务安装（NSSM）—— 保留既有生命周期管理
        ncard = self.card(self.body)
        ncard.pack(fill=tk.X, pady=(16, 0))
        self.card_head(ncard, '生产服务安装（NSSM）', '开机自启 · 崩溃自愈 · PG/Redis 启动依赖')
        nbody = tk.Frame(ncard, bg=TOKENS.c('bg_panel'))
        nbody.pack(fill=tk.X, padx=16, pady=(10, 16))
        nform = tk.Frame(nbody, bg=TOKENS.c('bg_panel'))
        nform.pack(fill=tk.X)
        tk.Label(nform, text='Worker 数', font=TOKENS.f(8), fg=TOKENS.c('text_secondary'),
                 bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT)
        app.hosting_workers_var = tk.StringVar(value=str(int(os.getenv('UVICORN_WORKERS', '4'))))
        combo = ttk.Combobox(nform, textvariable=app.hosting_workers_var, values=('2', '4', '6', '8'),
                             width=4, state='readonly', font=TOKENS.f(8))
        combo.pack(side=tk.LEFT, padx=(8, 0))
        tk.Label(nform, text='服务: erp-prod（--no-arq 监督器）+ erp-arq（队列 Worker）',
                 font=TOKENS.fm(7), fg=TOKENS.c('text_muted'), bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT, padx=(16, 0))
        nbtns = tk.Frame(nbody, bg=TOKENS.c('bg_panel'))
        nbtns.pack(fill=tk.X, pady=(12, 0))
        RoundedButton(nbtns, text='安装服务', variant='solid', tone='success', command=app._install_services,
                      canvas_bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT)
        RoundedButton(nbtns, text='卸载服务', variant='outlined', tone='danger', command=app._uninstall_services,
                      canvas_bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT, padx=(8, 0))
        RoundedButton(nbtns, text='打开日志目录', variant='outlined', tone='neutral', command=app._open_logs_dir,
                      canvas_bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT, padx=(8, 0))
        # 发布历史（时间 / 版本 / 结果 / 耗时 / 操作）
        hist = self.card(self.body)
        hist.pack(fill=tk.BOTH, expand=True, pady=(16, 0))
        self.card_head(hist, '发布历史', '最近 5 次')
        rows = tk.Frame(hist, bg=TOKENS.c('bg_panel'))
        rows.pack(fill=tk.BOTH, expand=True, padx=16, pady=(8, 16))
        hdr = tk.Frame(rows, bg=TOKENS.c('bg_panel'))
        hdr.pack(fill=tk.X)
        for txt, w in (('时间', 130), ('版本', 200), ('结果', 120), ('耗时', 90), ('操作', 90)):
            tk.Label(hdr, text=txt, font=TOKENS.f(7), fg=TOKENS.c('text_muted'),
                     bg=TOKENS.c('bg_panel'), anchor='w', width=w // 9).pack(side=tk.LEFT)
        for h in (
            ('08-22 13:02', 'v5.33 → v6.0', 'done', '成功', '4m 12s'),
            ('08-15 21:40', 'v5.32 → v5.33', 'done', '成功', '3m 55s'),
            ('08-12 09:15', 'v5.31 → v5.32', 'fail', '失败 · 已回滚', '2m 40s'),
        ):
            self._history_row(rows, h)

    def _build_stepper(self, parent, steps, states):
        """四步发布步骤条：done=品牌实心勾 / current=品牌描边 / wait=灰描边 / fail=红实心。"""
        for i, ((title, desc), state) in enumerate(zip(steps, states)):
            col = tk.Frame(parent, bg=TOKENS.c('bg_panel'))
            col.pack(side=tk.LEFT, fill=tk.X, expand=True)
            cv = tk.Canvas(col, width=30, height=30, highlightthickness=0, bg=TOKENS.c('bg_panel'))
            cv.pack()
            if state == 'done':
                cv.create_oval(3, 3, 27, 27, fill=TOKENS.c('brand'), outline='')
                cv.create_line(9, 15, 13, 19, 21, 10, fill='#ffffff', width=2,
                               capstyle=tk.ROUND, joinstyle=tk.ROUND)
            elif state == 'fail':
                cv.create_oval(3, 3, 27, 27, fill=TOKENS.c('danger'), outline='')
                cv.create_text(15, 15, text='!', fill='#ffffff',
                               font=TOKENS.f(9, 'bold'))
            elif state == 'current':
                cv.create_oval(3, 3, 27, 27, outline=TOKENS.c('brand'), width=1.5)
                cv.create_text(15, 15, text=str(i + 1), fill=TOKENS.c('brand'),
                               font=TOKENS.f(9, 'bold'))
            else:
                cv.create_oval(3, 3, 27, 27, outline=TOKENS.c('border_strong'), width=1.5)
                cv.create_text(15, 15, text=str(i + 1), fill=TOKENS.c('text_muted'),
                               font=TOKENS.f(9, 'bold'))
            tk.Label(col, text=title,
                     font=TOKENS.f(8, 'bold') if state in ('done', 'current') else TOKENS.f(8),
                     fg=TOKENS.c('text_primary') if state != 'wait' else TOKENS.c('text_muted'),
                     bg=TOKENS.c('bg_panel')).pack()
            tk.Label(col, text=desc, font=TOKENS.f(6), fg=TOKENS.c('text_muted'),
                     bg=TOKENS.c('bg_panel')).pack()
            if i < len(steps) - 1:
                line = tk.Frame(parent, bg=TOKENS.c('border_strong'), width=24)
                line.pack(side=tk.LEFT, fill=tk.Y, padx=(4, 4))

    def _history_row(self, parent, h):
        """发布历史行：结果列用 tint Tag 表达成功/失败。"""
        time_, ver, state, result, dur = h
        row = tk.Frame(parent, bg=TOKENS.c('bg_panel'))
        row.pack(fill=tk.X, pady=4)
        tk.Label(row, text=time_, font=TOKENS.fm(7), fg=TOKENS.c('text_secondary'),
                 bg=TOKENS.c('bg_panel'), anchor='w', width=14).pack(side=tk.LEFT)
        tk.Label(row, text=ver, font=TOKENS.fm(7), fg=TOKENS.c('text_secondary'),
                 bg=TOKENS.c('bg_panel'), anchor='w', width=22).pack(side=tk.LEFT)
        tone = 'success' if state == 'done' else 'danger'
        tk.Label(row, text=result, font=TOKENS.f(7), fg=TOKENS.c(tone),
                 bg=TOKENS.tint(f'{tone}_tint', 'bg_panel'), padx=8, pady=2).pack(side=tk.LEFT)
        tk.Label(row, text=dur, font=TOKENS.fm(7), fg=TOKENS.c('text_secondary'),
                 bg=TOKENS.c('bg_panel'), anchor='w', width=10).pack(side=tk.LEFT, padx=(14, 0))
        RoundedButton(row, text='查看日志', variant='outlined', tone='brand',
                      command=self.app._open_logs_dir, canvas_bg=TOKENS.c('bg_panel'),
                      small=True, pady=2).pack(side=tk.LEFT)


# ===================== 页面 6：告警中心（Alerts） =====================

class AlertsPage(Page):
    ROUTE, TITLE, SUBTITLE = 'alerts', '告警中心', '服务掉线 / 数据过期 / 健康检查失败自动上报'

    _LEVEL_META = {'error': ('danger', '严重'), 'warn': ('warning', '警告'), 'info': ('info', '提示')}

    def build(self):
        self.btn_confirm_all = RoundedButton(self.head_actions, text='全部确认', variant='outlined', tone='brand',
                                             command=self.app.confirm_all_alerts, canvas_bg=TOKENS.c('bg_page'), small=True)
        self.btn_confirm_all.pack(side=tk.RIGHT)
        self.list_card = self.card(self.body)
        self.list_card.pack(fill=tk.BOTH, expand=True)
        self.list_holder = tk.Frame(self.list_card, bg=TOKENS.c('bg_panel'))
        self.list_holder.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.rebuild()

    def rebuild(self):
        for w in self.list_holder.winfo_children():
            w.destroy()
        alerts = self.app.alerts.alerts
        if not alerts:
            EmptyState(self.list_holder, '暂无告警 · 一切正常').pack(fill=tk.BOTH, expand=True)
            return
        for a in reversed(alerts):  # 新的在上
            self._row(a)

    def _row(self, a):
        tone_key, tone_text = self._LEVEL_META.get(a['level'], self._LEVEL_META['info'])
        row = tk.Frame(self.list_holder, bg=TOKENS.c('bg_panel'))
        row.pack(fill=tk.X, pady=2)
        inner = tk.Frame(row, bg=TOKENS.c('bg_panel'))
        inner.pack(fill=tk.X, padx=8, pady=(8, 0))
        dot = tk.Canvas(inner, width=12, height=12, highlightthickness=0, bg=TOKENS.c('bg_panel'))
        color = TOKENS.c(tone_key)
        dot.create_oval(2, 2, 10, 10, fill=color, outline='')
        dot.pack(side=tk.LEFT)
        col = tk.Frame(inner, bg=TOKENS.c('bg_panel'))
        col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        head = tk.Frame(col, bg=TOKENS.c('bg_panel'))
        head.pack(fill=tk.X)
        fg = TOKENS.c('text_primary') if not a.get('confirmed') else TOKENS.c('text_muted')
        tk.Label(head, text=a['title'], font=TOKENS.f(9, 'bold'), fg=fg, bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT)
        tk.Label(head, text=tone_text, font=TOKENS.f(7), fg=color,
                 bg=TOKENS.tint(f'{tone_key}_tint', 'bg_panel'), padx=6).pack(side=tk.LEFT, padx=(8, 0))
        if a.get('confirmed'):
            tk.Label(head, text='已确认', font=TOKENS.f(7), fg=TOKENS.c('text_muted'), bg=TOKENS.c('bg_panel')).pack(side=tk.LEFT, padx=(8, 0))
        tk.Label(col, text=a['desc'], font=TOKENS.f(8), fg=TOKENS.c('text_secondary'),
                 bg=TOKENS.c('bg_panel'), anchor='w', wraplength=520, justify=tk.LEFT).pack(fill=tk.X)
        tk.Label(col, text=a['time'], font=TOKENS.fm(7), fg=TOKENS.c('text_muted'),
                 bg=TOKENS.c('bg_panel'), anchor='w').pack(fill=tk.X)
        if not a.get('confirmed'):
            RoundedButton(inner, text='确认', variant='outlined', tone='neutral', small=True, pady=2, radius=6,
                          command=lambda key=a['key']: self.app.confirm_alert(key),
                          canvas_bg=TOKENS.c('bg_panel')).pack(side=tk.RIGHT)
        tk.Frame(row, bg=TOKENS.c('border'), height=1).pack(fill=tk.X, padx=8, pady=(8, 0))

    def refresh_badges(self):
        app = self.app
        n = app.alerts.unconfirmed_count()
        app.sidenav.set_alert_badge(n)
        app.statusbar.set_alert_count(n)


class AlertEngine:
    """告警引擎：检测点上抛 → 去重（60s 冷却/未确认合并）→ 持久化（logs/server_manager_alerts.json，上限 100）。"""

    COOLDOWN = 60

    def __init__(self, app):
        self._app = app
        self.alerts = []
        self._last_raise = {}
        self._load()

    def _load(self):
        try:
            if _ALERTS_FILE.is_file():
                data = json.loads(_ALERTS_FILE.read_text(encoding='utf-8'))
                if isinstance(data, list):
                    self.alerts = [a for a in data if isinstance(a, dict) and 'key' in a][-100:]
        except Exception:
            pass

    def _save(self):
        with contextlib.suppress(Exception):
            _ALERTS_FILE.parent.mkdir(exist_ok=True)
            _ALERTS_FILE.write_text(json.dumps(self.alerts[-100:], ensure_ascii=False, indent=1), encoding='utf-8')

    def raise_alert(self, key, level, title, desc=''):
        now = time.time()
        last = self._last_raise.get(key, 0)
        if now - last < self.COOLDOWN:
            return
        for a in self.alerts:
            if a['key'] == key and not a.get('confirmed'):
                a['time'] = datetime.now().strftime('%m-%d %H:%M:%S')
                self._last_raise[key] = now
                return  # 未确认同键不重复入列
        self._last_raise[key] = now
        self.alerts.append({
            'key': key, 'level': level, 'title': title, 'desc': desc,
            'time': datetime.now().strftime('%m-%d %H:%M:%S'), 'confirmed': False,
        })
        if len(self.alerts) > 100:
            self.alerts = self.alerts[-100:]
        self._save()
        self._app.after_alert_change()
        if level in ('error', 'warn'):
            self._app.toast.show(level if level != 'warn' else 'warn', title, desc)

    def confirm(self, key=None, all_keys=False):
        changed = False
        for a in self.alerts:
            if all_keys or a['key'] == key:
                if not a.get('confirmed'):
                    a['confirmed'] = True
                    a['time'] += ' · 已确认'
                    changed = True
        if changed:
            self._save()
            self._app.after_alert_change()

    def unconfirmed_count(self):
        return sum(1 for a in self.alerts if not a.get('confirmed'))


# ===================== psutil 采样器（后台线程 → 队列 → 主线程渲染） =====================

class MetricsSampler:
    """2s 采样：CPU/内存/磁盘/网络速率/进程 Top5。psutil 缺失时上报一次不可用。"""

    INTERVAL = 2

    def __init__(self, msg_queue):
        self._q = msg_queue
        self._stop = threading.Event()
        self._last_net = None
        self._last_ts = None
        self._disk_cache = (0, None)
        self._proc_round = 0

    def start(self):
        if psutil is None:
            self._q.put(('metric', {'unavailable': True}))
            return
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        psutil.cpu_percent(interval=None)  # 建立基线
        while not self._stop.wait(self.INTERVAL):
            try:
                sample = self._sample()
                if sample:
                    self._q.put(('metric', sample))
            except Exception:
                self._q.put(('metric', {'error': True}))

    def _sample(self):
        now = time.time()
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        ts, cached = self._disk_cache
        if cached is None or now - ts > 30:
            cached = psutil.disk_usage(str(_PROJECT_DIR)).percent
            self._disk_cache = (now, cached)
        net = psutil.net_io_counters()
        dn_mb = up_kb = 0.0
        if self._last_net is not None and self._last_ts:
            dt = max(0.2, now - self._last_ts)
            dn_mb = max(0.0, (net.bytes_recv - self._last_net.bytes_recv) / dt / 1024 / 1024)
            up_kb = max(0.0, (net.bytes_sent - self._last_net.bytes_sent) / dt / 1024)
        self._last_net, self._last_ts = net, now
        sample = {
            'cpu': cpu, 'mem': mem, 'disk': cached,
            'net_dn_mb': dn_mb, 'net_up_kb': up_kb,
        }
        self._proc_round += 1
        if self._proc_round % 2 == 0:
            procs = []
            for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                try:
                    info = p.info
                    name = info['name'] or ''
                    if info['cpu_percent'] is None:
                        continue
                    procs.append((f'{name} ({info["pid"]})', info['cpu_percent'], info['memory_percent'] or 0))
                except Exception:
                    continue
            procs.sort(key=lambda x: x[1], reverse=True)
            sample['procs'] = procs[:5]
        return sample


# ===================== ServerManagerApp：装配 + 业务逻辑（v5.33 保留） =====================

class ServerManagerApp:
    """ERP 服务器管理器 — 开发/生产模式（三段式 UI v6）"""

    MAX_LOG_LINES = _APP_CONFIG['max_log_lines']
    LOG_KEEP_LINES = _APP_CONFIG['log_keep_lines']
    LOG_CLEANUP_MS, LOG_FLUSH_MS = 120000, 500

    def __init__(self, root):
        self.root = root
        self.root.title(_WINDOW_TITLE)
        self.root.geometry("1100x760")
        self.root.minsize(960, 680)
        self.root.resizable(True, True)
        self.root.withdraw()
        self._mode, self._process, self._frontend_process, self._redis_process = 'none', None, None, None
        self._log_buffer, self._flush_pending = [], False
        self._msg_queue = queue.Queue()
        self._startup_progress, self._startup_steps, self._startup_current_step, self._current_mode_key = 0, [], "", ""
        self._prod_running = False
        self._hosting_collecting, self._hosting_refresh_requested = False, False
        self._check_interval, self._after_ids = 5000, {}
        self._redis_running_cached = None     # None=未知 True/False=最近一次探测
        self._redis_starting = False
        self._last_hosting = {}
        self._sampler = None
        self._shutting_down = False
        self.setup_logging()
        self.alerts = AlertEngine(self)
        self._build_ui()
        self._set_window_icon()
        self._center_window()
        _apply_dark_titlebar(self.root)
        self.root.deiconify()
        self._fade_in()
        self._run_env_checks()
        self.check_server_status()
        self._refresh_hosting_status()
        self._schedule_log_cleanup()
        self._schedule_log_flush()
        self._poll_queue()
        self._tray_icon = None
        self._init_tray()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self._sampler = MetricsSampler(self._msg_queue)
        self._sampler.start()
        if psutil is None:
            self.alerts.raise_alert('psutil_missing', 'info', 'psutil 未安装',
                                    '运行监控页性能/进程采样不可用，请 pip install psutil 后重启管理器')
        self._ui_ready = True
        self.logger.info(f"服务器管理器已启动 ({_VERSION}, 主题={TOKENS.theme}, ReducedMotion={REDUCE_MOTION})")

    # ===================== UI 装配 =====================

    def _build_ui(self):
        self.root.configure(bg=TOKENS.c('bg_page'))
        self._setup_ttk_style()
        main = tk.Frame(self.root, bg=TOKENS.c('bg_page'))
        main.pack(fill=tk.BOTH, expand=True)
        self.sidenav = SideNav(main, self)
        self.sidenav.pack(side=tk.LEFT, fill=tk.Y)
        self.main_col = tk.Frame(main, bg=TOKENS.c('bg_page'))
        self.main_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.topbar = TopBar(self.main_col, self)
        self.topbar.pack(fill=tk.X)
        self.statusbar = StatusBar(self.main_col, self)
        self.statusbar.pack(fill=tk.X, side=tk.BOTTOM)
        self.toast = ToastManager(self.main_col)
        content = tk.Frame(self.main_col, bg=TOKENS.c('bg_page'))
        content.pack(fill=tk.BOTH, expand=True)
        self.router = PageRouter(content, self)
        self.router.pack(fill=tk.BOTH, expand=True)
        self.overview_page = OverviewPage(self, self.router)
        self.services_page = ServicesPage(self, self.router)
        self.logs_page = LogsPage(self, self.router)
        self.config_page = ConfigPage(self, self.router)
        self.deploy_page = DeployPage(self, self.router)
        self.alerts_page = AlertsPage(self, self.router)
        for page in (self.overview_page, self.services_page, self.logs_page,
                     self.config_page, self.deploy_page, self.alerts_page):
            self.router.register(page)
        # 兼容别名（业务方法引用）
        self.log_text = self.logs_page.log_text
        self.dual_dev_status = self.services_page.dev_status
        self.dual_dev_start_btn = self.services_page.dev_start_btn
        self.after_alert_change()
        self._init_one_click_actions()
        self.router.show('overview')

    def _setup_ttk_style(self):
        style = ttk.Style()
        with contextlib.suppress(Exception):
            style.theme_use('clam')
        style.configure('TCombobox', fieldbackground=TOKENS.c('bg_input'), background=TOKENS.c('bg_panel'),
                        foreground=TOKENS.c('text_primary'), arrowcolor=TOKENS.c('text_secondary'),
                        bordercolor=TOKENS.c('border'), lightcolor=TOKENS.c('bg_panel'),
                        darkcolor=TOKENS.c('bg_panel'))

    def navigate(self, route):
        self.router.show(route)

    def toggle_theme(self):
        new_theme = 'light' if TOKENS.theme == 'dark' else 'dark'
        _APP_CONFIG['theme'] = new_theme
        _save_app_config(_APP_CONFIG)
        TOKENS.set_theme(new_theme)
        self._rebuild_ui()

    def _rebuild_ui(self):
        """主题切换：整体重建 UI，保留日志内容与状态。"""
        logs = list(getattr(self.logs_page, '_log_index', []) or [])
        hosting = dict(self._last_hosting)
        self._stop_animations(self.root)
        for w in self.root.winfo_children():
            with contextlib.suppress(Exception):
                w.destroy()
        self._build_ui()
        self.logs_page.restore_content(logs)
        self._update_all_ui()
        if hosting:
            with contextlib.suppress(Exception):
                self.services_page.apply_hosting(hosting)
        self.overview_page.sync_stats()
        self.root.configure(bg=TOKENS.c('bg_page'))

    @staticmethod
    def _stop_animations(widget):
        for w in widget.winfo_children():
            if hasattr(w, 'stop_animation'):
                with contextlib.suppress(Exception):
                    w.stop_animation()
            if hasattr(w, 'winfo_children'):
                ServerManagerApp._stop_animations(w)

    # ===================== 通用一键操作（开发/生产共用组件） =====================

    def _init_one_click_actions(self):
        """接线通用『重启/关闭』组件：同一组件类 + 两套 spec，共享一把在途锁。

        - 差异（执行体/确认策略/运行态判定）收敛在 ModeActionSpec 内；
        - ActionLock 全局共享 → 开发/生产操作互斥；
        - 结果回调统一走 _action_ok / _action_fail（Toast + 告警中心）。
        """
        self._action_lock = ActionLock()
        sp = self.services_page

        # —— 开发模式：重启 / 关闭 ——
        self.dev_action_ctrl = OneClickActionController(
            self,
            ModeActionSpec(
                key='dev', display='开发模式',
                running=lambda: self._mode == 'dual_dev',
                do_restart=lambda: self._restart_dual_thread(),
                do_stop=lambda: self._stop_dual_mode_sync('dual_dev', '开发模式'),
                confirm_restart=False,
                confirm_stop=False,      # 开发关闭风险低，跳过二次确认
                report=False,            # dev 重启/停止结果由消息泵(_on_dual_*)反馈，组件不再重复 Toast
            ),
            self._action_lock,
            on_success=self._action_ok,
            on_failure=self._action_fail,
            on_busy_change=self._update_all_ui,
        )
        self.dev_actions = OneClickButtonGroup(sp.dev_restart_box, self.dev_action_ctrl,
                                               stop_parent=sp.dev_stop_box)
        self.dev_actions.sync()

        # —— 生产模式：重启 / 关闭 ——
        self.prod_action_ctrl = OneClickActionController(
            self,
            ModeActionSpec(
                key='prod', display='生产模式',
                running=lambda: self._prod_running,
                do_restart=lambda: self._prod_restart_sync(),
                do_stop=lambda: self._prod_stop_sync(),
                confirm_restart=False,
                confirm_stop=True,       # 生产关闭必二次确认
                stop_desc='将停止 erp-prod / erp-arq 服务（保留 NSSM 注册，可再次一键启动）。',
            ),
            self._action_lock,
            on_success=self._action_ok,
            on_failure=self._action_fail,
            on_busy_change=self._update_all_ui,
        )
        self.prod_actions = OneClickButtonGroup(sp.prod_restart_box, self.prod_action_ctrl,
                                                stop_parent=sp.prod_stop_box)
        self.prod_actions.sync()

    def _action_ok(self, kind, msg):
        """一键操作成功反馈（kind ∈ restart/stop）。"""
        display = {'restart': '重启', 'stop': '关闭'}.get(kind, kind)
        self.toast.show('ok', f'操作成功：{display}', msg or '')
        self.log_message(f'一键{display}完成')

    def _action_fail(self, kind, reason):
        """一键操作失败反馈：红 Toast + 告警中心 + 日志。"""
        display = {'restart': '重启', 'stop': '关闭'}.get(kind, kind)
        self.log_message(f'一键{display}失败: {reason}', 'ERROR')
        self.toast.show('error', f'操作失败：{display}', reason)
        self.alerts.raise_alert(f'{self._action_owner}_action_failed', 'error',
                                f'一键{display}失败', reason)
        self._update_all_ui()

    @property
    def _action_owner(self):
        for ctrl in (getattr(self, 'dev_action_ctrl', None), getattr(self, 'prod_action_ctrl', None)):
            if ctrl and ctrl.inflight():
                return ctrl.spec.key
        return 'app'

    def _stop_dual_mode_sync(self, mode, label):
        """同步版停止开发模式（通用组件执行体用；从 _stop_dual_mode_async 提取，
        控制器已开后台线程，此处同步执行，禁止再起线程）。"""
        frontend_proc, backend_proc = self._frontend_process, self._process
        self._frontend_process, self._process = None, None
        for proc, name in [(frontend_proc, '前端'), (backend_proc, '后端')]:
            if proc and proc.poll() is None:
                self.log_message(f'正在终止{name}进程树 (PID: {proc.pid})...')
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
                self.log_message(f'{name}进程已终止 (PID: {proc.pid})')
        self._stop_redis()
        self._kill_port_sync(_PORTS.api)
        self._kill_port_sync(_PORTS.web)
        self._mode = 'none'
        self._current_mode_key = ""
        self.log_message(f'{label}已停止，端口已释放')
        # 经消息泵回主线程反馈（组件线程不得直接触碰 Tk）
        self._msg_queue.put(('ui_update', {}))
        self._msg_queue.put(('toast', {'kind': 'info', 'title': f'{label}已停止', 'desc': '端口已释放'}))

    def _prod_restart_sync(self):
        """同步优雅重启生产（通用组件执行体用）。

        关键：nssm stop 必须等 STOPPED 确认后再 start，否则 AppExit Default Restart
        会把强杀误判为崩溃而自动重启，与新进程抢占 API 端口。
        （_wait_service_stopped 内部已含 nssm stop。）
        """
        for name in (_SVC_API, _SVC_ARQ):
            if not self._wait_service_stopped(name, timeout=45):
                raise RuntimeError(f'{name} 停止超时（STOP_PENDING 未确认），已中止重启')
        self._release_ports()
        for name in (_SVC_API, _SVC_ARQ):
            nssm = self._find_nssm()
            if nssm:
                subprocess.run(['nssm', 'start', name], executable=nssm, **_cap(30))
            else:
                subprocess.run(['sc', 'start', name], **_cap(30))
        if not self._wait_service_running(_SVC_API):
            raise RuntimeError('重启后未达 RUNNING，健康检查失败')
        self._msg_queue.put(('hosting_refresh', {}))

    def _prod_stop_sync(self):
        """同步停止生产服务（通用组件执行体用）：nssm stop ×2 → 等 STOPPED。"""
        for name in (_SVC_API, _SVC_ARQ):
            if not self._wait_service_stopped(name, timeout=45):
                raise RuntimeError(f'{name} 停止超时（STOP_PENDING 未确认）')
        self._msg_queue.put(('hosting_refresh', {}))

    def manual_refresh_all(self):
        self._refresh_hosting_status()
        self._update_all_ui()
        self.toast.show('info', '已刷新', '服务状态已重新收集')

    def toast_psutil_hint(self):
        self.toast.show('info', '安装 psutil', 'pip install psutil 并重启管理器后启用监控')

    # ===================== 告警路由 =====================

    def after_alert_change(self):
        if hasattr(self, 'alerts_page'):
            with contextlib.suppress(Exception):
                self.alerts_page.rebuild()
                self.alerts_page.refresh_badges()

    def confirm_alert(self, key):
        self.alerts.confirm(key=key)

    def confirm_all_alerts(self):
        n = self.alerts.unconfirmed_count()
        self.alerts.confirm(all_keys=True)
        if n:
            self.toast.show('success', '已确认全部告警', f'共 {n} 条')

    # ===================== 窗口 / 托盘（v5.33 保留） =====================

    def _fade_in(self):
        if REDUCE_MOTION:
            return
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
        self._shutting_down = True
        if self._mode != 'none':
            self._stop_process()
            self._mode = 'none'
        self._kill_tray()
        if self._sampler:
            self._sampler.stop()
        for aid in self._after_ids.values():
            with contextlib.suppress(Exception):
                self.root.after_cancel(aid)
        self._after_ids.clear()
        self._stop_animations(self.root)
        global _mutex_handle
        if _mutex_handle and _IS_WINDOWS:
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(_mutex_handle)
            except Exception:
                pass
            _mutex_handle = None
        # quit() 让 mainloop 立即返回；destroy 在个别子组件上可能抛
        # "can't delete Tcl command"（Tk 关闭期竞态），已无影响、容忍即可
        with contextlib.suppress(Exception):
            if hasattr(self, 'toast'):
                self.toast.cancel_all()
            self.root.quit()
        with contextlib.suppress(tk.TclError):
            self.root.destroy()

    def _kill_tray(self):
        if self._tray_icon:
            with contextlib.suppress(Exception):
                self._tray_icon.stop()
            self._tray_icon = None
            with contextlib.suppress(Exception):
                self.root.update()

    def on_closing(self):
        if self._tray_icon:
            self.root.withdraw()
        else:
            self._do_quit()


    # ===================== 日志（队列批量写入，主缓冲 + 过滤视图） =====================

    def setup_logging(self):
        log_dir = _PROJECT_DIR / 'logs'
        # 路径安全门：日志目录必须解析为项目内的绝对路径且不含 '..'（白名单校验）
        log_dir = log_dir.resolve()
        if '..' in log_dir.parts or not log_dir.is_absolute():
            log_dir = Path.cwd() / 'logs'
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
        page = getattr(self, 'logs_page', None)
        self.log_text.config(state=tk.NORMAL)
        for entry, level in buf:
            norm = level if level in ('INFO', 'WARNING', 'ERROR', 'SUCCESS') else 'INFO'
            self.log_text.insert(tk.END, entry, norm)
            if page:
                page.record(entry.rstrip('\n'), norm)
                page.append_line(entry.rstrip('\n'), norm)
        if page and page.auto_scroll:
            page.log_view.see(tk.END)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _schedule_log_flush(self):
        if self._log_buffer:
            self._flush_log_buffer()
        self._after_ids['flush'] = self.root.after(self.LOG_FLUSH_MS, self._schedule_log_flush)

    def clear_log(self):
        page = getattr(self, 'logs_page', None)
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete('1.0', tk.END)
        self.log_text.config(state=tk.DISABLED)
        if page:
            page.log_view.config(state=tk.NORMAL)
            page.log_view.delete('1.0', tk.END)
            page.log_view.config(state=tk.DISABLED)
            page._log_index.clear()
        self.log_message("日志已清空")

    def export_log(self):
        from tkinter import filedialog
        default_dir = (_PROJECT_DIR / 'logs').resolve()
        filename = filedialog.asksaveasfilename(initialdir=str(default_dir), initialfile=f"server_log_{datetime.now():%Y%m%d_%H%M%S}.txt", defaultextension=".txt", filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not filename:
            return
        # 路径安全门：导出目标必须为绝对路径、不含 '..'、父目录存在（路径穿越防护）
        target = Path(filename).resolve()
        if not target.is_absolute() or '..' in Path(filename).parts or not target.parent.is_dir():
            self.toast.show('error', '导出路径无效', '请选择有效的保存位置')
            self.log_message(f"导出路径无效: {filename}", 'ERROR')
            return
        try:
            with target.open('w', encoding='utf-8') as f:
                f.write(self.log_text.get('1.0', tk.END))
            self.log_message(f"日志已导出到: {target}")
            self.toast.show('success', '日志已导出', str(target))
        except Exception as e:
            self.log_message(f"导出日志失败: {str(e)}", 'ERROR')
            self.toast.show('error', '导出失败', str(e))

    def _schedule_log_cleanup(self):
        self._perform_log_cleanup()
        self._after_ids['cleanup'] = self.root.after(self.LOG_CLEANUP_MS, self._schedule_log_cleanup)

    def _perform_log_cleanup(self):
        page = getattr(self, 'logs_page', None)
        for text in ([self.log_text] + ([page.log_view] if page else [])):
            try:
                total = int(text.index('end-1c').split('.')[0])
                if total > self.MAX_LOG_LINES:
                    text.config(state=tk.NORMAL)
                    text.delete('1.0', f'{total - self.LOG_KEEP_LINES}.0')
                    text.config(state=tk.DISABLED)
            except (tk.TclError, ValueError):
                pass


    # ===================== 环境检查 / Redis（v5.33 保留） =====================

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
        """查找 Redis 可执行文件和配置文件（配置页显式路径优先）"""
        custom = str(_APP_CONFIG.get('redis_exe') or '')
        redis_exe = None
        if custom and Path(custom).is_file():
            redis_exe = custom
        if not redis_exe:
            redis_exe = next((str(p) for p in _REDIS_EXE_PATHS if p.is_file()), None)
        redis_conf = next((str(p) for p in _REDIS_CONF_PATHS if p.is_file()), None)
        return redis_exe, redis_conf

    def _is_redis_running(self):
        """检测 Redis 是否真正可用：TCP 连通 + 认证通过（RESP 协议 PING/AUTH）。

        仅做端口探测会误报（Redis 服务 Paused/停止或密码不匹配时端口探测仍可能
        短暂通过），故发送 PING：+PONG 为可用；-NOAUTH 需先用 .env 的
        REDIS_PASSWORD 认证后再 PING。
        """
        password = self._get_env_value('REDIS_PASSWORD')
        try:
            with socket.create_connection(('127.0.0.1', _PORTS.redis), timeout=1) as sock:
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

    def _start_redis(self):
        """启动 Redis 服务（阻塞，最长 ~7.5s；异步入口 start_redis_async）。"""
        if self._is_redis_running():
            self._msg_queue.put(('log', {'text': "Redis 已在运行"}))
            return True
        redis_exe, redis_conf = self._find_redis()
        if not redis_exe:
            self._msg_queue.put(('log', {'text': "Redis 未安装，请在配置管理页指定路径或安装 Redis for Windows", 'level': 'WARNING'}))
            return False
        try:
            common = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=False,
                          creationflags=_NO_WINDOW if _IS_WINDOWS else 0)
            redis_password = self._get_env_value('REDIS_PASSWORD')
            self._msg_queue.put(('log', {'text': f"正在启动 Redis: {redis_exe}"}))
            # argv[0] 字面量 + executable= 传入校验过的绝对路径（安全约定见文件头）
            if redis_conf and redis_password:
                self._redis_process = subprocess.Popen(['redis-server', redis_conf, '--requirepass', redis_password], executable=redis_exe, **common)
            elif redis_conf:
                self._redis_process = subprocess.Popen(['redis-server', redis_conf], executable=redis_exe, **common)
            elif redis_password:
                self._redis_process = subprocess.Popen(['redis-server', '--requirepass', redis_password], executable=redis_exe, **common)
            else:
                self._redis_process = subprocess.Popen(['redis-server'], executable=redis_exe, **common)
            threading.Thread(target=self._read_stdout, args=(self._redis_process,), daemon=True).start()
            for _ in range(15):
                time.sleep(0.5)
                if self._is_redis_running():
                    self._msg_queue.put(('log', {'text': f"Redis 启动成功 (PID: {self._redis_process.pid})"}))
                    return True
                if self._redis_process.poll() is not None:
                    self._msg_queue.put(('log', {'text': f"Redis 进程意外退出 (退出码: {self._redis_process.returncode})", 'level': 'ERROR'}))
                    return False
            self._msg_queue.put(('log', {'text': f"Redis 启动超时，请检查端口{_PORTS.redis}是否被占用", 'level': 'WARNING'}))
            return False
        except Exception as e:
            self._msg_queue.put(('log', {'text': f"Redis 启动失败: {str(e)}", 'level': 'ERROR'}))
            return False

    def _stop_redis(self):
        """停止 Redis 服务（阻塞；异步入口 stop_redis_async）。"""
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
            _kill_port_process(_PORTS.redis, self._msg_queue)
        if stopped:
            self._msg_queue.put(('log', {'text': "Redis 已停止"}))
        self._redis_process = None

    def start_redis_async(self):
        if self._redis_starting:
            return
        self._redis_starting = True
        self._update_all_ui()

        def _worker():
            ok = self._start_redis()
            self._redis_starting = False
            self._redis_running_cached = ok
            self._msg_queue.put(('ui_update', {}))
            self._msg_queue.put(('toast', {'kind': 'success' if ok else 'error',
                                           'title': 'Redis 已启动' if ok else 'Redis 启动失败',
                                           'desc': f'127.0.0.1:{_PORTS.redis}'}))
        threading.Thread(target=_worker, daemon=True).start()

    def stop_redis_async(self):
        def _worker():
            self._stop_redis()
            self._redis_running_cached = False
            self._msg_queue.put(('ui_update', {}))
            self._msg_queue.put(('toast', {'kind': 'info', 'title': 'Redis 已停止',
                                           'desc': f'端口 {_PORTS.redis} 已释放'}))
        threading.Thread(target=_worker, daemon=True).start()

    # ===================== 进程终止 / 端口清理（v5.33 保留） =====================

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
                            with contextlib.suppress(Exception):
                                _taskkill(cpid)
                        with contextlib.suppress(Exception):
                            proc.wait(timeout=3)
                        self._kill_port_sync(_PORTS.api)
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
                    self._kill_port_sync(_PORTS.api)
                except Exception as e:
                    self._msg_queue.put(('log', {'text': f"终止进程异常: {str(e)}", 'level': 'ERROR'}))
                    self._kill_port_sync(_PORTS.api)
                finally:
                    self._msg_queue.put(('ui_update', {}))
            threading.Thread(target=_kill_worker, daemon=True).start()
        else:
            self._msg_queue.put(('ui_update', {}))

    def _collect_process_tree(self, root_pid):
        pids = []
        try:
            result = subprocess.run(['wmic', 'process', 'where', f'(ParentProcessId={root_pid})', 'get', 'ProcessId'],
                                    **_cap(5))
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
            pids = self._find_port_pids(port)
            if not pids:
                return
            # 批量终止：psutil 直杀（秒级）；缺失时逐个 taskkill
            _taskkill_many(pids)
            time.sleep(0.5)

    def _find_port_pids(self, port):
        pids = set()
        try:
            output = subprocess.run(['netstat', '-ano'], **_cap(10))
            for line in output.stdout.splitlines():
                if 'LISTENING' not in line and 'TIME_WAIT' not in line:
                    continue
                parts = line.split()
                if len(parts) >= 5 and ':' in parts[1] and parts[1].rsplit(':', 1)[-1] == str(port) and parts[-1].isdigit() and int(parts[-1]) > 0:
                    pids.add(parts[-1])
        except Exception:
            pass
        return list(pids)

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

    # ===================== 开发模式（前后端 + Redis，v5.33 保留） =====================

    @staticmethod
    def _pick_log_font():
        """选择日志字体：优先 Microsoft YaHei Mono（等宽+CJK），回落 YaHei UI / NSimSun。"""
        candidates = ('Microsoft YaHei Mono', 'Microsoft YaHei UI', 'NSimSun', 'SimSun', 'Consolas')
        for fam in candidates:
            try:
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

    def start_dual_dev(self):
        self._start_dual_server('开发模式（前后端）')

    def stop_dual_dev(self):
        self._stop_dual_mode_async('dual_dev', '开发模式')

    def restart_dual_dev(self):
        self.log_message("正在重启开发模式...")
        threading.Thread(target=self._restart_dual_thread, daemon=True).start()

    def _start_dual_server(self, label):
        # 互斥守卫：开发模式正在启动/重启中则不操作
        if self._mode in ('starting', 'restarting'):
            self.log_message(f"开发模式正在启动/重启中，请稍候", 'WARNING')
            self.toast.show('warn', '操作被拒绝', '开发模式正在启动/重启中')
            return
        if self._mode != 'none':
            self.log_message(f"已有服务在运行，请先停止后再启动", 'WARNING')
            self.toast.show('warn', '操作被拒绝', '已有服务在运行，请先停止')
            return
        if not _PYTHON_EXE:
            self.log_message("无法启动: 未找到 Python 解释器，请安装 Python 并确保在 PATH 中", 'ERROR')
            messagebox.showerror("启动失败", "未找到可用的 Python 解释器！\n\n请安装 Python 3.12+ 并确保 python 在 PATH 中，\n或在项目目录下创建虚拟环境 (.venv313)")
            return
        if not _FRONTEND_DIR.exists():
            self.log_message(f"前端目录不存在: {_FRONTEND_DIR}", 'ERROR')
            messagebox.showerror("错误", f"前端目录不存在:\n{_FRONTEND_DIR}")
            return
        self._mode = 'starting'
        self._current_mode_key = 'dual_dev'
        self._startup_progress, self._startup_steps, self._startup_current_step = 0, ['停止生产模式', '检查Redis服务', '启动后端服务', '启动前端服务', '完成'], ''
        self._update_all_ui()
        self.log_message(f"正在启动{label}...")
        self.status_bar_label.config(text=f"正在启动{label}...")
        self.btn_loading_dev(True)
        # 互斥切换（停生产+清端口）含子进程调用，必须放后台线程，否则阻塞 Tk 主线程导致 GUI 卡死
        threading.Thread(target=self._start_dual_worker, args=(label,), daemon=True).start()

    def btn_loading_dev(self, loading):
        with contextlib.suppress(Exception):
            if loading:
                self.dual_dev_start_btn.set_loading(True, '启动中…')
            else:
                self.dual_dev_start_btn.set_loading(False, '启动开发模式')

    def _start_dual_worker(self, label):
        """后台执行互斥切换（停生产 + 清端口），随后复用现有启动流程"""
        try:
            self._msg_queue.put(('startup_progress', {'step': self._startup_steps[0], 'progress': 1, 'total': len(self._startup_steps)}))
            ok, reason, stopped_any = self._ensure_production_stopped()
            if not ok:
                self._msg_queue.put(('log', {'text': f"切换失败: {reason}", 'level': 'ERROR'}))
                self._msg_queue.put(('dual_failed', {'label': label, 'reason': reason}))
                return
            if stopped_any:
                self._msg_queue.put(('log', {'text': '已自动停止生产模式', 'level': 'INFO'}))
                self._msg_queue.put(('toast', {'kind': 'info', 'title': '已自动停止生产模式', 'desc': '开发/生产互斥托管'}))
            self._release_ports()
            self._start_dual_thread(label)
        except Exception as e:
            # 后台线程无 try/except 会静默终止，导致启动流程卡在 'starting' 且无任何日志
            self._msg_queue.put(('log', {'text': f"启动流程异常: {str(e)}", 'level': 'ERROR'}))
            self._msg_queue.put(('dual_failed', {'label': label, 'reason': str(e)}))

    def _start_dual_thread(self, label):
        try:
            self._msg_queue.put(('log', {'text': '正在清理端口...'}))
            self._kill_port_sync(_PORTS.api)
            self._kill_port_sync(_PORTS.web)
            self._startup_current_step, self._startup_progress = self._startup_steps[1], 2
            self._msg_queue.put(('startup_progress', {'step': self._startup_current_step, 'progress': self._startup_progress, 'total': len(self._startup_steps)}))
            if not self._start_redis():
                self._msg_queue.put(('log', {'text': '警告: Redis 未启动，部分功能可能不可用', 'level': 'WARNING'}))
            self._startup_current_step, self._startup_progress = self._startup_steps[2], 3
            self._msg_queue.put(('startup_progress', {'step': self._startup_current_step, 'progress': self._startup_progress, 'total': len(self._startup_steps)}))
            env = os.environ.copy()
            env.update({'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1', 'PYTHONPATH': str(_PROJECT_DIR)})
            # argv[0] 字面量 'python' + executable= 传入校验过的解释器绝对路径（安全约定见文件头）
            self._process = subprocess.Popen(
                ['python', '-u', '-m', 'uvicorn', 'fastapi_app.main:app', '--host', '0.0.0.0',
                 '--port', str(_PORTS.api), '--log-level', 'info', '--reload', '--reload-dir', 'fastapi_app'],
                executable=_PYTHON_EXE, cwd=str(_PROJECT_DIR), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=_NO_WINDOW if _IS_WINDOWS else 0, text=False)
            self._msg_queue.put(('log', {'text': f"后端进程已启动 (PID: {self._process.pid})"}))
            threading.Thread(target=self._read_stdout, args=(self._process,), daemon=True).start()
            backend_ready = False
            for _ in range(30):
                try:
                    urllib.request.urlopen(f'http://127.0.0.1:{_PORTS.api}/api/health', timeout=2)
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
            self._frontend_process = subprocess.Popen(
                [npm_cmd, 'run', 'dev', '--', '--port', str(_PORTS.web)], cwd=str(_FRONTEND_DIR),
                env={**os.environ, 'BACKEND_INTERNAL_URL': f'http://127.0.0.1:{_PORTS.api}'},
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=_NO_WINDOW if _IS_WINDOWS else 0, text=False)
            self._msg_queue.put(('log', {'text': f"前端进程已启动 (PID: {self._frontend_process.pid})"}))
            threading.Thread(target=self._read_frontend_stdout, args=(self._frontend_process,), daemon=True).start()
            frontend_ready = False
            for _ in range(60):
                try:
                    urllib.request.urlopen(f'http://127.0.0.1:{_PORTS.web}/', timeout=2)
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

    def _read_stdout(self, proc):
        try:
            if proc.stdout:
                try:
                    # 按行读取：读到 '\n' 即返回，避免阻塞凑块导致启动日志延迟显示
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

    def _stop_dual_mode_async(self, mode, label):
        self._msg_queue.put(('log', {'text': f"正在停止{label}..."}))

        def _stop_worker():
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
            self._kill_port_sync(_PORTS.api)
            self._kill_port_sync(_PORTS.web)
            self._mode = 'none'
            self._current_mode_key = ""
            self._msg_queue.put(('ui_update', {}))
            self._msg_queue.put(('log', {'text': f"{label}已停止，端口已释放"}))
            self._msg_queue.put(('toast', {'kind': 'info', 'title': f'{label}已停止', 'desc': '端口已释放'}))
        threading.Thread(target=_stop_worker, daemon=True).start()

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
        self._kill_port_sync(_PORTS.api)
        self._kill_port_sync(_PORTS.web)
        time.sleep(0.5)
        self._start_dual_thread(label)

    def _on_dual_started(self, label):
        self.btn_loading_dev(False)
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
        self.toast.show('success', f'{label}已启动', f'后端 :{_PORTS.api} · 前端 :{_PORTS.web}')
        self.log_message(f"{label}启动成功")
        self.log_message(f"  → 后端: http://localhost:{_PORTS.api}")
        self.log_message(f"  → 前端: http://localhost:{_PORTS.web}")

    def _on_dual_failed(self, label, reason):
        self.btn_loading_dev(False)
        self.log_message(f"{label}启动失败: {reason}", 'ERROR')
        self._mode, self._process, self._frontend_process = 'none', None, None
        self._current_mode_key = ""
        self._update_all_ui()
        self.status_bar_label.config(text=f"{label}启动失败: {reason}")
        self.toast.show('error', f'{label}启动失败', reason)
        self.alerts.raise_alert('dev_start_failed', 'error', '开发模式启动失败', reason)

    def stop_all(self):
        # 先在主线程立即重置状态（双重保险）
        self._mode = 'none'
        self._current_mode_key = ""
        self._update_all_ui()
        self.log_message("正在执行停止/重置操作...")
        self.status_bar_label.config(text="正在停止所有...")

        def _stop_all_worker():
            try:
                for proc, name in [(self._frontend_process, '前端'), (self._process, '后端')]:
                    if proc and proc.poll() is None:
                        self._msg_queue.put(('log', {'text': f'正在终止{name}进程 (PID: {proc.pid})...'}))
                        self._kill_process_tree(proc.pid)
                self._frontend_process = None
                self._process = None
                self._stop_redis()
                self._kill_residual_async()
                self._kill_port_sync(_PORTS.api)
                self._kill_port_sync(_PORTS.web)
                self._kill_port_sync(_PORTS.redis)
                self._msg_queue.put(('log', {'text': "已清理所有残留进程和端口"}))
                self._msg_queue.put(('ui_update', {}))
                self._msg_queue.put(('toast', {'kind': 'error', 'title': '已执行紧急停止', 'desc': f'已释放端口 {_PORTS.api}/{_PORTS.web}/{_PORTS.redis}'}))
            except Exception as e:
                self._msg_queue.put(('log', {'text': f"停止过程出错: {str(e)}", 'level': 'ERROR'}))
        threading.Thread(target=_stop_all_worker, daemon=True).start()

    def confirm_stop_all(self):
        if not messagebox.askyesno("紧急停止", "将终止全部开发/生产相关进程并释放端口。\n\n确定继续吗？"):
            return
        self.stop_all()

    def _kill_residual_async(self):
        def _kill_worker():
            if not _IS_WINDOWS:
                return
            if psutil is None:
                self._msg_queue.put(('log', {'text': "缺少psutil库，跳过残留进程清理", 'level': 'WARNING'}))
                return
            try:
                self._msg_queue.put(('log', {'text': "正在扫描残留进程..."}))
                pids_to_kill = [p.pid for p in psutil.process_iter(['pid', 'name', 'cmdline'])
                                if p.pid != os.getpid() and ('python' in (p.info['name'] or '').lower()
                                or 'uvicorn' in ' '.join(p.info['cmdline'] or []).lower()
                                or 'next' in ' '.join(p.info['cmdline'] or []).lower()
                                or 'node' in (p.info['name'] or '').lower())]
                if pids_to_kill:
                    self._msg_queue.put(('log', {'text': f"发现 {len(pids_to_kill)} 个残留进程，正在终止..."}))
                    for pid in pids_to_kill:
                        with contextlib.suppress(Exception):
                            _taskkill(pid)
            except Exception as e:
                self._msg_queue.put(('log', {'text': f"清理残留进程出错: {e}", 'level': 'WARNING'}))
        threading.Thread(target=_kill_worker, daemon=True).start()

    # ===================== 消息泵 / 状态轮询 =====================

    def _poll_queue(self):
        if getattr(self, '_shutting_down', False):
            return
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
                    self._on_dual_started(data['label'])
                elif msg_type == 'dual_started':
                    self._on_dual_started(data['label'])
                elif msg_type == 'dual_failed':
                    self._on_dual_failed(data['label'], data.get('reason', ''))
                elif msg_type == 'ui_update':
                    self._update_all_ui()
                elif msg_type == 'status':
                    self.status_bar_label.config(text=data['text'])
                elif msg_type == 'startup_progress':
                    self.status_bar_label.config(text=f"启动中: {data.get('step', '')} ({data.get('progress', 0)}/{data.get('total', 5)})")
                    self._startup_current_step, self._startup_progress = data.get('step', ''), data.get('progress', 0)
                elif msg_type == 'hosting_refresh':
                    try:
                        pending = self._after_ids.pop('hosting', None)
                        if pending:
                            self.root.after_cancel(pending)
                    except Exception:
                        pass
                    self._refresh_hosting_status()
                elif msg_type == 'hosting_apply':
                    self._apply_hosting_data(data['data'])
                elif msg_type == 'metric':
                    self._handle_metric(data)
                elif msg_type == 'toast':
                    self.toast.show(data.get('kind', 'info'), data.get('title', ''), data.get('desc', ''))
            except Exception:
                # 单条消息处理失败不能中断 poll 调度链，否则日志/状态更新全部停摆
                pass
            processed += 1
        self._after_ids['poll'] = self.root.after(200, self._poll_queue)

    def _handle_metric(self, data):
        with contextlib.suppress(Exception):
            if data.get('unavailable'):
                self.overview_page.set_proc_snapshot(None)
                return
            self.overview_page.push_metrics(data)
            if 'procs' in data:
                self.overview_page.set_proc_snapshot(data['procs'])

    def check_server_status(self):
        if getattr(self, '_shutting_down', False):
            return
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
            self.alerts.raise_alert('dev_crash', 'error', f'{label or "开发模式"}意外终止',
                                    f'退出码: {code}，请查看日志中心排查')
            if self._frontend_process and self._frontend_process.poll() is None:
                self._kill_process_tree(self._frontend_process.pid)
            if self._process and self._process.poll() is None:
                self._kill_process_tree(self._process.pid)
            self._mode, self._process, self._frontend_process = 'none', None, None
            self._current_mode_key = ""
            self._update_all_ui()
            self._after_ids['crash_warn'] = self.root.after(100, lambda: messagebox.showwarning("警告", f"{label}意外停止，请检查日志"))
        self._after_ids['status'] = self.root.after(self._check_interval, self.check_server_status)

    def _mode_label(self):
        return {'dual_dev': '开发模式', 'restarting': '重启中', 'starting': '启动中', 'stopping': '停止中'}.get(self._mode, '')

    def _update_all_ui(self):
        if not hasattr(self, 'services_page'):
            return
        with contextlib.suppress(Exception):
            self.services_page.sync()
            self.overview_page.sync_stats()
            # 通用一键操作组件：开发/生产『重启/关闭』按钮可用性 + loading
            for grp in (getattr(self, 'dev_actions', None), getattr(self, 'prod_actions', None)):
                if grp is not None:
                    grp.sync()
        self._update_mode_badge()
        with contextlib.suppress(Exception):
            self.stop_all_btn.config(state='normal')
        if self._mode == 'none':
            self.status_bar_label.config(text="就绪")
        elif self._mode in ('restarting', 'starting', 'stopping'):
            self.status_bar_label.config(text=f"{self._mode_label()}...")

    def _update_mode_badge(self):
        """全局模式徽章（TopBar + StatusBar）：未运行 / 开发 / 生产（含过渡态）。"""
        try:
            if self._mode == 'starting':
                state, text = 'deploying', '开发模式 · 启动中'
            elif self._mode in ('restarting', 'stopping'):
                state, text = 'restarting', f'开发模式 · {self._mode_label()}'
            elif self._mode == 'dual_dev':
                state, text = 'running', '开发模式'
            elif getattr(self, '_prod_running', False):
                state, text = 'running', '生产模式'
            else:
                state, text = 'stopped', '未运行'
            for badge in (self.topbar.mode_badge, self.statusbar.mode_badge):
                if state == 'running' and text == '生产模式':
                    badge.set_state(state, text, color_key='accent', tint_key='accent_tint')
                else:
                    badge.set_state(state, text)
        except Exception:
            pass


    # ===================== 生产模式 (Windows 服务 + NSSM，v5.33 保留) =====================
    # 安全约定：nssm 调用一律字面量列表 + executable=<校验过的 nssm.exe 绝对路径>

    def _find_nssm(self):
        custom = str(_APP_CONFIG.get('nssm_path') or '')
        if custom and Path(custom).is_file() and Path(custom).suffix.lower() == '.exe':
            return custom
        found = shutil.which('nssm')
        if found:
            return found
        for cand in _NSSM_CANDIDATES:
            if cand.is_file():
                return str(cand)
        return None

    def _svc_state(self, name):
        try:
            r = subprocess.run(['sc', 'query', name], **_cap(5))
            out, code = (r.stdout or '') + (r.stderr or ''), r.returncode
        except Exception:
            return '未知'
        if code != 0 or 'SERVICE_NAME' not in out:
            return '未安装'
        for line in out.splitlines():
            if 'STATE' in line:
                parts = line.split(':', 1)
                if len(parts) > 1:
                    return ' '.join(parts[1].split())[:28]
        return '未知'

    def _svc_pid(self, name):
        """查询 Windows 服务当前进程 PID（sc queryex），未运行返回 None"""
        try:
            r = subprocess.run(['sc', 'queryex', name], **_cap(5))
        except Exception:
            return None
        for line in (r.stdout or '').splitlines():
            stripped = line.strip()
            if stripped.startswith('PID'):
                parts = stripped.split(':', 1)
                if len(parts) > 1 and parts[1].strip().isdigit():
                    return int(parts[1].strip())
        return None

    def _detect_service_deps(self):
        """扫描本机 PostgreSQL / Redis 服务名，作为 erp 服务的启动依赖。

        SERVICE_DEPENDS_ON 环境变量可显式覆盖（逗号/分号分隔服务名）。
        经 wmic 输出在 Python 侧过滤；扫描不到时返回空列表。
        只读副本（replica）与手动/禁用实例不纳入依赖。
        """
        custom = os.getenv('SERVICE_DEPENDS_ON', '').strip()
        if custom:
            return [s.strip() for s in custom.replace(';', ',').split(',') if s.strip()]
        try:
            r = subprocess.run(['wmic', 'service', 'get', 'Name,StartMode,State'], **_cap(30))
            out = r.stdout or ''
        except Exception:
            return []
        deps = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            state, mode = parts[-1], parts[-2]
            name = ' '.join(parts[:-2])
            if mode == 'Auto' and state == 'Running' and _SERVICE_DEP_PATTERN.search(name) \
                    and 'replica' not in name.lower():
                deps.append(name)
        return deps

    def _wait_service_stopped(self, name, timeout=45):
        """发出 nssm stop 后轮询服务状态直到 STOPPED；超时返回 False。

        若在 STOP_PENDING 期间强杀被管进程，会被 AppExit Default Restart
        判定为崩溃而自动重启，与目标模式抢占端口，必须等待确认 STOPPED。
        """
        nssm = self._find_nssm()
        if nssm:
            with contextlib.suppress(Exception):
                subprocess.run(['nssm', 'stop', name], executable=nssm, **_cap(15))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self._svc_state(name)
            if 'STOPPED' in state:
                return True
            time.sleep(1)
        return False

    def _wait_service_running(self, name, timeout=60):
        """nssm start 后轮询服务至 RUNNING，并探测 /api/health 确认业务就绪。

        与 _wait_service_stopped 配对，用于生产模式『一键启动/重启』的就绪确认。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self._svc_state(name)
            if 'RUNNING' in state:
                try:
                    urllib.request.urlopen(f'http://127.0.0.1:{_PORTS.api}/api/health', timeout=2)
                    return True
                except Exception:
                    time.sleep(1)
                    continue
            time.sleep(1)
        return False

    def _ensure_production_stopped(self):
        """切换前停止生产模式：停 NSSM 服务 + 清残留 prod_runner 进程树。

        返回 (ok, fail_reason, stopped_any)：ok=True 且曾停止过生产则由调用方提示。
        手动启动的 prod_runner 不受 NSSM 控制，需按命令行特征扫描清理。
        """
        stopped_any = False
        for name in (_SVC_API, _SVC_ARQ):
            state = self._svc_state(name)
            if 'STOPPED' in state or '未安装' in state:
                continue
            self._msg_queue.put(('log', {'text': f'正在停止生产服务 {name}...'}))
            if not self._wait_service_stopped(name):
                return False, f'{name} 停止超时（STOP_PENDING 未确认），已中止切换', False
            stopped_any = True
        # 清理手动启动的残留 prod_runner 进程树（不受 NSSM 控制）
        if psutil is not None:
            for p in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    pid = p.info['pid']
                    if not pid or pid == os.getpid():
                        continue
                    if 'prod_runner' in ' '.join(p.info['cmdline'] or []):
                        self._kill_process_tree(pid)
                        self._msg_queue.put(('log', {'text': f'已清理残留 prod_runner 进程 (PID: {pid})'}))
                        stopped_any = True
                except Exception:
                    continue
        return True, None, stopped_any

    def _ensure_development_stopped(self):
        """切换前停止开发模式：只停开发子进程，不动 Redis，重置 GUI 状态。"""
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
        """清理 API 与 WEB 端口占用（复用 _kill_port_sync，多 PID 有 3 轮重试）。"""
        self._kill_port_sync(_PORTS.api)
        self._kill_port_sync(_PORTS.web)

    def _manual_refresh_hosting(self):
        """手动刷新生产模式状态（后台收集 + 主线程应用，不阻塞 UI）"""
        self._refresh_hosting_status()
        self.log_message('已手动刷新生产模式状态')

    def _refresh_hosting_status(self):
        """调度后台线程收集生产模式状态，经消息队列回主线程应用。

        sc query / 状态文件 IO / Redis 探测均为阻塞操作，绝不能在 Tk 主线程执行。
        收集期间重复调用只标记待刷新。
        """
        if getattr(self, '_shutting_down', False):
            return
        if getattr(self, '_hosting_collecting', False):
            self._hosting_refresh_requested = True
            return
        self._hosting_collecting = True

        def _collect():
            try:
                data = self._collect_hosting_data()
            except Exception:
                data = {'collect_error': True}
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
        data['arq_running'] = 'RUNNING' in data['arq_state'].upper() if data['arq_state'] else False
        data['redis_ok'] = self._is_redis_running()
        status_file = _PROD_STATUS_FILE
        data['status'], data['read_err'], data['mtime'], data['stale'], data['mtime_str'] = {}, None, 0, False, '—'
        if not data['api_running']:
            return data
        try:
            if status_file.is_file():
                data['status'] = json.loads(status_file.read_text(encoding='utf-8'))
            else:
                data['read_err'] = f'文件不存在: {status_file}'
        except Exception as e:
            data['read_err'] = f'读取失败: {type(e).__name__}: {e}'
        mtime = status_file.stat().st_mtime if status_file.is_file() else 0
        data['mtime'] = mtime
        data['stale'] = bool(status_file.is_file()) and (time.time() - mtime) > 15
        data['mtime_str'] = datetime.fromtimestamp(mtime).strftime('%H:%M:%S') if mtime else '—'
        # ARQ 由独立 NSSM 服务托管时（--no-arq），从 erp-arq 服务查询真实 PID
        if data['status'].get('services', {}).get('arq', {}).get('status') == 'external':
            data['arq_svc_pid'] = self._svc_pid(_SVC_ARQ)
        else:
            data['arq_svc_pid'] = None
        return data

    def _apply_hosting_data(self, data):
        """主线程应用收集到的生产模式状态（仅 UI 更新 + 告警，无阻塞 IO）"""
        try:
            self._prod_running = data.get('api_running', False)
            self._last_hosting = data
            if not data.get('collect_error'):
                with contextlib.suppress(Exception):
                    self.services_page.apply_hosting(data)
                self._redis_running_cached = data.get('redis_ok')
                with contextlib.suppress(Exception):
                    self.topbar.set_redis_lamp(bool(data.get('redis_ok')))
                    self.statusbar.set_heartbeat(data.get('mtime_str') or datetime.now().strftime('%H:%M:%S'))
                # 告警：生产运行但健康度异常（去重由 AlertEngine 冷却机制保证）
                if data.get('api_running'):
                    if data.get('stale'):
                        self.alerts.raise_alert('prod_stale', 'warn', '生产状态数据过期',
                                                f'logs\\{_PROD_STATUS_FILE_NAME} 超过 15s 未更新')
                    status = data.get('status') or {}
                    if status and not status.get('ready'):
                        self.alerts.raise_alert('prod_not_ready', 'warn', '生产服务未就绪',
                                                'erp-prod 运行中但 ready=False，请查看服务日志')
                    if not data.get('redis_ok'):
                        self.alerts.raise_alert('redis_down_prod', 'warn', 'Redis 不可用（生产运行中）',
                                                '生产后端依赖 Redis，当前 PING 失败')
            self._update_all_ui()
        finally:
            self._hosting_collecting = False
            # 收集期间有刷新请求 → 立即补一轮；否则按 5s 周期继续
            if getattr(self, '_shutting_down', False):
                return
            delay = 50 if self._hosting_refresh_requested else 5000
            self._hosting_refresh_requested = False
            self._after_ids['hosting'] = self.root.after(delay, self._refresh_hosting_status)

    def _nssm_install(self, name, app, params, env_extra):
        nssm = self._find_nssm()
        if not nssm:
            self.log_message(f'{name} 注册失败: 未找到 NSSM', 'ERROR')
            return False
        # Step 1: 创建服务（仅注册应用路径，不传参数，避免 NSSM 弹 GUI）
        try:
            r = subprocess.run(['nssm', 'install', name, app], executable=nssm, **_cap(30))
            code, out = r.returncode, (r.stdout or '') + (r.stderr or '')
        except Exception as e:
            code, out = -1, str(e)
        if code != 0:
            self.log_message(f'{name} 注册失败: {out}', 'ERROR')
            return False
        # Step 2: 设置启动参数（NSSM AppParameters 接受空格分隔的完整命令行）
        if params:
            with contextlib.suppress(Exception):
                subprocess.run(['nssm', 'set', name, 'AppParameters', ' '.join(params)], executable=nssm, **_cap(15))
        # Step 3: 设置其他属性
        settings = [
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
            with contextlib.suppress(Exception):
                subprocess.run(['nssm', 'set', name, key, val], executable=nssm, **_cap(15))
        # Step 4: 服务依赖——开机时 PG/Redis 先启动到达 RUNNING，再拉起 erp 服务，
        # 避免数据库慢启动导致后端健康检查失败、监督器退避重启（开机重启风暴）
        deps = self._detect_service_deps()
        if deps:
            with contextlib.suppress(Exception):
                subprocess.run(['nssm', 'set', name, 'DependOnService', ' '.join(deps)], executable=nssm, **_cap(15))
            self.log_message(f'{name} 已设置启动依赖: {", ".join(deps)}')
        else:
            self.log_message(f'{name} 未探测到本机 PostgreSQL/Redis 服务，跳过启动依赖'
                             '（如需指定可设置 SERVICE_DEPENDS_ON 环境变量后重装）', 'WARNING')
        self.log_message(f'{name} 已注册为 Windows 服务（开机自启 + 崩溃自动重启）')
        return True

    def _install_services(self):
        if self._mode not in ('none',):
            self.log_message('请先停止当前手动运行的服务，再安装 Windows 服务', 'WARNING')
            messagebox.showwarning('提示', '请先停止当前运行中的服务（开发/手动生产/调试），再安装 Windows 服务。')
            return
        nssm = self._find_nssm()
        if not nssm:
            self.log_message('未找到 NSSM，请在配置管理页指定路径或下载 https://nssm.cc 解压到 C:\\nssm\\nssm.exe', 'ERROR')
            messagebox.showerror('缺少 NSSM', '未找到 NSSM。\n请从 https://nssm.cc/download 下载并解压到 C:\\nssm\\nssm.exe，\n或在配置管理页指定 nssm.exe 路径。')
            return
        if not _PYTHON_EXE:
            messagebox.showerror('缺少 Python', '未找到 Python 解释器，无法安装服务。')
            return
        workers = self.hosting_workers_var.get().strip() or '4'
        env_extra = ('APP_ENV=production FASTAPI_DEBUG=false PYTHONPATH=' + str(_PROJECT_DIR) +
                     ' PYTHONUTF8=1 PYTHONUNBUFFERED=1 UVICORN_WORKERS=' + workers)

        def _worker():
            self.log_message(f'正在安装生产服务 (worker={workers})...')
            # erp-prod 监督器 --no-arq：ARQ 由独立 erp-arq 服务托管，避免双跑定时任务
            ok1 = self._nssm_install(_SVC_API, _PYTHON_EXE, ['-m', 'fastapi_app.core.prod_runner', '--no-arq'], env_extra)
            ok2 = self._nssm_install(_SVC_ARQ, _PYTHON_EXE, ['-m', 'arq', 'fastapi_app.core.arq_app.WorkerSettings'], env_extra)
            if ok1 and ok2:
                self._msg_queue.put(('log', {'text': '生产服务安装完成：erp-prod + erp-arq（开机自启）'}))
                self._msg_queue.put(('toast', {'kind': 'success', 'title': '生产服务安装完成', 'desc': 'erp-prod + erp-arq · 开机自启'}))
            else:
                self._msg_queue.put(('log', {'text': '生产服务安装未完全成功，请查看上方日志', 'level': 'WARNING'}))
            self._msg_queue.put(('hosting_refresh', {}))
        threading.Thread(target=_worker, daemon=True).start()

    def _service_cmd_sync(self, verb):
        nssm = self._find_nssm()
        for name in (_SVC_API, _SVC_ARQ):
            try:
                if nssm:
                    subprocess.run(['nssm', verb, name], executable=nssm, **_cap(30))
                else:
                    subprocess.run(['sc', verb, name], **_cap(30))
            except Exception:
                pass
            self.log_message(f'{name} {verb} 已执行')
        self._msg_queue.put(('hosting_refresh', {}))

    def _service_cmd(self, verb):
        threading.Thread(target=self._service_cmd_sync, args=(verb,), daemon=True).start()

    def _start_services(self):
        # 互斥守卫：开发模式正在启动/重启中则拒绝（防 TOCTOU 双后端抢 API 端口）
        if self._mode in ('starting', 'restarting'):
            self.log_message('开发模式正在启动中，请稍候', 'WARNING')
            self.toast.show('warn', '操作被拒绝', '开发模式正在启动中')
            return

        def _worker():
            # 互斥切换：停开发模式 + 清端口（含进程树终止等阻塞操作，放后台线程避免卡死 UI）
            if self._ensure_development_stopped():
                self._msg_queue.put(('log', {'text': '已自动停止开发模式', 'level': 'INFO'}))
                self._msg_queue.put(('toast', {'kind': 'info', 'title': '已自动停止开发模式', 'desc': '开发/生产互斥托管'}))
            self._release_ports()
            self._service_cmd_sync('start')
        threading.Thread(target=_worker, daemon=True).start()

    def _stop_services(self):
        self._service_cmd('stop')

    def _restart_services(self):
        self._service_cmd('restart')

    def _uninstall_services(self):
        nssm = self._find_nssm()
        if not nssm:
            messagebox.showerror('缺少 NSSM', '未找到 NSSM，无法卸载服务。')
            return

        def _worker():
            for name in (_SVC_API, _SVC_ARQ):
                with contextlib.suppress(Exception):
                    subprocess.run(['nssm', 'stop', name], executable=nssm, **_cap(30))
                try:
                    r = subprocess.run(['nssm', 'remove', name, 'confirm'], executable=nssm, **_cap(30))
                    code, out = r.returncode, (r.stdout or '') + (r.stderr or '')
                except Exception as e:
                    code, out = -1, str(e)
                if code == 0:
                    self.log_message(f'{name} 已卸载')
                else:
                    self.log_message(f'{name} 卸载失败: {out}', 'WARNING')
            self._msg_queue.put(('toast', {'kind': 'info', 'title': '服务已卸载', 'desc': 'erp-prod + erp-arq'}))
            self._msg_queue.put(('hosting_refresh', {}))
        threading.Thread(target=_worker, daemon=True).start()

    def _open_logs_dir(self):
        log_dir = _PROJECT_DIR / 'logs'
        log_dir.mkdir(exist_ok=True)
        try:
            os.startfile(str(log_dir))
        except Exception as e:
            self.log_message(f'打开日志目录失败: {e}', 'ERROR')


def main():
    _enable_dpi_awareness()
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
        crash_dir = (_PROJECT_DIR / 'logs').resolve()
        if '..' in crash_dir.parts or not crash_dir.is_absolute():
            crash_dir = Path.cwd() / 'logs'
        crash_file = None
        try:
            crash_dir.mkdir(exist_ok=True)
            crash_file = crash_dir / f'server_manager_crash_{datetime.now():%Y%m%d_%H%M%S}.log'
            crash_file.write_text(f"[CRASH] {datetime.now()}\n{tb_text}", encoding='utf-8')
        except Exception:
            pass
        with contextlib.suppress(Exception):
            messagebox.showerror("启动失败", f"服务器管理器启动失败:\n{str(e)}" + (f"\n\n日志: {crash_file}" if crash_file else ""))
        sys.exit(1)


if __name__ == '__main__':
    main()








