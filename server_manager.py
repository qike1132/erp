"""
ERP 服务器管理器 GUI —— 单文件 Tkinter 极简控制器。
(版本随 _VERSION; 代码审查发现的问题以「审查 #N」标注, 详见
.workbuddy/artifacts/服务器管理器v5.39代码审查报告-2026-09-11.md)

v5.40 变更(2026-09-11 全量审查修复):
  - 🔴#1  sc 状态判定只认 rc==1060(或无 STATE 行的 1060 错误文本), 根除 PID=1060 误判「未安装」
  - 🔴#2  开发启动兜底 except 先 abort 已起进程再置空句柄, 杜绝后端孤儿
  - 🔴#3  配置标量键(max_log_lines 等)统一归一化, 配置写坏不再炸启动
  - 🟡    _taskkill_many 补树语义 / 残留清理加项目标记校验 / 端口释放统一留痕 /
          共享状态改经 state_set 消息(线程契约) / 接管 Tk 回调异常 / 前端日志真批量 /
          SUCCESS 日志级别 / .env 引号剥离 / 历史日志 30 天轮转 / 删除 wmic 死代码

四件事: ① 一键启动开发模式(Redis+uvicorn+Vite) ② 一键启动生产模式(NSSM erp-prod/erp-arq)
③ 双模式互斥 ④ 一键紧急停止(分级: 单击=停止当前模式(含生产服务)+释放 5002/3000，Redis 服务保持运行;
长按≥1.5s=在轻量基础上接管 Redis 服务 + 残留清理 + 释放 6379)
另有日志集成: 启动/停止/运行状态/错误四类事件，落盘 + UI 实时展示。

Redis 生命周期(v5.37 归管理器负责): 生产监督器 prod_runner 明确不管理 Redis
(其注释原话「仅检查连通，预期为独立 Windows 服务，不拉起」)，故缓存 erp-redis / broker
erp-redis-broker 两个 Windows 服务由本管理器经 sc start/stop 托管；管理器自有的
redis-server.exe 进程方案仅在「配置里所有 Redis 服务都【明确未安装】」时作为回落保留。
服务状态语义(v5.37 关键): 只有 sc 返回 1060 才判「未安装」；其它查询失败一律判「未知」，
且「未知」按运行中保守处理 —— 绝不把「查不出来」当成「不存在」。该三态语义已贯通到
展示层: 点位显示「状态未知」而非「已停止」，全局徽章显示「生产模式 · 状态未知」而非「未运行」。

安全约定(项目静态扫描门禁): 所有 subprocess 的 argv[0] 均为字符串字面量
(python/npm.cmd/nssm/sc/taskkill/netstat/wmic/redis-server)，运行时解析的绝对路径一律经
executable= 传入；禁止 shell=True，禁止把变量拼进命令字符串。

中文 Windows 关键坑: sc/nssm/netstat/wmic 输出为 OEM 代码页(GBK)，PYTHONUTF8=1 下按 UTF-8
解码会抛异常导致 stdout 丢失、中文服务名被误判「未安装」——统一走 _cap()→encoding='oem'。

线程模型: Tk 组件绝不跨线程触碰。后台线程只向 _msg_queue 投递消息，主线程 _poll_queue()
每 200ms 消费(单条异常必须吞掉，否则调度链断裂、日志与状态全停摆)。
"""
import contextlib
import hashlib
import json
import locale
import logging
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Optional
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk
_VERSION = 'v5.40'
_WINDOW_TITLE = 'ERP 服务器管理器'
_IS_WINDOWS = sys.platform == 'win32'
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0
# 健康探针必须直连本机，绝不走系统代理。
# 根因(2026-09-10 实证): 本机设置了 HTTP_PROXY/HTTPS_PROXY=127.0.0.1:57562(代理客户端)
# 且无 NO_PROXY，urllib 默认会读取系统代理——包括 Windows 注册表代理设置——导致
# 探测 127.0.0.1:5002/3000 的请求被路由进代理。代理客户端抖动时健康检查间歇性失败:
# prod_runner 触发「连续失败 20s → 强制重启」的后端重启风暴(应用本身完全正常，
# 被杀前 0 秒间隔、业务日志连续)；管理器的启动就绪判定同样会被误导。
# ProxyHandler({}) 显式清空代理，保证探针永远直连。
_OPENER_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_DEFAULT_API_PORT, _DEFAULT_WEB_PORT, _DEFAULT_REDIS_PORT = 5002, 3000, 6379
_REDIS_EXE_PATHS = [Path(r'C:\Redis\redis-server.exe'), Path(r'C:\Program Files\Redis\redis-server.exe')]
_REDIS_CONF_PATHS = [Path(r'C:\Redis\redis.windows.conf'), Path(r'C:\Redis\redis.conf')]
_SVC_API, _SVC_ARQ = 'erp-prod', 'erp-arq'
# 由管理器托管的 Redis Windows 服务(缓存 6379 + broker/result 6380)。
# 说明: rediserp 是陈旧注册(net start 显示在运行但无对应进程)，刻意不纳入本列表。
_DEFAULT_REDIS_SERVICES = ['erp-redis', 'erp-redis-broker']
_NSSM_CANDIDATES = [Path(r'C:\nssm\nssm.exe'), Path(r'C:\Program Files\nssm\nssm.exe'),
                    Path(r'C:\Program Files (x86)\nssm\nssm.exe'), Path(r'C:\tools\nssm\nssm.exe')]
_PROD_STATUS_FILE_NAME = 'prod_runner.json'
_CONFIG_FILE_NAME = 'server_manager_config.json'
_NPM_CMD = 'npm.cmd' if _IS_WINDOWS else 'npm'
# psutil 可选依赖: 残留进程扫描/批量终止必需; 缺失时优雅降级(记 WARNING，不做宽特征兜底)
try:
    import psutil
except ImportError:
    psutil = None
# 语义色(业务态不得用装饰色)
_C = {'bg': '#F5F7FA', 'card': '#FFFFFF', 'border': '#E5E6EB', 'text': '#1D2129', 'muted': '#86909C',
      'green': '#00A870', 'gray': '#86909C', 'red': '#D54941', 'orange': '#FF8800', 'blue': '#1668DC'}
_DOT_COLOR = {'running': _C['green'], 'stopped': _C['gray'], 'error': _C['red'],
              'starting': _C['orange'], 'not_installed': _C['gray'], 'unknown': _C['gray']}
# 点位状态后缀文案(v5.37/D12): 「未知」必须显式标为「状态未知」，绝不能落成「已停止」
_DOT_TEXT = {'running': '运行中', 'stopped': '已停止', 'starting': '启动中',
             'not_installed': '未安装', 'unknown': '状态未知'}
# 状态枚举 → (文案, 颜色)
_STATUS_META = {'running': ('运行中', _C['green']), 'stopped': ('已停止', _C['gray']),
                'error': ('异常', _C['red']), 'switching': ('切换中', _C['orange']),
                'deploying': ('启动中', _C['orange']), 'not_installed': ('未安装', _C['gray']),
                'unknown': ('状态未知', _C['gray'])}

# ===================== v5.33 视觉表现层恢复（2026-09-16） =====================
# 背景: 用户要求恢复 v5.33 的圆角按钮 + 微交互动画 + Apple/iOS 配色。
# 规格来源: backups/version-prune-20260916/ERP服务器管理器_v5.33.exe.ORG-BEFORE-REPACK
#           （v5.33 源码已不存在，仅存编译产物 → 经 pyinstxtractor-ng 解包 +
#            marshal 反序列化 + dis 反汇编逐指令提取，见 _v533_ui_spec.txt）。
# ★ 恢复原则: 只恢复「表现层」，不改变任何业务逻辑与状态机语义；
#   _C 保留（业务代码仍引用其语义键），_PALETTE 为 v5.33 视觉层新增的独立色板。

# v5.33 原始色板（19 色，iOS/Apple 系统色系）
_V533_COLORS = {
    'accent': '#007aff', 'accent_hover': '#0064d1',
    'accent_tint': '#e8f1ff', 'accent_tint_h': '#d5e8ff', 'accent_border': '#c8dcfb',
    'success': '#34c759', 'success_hover': '#2ba847',
    'success_tint': '#e6f9ec', 'success_tint_h': '#d3f3dc', 'success_border': '#bbe6c5',
    'danger': '#ff3b30', 'danger_hover': '#d92d22',
    'danger_tint': '#ffece9', 'danger_tint_h': '#ffdad3', 'danger_border': '#f5b8b1',
    'white': '#ffffff', 'bg_input': '#f2f2f7', 'ring': '#e5e5ea', 'text_primary': '#1d1d1f',
    # warning 系（v5.33 过渡态橙，用于启动中/切换中徽章与 WARNING 日志级别）
    'warning': '#ff9500', 'warning_hover': '#d97e00',
    'warning_tint': '#fff4e5', 'warning_border': '#ffdcb0',
    # ★ 以下色值全部为【运行时像素实测校正】，来源:
    #   .workbuddy/artifacts/v533-ui-restore/ui-ref-v533-original.png
    #   （启动备份中的原始 v5.33 exe，1096×799 客户区截屏，按区域取色值众数）
    #   字节码里的 #f2f2f7 / #e5e5ea 实为「输入框底 / 分隔线」用色，与页面底色不同，
    #   仅凭常量表会得出错误结论 —— 故以实测像素为准。
    'page_bg': '#f5f5f7',            # 页面底色（实测）—— 非 #f2f2f7
    'text_dim': '#6e6e73',           # 次级文字（实测）
    'bg': '#f5f5f7', 'bg_card': '#ffffff',
    'border_card': '#e3e3e6',        # 卡片描边（实测）
    'log_surface': '#f9f9fb',        # 日志区底（实测）
    # 按钮语义色（实测校准）
    #   开发模式「启动」= 绿实心；生产模式「启动服务」= 蓝实心；
    #   「停止/卸载」= 白底 + 红描边；「重启」= 白底 + 蓝描边。
    'green_disabled': '#a8e0b8',     # 绿按钮禁用底
    'btn_secondary_bg': '#ffffff', 'btn_secondary_border': '#d2d2d7',
    'disabled_bg': '#f2f2f7', 'disabled_fg': '#adadb1',
}
# 语义映射到 _C 键的别名（供业务代码按需取 v5.33 视觉值）
_PALETTE = {
    'bg': _V533_COLORS['bg'], 'bg_card': _V533_COLORS['bg_card'],
    'border_card': _V533_COLORS['border_card'],
    'text_primary': _V533_COLORS['text_primary'], 'text_dim': _V533_COLORS['text_dim'],
    'accent': _V533_COLORS['accent'], 'accent_hover': _V533_COLORS['accent_hover'],
    'accent_h': _V533_COLORS['accent_hover'],   # v5.33 脉冲动画用键名（原样保留）
    'accent_tint': _V533_COLORS['accent_tint'], 'accent_tint_h': _V533_COLORS['accent_tint_h'],
    'success': _V533_COLORS['success'], 'success_hover': _V533_COLORS['success_hover'],
    'success_tint': _V533_COLORS['success_tint'], 'success_tint_h': _V533_COLORS['success_tint_h'],
    'danger': _V533_COLORS['danger'], 'danger_hover': _V533_COLORS['danger_hover'],
    'danger_tint': _V533_COLORS['danger_tint'], 'danger_tint_h': _V533_COLORS['danger_tint_h'],
    'warning': _V533_COLORS['warning'], 'warning_tint': _V533_COLORS['warning_tint'],
    'warning_border': _V533_COLORS['warning_border'],
    'ring': _V533_COLORS['ring'], 'bg_input': _V533_COLORS['bg_input'],
}
# v5.33 视觉层专用的状态色（仅换颜色，文案沿用 _STATUS_META，不改任何语义）。
_STATUS_COLOR_KEY_V533 = {'running': 'success', 'error': 'danger', 'stopped': None,
                          'switching': None, 'deploying': None, 'not_installed': None, 'unknown': None}
_BADGE_META_V533 = {
    k: (text, _V533_COLORS[_STATUS_COLOR_KEY_V533[k]] if _STATUS_COLOR_KEY_V533.get(k) else color)
    for k, (text, color) in _STATUS_META.items()
}
# 按钮 变体×色调 调色板（v5.33 原样：fill/fill_h/tint/tint_h/fg/subtle_border/transparent_fill）
_BUTTON_VARIANT_PALETTE = {
    'accent': {'fill': '#007aff', 'fill_h': '#0064d1', 'tint': '#e8f1ff', 'tint_h': '#d5e8ff',
               'fg': '#ffffff', 'subtle_border': '#c8dcfb', 'transparent_fill': '#ffffff'},
    'success': {'fill': '#34c759', 'fill_h': '#2ba847', 'tint': '#e6f9ec', 'tint_h': '#d3f3dc',
                'fg': '#ffffff', 'subtle_border': '#bbe6c5', 'transparent_fill': '#ffffff'},
    'danger': {'fill': '#ff3b30', 'fill_h': '#d92d22', 'tint': '#ffece9', 'tint_h': '#ffdad3',
               'fg': '#ffffff', 'subtle_border': '#f5b8b1', 'transparent_fill': '#ffffff'},
    'neutral': {'fill': '#f2f2f7', 'fill_h': '#e5e5ea', 'tint': '#f2f2f7', 'tint_h': '#e5e5ea',
                'fg': '#1d1d1f', 'subtle_border': '#e5e5ea', 'transparent_fill': '#ffffff'},
}
# 按钮尺寸/动效（v5.33 原规格）
_BTN_RADIUS, _BTN_HOVER_SHIFT, _BTN_ANIM_MS, _BTN_PRESS_DY = 10, -12, 180, 1
# 徽章脉冲与窗口淡入（v5.33 原规格）
_BADGE_PULSE_MS = 900
_FADE_STEPS, _FADE_INTERVAL_MS = 10, 30      # 窗口淡入 10 步 × 30ms = 300ms
_PULSE_STEPS, _PULSE_INTERVAL_MS = 10, 30    # 边框脉冲 10 步 × 30ms = 660ms（三角波往复）
_CARD_INTRO_STAGGER_MS = 80                  # 卡片入场错峰间隔


def _apply_v533_visual_layer():
    """把 _C 语义色整体切换为 v5.33 的 Apple/iOS 色值（视觉层唯一开关）。

    ★ 为什么改 _C 而不是让各处改引 _PALETTE:
      _C 在本文件中被 200+ 处以 _C['xxx'] 形式引用（含 Label/Frame/Canvas 的 bg/fg）。
      若逐处改引，一是改动面巨大易漏，二是后续新增控件会再次落回旧色板，形成双色板漂移。
      在**模块初始化阶段**（任何控件创建之前）一次性替换 _C 的取值，即可获得
      「一处切换、全应用生效」的效果，且不触碰任何业务逻辑。

    ★ 安全性: _DOT_COLOR / _STATUS_META 在 _C 替换**之前**已用旧对象建立完毕
      （见上方定义顺序），此处不重建它们，避免改变状态语义映射。
      _V533_COLORS 与 _BUTTON_VARIANT_PALETTE 仍保有原始色值，互不干扰。

    ★ 可回滚: 删除本函数的调用即完整回到 v5.40 原配色，无残留。
    """
    _C.update({
        'bg': _V533_COLORS['page_bg'],           # #f5f5f7  iOS 分组背景（实测校准值）
        'card': _V533_COLORS['bg_card'],         # #ffffff
        'border': _V533_COLORS['border_card'],   # #e3e3e6
        'text': _V533_COLORS['text_primary'],    # #1d1d1f
        'muted': _V533_COLORS['text_dim'],       # #6e6e73  iOS 次级文字（实测校准值）
        'green': _V533_COLORS['success'],        # #34c759
        'gray': _V533_COLORS['text_dim'],        # #6e6e73
        'red': _V533_COLORS['danger'],           # #ff3b30
        'orange': _V533_COLORS['warning'],       # #ff9500
        'blue': _V533_COLORS['accent'],          # #007aff  iOS 系统蓝
    })


def _hex_to_rgb_v533(hex_c):
    """'#rrggbb' → (r, g, b)。v5.33 原函数（名 _hex_to_rgb 已被当前版本占用）。"""
    hex_c = hex_c.lstrip('#')
    return int(hex_c[0:2], 16), int(hex_c[2:4], 16), int(hex_c[4:6], 16)


def _shift_color(hex_c, amount):
    """颜色偏移 - 模块级公共函数（v5.33 原样恢复）。

    amount 为正则每个通道加亮，为负则加深；通道值钳制在 [0, 255]。
    """
    r, g, b = (max(0, min(255, int(c) + amount)) for c in _hex_to_rgb_v533(hex_c))
    return f'#{r:02x}{g:02x}{b:02x}'


def _lerp_color(c1, c2, t):
    """颜色线性插值 - 模块级公共函数（v5.33 原样恢复）。

    t=0 返回 c1，t=1 返回 c2；用于 Hover 的平滑过渡与卡片入场渐变。
    """
    r1, g1, b1 = _hex_to_rgb_v533(c1)
    r2, g2, b2 = _hex_to_rgb_v533(c2)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f'#{r:02x}{g:02x}{b:02x}'


def _font_exists(name):
    """字体存在性探测（v5.33 原样恢复，带缓存）。用于图标字体优雅降级。"""
    if not _FONT_CACHE:
        try:
            import tkinter.font as tkfont
            root = tk._default_root or tk.Tk()
            _FONT_CACHE.update({f: True for f in tkfont.families(root)})
        except Exception:
            return False
    return name in _FONT_CACHE


_FONT_CACHE = {}

# ★ v5.33 视觉层生效点 —— 必须位于 _C / _DOT_COLOR / _STATUS_META / _PALETTE
#   / _BADGE_META_V533 全部定义完之后、任何控件创建之前。
#   在此处调用可保证：派生表仍绑定旧对象（互不污染），而所有控件的 _C['xxx'] 取值
#   在创建时已是 v5.33 色值。
_apply_v533_visual_layer()


_mutex_handle = None


class _Ports:
    """端口配置单例: 业务代码统一经 _PORTS 取端口，配置保存后热更新。"""

    def __init__(self):
        self.api, self.web, self.redis = _DEFAULT_API_PORT, _DEFAULT_WEB_PORT, _DEFAULT_REDIS_PORT
_PORTS = _Ports()


def _cap(timeout=15, oem=True):
    """subprocess.run 公共 kwargs: 无窗口 + 捕获输出。

    oem=True 按 OEM 代码页解码(sc/nssm/netstat/wmic 在中文 Windows 上是 GBK)。
    """
    kw = dict(creationflags=_NO_WINDOW, capture_output=True, timeout=timeout)
    if oem and _IS_WINDOWS:
        kw.update(encoding='oem', errors='replace')
    else:
        # errors='replace' 必给: PYTHONUTF8=1 环境下 text 模式默认 UTF-8 解码，
        # 遇到 OEM 输出会在读取线程抛 UnicodeDecodeError 致 stdout 丢失。
        kw.update(text=True, errors='replace')
    return kw


def _parse_sc_state(code, out):
    """sc query 输出 → 服务状态文本('未安装'|'未知'|STATE 行文本)。纯函数, 供单测。

    ★ v5.40 修复(审查 #1): 「未安装」只认 rc==1060，或输出是 1060 错误文本且【没有】STATE 行。
      旧版裸写 `'1060' in out` —— 运行中服务的输出含 `PID : 1060` 时(开机早期自启服务的
      PID 完全可能落在 1060)会被误判「未安装」，导致 _ensure_production_stopped 跳过停止，
      开发模式直接抢占 5002/3000 与生产互杀 —— 恰好复发 v5.36 堵住的互杀事故。
    """
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


def _enable_dpi_awareness():
    """DPI 感知，必须在 tk.Tk() 之前调用；只取 System DPI Aware。

    Per-Monitor v2 与 Tk 8.6 不兼容，RDP 重连/DPI 变化会造成窗口重绘风暴。
    """
    if not _IS_WINDOWS:
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        with contextlib.suppress(Exception):
            ctypes.windll.user32.SetProcessDPIAware()


def _ensure_single_instance():
    """内核互斥体单实例。True=首次启动，False=已有实例。"""
    global _mutex_handle
    if not _IS_WINDOWS:
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetLastError(0)
        profile = os.environ.get('USERPROFILE', str(Path.home()))
        user_hash = hashlib.sha256(profile.encode('utf-8', 'replace')).hexdigest()[:8]
        handle = kernel32.CreateMutexW(None, False, f'ERP_Server_Manager_{user_hash}_v1')
        if ctypes.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return False
        _mutex_handle = handle
        return True
    except Exception as e:
        logging.warning(f'互斥体创建异常: {e}')
        return True


def _activate_existing_window():
    """把已在运行的窗口置前。"""
    if not _IS_WINDOWS:
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, _WINDOW_TITLE)
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _get_project_dir():
    """项目根定位: 源码=本文件目录; exe=exe 目录 → erp_project_path.txt → d:\\erp_system。"""
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        if (exe_dir / 'fastapi_app').is_dir():
            return exe_dir
        path_cfg = exe_dir / 'erp_project_path.txt'
        if path_cfg.is_file():
            with contextlib.suppress(Exception):
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
    """纯文件系统校验(不执行): which 归一化 + 绝对路径 + .exe 后缀 + 存在。"""
    if not python_exe:
        return False
    resolved = shutil.which(python_exe)
    if not resolved:
        return False
    exe = Path(resolved)
    return exe.is_absolute() and exe.suffix.lower() == '.exe' and exe.is_file()


def _get_python_executable():
    """定位 Python: 源码=sys.executable; frozen 依次找 venv/py.exe/PATH/常见安装目录。"""
    if not getattr(sys, 'frozen', False):
        return sys.executable
    project_dir = _get_project_dir()
    for venv_name in ('.venv313', '.venv', 'venv'):
        venv_py = project_dir / venv_name / 'Scripts' / 'python.exe'
        if venv_py.is_file():
            return str(venv_py)
    py_exe = Path(os.environ.get('SYSTEMROOT', r'C:\Windows')) / 'py.exe'
    if py_exe.is_file():
        return str(py_exe)
    python_in_path = shutil.which('python')
    if python_in_path:
        return python_in_path
    local_appdata = os.environ.get('LOCALAPPDATA', '')
    for candidate in (Path(local_appdata) / 'Programs' / 'Python' / 'Python313' / 'python.exe',
                      Path(r'C:\Python313\python.exe'),
                      Path(local_appdata) / 'Programs' / 'Python' / 'Python312' / 'python.exe',
                      Path(r'C:\Python312\python.exe')):
        if candidate.is_file():
            return str(candidate)
    return None
_PROJECT_DIR = _get_project_dir()
_FRONTEND_DIR = _PROJECT_DIR / 'frontend-vite'
_PROD_STATUS_FILE = _PROJECT_DIR / 'logs' / _PROD_STATUS_FILE_NAME
_CONFIG_FILE = _PROJECT_DIR / _CONFIG_FILE_NAME
_PYTHON_EXE = _get_python_executable()
if _PYTHON_EXE and not _validate_python_exe(_PYTHON_EXE):
    _PYTHON_EXE = None
_APP_CONFIG_DEFAULTS = {'api_port': _DEFAULT_API_PORT, 'web_port': _DEFAULT_WEB_PORT,
                        'redis_port': _DEFAULT_REDIS_PORT, 'redis_exe': '', 'nssm_path': '',
                        'max_log_lines': 2000, 'log_keep_lines': 1600, 'full_stop_hold_ms': 1500,
                        'redis_services': list(_DEFAULT_REDIS_SERVICES), 'redis_service_wait_s': 30}


def _load_app_config():
    """逐键白名单合并; 文件不存在/损坏时回落默认值(绝不因配置崩溃)。

    list 类型键(redis_services)额外做元素类型校验: 非 list / 含非 str 元素 / 空列表
    → 回落默认值(D5: 空列表等于「不再托管任何 Redis 服务」，几乎不可能是用户本意)。
    redis_service_wait_s 做正整数归一化，非法值回落默认 30。
    D4: 返回值里的 redis_services 始终是独立副本，绝不与模块级默认值共享别名。
    D10: 配置文件损坏时记 WARNING(仍回落默认 —— 否则用户会误以为配置生效)。
    """
    cfg = dict(_APP_CONFIG_DEFAULTS)
    try:
        if _CONFIG_FILE.is_file():
            stored = json.loads(_CONFIG_FILE.read_text(encoding='utf-8'))
            if isinstance(stored, dict):
                cfg.update({k: v for k, v in stored.items() if k in cfg})
    except Exception as e:
        logging.getLogger('server_manager').warning(f'配置文件读取/解析失败，已回落默认配置: {type(e).__name__}: {e}')
    services = cfg.get('redis_services')
    valid = isinstance(services, list) and bool(services) and all(isinstance(s, str) and s for s in services)
    if valid:
        cfg['redis_services'] = list(services)  # D4: 显式拷贝，杜绝与默认值/存储对象共享别名
    else:
        if isinstance(services, list) and not services:
            logging.getLogger('server_manager').warning('redis_services 为空列表，按非法配置处理，回落默认托管列表')
        cfg['redis_services'] = list(_DEFAULT_REDIS_SERVICES)
    try:
        cfg['redis_service_wait_s'] = max(1, int(cfg.get('redis_service_wait_s')))
    except (TypeError, ValueError):
        cfg['redis_service_wait_s'] = int(_APP_CONFIG_DEFAULTS['redis_service_wait_s'])
    # v5.40 修复(审查 #3): 标量键统一归一化 —— 此前 max_log_lines/log_keep_lines/full_stop_hold_ms
    # 由 __init__ 直接 int()，配置写坏(如 "abc"/数组)会抛 ValueError 炸掉启动，
    # 违背本函数「绝不因配置崩溃」的承诺。非法值回落默认并留 WARNING(D10)。
    for key, default, floor in (('max_log_lines', 2000, 100), ('log_keep_lines', 1600, 50),
                                ('full_stop_hold_ms', 1500, 200)):
        try:
            val = max(floor, int(cfg.get(key)))
        except (TypeError, ValueError):
            val = default
            logging.getLogger('server_manager').warning(
                f'配置项 {key} 非法({cfg.get(key)!r})，回落默认值 {default}')
        cfg[key] = val
    # keep 必须 < max，否则日志裁剪退化为空操作
    if cfg['log_keep_lines'] >= cfg['max_log_lines']:
        cfg['log_keep_lines'] = max(50, cfg['max_log_lines'] - 200)
    return cfg


def _save_app_config(cfg):
    try:
        _CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
        return True
    except Exception:
        return False


def _apply_config_to_runtime(cfg):
    """端口热更新，1..65535 范围校验。返回非法端口键列表(v5.40/审查 #22: 配置损坏必须留痕，不静默)。"""
    invalid = []
    for attr, key in (('api', 'api_port'), ('web', 'web_port'), ('redis', 'redis_port')):
        try:
            v = int(cfg.get(key))
        except (TypeError, ValueError):
            invalid.append(key)
            continue
        if 1 <= v <= 65535:
            setattr(_PORTS, attr, v)
        else:
            invalid.append(key)
    return invalid
_APP_CONFIG = _load_app_config()
_INVALID_CONFIG_KEYS = _apply_config_to_runtime(_APP_CONFIG)


def _hex_to_rgb(hex_c):
    return int(hex_c[1:3], 16), int(hex_c[3:5], 16), int(hex_c[5:7], 16)


def _rgb_to_hex(r, g, b):
    return f'#{max(0, min(255, int(r))):02x}{max(0, min(255, int(g))):02x}{max(0, min(255, int(b))):02x}'


def _blend(fg_hex, bg_hex, alpha):
    """rgba 扁平化: Tk 颜色不支持 alpha，按底色压成不透明 hex。"""
    fr, fg, fb = _hex_to_rgb(fg_hex)
    br, bg, bb = _hex_to_rgb(bg_hex)
    return _rgb_to_hex(fr * alpha + br * (1 - alpha), fg * alpha + bg * (1 - alpha), fb * alpha + bb * (1 - alpha))


def _taskkill(pid, force=True, tree=True):
    """统一进程终止: 参数列表 + 字面量 argv[0]，绝无 shell 参与。"""
    if not _IS_WINDOWS or not pid:
        return
    argv = ['taskkill'] + (['/F'] if force else []) + (['/T'] if tree else []) + ['/PID', str(int(pid))]
    with contextlib.suppress(Exception):
        subprocess.run(argv, **_cap(10, oem=False))


def _taskkill_many(pids, force=True, tree=True):
    """批量终止; 优先 psutil(秒级无进程创建开销)，缺失时逐个 taskkill。

    ★ v5.40 修复(审查 #4): psutil 路径必须与 taskkill /T 同语义 —— 终止【自身+全部后代】。
      此前只杀 netstat 报告的单个 PID: 监听 socket 句柄会被 --reload supervisor / npm 等
      父子进程共享继承，单杀一个后其余进程仍持有句柄，端口释放 3 轮重试空转后静默失效。
      注意绝不能向上杀祖先链(可能殃及 explorer 等无辜进程)。
    """
    if not _IS_WINDOWS or not pids:
        return
    if psutil is not None:
        killed = set()
        for pid in pids:
            if pid in killed:
                continue
            try:
                proc = psutil.Process(int(pid))
            except Exception:
                _taskkill(pid, force=force, tree=tree)
                continue
            family = [proc]
            with contextlib.suppress(Exception):
                family.extend(proc.children(recursive=True))
            for p in family:
                killed.add(p.pid)
                with contextlib.suppress(Exception):
                    p.kill()
        return
    for pid in pids:
        _taskkill(pid, force=force, tree=tree)


def _get_port_occupier(port):
    """占用指定端口的进程信息 [(pid, name), ...]。"""
    occupiers = []
    try:
        result = subprocess.run(['netstat', '-ano'], **_cap(5))
        pids = {line.split()[-1] for line in (result.stdout or '').splitlines()
                if f':{port}' in line and ('LISTENING' in line or 'ESTABLISHED' in line)
                and len(line.split()) >= 5 and line.split()[-1].isdigit()}
        for pid in pids:
            name = '未知进程'
            with contextlib.suppress(Exception):
                tasklist = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'], **_cap(5))
                lines = [ln.strip() for ln in (tasklist.stdout or '').splitlines() if ln.strip()]
                if lines and len(lines[0].split('","')) >= 2:
                    name = lines[0].split('","')[0].strip('"')
            occupiers.append((pid, name))
    except Exception as e:
        # D14: 该函数已在轻量停止的端口释放关键路径上，查询失败必须留痕
        # (保持「尽力而为、不阻断」的失败语义，仍返回已收集项)
        logging.getLogger('server_manager').warning(f'查询端口 {port} 占用者失败: {type(e).__name__}: {e}')
    return occupiers


class RoundedButton(tk.Canvas):
    """基于 Canvas 的圆角按钮 — v5.33 视觉层恢复（含 Hover/Press 微交互）。

    三种视觉变体：solid / outlined / subtle。
    规格（v5.33 原始规格，经字节码提取确认）：
        高度    36px (padx=16, pady=6 + font linespace ≈ 36)；mini 26px (pady=2)
        圆角    10px (mini 8px)
        字号    9pt bold (mini 8pt)
        Hover   180ms 平滑过渡到 +12 加深色（solid）/ 主色 12% 透明染（outlined/subtle）
        Press   立即下沉 1px、背景再加深 6%
        Disabled 背景 #f2f2f7 / 文字 #aeaeb2 / 边框 #e5e5ea / cursor not-allowed

    ★ 恢复要点: 本类为**纯表现层**，通过 command 回调驱动业务，
      不直接触碰任何状态机字段，故不影响 v5.40 的线程契约与 TOCTOU 防护。

    ★★ 命名陷阱（务必勿改回）: 自绘宽高属性必须叫 _cw / _ch，
      **绝不能叫 _w / _h** —— `_w` 是 tkinter.Misc 内部的窗口路径名字符串
      （`self.tk.call(..., self._w)` 全靠它定位控件）。若在子类里用 int 覆盖它，
      所有 Tk 调用都会收到一个整数当窗口名，抛
      `TclError: bad argument "110": must be name of window`
      （110 也正是按钮自身的像素宽度）。该故障点远离赋值处，极难排查。
    """

    _DISABLED_BG, _DISABLED_FG, _DISABLED_BORDER = '#f2f2f7', '#aeaeb2', '#e5e5ea'

    def __init__(self, parent, text='', variant='solid', tone='accent', command=None,
                 font=None, padx=16, pady=6, radius=_BTN_RADIUS, state='normal',
                 canvas_bg=None, hover_fill=None, fg=None, **kw):
        self._text = text
        self._variant = variant if variant in ('solid', 'outlined', 'subtle') else 'solid'
        self._command = command
        self._font = font or ('Microsoft YaHei UI', 9, 'bold')
        self._radius = radius
        self._state = state
        self._hover = False
        self._press = False
        self._anim_after_id = None

        palette = _BUTTON_VARIANT_PALETTE.get(tone) or _BUTTON_VARIANT_PALETTE['accent']
        cfg_fill = palette['fill']
        cfg_hover = hover_fill or palette['fill_h']
        cfg_fg = fg or palette['fg']
        cfg_outline = palette['subtle_border']
        cfg_outline_hover = _shift_color(cfg_outline, -12)
        cfg_outline_w = 1

        eff_variant = self._variant
        if self._variant == 'outlined':
            self._fill = canvas_bg or _PALETTE['bg_card']
            self._hover_fill = palette['tint']
            self._fg = cfg_fill if fg is None else cfg_fg
            cfg_outline = cfg_fill
            cfg_outline_hover = cfg_hover
        elif self._variant == 'subtle':
            self._fill = palette['tint']
            self._hover_fill = palette['tint_h']
            self._fg = cfg_fill if fg is None else cfg_fg
        else:
            self._fill = cfg_fill
            self._hover_fill = cfg_hover
            self._fg = cfg_fg
        self._outline = cfg_outline if eff_variant != 'solid' else (canvas_bg or _PALETTE['bg_card'])
        self._outline_hover = cfg_outline_hover
        self._outline_w = cfg_outline_w if eff_variant != 'solid' else 0

        # 向后兼容: fill/hover_fill/fg 旧参数若显式传入则覆盖
        if 'fill' in kw and kw['fill']:
            self._fill = kw.pop('fill')
        if hover_fill:
            self._hover_fill = hover_fill
        if fg:
            self._fg = fg
        for legacy in ('fill_h', 'outline', 'outline_hover', 'outline_w'):
            kw.pop(legacy, None)

        tkfont_ = tkfont.Font(font=self._font)
        text_w = tkfont_.measure(text)
        linespace = tkfont_.metrics('linespace')
        w = text_w + padx * 2
        h = linespace + pady * 2
        bg = canvas_bg or _PALETTE['bg_card']
        self._bg = bg
        super().__init__(parent, width=w, height=h, highlightthickness=0, bg=bg, bd=0)
        self._cw, self._ch = w, h
        # ★ 禁用态色按 tone 派生（v5.33 实测: 灰按钮 #f2f2f7/#adadb1；
        #   绿按钮禁用底 #a8e0b8）。tone 未知时回落通用灰。
        self._disabled_bg = _V533_COLORS['disabled_bg']
        self._disabled_fg = _V533_COLORS['disabled_fg']
        self._disabled_border = _V533_COLORS['disabled_bg']
        if tone == 'success':
            self._disabled_bg = _V533_COLORS['green_disabled']
            self._disabled_border = _V533_COLORS['green_disabled']
        cursor = 'hand2' if state == 'normal' else 'arrow'
        self.configure(cursor=cursor)
        self.bind('<Enter>', self._hover_in)
        self.bind('<Leave>', self._hover_out)
        self.bind('<ButtonPress-1>', self._press_in)
        self.bind('<ButtonRelease-1>', self._press_out)
        self._draw()

    def set_tone(self, tone):
        """运行时切换色调（v5.33 语义: 开发/生产按钮的运行态用不同色调表达）。

        重算 fill / hover / fg / outline 与禁用态色，随后重绘。
        """
        palette = _BUTTON_VARIANT_PALETTE.get(tone) or _BUTTON_VARIANT_PALETTE['accent']
        if self._variant == 'outlined':
            self._fill = self._bg
            self._hover_fill = palette['tint']
            self._fg = palette['fill']
            self._outline = palette['fill']
            self._outline_hover = palette['fill_h']
            self._outline_w = 1
        elif self._variant == 'subtle':
            self._fill = palette['tint']
            self._hover_fill = palette['tint_h']
            self._fg = palette['fill']
            self._outline_w = 0
        else:
            self._fill = palette['fill']
            self._hover_fill = palette['fill_h']
            self._fg = palette['fg']
            self._outline = self._bg
            self._outline_w = 0
        self._disabled_bg = (_V533_COLORS['green_disabled'] if tone == 'success'
                             else _V533_COLORS['disabled_bg'])
        self._disabled_fg = _V533_COLORS['disabled_fg']
        self._disabled_border = self._disabled_bg
        self._draw()

    def config(self, **kw):
        """兼容 tk.Button API: text / state / command / bg / tone / variant 可运行时变更。"""
        if 'text' in kw:
            self.set_text(kw.pop('text'))
        if 'variant' in kw:
            v = kw.pop('variant')
            if v in ('solid', 'outlined', 'subtle'):
                self._variant = v
        if 'tone' in kw:
            self.set_tone(kw.pop('tone'))
        if 'state' in kw:
            self._state = kw.pop('state')
            self.configure(cursor='hand2' if self._state == 'normal' else 'arrow')
        if 'command' in kw:
            self._command = kw.pop('command')
        if 'bg' in kw:
            self._bg = kw.pop('bg')
            super().configure(bg=self._bg)
        if kw:
            with contextlib.suppress(Exception):
                super().configure(**kw)
        self._draw()

    configure = config

    def set_text(self, text):
        """更新文案并自适应宽度（保持与 tk.Button 等价的语义）。"""
        self._text = text
        f = tkfont.Font(font=self._font)
        self._cw = f.measure(text) + 32
        self._ch = f.metrics('linespace') + 12
        with contextlib.suppress(Exception):
            super().configure(width=self._cw, height=self._ch)
        self._draw()

    # ---- geometry 转发（tk.Canvas 没有 pack/grid/place），使 RoundedButton 可
    #      与 tk.Button 完全同样的方式装配，避免调用点被迫区分控件类型。----
    # ★ 必须用 *args/**kw 透传，不能声明 `cnf=None` 再 `super().pack(cnf, **kw)`:
    #   tk.Canvas.pack 的签名是 pack(cnf={}, **kw)，其内部走 _options(cnf, kw)。
    #   若把 None 当作位置参数传入，_options 会把该 None 与 kw 合并失败，
    #   进而把 pady=(10,12) 摊平成 "10 12" 并触发
    #   `TclError: bad argument "110": must be name of window`（实测复现）。
    #   透传 *args 则无参数时 args 为空，等价于原生调用，零副作用。
    def pack(self, *args, **kw):
        super().pack(*args, **kw)
        return self

    def grid(self, *args, **kw):
        super().grid(*args, **kw)
        return self

    def place(self, *args, **kw):
        super().place(*args, **kw)
        return self

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        """绘制圆角矩形（Canvas 无原生圆角，用 polygon + smooth 近似）。"""
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
               x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _draw(self):
        with contextlib.suppress(Exception):
            self.delete('all')
            disabled = (self._state == 'disabled')
            if disabled:
                fill, fg, outline = self._disabled_bg, self._disabled_fg, self._disabled_border
            else:
                fill = self._hover_fill if (self._hover and self._outline_w == 0) else self._fill
                if self._hover and self._outline_w:
                    fill = self._hover_fill
                fg = self._fg
                outline = self._outline_hover if self._hover else self._outline
            dy = _BTN_PRESS_DY if (self._press and not disabled) else 0
            x1, y1 = 0, dy
            x2, y2 = self._cw, self._ch + dy
            border = outline if self._outline_w else fill
            self._round_rect(x1, y1, x2, y2, self._radius,
                             fill=fill, outline=border, width=1)
            self.create_text(self._cw / 2, (self._ch / 2) + dy, text=self._text,
                             font=self._font, fill=fg)

    def _animate_hover(self, target_fill):
        """180ms 平滑过渡（4 步插值，v5.33 原规格）。"""
        if self._anim_after_id:
            with contextlib.suppress(Exception):
                self.after_cancel(self._anim_after_id)
            self._anim_after_id = None
        start = self._fill
        steps = 4
        interval = max(1, _BTN_ANIM_MS // steps)

        def step(i):
            if i > steps:
                self._anim_after_id = None
                return
            if self._state == 'disabled':
                return
            self._fill = _lerp_color(start, target_fill, i / steps)
            self._draw()
            self._anim_after_id = self.after(interval, lambda: step(i + 1))
        step(0)

    def _hover_in(self, _e=None):
        if self._state == 'disabled':
            return
        self._hover = True
        self._animate_hover(self._hover_fill)

    def _hover_out(self, _e=None):
        self._hover = False
        if self._state == 'disabled':
            self._draw()
            return
        self._animate_hover(self._fill if self._outline_w else self._fill)

    def _press_in(self, _e=None):
        if self._state == 'disabled':
            return
        self._press = True
        self._draw()

    def _press_out(self, _e=None):
        if self._state == 'disabled':
            return
        was_press = self._press
        self._press = False
        self._draw()
        # 只有「按下后在本控件内释放」才触发命令（与原生 Button 语义一致）
        if was_press and self._command:
            with contextlib.suppress(Exception):
                self._command()


class StatusBadge(tk.Canvas):
    """圆角胶囊状态徽章(色点 + 文字)。

    v5.33 视觉层恢复: ① 色值取 _BADGE_META_V533（iOS 色系）；
    ② 恢复徽章脉冲微交互 —— 过渡态(deploying/switching)下圆点做呼吸式明暗循环。
    ★ 脉冲只改 Canvas item 的 fill，不触碰任何状态字段，与业务状态机完全解耦。
    """

    _PULSING_STATES = ('deploying', 'switching')

    def __init__(self, parent, state='stopped', text=None, font=None, bg=None):
        self._font = font or ('Microsoft YaHei UI', 10, 'bold')
        self._bg = bg or _C['card']
        self._fobj = tkfont.Font(font=self._font)
        meta = _BADGE_META_V533.get(state, _BADGE_META_V533['stopped'])
        self._state, self._text, self._color = state, (text or meta[0]), meta[1]
        self._w = self._fobj.measure(self._text) + 46
        self._pulse_after_id, self._pulse_on = None, True
        super().__init__(parent, width=self._w, height=28, highlightthickness=0, bg=self._bg)
        self.bind('<Configure>', self._draw)
        self._draw()
        self._sync_pulse()

    def set_state(self, state, text=None):
        meta = _BADGE_META_V533.get(state, _BADGE_META_V533['stopped'])
        self._state, self._text, self._color = state, (text if text is not None else meta[0]), meta[1]
        self._w = self._fobj.measure(self._text) + 46
        with contextlib.suppress(Exception):
            self.configure(width=self._w)
        self._draw()
        self._sync_pulse()

    def _sync_pulse(self):
        """进入过渡态起脉冲、离开则停（幂等）。"""
        want = self._state in self._PULSING_STATES
        if want and self._pulse_after_id is None:
            self._pulse_on = True
            self._pulse_tick()
        elif not want and self._pulse_after_id is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._pulse_after_id)
            self._pulse_after_id = None
            self._pulse_on = True

    def _pulse_tick(self):
        # TclError 防护: 窗口销毁后仍可能有排队的 after 回调。
        try:
            self._pulse_on = not self._pulse_on
            self._draw()
            self._pulse_after_id = self.after(_BADGE_PULSE_MS // 2, self._pulse_tick)
        except tk.TclError:
            self._pulse_after_id = None

    def _draw(self, _=None):
        # TclError 防护: 窗口销毁时仍可能有排队的 <Configure> 回调，此时控件已失效，
        # 重绘会抛 invalid command name 噪声。
        try:
            self.delete('all')
            w = self.winfo_width() or self._w
            h = self.winfo_height() or 28
            if w < 4 or h < 4:
                return
            r = (h - 2) // 2
            x1, y1, x2, y2 = 1, 1, w - 1, h - 1
            pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
            self.create_polygon(pts, smooth=True, fill=_blend(self._color, self._bg, 0.13), outline=self._color)
            cy = h // 2
            # 脉冲: 圆点颜色在「本色 ↔ 变淡」之间切换；仅过渡态生效。
            dot_color = self._color
            if self._state in self._PULSING_STATES and not self._pulse_on:
                dot_color = _blend(self._color, self._bg, 0.35)
            self.create_oval(9, cy - 4, 17, cy + 4, fill=dot_color, outline='')
            self.create_text(24, cy, text=self._text, fill=self._color, font=self._font, anchor='w')
        except tk.TclError:
            pass


class ServerManagerApp:
    """单窗口服务器管理器: 装配 UI + 承载全部业务逻辑。

    线程契约(v5.40/审查 #7): _mode/_prod_running/_prod_busy/_stop_in_progress 只允许主线程
    经 state_set 消息变更(后台线程直写已全部移除)；后台线程仅管理 _process/_frontend_process
    的 Popen 生命周期(启动/终止/置 None —— GIL 下句柄赋值原子，且只有持有线程会写)。
    """
    LOG_FLUSH_MS, LOG_CLEANUP_MS, QUEUE_POLL_MS = 500, 120000, 200

    def __init__(self, root):
        self.root = root
        self.root.title(_WINDOW_TITLE)
        self.root.geometry('880x640')
        self.root.minsize(760, 560)
        self.root.configure(bg=_C['bg'])
        self.root.withdraw()  # 先 withdraw 再构建，避免白屏闪烁
        self._mode = 'none'            # v5.40(P2): 活枚举 = none | starting | dual_dev | stopping
        #                              'restarting' 已移除 —— 全文件从无写入点(死字面量)，
        #                              保留会形成「看似可达实则永远为假」的分支，误导后续维护
        self._process = None           # 后端 uvicorn Popen
        self._frontend_process = None  # 前端 npm/vite Popen
        self._redis_process = None     # 管理器启动的 Redis Popen
        self._prod_running = False     # 生产运行中(来自服务状态轮询)
        self._prod_unknown = False     # 生产状态「未知」(sc 查询失败) —— 仅供展示层，勿与 _prod_running 混用
        self._prod_busy = False        # 生产启/停命令在途
        self._redis_running_cached = None
        self._last_hosting = {}
        self._startup_steps, self._startup_progress, self._startup_current_step = [], 0, ''
        self._msg_queue = queue.Queue()
        self._log_buffer, self._flush_pending = [], False
        self._after_ids = {}
        self._shutting_down = False
        self._hosting_collecting = False
        self._hosting_refresh_requested = False
        self._stop_in_progress = False   # 紧急停止防重入(§6.5)
        self._stop_hold_fired = False
        self._stop_hold_after = None
        self._full_stop_hold_ms = int(_APP_CONFIG.get('full_stop_hold_ms') or 1500)
        self._max_log_lines = int(_APP_CONFIG.get('max_log_lines') or 2000)
        self._log_keep_lines = int(_APP_CONFIG.get('log_keep_lines') or 1600)
        self._font_ui, self._font_ui_bold = ('Microsoft YaHei UI', 10), ('Microsoft YaHei UI', 10, 'bold')
        self.setup_logging()
        # v5.40(审查 #8): 接管 Tk 回调异常 —— windowed exe 无 stderr，默认 handler 会静默丢弃，
        # 用户只看到"点了没反应"。统一落文件日志 + UI 日志留痕。
        self.root.report_callback_exception = self._report_callback_exception
        self._build_ui()
        self._font_log = self._pick_log_font()
        with contextlib.suppress(Exception):
            self.log_text.configure(font=self._font_log)
        self._center_window()
        self._init_tray()
        self.root.protocol('WM_DELETE_WINDOW', self.on_closing)
        self.root.deiconify()
        # v5.33 微交互: 窗口淡入 + 卡片错峰脉冲；窗口可见后再跑，避免 withdraw 期间空转。
        with contextlib.suppress(Exception):
            self._fade_in()
            self._animate_cards_intro()
        self._run_env_checks()
        self._update_all_ui()
        self._poll_queue()
        self._check_server_status()
        self._refresh_hosting_status()
        self._schedule_log_flush()
        self._schedule_log_cleanup()
        # D9: 首次运行落盘默认配置，便于用户发现并手工编辑(配置文件不存在时才写)
        if not _CONFIG_FILE.is_file() and _save_app_config(dict(_APP_CONFIG)):
            self.log_message(f'已生成默认配置: {_CONFIG_FILE}')
        self.log_message(f'{_WINDOW_TITLE} {_VERSION} 已启动')
        self.log_message(f'项目路径: {_PROJECT_DIR}')
        self.log_message(f'端口: API {_PORTS.api} / WEB {_PORTS.web} / Redis {_PORTS.redis}')
        for key in _INVALID_CONFIG_KEYS:
            self.log_message(f'配置项 {key} 非法，已回落默认值，请检查 {_CONFIG_FILE.name}', 'WARNING')
        if psutil is None:
            self.log_message('未安装 psutil，残留进程清理将降级(仅终止自有进程树)', 'WARNING')
    # ===================== UI 装配 =====================

    def _report_callback_exception(self, exc_type, exc_val, exc_tb):
        """Tk mainloop 回调异常统一入口(v5.40/审查 #8): 落 crash 级日志 + UI 留痕，绝不静默。"""
        tb_text = ''.join(traceback.format_exception(exc_type, exc_val, exc_tb))
        with contextlib.suppress(Exception):
            self.logger.error(f'UI 回调异常: {exc_type.__name__}: {exc_val}\n{tb_text}')
        with contextlib.suppress(Exception):
            self.log_message(f'界面操作异常: {exc_type.__name__}: {exc_val}', 'ERROR')

    def _build_ui(self):
        header = tk.Frame(self.root, bg=_C['bg'])
        header.pack(fill=tk.X, padx=14, pady=(12, 6))
        tk.Label(header, text=f'ERP 服务器管理器 {_VERSION}', font=('Microsoft YaHei UI', 13, 'bold'), fg=_C['text'], bg=_C['bg']).pack(side=tk.LEFT)
        self.mode_badge = StatusBadge(header, state='stopped', bg=_C['bg'])
        self.mode_badge.pack(side=tk.RIGHT)
        body = tk.Frame(self.root, bg=_C['bg'])
        body.pack(fill=tk.X, padx=14, pady=6)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        dev_card, dev_inner = self._make_card(body, '开发模式')
        dev_card.grid(row=0, column=0, sticky='nsew', padx=(0, 7))
        self.dev_dots = {'redis': self._make_dot(dev_inner, 'Redis'),
                         'backend': self._make_dot(dev_inner, '后端'),
                         'frontend': self._make_dot(dev_inner, '前端')}
        # v5.33 视觉层: 圆角按钮(Canvas) + accent 实心色调；command 回调驱动业务，untouched 状态机。
        self.dev_btn = RoundedButton(dev_inner, text='启动开发模式', variant='solid', tone='accent',
                                     font=self._font_ui_bold, command=self.toggle_dev)
        self.dev_btn.pack(fill=tk.X, padx=12, pady=(10, 12))
        prod_card, prod_inner = self._make_card(body, '生产模式')
        prod_card.grid(row=0, column=1, sticky='nsew', padx=(7, 0))
        self.prod_dots = {'api': self._make_dot(prod_inner, _SVC_API), 'arq': self._make_dot(prod_inner, _SVC_ARQ)}
        self.prod_btn = RoundedButton(prod_inner, text='启动生产模式', variant='solid', tone='accent',
                                      font=self._font_ui_bold, command=self.toggle_prod)
        self.prod_btn.pack(fill=tk.X, padx=12, pady=(10, 12))
        action = tk.Frame(self.root, bg=_C['bg'])
        action.pack(fill=tk.X, padx=14, pady=(2, 6))
        # ★ 紧急停止按钮: command 必须留空 —— RoundedButton 内部已绑定
        #   <ButtonPress-1>/<ButtonRelease-1> 做 Hover/Press 视觉反馈，
        #   若再让类内 _press_out 触发 command，会与下方 _on_stop_press/_on_stop_release
        #   的分级长按语义（单击=轻量 / 长按=全清）叠加，造成一次点击触发两条停止路径。
        #   故此处仅借 RoundedButton 的「外观」，事件语义完全由外部绑定接管。
        self.stop_btn = RoundedButton(action, text='紧急停止', variant='solid', tone='danger',
                                      font=self._font_ui_bold, command=None, padx=24)
        self.stop_btn.pack(side=tk.LEFT)
        # 分级语义必须让用户可感知: 单击=轻量停止; 长按≥阈值=全清
        # ★ add='+' 保留 RoundedButton 内部的 Press/Release 视觉回调，二者叠加而非覆盖。
        self.stop_btn.bind('<ButtonPress-1>', self._on_stop_press, add='+')
        self.stop_btn.bind('<ButtonRelease-1>', self._on_stop_release, add='+')
        tk.Label(action, text=f'单击停止当前模式 · 长按 {self._full_stop_hold_ms / 1000:.1f} 秒全清（含服务）',
                 font=('Microsoft YaHei UI', 9), fg=_C['muted'], bg=_C['bg']).pack(side=tk.LEFT, padx=(10, 0))
        self.status_label = tk.Label(action, text='就绪', font=('Microsoft YaHei UI', 9, 'bold'), fg=_C['text'], bg=_C['bg'])
        self.status_label.pack(side=tk.RIGHT)
        # v5.33 视觉层: 日志区改用带 highlight 边框的卡片式外框（LabelFrame 的 labelanchor
        #   在浅灰底上视觉重量偏重，且与卡片圆角语言不一致）。
        log_wrap = tk.Frame(self.root, bg=_C['card'], highlightbackground=_C['border'], highlightthickness=1, bd=0)
        log_wrap.pack(fill=tk.BOTH, expand=True, padx=14, pady=(2, 6))
        tk.Label(log_wrap, text='运行日志', font=('Microsoft YaHei UI', 10, 'bold'),
                 fg=_C['text'], bg=_C['card']).pack(anchor='w', padx=12, pady=(8, 2))
        # ★ 不用 ScrolledText: 其 Tk 原生 scrollbar 在浅灰底上风格突兀。
        #   改为 Text + 独立 ttk.Scrollbar，视觉更贴近 v5.33 的克制表达。
        # ★ 正文底色用 #f9f9fb（v5.33 实测）而非纯白 —— 与卡片外框形成极轻的内凹层次。
        log_body = tk.Frame(log_wrap, bg=_V533_COLORS['log_surface'])
        log_body.pack(fill=tk.BOTH, expand=True, padx=(12, 4), pady=(0, 10))
        self.log_text = tk.Text(log_body, wrap=tk.WORD, font=('Microsoft YaHei UI', 9),
                                bg=_V533_COLORS['log_surface'],
                                fg=_C['text'], relief=tk.FLAT, bd=0, state=tk.DISABLED, height=10,
                                highlightthickness=0, padx=2, pady=2)
        log_scroll = ttk.Scrollbar(log_body, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        for lvl, color in (('INFO', _C['muted']), ('WARNING', _C['orange']), ('ERROR', _C['red']), ('SUCCESS', _C['green'])):
            self.log_text.tag_config(lvl, foreground=color)
        controls = tk.Frame(self.root, bg=_C['bg'])
        controls.pack(fill=tk.X, padx=14, pady=(0, 12))
        # v5.33 视觉层: 次级操作按钮统一走 RoundedButton 的 outlined 变体
        #   （白底 + 彩色描边 + tint 悬停），替代 flat tk.Button 的零反馈观感。
        for text, cmd in (('清空日志', self.clear_log), ('导出日志', self.export_log), ('打开日志目录', self._open_logs_dir)):
            RoundedButton(controls, text=text, variant='outlined', tone='accent',
                          font=('Microsoft YaHei UI', 9), command=cmd,
                          padx=12, pady=4, canvas_bg=_C['bg']).pack(side=tk.LEFT, padx=(0, 8))
        self.auto_scroll_var = tk.BooleanVar(value=True)
        tk.Checkbutton(controls, text='自动滚动', variable=self.auto_scroll_var, font=('Microsoft YaHei UI', 9),
                       bg=_C['bg'], fg=_C['text'], activebackground=_C['bg'], selectcolor=_C['card'],
                       cursor='hand2').pack(side=tk.RIGHT)
        # v5.33 微交互: 窗口淡入 + 卡片边框错峰脉冲。
        #   规格经字节码闭包反汇编逐指令复原（见 _anim_closures.txt）：
        #     _fade_in:            attributes('-alpha', 0.0) → step(i)，i>10 置 1.0，
        #                          否则 alpha=i/10，after(30, step(i+1)) ⇒ 10 步 / 300ms
        #     _animate_cards_intro: for idx, card in enumerate(cards): after(80*idx, ...)
        #                          ⇒ 卡片【错峰】入场，非同时（这点极易做错）
        #     _pulse_card_border:  base=_PALETTE['border_card'], accent=_PALETTE['accent_h']
        #                          t=i/10 走三角波: t<=0.5 用 (base→accent, t*2)，
        #                          否则 (accent→base, (t-0.5)*2)；到 i>10 复位 base
        #                          ⇒ 边框「亮一下再暗回来」660ms，仅此一次
        self._server_cards = (dev_card, prod_card)

    def _fade_in(self):
        """窗口淡入（v5.33 原规格: 10 步 / 30ms = 300ms）。

        ★ 必须整体包在 suppress 里: 部分 Windows 主题/远程桌面会话下
          `attributes('-alpha', ...)` 不被支持会抛 TclError。淡入失败绝不能影响功能。
        """
        with contextlib.suppress(Exception):
            self.root.attributes('-alpha', 0.0)

            def step(i):
                if self._shutting_down:
                    return
                if i > 10:
                    with contextlib.suppress(Exception):
                        self.root.attributes('-alpha', 1.0)
                    return
                with contextlib.suppress(Exception):
                    self.root.attributes('-alpha', i / 10)
                self.root.after(30, lambda: step(i + 1))
            step(0)

    def _animate_cards_intro(self):
        """卡片错峰入场（v5.33 原规格: 第 idx 张延迟 80*idx ms 启动脉冲）。"""
        with contextlib.suppress(Exception):
            for idx, card in enumerate(getattr(self, '_server_cards', ())):
                self.root.after(80 * idx, lambda c=card: self._pulse_card_border(c))

    def _pulse_card_border(self, card):
        """卡片边框脉冲（v5.33 原规格: 三角波往复, 10 步 / 30ms = 660ms）。

        色键取自 _PALETTE: border_card（静息边框色）→ accent_h（高亮色）→ 回到静息。
        ★ 单次动画，不做常驻循环 —— v5.33 原实现同样只跑一轮，
          常驻脉冲会在长时间值守时构成视觉干扰。
        """
        base = _PALETTE['border_card']
        accent = _PALETTE.get('accent_h') or _V533_COLORS['accent_hover']

        def tick(i):
            if self._shutting_down:
                return
            try:
                if i > 10:
                    with contextlib.suppress(Exception):
                        card.configure(highlightbackground=base)
                    return
                t = i / 10
                if t <= 0.5:
                    color = _lerp_color(base, accent, t * 2)
                else:
                    color = _lerp_color(accent, base, (t - 0.5) * 2)
                with contextlib.suppress(Exception):
                    card.configure(highlightbackground=color)
                self.root.after(30, lambda: tick(i + 1))
            except Exception:
                pass
        tick(0)

    def _make_card(self, parent, title):
        card = tk.Frame(parent, bg=_C['card'], highlightbackground=_C['border'], highlightthickness=1, bd=0)
        inner = tk.Frame(card, bg=_C['card'])
        inner.pack(fill=tk.BOTH, expand=True)
        tk.Label(inner, text=title, font=('Microsoft YaHei UI', 11, 'bold'), fg=_C['text'], bg=_C['card']).pack(anchor='w', padx=12, pady=(12, 6))
        return card, inner

    def _make_dot(self, parent, name):
        lbl = tk.Label(parent, text=f'○ {name}', font=('Microsoft YaHei UI', 10), fg=_C['gray'], bg=_C['card'], anchor='w')
        lbl.pack(anchor='w', padx=14, pady=2)
        return lbl

    def _center_window(self):
        self.root.update_idletasks()
        w, h = 880, 640
        x = max(0, (self.root.winfo_screenwidth() - w) // 2)
        y = max(0, (self.root.winfo_screenheight() - h) // 3)
        self.root.geometry(f'{w}x{h}+{x}+{y}')
    # ===================== 消息泵(后台线程 → 主线程唯一通道) =====================

    def _poll_queue(self):
        if self._shutting_down:
            return
        processed = 0
        while not self._msg_queue.empty() and processed < 30:
            try:
                msg_type, data = self._msg_queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._dispatch_message(msg_type, data)
            except Exception as e:
                # 单条失败不能中断 poll 调度链(否则日志/状态更新全部停摆) —— 故仍吞异常不重抛；
                # ★ v5.38(D16): 但必须留痕 —— 被丢弃的消息可能承载「停止失败/端口未释放」等关键日志。
                # 用 logger 写文件而非 log_message，避免在 dispatch 失败时递归回同一路径。
                with contextlib.suppress(Exception):
                    self.logger.warning(f'消息处理失败已跳过(type={msg_type}): {type(e).__name__}: {e}')
            processed += 1
        if not self._shutting_down:
            self._after_ids['poll'] = self.root.after(self.QUEUE_POLL_MS, self._poll_queue)

    def _dispatch_message(self, msg_type, data):
        if msg_type == 'log':
            self.log_message(data['text'], data.get('level', 'INFO'))
        elif msg_type == 'log_batch':
            # v5.40(审查 #9): 支持 (text, level) 元组逐行级别; 兼容旧的纯字符串列表。
            for item in data['lines']:
                if isinstance(item, (tuple, list)) and len(item) == 2:
                    self.log_message(item[0], item[1])
                else:
                    self.log_message(item, data.get('level', 'INFO'))
        elif msg_type == 'dual_started':
            self._on_dual_started(data['label'])
        elif msg_type == 'dual_failed':
            self._on_dual_failed(data['label'], data.get('reason', ''))
        elif msg_type == 'ui_update':
            self._update_all_ui()
        elif msg_type == 'startup_progress':
            self.status_label.config( text=f"启动中: {data.get('step', '')} ({data.get('progress', 0)}/{data.get('total', 5)})")
        elif msg_type == 'hosting_apply':
            self._apply_hosting_data(data['data'])
        elif msg_type == 'hosting_refresh':
            self._refresh_hosting_status()
        elif msg_type == 'state_set':
            # v5.40(审查 #7) 线程契约: _mode/_prod_running/_prod_busy/_stop_in_progress 只允许
            # 主线程经本消息变更(后台线程直写已全部移除，GIL 之外还有状态机纪律问题)。
            for key in ('mode', 'prod_running', 'prod_busy', 'stop_in_progress'):
                if key in data:
                    setattr(self, f'_{key}', data[key])
            self._update_all_ui()
        elif msg_type == 'toast':
            self._show_toast(data.get('title', ''), data.get('desc', ''))

    def _show_toast(self, title, desc=''):
        """轻量提示: 写入状态栏，不弹窗打断用户。"""
        if title:
            self.status_label.config(text=title + (f' — {desc}' if desc else ''))
    # ===================== 日志系统 =====================

    def setup_logging(self):
        log_dir = (_PROJECT_DIR / 'logs').resolve()
        if '..' in log_dir.parts or not log_dir.is_absolute():  # 路径安全门
            log_dir = Path.cwd() / 'logs'
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f'server_manager_{datetime.now():%Y%m%d}.log'
        fmt = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s')
        self.logger = logging.getLogger('server_manager')
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:  # 幂等，避免重复 handler 导致双份日志
            fh = logging.FileHandler(log_file, encoding='utf-8')
            fh.setFormatter(fmt)
            self.logger.addHandler(fh)
            if sys.stdout:
                sh = logging.StreamHandler(sys.stdout)
                sh.setFormatter(fmt)
                self.logger.addHandler(sh)
        self._cleanup_old_logs(log_dir)

    def _cleanup_old_logs(self, log_dir, keep_days=30):
        """v5.40(审查 #17): 清理超过 keep_days 的历史 server_manager 日志(含 crash 日志)，
        防止按天累积无限膨胀。失败只留 WARNING，绝不影响启动。"""
        cutoff = time.time() - max(1, keep_days) * 86400
        try:
            for f in log_dir.glob('server_manager_*.log'):
                with contextlib.suppress(OSError):
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
        except Exception as e:
            self.logger.warning(f'清理历史日志失败(不影响运行): {type(e).__name__}: {e}')

    def log_message(self, message, level='INFO'):
        """追加 UI 缓冲 + 同步写文件日志; UI 落屏经 after_idle 合并到主线程。"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        self._log_buffer.append((f'[{timestamp}] {level}: {message}\n', level))
        # v5.40(审查 #10): 显式级别映射 —— 此前 SUCCESS 走 getattr(logger,'success') 拿不到
        # 回落 warning，文件日志里所有成功消息都被记成 WARNING 干扰分析。
        level_fn = {'info': 'info', 'success': 'info', 'warning': 'warning', 'error': 'error'}.get(str(level).lower())
        fn = getattr(self.logger, level_fn, None) or self.logger.warning
        with contextlib.suppress(Exception):
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
        buf, self._log_buffer = self._log_buffer[:], []
        try:
            self.log_text.config(state=tk.NORMAL)
            for entry, level in buf:
                self.log_text.insert(tk.END, entry, level if level in ('INFO', 'WARNING', 'ERROR', 'SUCCESS') else 'INFO')
            if self.auto_scroll_var.get():
                self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        except tk.TclError:
            pass

    def _schedule_log_flush(self):
        if self._log_buffer:
            self._flush_log_buffer()
        if not self._shutting_down:
            self._after_ids['flush'] = self.root.after(self.LOG_FLUSH_MS, self._schedule_log_flush)

    def _schedule_log_cleanup(self):
        self._perform_log_cleanup()
        if not self._shutting_down:
            self._after_ids['cleanup'] = self.root.after(self.LOG_CLEANUP_MS, self._schedule_log_cleanup)

    def _perform_log_cleanup(self):
        """裁剪超限行，仅保留 keep 行，防止长跑内存膨胀。"""
        try:
            total = int(self.log_text.index('end-1c').split('.')[0])
            if total > self._max_log_lines:
                self.log_text.config(state=tk.NORMAL)
                self.log_text.delete('1.0', f'{total - self._log_keep_lines}.0')
                self.log_text.config(state=tk.DISABLED)
        except (tk.TclError, ValueError):
            pass

    def clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete('1.0', tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.log_message('日志已清空')

    def export_log(self):
        default_dir = (_PROJECT_DIR / 'logs').resolve()
        filename = filedialog.asksaveasfilename(
            initialdir=str(default_dir), initialfile=f'server_log_{datetime.now():%Y%m%d_%H%M%S}.txt',
            defaultextension='.txt', filetypes=[('文本文件', '*.txt'), ('所有文件', '*.*')])
        if not filename:
            return
        target = Path(filename).resolve()
        # 路径安全门: 绝对路径 + 不含 '..' + 父目录存在(路径穿越防护)
        if not target.is_absolute() or '..' in Path(filename).parts or not target.parent.is_dir():
            self.log_message(f'导出路径无效: {filename}', 'ERROR')
            self._show_toast('导出路径无效', '请选择有效的保存位置')
            return
        try:
            content = self.log_text.get('1.0', tk.END)
            with target.open('w', encoding='utf-8') as f:
                f.write(content)
            self.log_message(f'日志已导出到: {target}')
            self._show_toast('日志已导出', str(target))
        except Exception as e:
            self.log_message(f'导出日志失败: {e}', 'ERROR')

    def _open_logs_dir(self):
        log_dir = _PROJECT_DIR / 'logs'
        with contextlib.suppress(Exception):
            log_dir.mkdir(exist_ok=True)
        try:
            os.startfile(str(log_dir))
        except Exception as e:
            self.log_message(f'打开日志目录失败: {e}', 'ERROR')

    @staticmethod
    def _pick_log_font():
        """日志字体: 等宽+CJK 优先，回落链保证中文不作豆腐块。"""
        for fam in ('Microsoft YaHei Mono', 'Microsoft YaHei UI', 'NSimSun', 'SimSun', 'Consolas'):
            try:
                if fam.lower() in (x.lower() for x in tkfont.families()):
                    return (fam, 9)
            except Exception:
                continue
        return ('Microsoft YaHei UI', 9)

    def _run_env_checks(self):
        errors = []
        if not _PYTHON_EXE:
            errors.append('未找到 Python 解释器！请安装 Python 3.12+ 并确保 python 在 PATH 中，' '或在项目目录下创建虚拟环境 (.venv313)')
        elif not (_PROJECT_DIR / 'fastapi_app').is_dir():
            errors.append(f'项目目录无效: {_PROJECT_DIR}\n未找到 fastapi_app 目录，请检查 erp_project_path.txt')
        if not (_PROJECT_DIR / '.env').is_file():
            errors.append(f'未找到 .env 配置文件: {_PROJECT_DIR / ".env"}\n' '服务器启动将因缺少 SECRET_KEY 而失败')
        if errors:
            self.root.after(500, lambda: messagebox.showwarning('环境检查警告', '\n\n'.join(errors)))
            for err in errors:
                self.log_message(err, 'ERROR')

    def _get_env_value(self, key):
        """.env 逐行解析: 跳过注释行，partition('=') 取首个等号左值。"""
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
                    v = v.strip()
                    # v5.40(审查 #19): 剥掉成对引号 —— `REDIS_PASSWORD="abc"` 带引号去 AUTH 必失败
                    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                        v = v[1:-1]
                    return v
        except Exception as e:
            # D10: .env 读取失败会让 Redis AUTH 莫名失败，必须留痕(仍返回空，不改失败语义)
            self._msg_queue.put(('log', {'text': f'读取 .env 失败({key}): {type(e).__name__}: {e}', 'level': 'WARNING'}))
        return ''
    # ===================== Redis =====================

    def _find_redis(self):
        custom = str(_APP_CONFIG.get('redis_exe') or '')
        redis_exe = custom if (custom and Path(custom).is_file()) else None
        if not redis_exe:
            redis_exe = next((str(p) for p in _REDIS_EXE_PATHS if p.is_file()), None)
        redis_conf = next((str(p) for p in _REDIS_CONF_PATHS if p.is_file()), None)
        return redis_exe, redis_conf

    def _is_redis_running(self):
        """Redis 可用性: TCP 连通 + RESP 协议 PING/AUTH 确认。

        仅端口探测会误报(服务 Paused / 密码不匹配时端口仍可能短暂通过)，故发 PING:
        +PONG 可用; -NOAUTH 需先用 .env 的 REDIS_PASSWORD 认证后再 PING。
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
                    sock.sendall(f'*2\r\n$4\r\nAUTH\r\n${len(password)}\r\n{password}\r\n'.encode())
                    if not sock.recv(64).startswith(b'+OK'):
                        return False
                    sock.sendall(b'*1\r\n$4\r\nPING\r\n')
                    return sock.recv(64).startswith(b'+PONG')
            return False
        except Exception:
            return False

    def _start_redis(self):
        """启动 Redis(阻塞最长 ~7.5s，必须放后台线程)。失败不阻断开发模式启动。"""
        if self._is_redis_running():
            return True
        redis_exe, redis_conf = self._find_redis()
        if not redis_exe:
            self._msg_queue.put(('log', {'text': 'Redis 未安装，请在配置中指定路径或安装 Redis for Windows', 'level': 'WARNING'}))
            return False
        try:
            password = self._get_env_value('REDIS_PASSWORD')
            common = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=False, creationflags=_NO_WINDOW if _IS_WINDOWS else 0)
            self._msg_queue.put(('log', {'text': f'正在启动 Redis: {redis_exe}'}))
            # argv[0] 字面量 + executable= 传入校验过的绝对路径
            if redis_conf and password:
                argv = ['redis-server', redis_conf, '--requirepass', password]
            elif redis_conf:
                argv = ['redis-server', redis_conf]
            elif password:
                argv = ['redis-server', '--requirepass', password]
            else:
                argv = ['redis-server']
            self._redis_process = subprocess.Popen(argv, executable=redis_exe, **common)
            threading.Thread(target=self._read_stdout, args=(self._redis_process, None), daemon=True).start()
            for _ in range(15):
                time.sleep(0.5)
                if self._is_redis_running():
                    self._msg_queue.put(('log', {'text': f'Redis 启动成功 (PID: {self._redis_process.pid})'}))
                    return True
                if self._redis_process.poll() is not None:
                    self._msg_queue.put(('log', {'text': f'Redis 进程意外退出 (退出码: ' f'{self._redis_process.returncode})', 'level': 'ERROR'}))
                    return False
            self._msg_queue.put(('log', {'text': f'Redis 启动超时，请检查端口 {_PORTS.redis} 是否被占用', 'level': 'WARNING'}))
            return False
        except Exception as e:
            self._msg_queue.put(('log', {'text': f'Redis 启动失败: {e}', 'level': 'ERROR'}))
            return False

    def _stop_owned_redis(self):
        """只终止本管理器自己启动的 _redis_process(terminate → wait(3) → kill)。

        ★ 绝不按端口强杀 6379: 该端口可能由 erp-redis Windows 服务承载，
        无差别端口强杀会误杀原生服务进程，而本管理器无法把原生 Windows 服务
        重新拉起(那是 SCM 的职责) —— 这正是 v5.34 的致命隐患，本版彻底移除。
        """
        proc = self._redis_process
        self._redis_process = None
        if not proc or proc.poll() is not None:
            return
        self._msg_queue.put(('log', {'text': f'正在终止管理器自有 Redis 进程 (PID: {proc.pid})...'}))
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            with contextlib.suppress(Exception):
                proc.kill()
        self._msg_queue.put(('log', {'text': '管理器自有 Redis 进程已终止'}))

    def _wait_redis_svc_running(self, name, timeout=30):
        """轮询 _svc_state 直到 RUNNING(Redis 服务就绪确认，不涉 nssm/HTTP)。

        v5.40(审查 #20): 原 _wait_svc_running —— 加 redis 前缀与 NSSM 侧 _wait_service_* 区分。
        命名约定: _redis_svc_*=Redis 原生服务(仅 sc); _service_*=NSSM 托管服务;
        _svc_state/_svc_pid=两者共用的 sc 查询原语。
        """
        deadline = time.monotonic() + max(1, timeout)
        while time.monotonic() < deadline:
            if 'RUNNING' in self._svc_state(name).upper():
                return True
            time.sleep(1)
        return False

    def _wait_redis_svc_stopped(self, name, timeout=30):
        """轮询 _svc_state 直到 STOPPED(Redis 服务停止确认)。v5.40(审查 #20): 原 _wait_svc_stopped。"""
        deadline = time.monotonic() + max(1, timeout)
        while time.monotonic() < deadline:
            state = self._svc_state(name).upper()
            if 'STOPPED' in state and 'STOP_PENDING' not in state:
                return True
            time.sleep(1)
        return False

    def _wait_redis_services_running(self, timeout=30):
        """确保配置里的 Redis 服务全部 RUNNING。

        逐服务:
          - STATE 含 RUNNING → 跳过;
          - _svc_absent()(明确「未安装」) → 记 WARNING 并跳过(视为该服务不存在);
          - 其它(含「未知」) → sc start 后轮询 _svc_state 直到 RUNNING。
        ★ v5.36: 「未知」(查询失败) 不得计入「未安装」而跳过 —— 只有明确未安装才跳过。
        返回 (是否全部就绪, 未就绪服务名列表)。
        """
        services = list(_APP_CONFIG.get('redis_services') or [])
        not_ready = []
        for name in services:
            state = self._svc_state(name)
            if 'RUNNING' in state.upper():
                continue
            if self._svc_absent(state):
                self._msg_queue.put(('log', {'text': f'Redis 服务 {name} 未安装，跳过', 'level': 'WARNING'}))
                continue
            if self._svc_unknown(state):
                self._msg_queue.put(('log', {'text': f'Redis 服务 {name} 状态未知（sc 查询失败），按未就绪处理并尝试启动', 'level': 'WARNING'}))
            self._msg_queue.put(('log', {'text': f'正在启动 Redis 服务 {name}...'}))
            try:
                r = subprocess.run(['sc', 'start', name], **_cap(30))
                code, out = r.returncode, ((r.stdout or '') + (r.stderr or '')).strip()
                if code != 0:
                    self._msg_queue.put(('log', {'text': f'{name} sc start 返回非零(退出码 {code}): {out or "无输出"}', 'level': 'WARNING'}))
            except subprocess.TimeoutExpired:
                self._msg_queue.put(('log', {'text': f'{name} sc start 命令超时(30s)', 'level': 'ERROR'}))
            except Exception as e:
                self._msg_queue.put(('log', {'text': f'{name} sc start 异常: {type(e).__name__}: {e}', 'level': 'ERROR'}))
            if self._wait_redis_svc_running(name, timeout):
                self._msg_queue.put(('log', {'text': f'Redis 服务 {name} 已确认 RUNNING'}))
            else:
                not_ready.append(name)
        return (len(not_ready) == 0), not_ready

    def _stop_redis_services(self, timeout=30):
        """停止配置里的 Redis 服务。

        逐服务: RUNNING(或 STOP_PENDING) → sc stop + 轮询 _svc_state 直到 STOPPED;
        明确 STOPPED / 明确「未安装」→ 跳过; 「未知」→ 保守尝试停止(不跳过)。
        ★ 失败原因必须带真实文本(命令退出码 / stdout / 超时)，绝不静默吞。
        ★ v5.36: 只有 _svc_absent() 才允许跳过；「未知」不得被当作未安装而不停。
        返回 (是否全部成功, 失败服务名列表)。
        """
        services = list(_APP_CONFIG.get('redis_services') or [])
        failed = []
        for name in services:
            state = self._svc_state(name)
            if self._svc_absent(state):
                continue
            if self._svc_unknown(state):
                self._msg_queue.put(('log', {'text': f'Redis 服务 {name} 状态未知（sc 查询失败），保守尝试停止', 'level': 'WARNING'}))
            elif 'STOPPED' in state.upper() and 'STOP_PENDING' not in state.upper():
                continue
            self._msg_queue.put(('log', {'text': f'正在停止 Redis 服务 {name}...'}))
            try:
                r = subprocess.run(['sc', 'stop', name], **_cap(30))
                code, out = r.returncode, ((r.stdout or '') + (r.stderr or '')).strip()
                if code != 0:
                    self._msg_queue.put(('log', {'text': f'{name} sc stop 返回非零(退出码 {code}): {out or "无输出"}', 'level': 'WARNING'}))
            except subprocess.TimeoutExpired:
                self._msg_queue.put(('log', {'text': f'{name} sc stop 命令超时(30s)', 'level': 'ERROR'}))
            except Exception as e:
                self._msg_queue.put(('log', {'text': f'{name} sc stop 异常: {type(e).__name__}: {e}', 'level': 'ERROR'}))
            if self._wait_redis_svc_stopped(name, timeout):
                self._msg_queue.put(('log', {'text': f'Redis 服务 {name} 已确认 STOPPED'}))
            else:
                failed.append(name)
                self._msg_queue.put(('log', {'text': f'{name} 未在超时内确认 STOPPED(仍为 STOP_PENDING 或拒绝访问)', 'level': 'ERROR'}))
        return (len(failed) == 0), failed

    def _ensure_redis_ready(self):
        """开发/生产启动前的 Redis 就绪保障(取代原来直接调 _start_redis 的做法)。

        ① 调 _wait_redis_services_running() 确保配置里的 Redis 服务全部 RUNNING;
        ② 若有任一 Redis 服务就绪 → 用 _is_redis_running()(RESP PING/AUTH)有界重试复核
           6379 实际连通性并以它为准(仅端口探测会误报，PING 才是判据);
        ③ 仅当**配置里所有** Redis 服务都【明确『未安装』】才回落 _start_redis()，即
           管理器有意的自有 redis-server.exe 进程方案;
        ④ 回落路径失败仅记 WARNING，不阻断开发模式启动(保持 v5.33 基线行为)。
        ★ v5.36: 「未知」(查询失败) 不得被当作未安装 —— 否则会再起自有 redis-server 抢 6379。
        """
        services = list(_APP_CONFIG.get('redis_services') or [])
        wait_s = int(_APP_CONFIG.get('redis_service_wait_s') or 30)
        all_ready, not_ready = self._wait_redis_services_running(wait_s)
        states = {name: self._svc_state(name) for name in services}
        any_running = any('RUNNING' in st.upper() for st in states.values())
        all_absent = bool(services) and all(self._svc_absent(st) for st in states.values())
        if any_running:
            reachable = False
            for _ in range(5):  # D3: 有界重试 5 次(每次 1s) —— sc start 返回后 Redis 常仍在加载 RDB
                if self._is_redis_running():
                    reachable = True
                    break
                time.sleep(1)
            if reachable:
                self._msg_queue.put(('log', {'text': 'Redis 服务就绪，6379 连通性复核通过'}))
            else:
                self._msg_queue.put(('log', {'text': 'Redis 服务显示 RUNNING，但 6379 连通性复核失败(请检查密码/端口)', 'level': 'WARNING'}))
            return reachable
        if all_absent:
            self._msg_queue.put(('log', {'text': '未检测到 Redis 服务，回落到托管自有 redis-server 进程'}))
            ok = self._start_redis()
            if not ok:
                self._msg_queue.put(('log', {'text': '自有 Redis 进程回落启动失败，不阻断启动', 'level': 'WARNING'}))
            return ok
        # 服务存在但未能在超时内 RUNNING
        self._msg_queue.put(('log', {'text': f'Redis 服务未就绪: {"、".join(not_ready) or "未知"} (all_ready={all_ready})', 'level': 'WARNING'}))
        return False
    # ===================== 进程终止 / 端口清理 =====================

    def _find_port_pids(self, port):
        pids = set()
        try:
            result = subprocess.run(['netstat', '-ano'], **_cap(10))
            for line in (result.stdout or '').splitlines():
                # v5.40(审查 #23): 只认 LISTENING —— TIME_WAIT 会自行过期且不阻塞重绑，
                # 纳入击杀目标只会产生多余的击杀尝试。
                if 'LISTENING' not in line:
                    continue
                parts = line.split()
                if (len(parts) >= 5 and ':' in parts[1] and parts[1].rsplit(':', 1)[-1] == str(port) and parts[-1].isdigit() and int(parts[-1]) > 0):
                    pids.add(parts[-1])
        except Exception as e:
            # D10: netstat 失败会让端口释放静默失效 —— 必须留痕，不改失败语义(仍返回空)
            self._msg_queue.put(('log', {'text': f'netstat 查询端口 {port} 占用失败: {type(e).__name__}: {e}', 'level': 'WARNING'}))
        return list(pids)

    def _kill_port_sync(self, port):
        """3 轮重试终止端口占用进程(应对 PID 复用 / 延迟释放)。"""
        for _ in range(3):
            pids = self._find_port_pids(port)
            if not pids:
                return
            _taskkill_many(pids)
            time.sleep(0.5)

    # v5.40(审查 #12): 删除死代码 _collect_process_tree —— 全文件无调用点(taskkill /T 已覆盖
    # 进程树清理)，且依赖在新版 Windows 上已移除的 wmic，留着只会误导维护。

    def _kill_process_tree(self, pid):
        if not pid:
            return
        if _IS_WINDOWS:
            _taskkill(pid)
        else:
            with contextlib.suppress(Exception):
                os.kill(pid, 15)

    def _release_ports(self):
        """释放 API/WEB 端口。v5.40(审查 #6): 击杀前统一经 _get_port_occupier 留痕占用者 ——
        按端口击杀是清场工具本职，但用户必须知道杀了谁；留痕失败绝不阻断清场主流程(D15 教训)。"""
        for port in (_PORTS.api, _PORTS.web):
            try:
                for pid, pname in _get_port_occupier(port):
                    self._msg_queue.put(('log', {'text': f'端口 {port} 被 {pname}(PID {pid}) 占用，即将释放'}))
            except Exception as e:
                self._msg_queue.put(('log', {'text': f'查询端口占用者失败(不影响清场): {type(e).__name__}: {e}', 'level': 'WARNING'}))
            self._kill_port_sync(port)
    # ===================== 子进程日志读取 =====================

    @staticmethod
    def _decode_line(raw_line):
        """级联解码: utf-8 → utf-8-sig → gb18030 → cp936 → 系统首选; 全败则 replace。"""
        if not raw_line:
            return ''
        preferred = locale.getpreferredencoding(False) or ''
        tried = set()
        for enc in ['utf-8', 'utf-8-sig', 'gb18030', 'cp936'] + ([preferred] if preferred else []):
            if enc.lower() in tried:
                continue
            tried.add(enc.lower())
            try:
                return raw_line.decode(enc, errors='strict').strip()
            except Exception:
                continue
        return raw_line.decode('utf-8', errors='replace').strip()

    def _read_stdout(self, proc, prefix=None):
        """后端/Redis stdout → 队列; 攒 10 行批量入队，减少主线程唤醒。"""
        try:
            if not proc.stdout:
                return
            try:
                batch = []
                for raw_line in proc.stdout:
                    line = self._decode_line(raw_line) if isinstance(raw_line, bytes) else str(raw_line).strip()
                    if not line:
                        continue
                    batch.append(f'{prefix} {line}' if prefix else line)
                    if len(batch) >= 10:
                        self._msg_queue.put(('log_batch', {'lines': batch[:], 'level': 'INFO'}))
                        batch.clear()
                if batch:
                    self._msg_queue.put(('log_batch', {'lines': batch, 'level': 'INFO'}))
            finally:
                with contextlib.suppress(Exception):
                    proc.stdout.close()
        except Exception as e:
            self._msg_queue.put(('log', {'text': f'读取日志异常: {e}', 'level': 'ERROR'}))

    def _read_frontend_stdout(self, proc):
        """前端 stdout 加 [WEB] 前缀; 含 error/exception/failed 关键字标 ERROR。

        v5.40(审查 #9): 攒 10 行后整批一条 log_batch 消息(逐行级别)入队 —— 此前逐行 put，
        _poll_queue 每 200ms 只消费 30 条(=150 行/秒上限)，vite 报错风暴时队列积压、UI 滞后。
        """
        try:
            if not proc.stdout:
                return
            batch = []
            for raw_line in proc.stdout:
                text = self._decode_line(raw_line) if isinstance(raw_line, bytes) else str(raw_line).strip()
                if not text:
                    continue
                low = text.lower()
                batch.append((f'[WEB] {text}', 'ERROR' if any(k in low for k in ('error', 'exception', 'failed')) else 'INFO'))
                if len(batch) >= 10:
                    self._msg_queue.put(('log_batch', {'lines': batch[:], 'level': 'INFO'}))
                    batch.clear()
            if batch:
                self._msg_queue.put(('log_batch', {'lines': batch, 'level': 'INFO'}))
        except Exception as e:
            self._msg_queue.put(('log', {'text': f'读取前端日志异常: {e}', 'level': 'ERROR'}))
    # ===================== 开发模式: 5 步流水线 =====================

    def start_dual_dev(self):
        self._start_dual_server('开发模式（前后端）')

    def stop_dual_dev(self):
        # 与 start_dual_dev 对称: spawn 前同步登记忙状态，闭合 TOCTOU 重入窗口。
        # 此前本路径不起任何忙标志 → 停止的数秒窗口内 _mode 恒为 'dual_dev' →
        # _is_busy() 为 False → 再次点击可并发起第二个 _stop_dual_worker(重复 taskkill/清端口/停 Redis)。
        # ★ 本方法由 toggle_dev 在主线程调用，此处直接赋值 _mode 符合 §线程契约
        #   (line 462-464 / 658-663: 状态只允许主线程变更; 后台线程须经 state_set)。
        self._mode = 'stopping'
        self._update_all_ui()
        threading.Thread(target=self._stop_dual_worker, args=('开发模式',), daemon=True).start()

    def _start_dual_server(self, label):
        """入口守卫(防 TOCTOU): 过渡态/已有服务/缺解释器/缺前端目录一律拒绝。"""
        # v5.40(P2): 原元组含死字面量 'restarting'(从无写入点) → 已移除。
        #   本守卫真实语义 = 仅拒绝「正在启动」; 'stopping' 不在此列，
        #   因其已由 toggle_dev 经 _is_busy() 前置拦截。
        if self._mode == 'starting':
            self.log_message('开发模式正在启动中，请稍候', 'WARNING')
            return
        if self._mode != 'none':
            self.log_message('已有服务在运行，请先停止后再启动', 'WARNING')
            return
        if not _PYTHON_EXE:
            self.log_message('无法启动: 未找到 Python 解释器，请安装 Python 并确保在 PATH 中', 'ERROR')
            messagebox.showerror('启动失败', '未找到可用的 Python 解释器！\n\n' '请安装 Python 3.12+ 并确保 python 在 PATH 中，\n' '或在项目目录下创建虚拟环境 (.venv313)')
            return
        if not _FRONTEND_DIR.exists():
            self.log_message(f'前端目录不存在: {_FRONTEND_DIR}', 'ERROR')
            messagebox.showerror('错误', f'前端目录不存在:\n{_FRONTEND_DIR}')
            return
        self._mode = 'starting'
        self._startup_steps = ['停止生产模式', '检查Redis服务', '启动后端服务', '启动前端服务', '完成']
        self._startup_progress, self._startup_current_step = 0, ''
        self._update_all_ui()
        self.log_message(f'正在启动{label}...')
        self.status_label.config(text=f'正在启动{label}...')
        threading.Thread(target=self._start_dual_worker, args=(label,), daemon=True).start()

    def _start_dual_worker(self, label):
        """① 互斥: 停生产(NamedTuple 三元组契约) ② 清端口 → 转 _start_dual_thread 继续 ③④⑤。"""
        try:
            self._msg_queue.put(('startup_progress', {'step': self._startup_steps[0], 'progress': 1, 'total': len(self._startup_steps)}))
            result = self._ensure_production_stopped()
            if not result.ok:
                self._msg_queue.put(('log', {'text': f'切换失败: {result.reason}', 'level': 'ERROR'}))
                self._msg_queue.put(('dual_failed', {'label': label, 'reason': result.reason}))
                return
            if result.stopped_any:
                self._msg_queue.put(('log', {'text': '已自动停止生产模式'}))
                self._msg_queue.put(('toast', {'title': '已自动停止生产模式', 'desc': '开发/生产互斥托管'}))
            # v5.40(审查 #18): 端口清理统一由 _start_dual_thread 负责(此处原本重复清一次，双倍 netstat)
            self._start_dual_thread(label)
        except Exception as e:
            # 后台线程无 try/except 会静默终止，导致启动卡在 'starting' 且无任何日志
            self._msg_queue.put(('log', {'text': f'启动流程异常: {e}', 'level': 'ERROR'}))
            self._msg_queue.put(('dual_failed', {'label': label, 'reason': str(e)}))

    def _start_dual_thread(self, label):
        """③ Redis → ④ 后端(30×1s) → ⑤ 前端(60×1s); 任一未就绪则回滚全部已起进程。"""
        try:
            self._msg_queue.put(('log', {'text': '正在清理端口...'}))
            self._release_ports()
            self._msg_queue.put(('startup_progress', {'step': self._startup_steps[1], 'progress': 2, 'total': len(self._startup_steps)}))
            if not self._ensure_redis_ready():
                self._msg_queue.put(('log', {'text': '警告: Redis 未就绪，部分功能可能不可用', 'level': 'WARNING'}))
            self._msg_queue.put(('startup_progress', {'step': self._startup_steps[2], 'progress': 3, 'total': len(self._startup_steps)}))
            env = os.environ.copy()
            env.update({'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1', 'PYTHONPATH': str(_PROJECT_DIR)})
            # argv[0] 字面量 'python' + executable= 校验过的解释器绝对路径
            self._process = subprocess.Popen(
                ['python', '-u', '-m', 'uvicorn', 'fastapi_app.main:app', '--host', '0.0.0.0',
                 '--port', str(_PORTS.api), '--log-level', 'info', '--reload', '--reload-dir', 'fastapi_app'],
                executable=_PYTHON_EXE, cwd=str(_PROJECT_DIR), env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, creationflags=_NO_WINDOW if _IS_WINDOWS else 0, text=False)
            self._msg_queue.put(('log', {'text': f'后端进程已启动 (PID: {self._process.pid})'}))
            threading.Thread(target=self._read_stdout, args=(self._process, None), daemon=True).start()
            if not self._wait_http(f'http://127.0.0.1:{_PORTS.api}/api/health', 30):
                self._msg_queue.put(('log', {'text': '后端启动失败或健康检查未通过', 'level': 'ERROR'}))
                self._abort_process(self._process, '后端')
                self._process = None
                self._msg_queue.put(('dual_failed', {'label': label, 'reason': '后端未就绪'}))
                return
            self._msg_queue.put(('startup_progress', {'step': self._startup_steps[3], 'progress': 4, 'total': len(self._startup_steps)}))
            frontend_env = os.environ.copy()
            frontend_env['BACKEND_INTERNAL_URL'] = f'http://127.0.0.1:{_PORTS.api}'
            self._frontend_process = subprocess.Popen(
                [_NPM_CMD, 'run', 'dev', '--', '--port', str(_PORTS.web)], cwd=str(_FRONTEND_DIR),
                env=frontend_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=_NO_WINDOW if _IS_WINDOWS else 0, text=False)
            self._msg_queue.put(('log', {'text': f'前端进程已启动 (PID: {self._frontend_process.pid})'}))
            threading.Thread(target=self._read_frontend_stdout, args=(self._frontend_process,), daemon=True).start()
            if not self._wait_http(f'http://127.0.0.1:{_PORTS.web}/', 60):
                self._msg_queue.put(('log', {'text': '前端启动失败或健康检查未通过', 'level': 'ERROR'}))
                # 尤其重要: 前后端全部终止，不留孤儿进程占端口
                self._abort_process(self._frontend_process, '前端')
                self._abort_process(self._process, '后端')
                self._process, self._frontend_process = None, None
                self._msg_queue.put(('dual_failed', {'label': label, 'reason': '前端未就绪'}))
                return
            self._msg_queue.put(('startup_progress', {'step': self._startup_steps[4], 'progress': 5, 'total': len(self._startup_steps)}))
            self._msg_queue.put(('dual_started', {'label': label}))
        except Exception as e:
            # v5.40 修复(审查 #2): 兜底 except 必须先清理已启动进程再置空句柄。
            # 此前直接置 None —— 若异常发生在后端 Popen 之后(最现实: 机器无 Node 时前端
            # Popen(['npm.cmd'...]) 抛 FileNotFoundError)，后端成孤儿占 5002，UI 显示失败
            # 但实际在跑、无人监控。_abort_process 对 None 安全，两条显式失败分支同款清理序。
            self._abort_process(self._frontend_process, '前端')
            self._abort_process(self._process, '后端')
            self._process, self._frontend_process = None, None
            self._msg_queue.put(('dual_failed', {'label': label, 'reason': f'异常: {e}'}))

    @staticmethod
    def _wait_http(url, attempts, timeout=2):
        """轮询 HTTP 健康检查: attempts 次，每次间隔 1s。直连，不走系统代理。"""
        for _ in range(attempts):
            try:
                _OPENER_DIRECT.open(url, timeout=timeout)
                return True
            except Exception:
                time.sleep(1)
        return False

    def _abort_process(self, proc, name):
        """终止未就绪进程树并等待回收(避免端口被孤儿占用)。"""
        if proc and proc.poll() is None:
            self._msg_queue.put(('log', {'text': f'正在终止未就绪的{name}进程 (PID: {proc.pid})...'}))
            self._kill_process_tree(proc.pid)
            with contextlib.suppress(Exception):
                proc.wait(timeout=3)

    def _on_dual_started(self, label):
        backend_alive = self._process and self._process.poll() is None
        frontend_alive = self._frontend_process and self._frontend_process.poll() is None
        if not (backend_alive and frontend_alive):
            self.log_message(f'{label}启动后进程已退出，正在清理', 'ERROR')
            self._abort_process(self._frontend_process, '前端')
            self._abort_process(self._process, '后端')
            self._set_mode_none()
            return
        self._mode = 'dual_dev'
        self._update_all_ui()
        self.status_label.config(text=f'{label}运行中')
        self.log_message(f'{label}启动成功')
        self.log_message(f'  → 后端: http://localhost:{_PORTS.api}')
        self.log_message(f'  → 前端: http://localhost:{_PORTS.web}')
        self._show_toast(f'{label}已启动', f'后端 :{_PORTS.api} · 前端 :{_PORTS.web}')

    def _on_dual_failed(self, label, reason):
        self._set_mode_none()
        self.status_label.config(text=f'{label}启动失败: {reason}')
        self.log_message(f'{label}启动失败: {reason}', 'ERROR')

    def _stop_dual_worker(self, label):
        """停止开发: 终止前端/后端进程树 + 停自有 Redis 进程 + 释放端口 + 状态复位。

        ★ 只终止管理器自有的 Redis 进程，不动托管的 Redis 服务(共享基础设施)。
        """
        self._msg_queue.put(('log', {'text': f'正在停止{label}...'}))
        # ★ v5.40 补丁: 停止路径必须保证状态复位 —— 若中途抛异常(如 taskkill/端口释放失败)，
        #   原实现会跳过 line「state_set(mode='none')」而永久卡在 _mode='stopping'，
        #   反而让按钮永久禁用。故用 try/finally 兜底复位，并对异常留痕不静默。
        try:
            frontend_proc, backend_proc = self._frontend_process, self._process
            self._frontend_process, self._process = None, None
            for proc, name in ((frontend_proc, '前端'), (backend_proc, '后端')):
                if proc and proc.poll() is None:
                    self._msg_queue.put(('log', {'text': f'正在终止{name}进程树 (PID: {proc.pid})...'}))
                    self._kill_process_tree(proc.pid)
                    with contextlib.suppress(Exception):
                        proc.wait(timeout=3)
                    self._msg_queue.put(('log', {'text': f'{name}进程已终止'}))
            self._stop_owned_redis()
            self._release_ports()
        except Exception as e:
            self._msg_queue.put(('log', {'text': f'停止{label}出错: {type(e).__name__}: {e}', 'level': 'ERROR'}))
        finally:
            # v5.40(审查 #7): _mode 经主线程消息复位，不再后台直写。
            # finally 保证 'stopping' → 'none' 流转闭合(无论正常/异常均复位，不产生死状态)。
            self._msg_queue.put(('state_set', {'mode': 'none'}))
            self._msg_queue.put(('log', {'text': f'{label}已停止，端口已释放'}))
            self._msg_queue.put(('toast', {'title': f'{label}已停止', 'desc': '端口已释放'}))

    def _set_mode_none(self):
        self._mode = 'none'
        if not self._shutting_down:
            self._update_all_ui()
    # ===================== 生产模式: Windows 服务(NSSM)控制 =====================

    def _find_nssm(self):
        """NSSM 定位: 配置项优先(校验 .exe 后缀) → PATH → 候选路径。"""
        custom = str(_APP_CONFIG.get('nssm_path') or '')
        if custom and Path(custom).is_file() and Path(custom).suffix.lower() == '.exe':
            return custom
        found = shutil.which('nssm')
        if found:
            return found
        return next((str(c) for c in _NSSM_CANDIDATES if c.is_file()), None)

    def _svc_state(self, name):
        """返回：'未安装' | '未知' | 查询到的 STATE 文本（如 '4 RUNNING' / '1 STOPPED' / '3 STOP_PENDING'）。

        ★ 语义区分（v5.36 修正，勿回退）：
          只有 rc == 1060（ERROR_SERVICE_DOES_NOT_EXIST）或输出明确含 '1060' 才判「未安装」；
          其它非 0 返回码（5=拒绝访问、被安全软件拦截、超时、异常）一律判「未知」。
          绝不能把「查不出来」当成「不存在」——否则 _ensure_production_stopped 会静默跳过
          仍在运行的生产服务，开发模式随即抢占 5002/3000，与生产互相厮杀。
        解析逻辑在模块级 _parse_sc_state()（纯函数，可单测）。
        """
        try:
            r = subprocess.run(['sc', 'query', name], **_cap(5))
            out, code = (r.stdout or '') + (r.stderr or ''), r.returncode
        except Exception:
            return '未知'
        return _parse_sc_state(code, out)

    @staticmethod
    def _svc_absent(state):
        """服务状态的「未安装」判定（统一入口，避免 '未安装' 字面量散落各调用点）。"""
        return '未安装' in state

    @staticmethod
    def _svc_unknown(state):
        """服务状态的「查询失败/未知」判定 —— 语义上必须与「未安装」严格区分。"""
        return state == '未知'

    def _svc_pid(self, name):
        """sc queryex 取服务当前进程 PID; 未运行返回 None。"""
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

    def _wait_service_stopped(self, name, timeout=45):
        """确认 STOPPED; 有 nssm 时先发 nssm stop。

        若在 STOP_PENDING 期间强杀被管进程，会被 AppExit Default Restart 判定为崩溃而
        自动重启、与目标模式抢占端口 —— 所以必须等 STOPPED 确认，不能只看 returncode。
        """
        nssm = self._find_nssm()
        if nssm:
            with contextlib.suppress(Exception):
                subprocess.run(['nssm', 'stop', name], executable=nssm, **_cap(15))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if 'STOPPED' in self._svc_state(name):
                return True
            time.sleep(1)
        return False

    @staticmethod
    def _probe_http(url, timeout=2):
        """单次 HTTP 探针: 无异常即视为通过。直连，不走系统代理。"""
        try:
            _OPENER_DIRECT.open(url, timeout=timeout)
            return True
        except Exception:
            return False

    def _wait_service_running(self, name, timeout=60):
        """确认 RUNNING 且业务就绪。

        erp-prod 承载 API 与 nginx，故除现有 /api/health 外再探测前端专用探针
        /nginx-health，两项都通过才返回 True；两项探针与 RUNNING 判定共享同一
        timeout 预算(总超时不放大)。
        """
        need_web = name == _SVC_API
        deadline = time.monotonic() + timeout
        api_ready = web_ready = False
        while time.monotonic() < deadline:
            if 'RUNNING' not in self._svc_state(name):
                time.sleep(1)
                continue
            if not api_ready:
                api_ready = self._probe_http(f'http://127.0.0.1:{_PORTS.api}/api/health')
            if need_web and not web_ready:
                web_ready = self._probe_http(f'http://127.0.0.1:{_PORTS.web}/nginx-health')
            if api_ready and (web_ready or not need_web):
                return True
            time.sleep(1)
        return False

    def _service_restart_guard(self, on):
        """临时切换 NSSM 崩溃自动重启，防止强杀被管进程后 5 秒复活(§6.4)。

        on=True→AppExit Default Restart(恢复); on=False→Exit(停止前临时禁用)。
        任何 stop/restart/紧急全清路径都必须成对调用，finally 保证恢复。
        ★ 作用域(D6，勿误读): guard 只对 **NSSM 托管的 erp-prod / erp-arq 有效**
          (AppExit 是 NSSM 特有概念)。它对原生 Windows 服务 erp-redis / erp-redis-broker
          **完全没有作用** —— 两者不受 NSSM 管辖。因此紧急全清里 guard 不覆盖 Redis 服务
          的停止，属预期行为，并非遗漏。
        """
        nssm = self._find_nssm()
        if not nssm:
            return
        value = 'Restart' if on else 'Exit'
        for name in (_SVC_API, _SVC_ARQ):
            with contextlib.suppress(Exception):
                subprocess.run(['nssm', 'set', name, 'AppExit', 'Default', value], executable=nssm, **_cap(15))

    def _service_one(self, name, verb, nssm):
        """对单个服务执行 verb 并【确认目标状态】。返回 (ok, reason)。

        契约: ok=True 表示目标状态已确认达成; 失败必须带真实原因(拒绝访问/超时/异常文本)。
        绝不能用 except: pass 掩盖失败 —— 那正是 v5.33「停不掉」的根因之一(§6.2)。
        """
        argv = ['nssm', verb, name] if nssm else ['sc', verb, name]
        kwargs = _cap(30)
        if nssm:
            kwargs['executable'] = nssm
        try:
            r = subprocess.run(argv, **kwargs)
            code, out = r.returncode, ((r.stdout or '') + (r.stderr or '')).strip()
        except subprocess.TimeoutExpired:
            return False, f'{verb} 命令超时(30s)'
        except Exception as e:
            return False, f'{verb} 命令异常: {type(e).__name__}: {e}'
        if code != 0:
            return False, f'{verb} 命令失败(退出码 {code}): {out or "无输出"}'
        if verb in ('start', 'restart'):
            if self._wait_service_running(name):
                return True, None
            return False, f'{name} 未在超时内确认 RUNNING(可能被拒绝访问或启动即崩溃)'
        if verb == 'stop':
            if self._wait_service_stopped(name):
                return True, None
            return False, f'{name} 未在超时内确认 STOPPED(拒绝访问或仍为 STOP_PENDING)'
        return True, None

    def _service_cmd_sync(self, verb):
        """同步 start/stop/restart(后台线程内调用)，逐服务确认结果。

        stop/restart 前后成对禁用/恢复 NSSM 自动重启(finally 保证恢复)——
        若残留清理在 STOP_PENDING 期间强杀被管进程，服务会被 5 秒复活(§6.3/§6.4)。
        """
        nssm = self._find_nssm()
        guard_needed = verb in ('stop', 'restart')
        if guard_needed:
            self._service_restart_guard(False)
        failures = []
        try:
            for name in (_SVC_API, _SVC_ARQ):
                if '未安装' in self._svc_state(name):
                    self._msg_queue.put(('log', {'text': f'{name} 未安装，跳过 {verb}', 'level': 'WARNING'}))
                    continue
                ok, reason = self._service_one(name, verb, nssm)
                if ok:
                    self._msg_queue.put(('log', {'text': f'{name} {verb} 已生效'}))
                else:
                    failures.append((name, reason))
                    self._msg_queue.put(('log', {'text': f'{name} {verb} 失败: {reason}', 'level': 'ERROR'}))
        finally:
            if guard_needed:
                self._service_restart_guard(True)
        if failures:
            self._msg_queue.put(('toast', {'title': f'服务 {verb} 部分失败', 'desc': '、'.join(n for n, _ in failures)}))
        else:
            self._msg_queue.put(('toast', {'title': f'服务 {verb} 完成', 'desc': f'{_SVC_API} + {_SVC_ARQ}'}))
    class _ProdStopResult(NamedTuple):
        """_ensure_production_stopped 的返回值契约。

        三字段固定存在 —— 杜绝 v5.33 因超时分支返回 2 元组导致的
        ValueError: not enough values to unpack (expected 3, got 2)(§6.1)。
        """
        ok: bool
        reason: Optional[str]
        stopped_any: bool

    def _ensure_production_stopped(self):
        """切换开发前停止生产: 停 NSSM 服务 + 清手动启动的 prod_runner 残留。

        所有 return 分支一律返回 _ProdStopResult(3 字段)，从类型层面杜绝解包崩溃(§6.1)。
        全程禁用 NSSM 崩溃自动重启(§6.4): 若 _svc_state 因解码异常误报「未安装」，
        随后的 prod_runner 清理会误杀被管进程，AppExit Restart 会让服务 5 秒复活(§6.3)。
        ★ v5.36: 服务状态为「未知」(sc 查询失败，如拒绝访问)时按运行中保守处理，
          且若无法在超时内确认 STOPPED 则返回 ok=False 中止切换 —— 绝不静默放行去抢端口。
        """
        stopped_any = False
        nssm_existed = self._find_nssm() is not None
        if nssm_existed:
            self._service_restart_guard(False)
        try:
            for name in (_SVC_API, _SVC_ARQ):
                state = self._svc_state(name)
                if self._svc_absent(state):
                    continue
                unknown = self._svc_unknown(state)
                if unknown:
                    # ★ 半查询失败不得当「不存在」: 按运行中保守处理，宁可中止切换也不放行抢端口
                    self._msg_queue.put(('log', {'text': f'无法查询 {name} 状态（sc 查询失败），按运行中保守处理', 'level': 'WARNING'}))
                elif 'STOPPED' in state:
                    continue
                self._msg_queue.put(('log', {'text': f'正在停止生产服务 {name}...'}))
                if not self._wait_service_stopped(name):
                    reason = (f'{name} 状态未知且未能在超时内确认 STOPPED，已中止切换' if unknown
                              else f'{name} 停止超时（STOP_PENDING 未确认），已中止切换')
                    return self._ProdStopResult(False, reason, False)
                stopped_any = True
            if psutil is not None:  # 手动启动的 prod_runner 不受 NSSM 控制
                protected = {os.getpid()}
                for name in (_SVC_API, _SVC_ARQ):
                    pid = self._svc_pid(name)
                    if pid:
                        protected.add(pid)
                for p in psutil.process_iter(['pid', 'name', 'cmdline']):
                    try:
                        pid = p.info['pid']
                        if not pid or pid in protected:
                            continue
                        if 'prod_runner' in ' '.join(p.info['cmdline'] or []):
                            self._kill_process_tree(pid)
                            self._msg_queue.put(('log', {'text': f'已清理残留 prod_runner 进程 (PID: {pid})'}))
                            stopped_any = True
                    except Exception:
                        continue
            return self._ProdStopResult(True, None, stopped_any)
        finally:
            if nssm_existed:
                self._service_restart_guard(True)

    def _ensure_development_stopped(self):
        """切换生产前停止开发: 只停开发子进程，★不动 Redis★，重置 _mode='none'。返回 stopped_any。"""
        stopped_any = False
        for proc, name in ((self._frontend_process, '前端'), (self._process, '后端')):
            if proc and proc.poll() is None:
                self._msg_queue.put(('log', {'text': f'正在终止开发{name}进程树 (PID: {proc.pid})...'}))
                self._kill_process_tree(proc.pid)
                with contextlib.suppress(Exception):
                    proc.wait(timeout=5)
                self._msg_queue.put(('log', {'text': f'开发{name}进程已终止'}))
                stopped_any = True
        self._process, self._frontend_process = None, None
        # v5.40(审查 #7): _mode 经主线程消息复位(线程契约); state_set 内部会刷新 UI
        self._msg_queue.put(('state_set', {'mode': 'none'}))
        if stopped_any:
            self._msg_queue.put(('log', {'text': '开发模式已停止'}))
        return stopped_any
    # ===================== 生产模式: 启动 / 停止(互斥切换) =====================

    def start_prod(self):
        if self._is_busy():
            self.log_message('操作正在执行中，请稍候', 'WARNING')
            return
        self._prod_busy = True
        self._update_all_ui()
        self.log_message('正在启动生产模式...')
        threading.Thread(target=self._start_prod_worker, daemon=True).start()

    def stop_prod(self):
        if self._is_busy():
            self.log_message('操作正在执行中，请稍候', 'WARNING')
            return
        self._prod_busy = True
        self._update_all_ui()
        self.log_message('正在停止生产模式...')
        threading.Thread(target=self._stop_prod_worker, daemon=True).start()

    def _start_prod_worker(self):
        """互斥: 先停开发(不动 Redis) → 清端口 → 保障 Redis → 启动 NSSM 服务并确认 RUNNING。"""
        try:
            if self._ensure_development_stopped():
                self._msg_queue.put(('log', {'text': '已自动停止开发模式'}))
                self._msg_queue.put(('toast', {'title': '已自动停止开发模式', 'desc': '开发/生产互斥托管'}))
            self._release_ports()
            # Redis 生命周期归管理器: 生产启动前确保 erp-redis / erp-redis-broker 服务就绪
            if not self._ensure_redis_ready():
                self._msg_queue.put(('log', {'text': '警告: Redis 未就绪，生产服务可能无法连接缓存/broker', 'level': 'WARNING'}))
            self._service_cmd_sync('start')
        except Exception as e:
            self._msg_queue.put(('log', {'text': f'启动生产模式异常: {e}', 'level': 'ERROR'}))
        finally:
            # v5.40(审查 #7): _prod_busy 经主线程消息复位(线程契约); state_set 内部会刷新 UI
            self._msg_queue.put(('state_set', {'prod_busy': False}))
            self._msg_queue.put(('hosting_refresh', {}))

    def _stop_prod_worker(self):
        try:
            self._service_cmd_sync('stop')
        except Exception as e:
            self._msg_queue.put(('log', {'text': f'停止生产模式异常: {e}', 'level': 'ERROR'}))
        finally:
            # v5.40(审查 #7): _prod_busy 经主线程消息复位(线程契约)
            self._msg_queue.put(('state_set', {'prod_busy': False}))
            self._msg_queue.put(('hosting_refresh', {}))
    # ===================== 紧急停止(分级) =====================
    # 分级定级理由: Redis 是 ERP 的共享基础设施(缓存 6379 + broker 6380)，单击就停它
    # 不符合用户「默认只停自有进程树」的要求；但用户同时要求「一键紧急停止关闭所有正在
    # 运行的服务器」，所以单击必须能停掉当前模式(含生产模式的服务)，长按才进一步接管
    # Redis 服务与残留清理。

    def _on_stop_press(self, _event=None):
        """按下起长按计时器; 未满阈值松手 → 轻量停止。

        v5.40(P2 / QA O-2): 起计时器前先过统一守卫 —— 若此刻已在进行中/过渡态，
        直接拒绝且**不得**登记 _stop_hold_fired，否则上一轮的 _on_stop_release
        会因 fired 残留而空转，或长按全清在轻量停止刚结束的瞬间被误触发。
        """
        if not self._stop_entry_guard('紧急停止'):
            return
        self._stop_hold_fired = False
        self._cancel_hold_timer()
        self._stop_hold_after = self.root.after(self._full_stop_hold_ms, self._on_stop_hold)

    def _on_stop_release(self, _event=None):
        self._cancel_hold_timer()
        if self._stop_hold_fired:
            self._stop_hold_fired = False
            return
        self.emergency_stop_light()

    def _on_stop_hold(self):
        self._stop_hold_after = None
        self._stop_hold_fired = True
        self.emergency_stop_full()

    def _cancel_hold_timer(self):
        if self._stop_hold_after:
            with contextlib.suppress(Exception):
                self.root.after_cancel(self._stop_hold_after)
            self._stop_hold_after = None

    def _stop_entry_guard(self, action):
        """紧急停止统一入口守卫 (v5.40 P2 / QA O-2)。

        收口三类竞态:
        ① 已在进行中(_stop_in_progress) → 拒绝重复起 worker;
        ② 其它过渡态(_mode in starting/stopping) → 拒绝抢占同一批端口;
        ③ 生产命令在途(_prod_busy) → 拒绝与 _service_cmd_sync 交叉。

        ★ 必须由主线程调用(直接读写 _stop_in_progress，符合 §线程契约)。
        ★ 本守卫只判定不登记; _stop_in_progress 由调用方在守卫通过后立即置位，
          以保证「判定 → 置位」无间隙(TOCTOU 闭合)。
        """
        if self._stop_in_progress:
            self.log_message('操作正在执行中，请稍候', 'WARNING')
            return False
        if self._mode in ('starting', 'stopping'):
            self.log_message(f'当前处于{"启动" if self._mode == "starting" else "停止"}过渡态，请稍候再执行{action}', 'WARNING')
            return False
        if self._prod_busy:
            self.log_message(f'生产命令执行中，请稍候再执行{action}', 'WARNING')
            return False
        return True

    def emergency_stop_light(self):
        """单击: 停当前模式(开发进程树 / 生产 erp-prod+erp-arq) + 停自有 Redis 进程 + 释放 5002/3000。

        Redis 服务保持运行(共享基础设施)。
        """
        if not self._stop_entry_guard('紧急停止'):
            return
        self._stop_in_progress = True
        self.status_label.config(text='正在紧急停止（轻量）...')
        self.log_message('正在执行紧急停止（当前模式 + 自有进程 + 5002/3000）...')
        threading.Thread(target=self._light_stop_worker, daemon=True).start()

    def emergency_stop_full(self):
        """长按≥1.5s: 轻量停止 + 停 Redis 服务 + 扫游离残留 + 释放 6379。需二次确认。"""
        if not self._stop_entry_guard('紧急全清'):
            return
        redis_svcs = ' / '.join(_APP_CONFIG.get('redis_services') or [])
        if not messagebox.askyesno(
                '紧急全清确认',
                '将执行【全清（全部清场）】操作，影响面如下：\n\n'
                f'  1. 停止生产服务 {_SVC_API} / {_SVC_ARQ}（等待 STOPPED 确认，nginx 随之优雅关闭）\n'
                f'  2. 停止 Redis 服务 {redis_svcs}（缓存 6379 / broker 6380）\n'
                '  3. 终止本管理器启动的前端 / 后端进程树\n'
                '  4. 扫描并清理游离残留进程（排除服务被管进程）\n'
                f'  5. 释放端口 {_PORTS.api} / {_PORTS.web} / {_PORTS.redis}\n\n'
                '确定继续吗？'):
            self.log_message('已取消紧急全清')
            return
        self._stop_in_progress = True
        self.status_label.config(text='正在紧急全清...')
        self.log_message('正在执行紧急全清...')
        threading.Thread(target=self._full_stop_worker, daemon=True).start()

    def _do_light_stop(self):
        """轻量停止共用实现(后台线程内调用)。

        ① 开发模式运行中 → 停 dev 前后端进程树;
        ② 生产模式运行中 → _service_cmd_sync('stop') 停 erp-prod / erp-arq
           (等 STOPPED 确认，nginx 由 prod_runner 优雅关闭);
        ③ _stop_owned_redis() 仅终止管理器自有的 Redis 进程;
        ④ 释放 5002 / 3000;
        ⑤ Redis 服务保持运行(共享基础设施，单击不停)。
        """
        for proc, name in ((self._frontend_process, '前端'), (self._process, '后端')):
            if proc and proc.poll() is None:
                self._msg_queue.put(('log', {'text': f'正在终止{name}进程树 (PID: {proc.pid})...'}))
                self._kill_process_tree(proc.pid)
                with contextlib.suppress(Exception):
                    proc.wait(timeout=3)
                self._msg_queue.put(('log', {'text': f'{name}进程已终止 (PID: {proc.pid})'}))
        self._frontend_process, self._process = None, None
        prod_state = self._svc_state(_SVC_API)
        # ★ v5.36: 状态「未知」(sc 查询失败) 同样视为运行中 → 停生产，绝不放行抢端口
        if 'RUNNING' in prod_state.upper() or self._svc_unknown(prod_state) or self._prod_running:
            self._msg_queue.put(('log', {'text': '正在停止生产服务(nginx 将由 prod_runner 优雅关闭)...'}))
            self._service_cmd_sync('stop')
            # v5.40(审查 #7): _prod_running 经主线程消息复位(线程契约)
            self._msg_queue.put(('state_set', {'prod_running': False}))
        self._stop_owned_redis()
        # v5.40(审查 #6): 占用者留痕已统一收进 _release_ports(所有调用点都覆盖，含启动前清理)，
        # 此处不再单独做诊断查询 —— 可观测性代码失败不得扩散到清场主流程(D15 教训)。
        self._release_ports()      # ← 无论如何都要执行
        self._msg_queue.put(('log', {'text': f'端口已释放: {_PORTS.api}/{_PORTS.web}（Redis 服务保持运行）'}))

    def _light_stop_worker(self):
        try:
            self._do_light_stop()
            self._msg_queue.put(('toast', {'title': '已执行紧急停止', 'desc': f'已停止当前模式并释放端口 {_PORTS.api}/{_PORTS.web}'}))
        except Exception as e:
            self._msg_queue.put(('log', {'text': f'紧急停止出错: {e}', 'level': 'ERROR'}))
        finally:
            self._finish_stop()

    def _full_stop_worker(self):
        """全清: 轻量停止 + 停 Redis 服务 + 扫游离残留 + 释放 6379。

        ★ v5.36 关键次序(D11): guard(False) → [停 Redis 服务 + _kill_residual] → guard(True)
          —— _kill_residual() 必须仍在 guard 窗口内(guard 存在的唯一目的就是防止残留扫描
          误杀被管进程后 NSSM 5 秒复活，恢复早了等于窗口没覆盖它本该保护的对象)，
          端口释放则在 guard 恢复之后。
        ★ 6379 释放以 _stop_redis_services() 的 ok 门控(D2): 服务没停成还强杀端口会导致
          SCM 认为 RUNNING 但进程已死，状态不一致。
        """
        try:
            self._do_light_stop()
            self._msg_queue.put(('log', {'text': '正在停止 Redis 服务...'}))
            guard_applied = self._find_nssm() is not None
            if guard_applied:
                self._service_restart_guard(False)
            ok, failed = False, []
            try:
                try:
                    ok, failed = self._stop_redis_services()
                except Exception as e:  # D7: 异常按失败处理，且不得跳过残留清理
                    ok, failed = False, []
                    self._msg_queue.put(('log', {'text': f'停止 Redis 服务异常(按失败处理): {type(e).__name__}: {e}', 'level': 'ERROR'}))
                # ⑧ 残留扫描: 必须仍在 guard 窗口内
                self._kill_residual()
            finally:
                if guard_applied:
                    self._service_restart_guard(True)
            # ⑨ 释放 6379(guard 恢复之后，且以 ok 门控)
            if ok:
                self._msg_queue.put(('log', {'text': 'Redis 服务已全部停止'}))
                self._kill_port_sync(_PORTS.redis)
                self._msg_queue.put(('log', {'text': f'端口已释放: {_PORTS.redis}'}))
            else:
                self._msg_queue.put(('log', {'text': f'Redis 服务未能全部停止（{"、".join(failed) or "异常"}），已跳过 6379 强制释放以避免 SCM 状态不一致，请手工确认服务状态', 'level': 'ERROR'}))
            self._msg_queue.put(('toast', {'title': '已执行紧急全清', 'desc': '服务 + 残留进程已处理'}))
        except Exception as e:
            self._msg_queue.put(('log', {'text': f'紧急全清出错: {e}', 'level': 'ERROR'}))
        finally:
            # v5.40(审查 #7): _prod_running 经主线程消息复位(线程契约)
            self._msg_queue.put(('state_set', {'prod_running': False}))
            self._finish_stop()

    def _finish_stop(self):
        # v5.40(审查 #7): 状态复位经主线程消息(线程契约); state_set 内部会刷新 UI
        self._msg_queue.put(('state_set', {'mode': 'none', 'stop_in_progress': False}))
        if not self._shutting_down:
            self._msg_queue.put(('hosting_refresh', {}))

    def _kill_residual(self):
        """扫描并清理游离残留进程 —— 必须排除 NSSM 被管进程，否则触发 AppExit 复活(§6.3)。

        排除白名单: 本进程 PID、_SVC_API/_SVC_ARQ 的服务 PID 及其后代、cmdline 含
        prod_runner / arq_app 的进程。psutil 缺失时记 WARNING 并跳过，绝不做
        「python/node 宽特征」兜底 —— 那必然误杀服务工作进程，导致 5 秒自动重启。
        """
        if not _IS_WINDOWS:
            return
        if psutil is None:
            self._msg_queue.put(('log', {'text': '缺少 psutil，跳过残留进程清理（不做宽特征兜底）', 'level': 'WARNING'}))
            return
        roots = {os.getpid()}
        for name in (_SVC_API, _SVC_ARQ):
            pid = self._svc_pid(name)
            if pid:
                roots.add(pid)
        self._msg_queue.put(('log', {'text': '正在扫描游离残留进程...'}))
        victims = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                pid = proc.info['pid']
                if not pid or pid in roots:
                    continue
                cmdline = ' '.join(proc.info.get('cmdline') or [])
                low = cmdline.lower()
                pname = (proc.info.get('name') or '').lower()
                if 'prod_runner' in low or 'arq_app' in low:
                    continue  # NSSM 被管业务进程: 误杀会被 AppExit 判为崩溃并自动重启
                if any(anc.pid in roots for anc in proc.parents()):
                    continue  # 服务进程的后代同样受保护
                # v5.40(审查 #5): 宽特征('node' in pname)会误杀机器上所有 node.exe(编辑器插件等)。
                # 加项目标记二级校验: cmdline 或 cwd 含 erp_system / frontend-vite 才可能是本系统进程;
                # cwd 读取失败(权限)按无标记处理 → 放行(宁可漏杀，不可误杀)。
                try:
                    cwd_s = str(proc.cwd() or '').lower()
                except Exception:
                    cwd_s = ''
                if not ('erp_system' in low or 'erp_system' in cwd_s
                        or 'frontend-vite' in low or 'frontend-vite' in cwd_s):
                    continue
                if ('uvicorn' in low or 'vite' in low or 'node' in pname or ('python' in pname and 'fastapi_app' in low)):
                    victims.append(pid)
            except Exception:
                continue
        if not victims:
            self._msg_queue.put(('log', {'text': '未发现游离残留进程'}))
            return
        self._msg_queue.put(('log', {'text': f'发现 {len(victims)} 个游离残留进程，正在终止...'}))
        for pid in victims:
            self._kill_process_tree(pid)
        self._msg_queue.put(('log', {'text': '残留进程清理完成'}))
    # ===================== 生产状态轮询(每 5 秒，后台收集) =====================

    def _refresh_hosting_status(self):
        """调度后台收集。sc query / 状态文件 IO / Redis 探测都是阻塞操作，绝不能在主线程执行。

        收集期间重复请求只置 _hosting_refresh_requested，回来立刻补一轮。
        """
        if self._shutting_down:
            return
        if self._hosting_collecting:
            self._hosting_refresh_requested = True
            return
        self._hosting_collecting = True
        threading.Thread(target=self._collect_worker, daemon=True).start()

    def _collect_worker(self):
        try:
            data = self._collect_hosting_data()
        except Exception:
            data = {'collect_error': True}
        self._msg_queue.put(('hosting_apply', {'data': data}))

    def _collect_hosting_data(self):
        """纯数据收集(后台线程)，不触碰任何 UI 组件。"""
        data = {'nssm': self._find_nssm(), 'api_state': self._svc_state(_SVC_API), 'arq_state': self._svc_state(_SVC_ARQ)}
        data['api_running'] = 'RUNNING' in data['api_state'].upper()
        data['arq_running'] = 'RUNNING' in data['arq_state'].upper()
        data['api_installed'] = '未安装' not in data['api_state']
        data['arq_installed'] = '未安装' not in data['arq_state']
        # ★ v5.37(D12): 三态语义贯通到展示层 —— 查询失败(未知)必须与「未安装/已停止」区分
        data['api_unknown'] = self._svc_unknown(data['api_state'])
        data['arq_unknown'] = self._svc_unknown(data['arq_state'])
        data['redis_ok'] = self._is_redis_running()
        data['status'], data['mtime'], data['stale'], data['mtime_str'] = {}, 0, False, '—'
        if data['api_running'] and _PROD_STATUS_FILE.is_file():
            try:
                data['status'] = json.loads(_PROD_STATUS_FILE.read_text(encoding='utf-8'))
                data['mtime'] = _PROD_STATUS_FILE.stat().st_mtime
                data['stale'] = (time.time() - data['mtime']) > 15
                data['mtime_str'] = datetime.fromtimestamp(data['mtime']).strftime('%H:%M:%S')
            except Exception as e:
                data['read_err'] = f'{type(e).__name__}: {e}'
        return data

    def _apply_hosting_data(self, data):
        """主线程应用生产状态(仅 UI 更新，无阻塞 IO)。"""
        try:
            if not data.get('collect_error'):
                self._last_hosting = data
                self._prod_running = bool(data.get('api_running'))
                # ★ v5.37(D12b): 独立未知标志供展示层使用；不改 _prod_running(它被 _do_light_stop 等
                # 当作「确认在运行」的依据)。注意此处无任何基于 api_running 的停止计时告警分支，
                # 故「未知」不会误触发「服务已停止 N 分钟」类误报。
                self._prod_unknown = bool(data.get('api_unknown'))
                self._redis_running_cached = bool(data.get('redis_ok'))
                if data.get('stale'):
                    self.log_message(f'logs/{_PROD_STATUS_FILE_NAME} 超过 15 秒未更新(可能已停止心跳)', 'WARNING')
        finally:
            self._hosting_collecting = False
            if self._shutting_down:
                return
            delay = 50 if self._hosting_refresh_requested else 5000
            self._hosting_refresh_requested = False
            self._update_all_ui()
            self._after_ids['hosting'] = self.root.after(delay, self._refresh_hosting_status)
    # ===================== 运行状态检查(自有进程存活) =====================

    def _check_server_status(self):
        if self._shutting_down:
            return
        if self._mode == 'dual_dev':
            backend_crashed = self._process and self._process.poll() is not None
            frontend_crashed = self._frontend_process and self._frontend_process.poll() is not None
            if backend_crashed or frontend_crashed:
                code = self._process.poll() if self._process else None
                which = '前后端' if (backend_crashed and frontend_crashed) else ('后端' if backend_crashed else '前端')
                self.log_message(f'开发模式{which}进程意外终止 (退出码: {code})', 'ERROR')
                self._abort_process(self._frontend_process, '前端')
                self._abort_process(self._process, '后端')
                self._set_mode_none()
        self._after_ids['status'] = self.root.after(5000, self._check_server_status)
    # ===================== 模式状态机 / UI 同步 =====================

    def _is_busy(self):
        # v5.40 补丁: 纳入紧急停止进行中 —— 否则紧急停止期间 toggle_dev/toggle_prod
        # 仍可穿过此处进入启动链，形成次级竞态(与 _stop_in_progress 抢占同一批资源)。
        # v5.40(P2): 移除死字面量 'restarting'(全文件无写入点)。
        return (self._mode in ('starting', 'stopping')
                or self._prod_busy
                or self._stop_in_progress)

    def toggle_dev(self):
        if self._is_busy():
            self.log_message('操作正在执行中，请稍候', 'WARNING')
            return
        self.stop_dual_dev() if self._mode == 'dual_dev' else self.start_dual_dev()

    def toggle_prod(self):
        if self._is_busy():
            self.log_message('操作正在执行中，请稍候', 'WARNING')
            return
        self.stop_prod() if self._prod_running else self.start_prod()

    def _update_all_ui(self):
        """按钮状态机(§7.3): 互斥是「启动即自动停对方」，故对方按钮在自身运行时仍可用。

        ★ v5.33 视觉语义（实测 ui-ref-v533-original.png）:
          按钮外观同时表达【意图】与【可用性】——
            · 意图=启动 → 实心彩色（开发绿 #34c759 / 生产蓝 #007aff）
            · 意图=停止 → 白底 + 同色描边（outlined）
            · 禁用     → 该色调的浅色底（绿 ⇒ #a8e0b8 / 其它 ⇒ #f2f2f7）
          这与 v5.40 原实现「一律蓝实心、禁用变灰」的单一表达不同，
          但**只改视觉映射，不改任何状态判定**（busy 判定与按钮可用性完全沿用原逻辑）。
        """
        if self._shutting_down or not hasattr(self, 'dev_btn'):
            return
        if self._is_busy():
            self._set_btn(self.dev_btn, '启动中…', False, 'success', 'start')
            self._set_btn(self.prod_btn, '启动中…', False, 'accent', 'start')
        else:
            dev_running = self._mode == 'dual_dev'
            self._set_btn(self.dev_btn, '停止开发模式' if dev_running else '启动开发模式',
                          True, 'success', 'stop' if dev_running else 'start')
            self._set_btn(self.prod_btn, '停止生产模式' if self._prod_running else '启动生产模式',
                          True, 'accent', 'stop' if self._prod_running else 'start')
        self._update_mode_badge()
        self._update_dots()

    def _set_btn(self, btn, text, enabled, tone='accent', intent='start'):
        """按钮状态机 → 控件层。

        ★ v5.33 视觉层适配: 主操作按钮已由 tk.Button 换成 RoundedButton（Canvas 子类）。
          RoundedButton.config 只认 text/state/command/bg/tone 五个键，不认 fg/cursor，
          且禁用态配色由 tone 派生（绿按钮 #a8e0b8 / 其它 #f2f2f7），
          外部再传 bg= 会污染 Canvas 底色、破坏圆角外观。
          故按控件能力分流：具备 set_text（即 RoundedButton）走精简参数，
          其余（如残留的 tk.Button）保留旧行为，保证零回归。
        """
        with contextlib.suppress(Exception):
            if hasattr(btn, 'set_text'):
                # intent='stop' → outlined(白底描边)；'start' → solid(实心彩色)
                btn.config(text=text, tone=tone,
                           variant='outlined' if intent == 'stop' else 'solid',
                           state=tk.NORMAL if enabled else tk.DISABLED)
            else:
                btn.config(text=text, state=tk.NORMAL if enabled else tk.DISABLED,
                           bg=_C['blue'] if enabled else _C['border'],
                           fg='#FFFFFF' if enabled else _C['muted'],
                           cursor='hand2' if enabled else 'arrow')

    def _update_mode_badge(self):
        """模式徽章: 过渡态优先于稳态，生产运行由服务轮询决定。"""
        if self._mode == 'starting' or (self._prod_busy and not self._prod_running):
            state, text = 'deploying', '启动中'
        elif self._mode == 'stopping' or self._prod_busy:
            # v5.40(P2): state 由死字面量 'restarting' 改为活枚举 'switching'(→ _STATUS_META)。
            #   此前直接传 'restarting' 而非查表，字面量一经清理即无从解析; 改用 'switching'
            #   并在 _STATUS_META 建同名条目，语义(橙色/切换中)完全等价。
            state, text = 'switching', '切换中'
        elif self._mode == 'dual_dev':
            state, text = 'running', '开发模式运行中'
        elif self._prod_running:
            state, text = 'running', '生产模式运行中'
        elif self._prod_unknown:
            # ★ v5.37(D12b): 生产状态「未知」不得显示「未运行」——否则误导现场判断生产是否在跑
            state, text = 'unknown', '生产模式 · 状态未知'
        else:
            state, text = 'stopped', '未运行'
        with contextlib.suppress(Exception):
            self.mode_badge.set_state(state, text)

    def _update_dots(self):
        hosting = self._last_hosting
        dev_starting = self._mode == 'starting'
        if self._redis_running_cached is True:
            redis_state = 'running'
        elif self._redis_running_cached is False:
            redis_state = 'stopped'
        else:
            redis_state = 'starting' if dev_starting else 'unknown'
        self._set_dot(self.dev_dots['redis'], 'Redis', redis_state)
        self._set_dot(self.dev_dots['backend'], '后端', self._proc_dot_state(self._process, dev_starting))
        self._set_dot(self.dev_dots['frontend'], '前端', self._proc_dot_state(self._frontend_process, dev_starting))
        self._set_dot(self.prod_dots['api'], _SVC_API, self._svc_dot_state(
            hosting.get('api_installed'), hosting.get('api_running'), self._prod_busy, hosting.get('api_unknown')))
        self._set_dot(self.prod_dots['arq'], _SVC_ARQ, self._svc_dot_state(
            hosting.get('arq_installed'), hosting.get('arq_running'), self._prod_busy, hosting.get('arq_unknown')))

    @staticmethod
    def _proc_dot_state(proc, starting):
        if proc and proc.poll() is None:
            return 'running'
        return 'starting' if starting else 'stopped'

    @staticmethod
    def _svc_dot_state(installed, running, busy, unknown=False):
        # ★ v5.37: unknown 优先于 installed/running —— 「查不出来」绝不能显示为「没在跑」。
        #   注意 running 在未知时天然为 False('RUNNING' not in '未知')，
        #   若不先判 unknown 就会落到 installed=True 分支显示成「已安装·未运行」。
        if unknown:
            return 'unknown'
        if installed is False:
            return 'not_installed'
        if running is True:
            return 'running'
        return 'starting' if busy else 'stopped'

    def _set_dot(self, label, name, state):
        color = _DOT_COLOR.get(state, _C['gray'])
        glyph = '○' if state in ('stopped', 'not_installed', 'unknown') else '●'
        suffix = _DOT_TEXT.get(state)
        with contextlib.suppress(Exception):
            label.config(text=f'{glyph} {name}' + (f' · {suffix}' if suffix else ''), fg=color)
    # ===================== 窗口 / 托盘 / 退出 =====================

    def _init_tray(self):
        """系统托盘(pystray 可选依赖，延迟 import; 失败静默降级只记一行日志)。"""
        self._tray_icon = None
        try:
            import pystray
            from PIL import Image, ImageDraw
            img = Image.new('RGBA', (16, 16), (0, 0, 0, 0))
            ImageDraw.Draw(img).ellipse([2, 2, 14, 14], fill=(22, 104, 220, 255))
            menu = pystray.Menu(pystray.MenuItem('显示窗口', self._show_window, default=True), pystray.MenuItem('退出', self._quit_from_tray))
            self._tray_icon = pystray.Icon('erp_server_manager', img, _WINDOW_TITLE, menu)
            threading.Thread(target=self._tray_icon.run, daemon=True).start()
            self.log_message('系统托盘已启用')
        except Exception as e:
            self.log_message(f'系统托盘不可用，已降级为普通窗口模式: {e}', 'WARNING')
            self._tray_icon = None

    def _show_window(self, _icon=None, _item=None):
        with contextlib.suppress(Exception):
            self.root.after(0, self._do_show_window)

    def _do_show_window(self):
        with contextlib.suppress(Exception):
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()

    def _quit_from_tray(self, _icon=None, _item=None):
        with contextlib.suppress(Exception):
            self.root.after(0, self._do_quit)

    def on_closing(self):
        """关闭按钮: 托盘可用则最小化到托盘，否则直接退出。"""
        if self._tray_icon is not None:
            with contextlib.suppress(Exception):
                self.root.withdraw()
            self.log_message('已最小化到系统托盘')
        else:
            self._do_quit()

    def _do_quit(self):
        if self._shutting_down:
            return
        self._shutting_down = True
        self.log_message('正在退出服务器管理器...')
        for key, aid in list(self._after_ids.items()):
            with contextlib.suppress(Exception):
                self.root.after_cancel(aid)
        if self._tray_icon is not None:
            with contextlib.suppress(Exception):
                self._tray_icon.stop()
        # 退出时只回收本管理器启的进程与自有 Redis，不动托管的 Redis 服务与 NSSM 生产服务
        for proc, name in ((self._frontend_process, '前端'), (self._process, '后端')):
            if proc and proc.poll() is None:
                with contextlib.suppress(Exception):
                    self._kill_process_tree(proc.pid)
        self._stop_owned_redis()
        with contextlib.suppress(Exception):
            self.root.destroy()


def main():
    _enable_dpi_awareness()  # 必须在 tk.Tk() 之前
    if not _ensure_single_instance():
        _activate_existing_window()
        sys.exit(0)
    try:
        root = tk.Tk()
        ServerManagerApp(root)
        root.mainloop()
    except Exception as e:
        tb_text = traceback.format_exc()
        crash_dir = (_PROJECT_DIR / 'logs').resolve()
        if '..' in crash_dir.parts or not crash_dir.is_absolute():
            crash_dir = Path.cwd() / 'logs'
        crash_file = None
        try:
            crash_dir.mkdir(exist_ok=True)
            crash_file = crash_dir / f'server_manager_crash_{datetime.now():%Y%m%d_%H%M%S}.log'
            crash_file.write_text(f'[CRASH] {datetime.now()}\n{tb_text}', encoding='utf-8')
        except Exception:
            pass
        with contextlib.suppress(Exception):
            messagebox.showerror('启动失败', f'服务器管理器启动失败:\n{e}' + (f'\n\n日志: {crash_file}' if crash_file else ''))
        sys.exit(1)
if __name__ == '__main__':
    main()