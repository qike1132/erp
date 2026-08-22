# -*- coding: utf-8 -*-
"""
ERP 服务器管理器 v6.0 — Console Edition（Windows 控制台版）
================================================================================
经典 CMD 风格控制台程序：
  - 黑底白字 / 系统等宽字体（Consolas / Courier New / 新宋体）
  - 纯文本 + ASCII 边框（+ - | =）组织内容，无任何图形组件 / 图标 / 动画
  - 输入序号 + 回车 的交互方式（请输入选项:）
  - PyInstaller --console 打包为 *.exe，双击即为标准 Windows 命令提示符窗口

用法:
    python server_manager_console.py        # 正常启动
    python server_manager_console.py --color  # 启用经典 DOS 绿色提示（可选）

说明:
    - 业务逻辑（进程树终止 / 端口释放 / Redis 探测 / 健康检查）复用 server_manager.py
      的模块级工具函数，保证与原 GUI 版行为一致。
================================================================================
"""
import contextlib
import io
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

_IS_WINDOWS = sys.platform == 'win32'

# 控制台编码：确保中文在 cmd 窗口正常显示
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
if _IS_WINDOWS:
    with contextlib.suppress(Exception):
        os.system('chcp 65001 >nul 2>&1')

# ---- 复用原 server_manager.py 的模块级工具函数 ----
# （仅 import 模块级函数，不会触发任何 GUI 初始化）
from server_manager import (  # noqa: E402
    _API_PORT, _WEB_PORT, _REDIS_PORT,
    _PROJECT_DIR, _FRONTEND_DIR, _PYTHON_EXE,
    _taskkill, _taskkill_many, _kill_port_process, _get_port_occupier,
    _ensure_single_instance, _activate_existing_window,
    _REDIS_EXE_PATHS, _REDIS_CONF_PATHS,
    _SVC_API, _SVC_ARQ, _NSSM_CANDIDATES, _PROD_STATUS_FILE,
)

VERSION = 'v6.0 (Console)'
REDIS_EXE_PATHS = _REDIS_EXE_PATHS
REDIS_CONF_PATHS = _REDIS_CONF_PATHS

# 是否启用 ANSI 绿色提示（经典 DOS 观感，默认关闭=纯黑白）
USE_COLOR = '--color' in sys.argv[1:]
if USE_COLOR and _IS_WINDOWS:
    with contextlib.suppress(Exception):
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)

def _c(text, code):
    """绿色提示（仅 --color 模式生效），否则原样输出"""
    if USE_COLOR:
        return f'\033[{code}m{text}\033[0m'
    return text

# =====================================================================
# 控制台基础组件（纯文本）
# =====================================================================
W = 74  # 边框宽度

def disp_w(s):
    """按显示宽度计算长度：中文/全角字符计 2，ASCII 计 1"""
    w = 0
    for ch in s:
        w += 2 if ord(ch) > 0x2E7F else 1
    return w

def pad(s, n, align='l'):
    """按显示宽度补齐到 n 列"""
    gap = n - disp_w(s)
    if gap <= 0:
        return s
    if align == 'r':
        return ' ' * gap + s
    if align == 'c':
        left = gap // 2
        return ' ' * left + s + ' ' * (gap - left)
    return s + ' ' * gap

def hr(char='-', n=W):
    print(char * n)

def title(text):
    """主标题：==== 文字 ===="""
    text = f'  {text}  '
    total = W - 4
    side = max(0, (total - disp_w(text)) // 2)
    print('=' * W)
    print('=' + ' ' * side + text + ' ' * (W - 2 - side - disp_w(text)) + '=')
    print('=' * W)

def section(text):
    """分区标题：--- 文字 ---"""
    text = f' {text} '
    total = W - 2
    side = max(0, (total - disp_w(text)) // 2)
    print('-' * W)
    print('-' + ' ' * side + text + ' ' * (W - 2 - side - disp_w(text)) + '-')
    print('-' * W)

def msg(text):
    print('  ' + text)

def ok(text):
    print('  ' + _c(text, '32'))

def warn(text):
    print('  ' + _c(text, '33'))

def err(text):
    print('  ' + _c(text, '31'))

def ask(prompt='请输入选项: '):
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return '0'

def pause():
    try:
        input('  按回车键返回...')
    except (EOFError, KeyboardInterrupt):
        print()

def table(headers, rows):
    """ASCII 表格：| 列1 | 列2 | ... 行间以 +----+ 分隔"""
    widths = [max(disp_w(h), max((disp_w(r[i]) for r in rows), default=0)) + 2 for i, h in enumerate(headers)]
    line = '+' + '+'.join('-' * w for w in widths) + '+'
    def draw_row(cells, is_head=False):
        line_cells = '|' + '|'.join(' ' + pad(c, widths[i] - 2) + ' ' for i, c in enumerate(cells)) + '|'
        print(line_cells)
    print(line)
    draw_row(headers)
    print(line)
    for r in rows:
        draw_row(r)
    print(line)

# =====================================================================
# 状态检测（只读，不启动任何服务）
# =====================================================================
def redis_running():
    """RESP PING 探测 Redis（与原 GUI 版同逻辑）"""
    try:
        with socket.create_connection(('127.0.0.1', _REDIS_PORT), timeout=1) as sock:
            sock.sendall(b'*1\r\n$4\r\nPING\r\n')
            resp = sock.recv(64)
            if resp.startswith(b'+PONG'):
                return True
            if resp.startswith(b'-NOAUTH'):
                pwd = _env_value('REDIS_PASSWORD')
                if not pwd:
                    return False
                sock.sendall((f'*2\r\n$4\r\nAUTH\r\n${len(pwd)}\r\n{pwd}\r\n').encode())
                if not sock.recv(64).startswith(b'+OK'):
                    return False
                sock.sendall(b'*1\r\n$4\r\nPING\r\n')
                return sock.recv(64).startswith(b'+PONG')
        return False
    except Exception:
        return False

def _env_value(key):
    env_file = _PROJECT_DIR / '.env'
    try:
        if env_file.is_file():
            for line in env_file.read_text(encoding='utf-8', errors='ignore').splitlines():
                line = line.strip()
                if line.startswith(key + '='):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ''

def find_redis():
    redis_exe = next((str(p) for p in REDIS_EXE_PATHS if p.is_file()), None)
    redis_conf = next((str(p) for p in REDIS_CONF_PATHS if p.is_file()), None)
    return redis_exe, redis_conf

def find_nssm():
    return next((str(p) for p in _NSSM_CANDIDATES if p.is_file()), None)

def svc_state(name):
    """sc query 查询服务状态 -> 'RUNNING' / 'STOPPED' / 'NOT_FOUND' / ..."""
    try:
        r = subprocess.run(['sc', 'query', name], capture_output=True, text=True, timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0)
        for line in r.stdout.splitlines():
            if 'STATE' in line.upper():
                parts = line.split()
                if len(parts) >= 4:
                    return parts[3].upper()
        return 'NOT_FOUND' if 'FAILED 1060' in r.stdout.upper() or 'FAILED' in r.stdout.upper() else 'UNKNOWN'
    except Exception:
        return 'UNKNOWN'

def svc_pid(name):
    """查询服务对应进程 PID（用于状态表展示）"""
    try:
        r = subprocess.run(['sc', 'queryex', name], capture_output=True, text=True, timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0)
        for line in r.stdout.splitlines():
            if 'PID' in line.upper() and 'SERVICE' not in line.upper():
                parts = line.split()
                if len(parts) >= 2 and parts[-1].isdigit():
                    return parts[-1]
    except Exception:
        pass
    return '-'

def backend_ready():
    """后端健康检查"""
    import urllib.request
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{_API_PORT}/api/health', timeout=2):
            return True
    except Exception:
        return False

def frontend_ready():
    import urllib.request
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{_WEB_PORT}/', timeout=2):
            return True
    except Exception:
        return False

def collect_hosting_status():
    """收集生产模式状态（简化版，与原 GUI 版 _collect_hosting_data 对齐）"""
    status = {'nssm': find_nssm()}
    status['api_state'] = svc_state(_SVC_API)
    status['arq_state'] = svc_state(_SVC_ARQ)
    status['api_running'] = status['api_state'] == 'RUNNING'
    status['redis_ok'] = redis_running()
    status['detail'] = {}
    if status['api_running'] and _PROD_STATUS_FILE.is_file():
        try:
            detail = json.loads(_PROD_STATUS_FILE.read_text(encoding='utf-8'))
            svcs = detail.get('services', {})
            status['detail'] = {
                'backend': '运行中' if svcs.get('backend', {}).get('status') == 'ready' else '异常',
                'arq': svcs.get('arq', {}).get('status', '-'),
                'frontend': '运行中' if svcs.get('frontend', {}).get('status') in ('running', 'ready') else '异常',
                'ready': detail.get('ready', False),
            }
        except Exception:
            pass
    return status

# =====================================================================
# 进程句柄（模块级保存，供启动/停止使用）
# =====================================================================
DEV_BACKEND = None      # 后端 subprocess
DEV_FRONTEND = None     # 前端 subprocess
REDIS_PROC = None       # Redis subprocess
DEV_RUNNING = False

# =====================================================================
# 动作：开发模式
# =====================================================================
def _release_ports():
    for port in (_API_PORT, _WEB_PORT, _REDIS_PORT):
        if _get_port_occupier(port):
            msg(f'清理端口 {port} ...')
            _kill_port_process(port)

def _stop_production_for_switch():
    """互斥切换：若生产服务运行则停止（简化：仅提示并停止）"""
    state = svc_state(_SVC_API)
    if state == 'RUNNING':
        warn('检测到生产模式运行中，正在停止以释放端口...')
        subprocess.run(['sc', 'stop', _SVC_API], capture_output=True, timeout=30,
                       creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0)
        time.sleep(3)

def start_dev():
    """启动开发模式：Redis + 后端(uvicorn) + 前端(vite)，带步骤输出与健康检查"""
    global DEV_BACKEND, DEV_FRONTEND, REDIS_PROC, DEV_RUNNING
    if DEV_RUNNING:
        warn('开发模式已在运行，请先停止（选项 3）')
        pause()
        return
    if not _PYTHON_EXE:
        err('[错误] 未找到 Python 解释器，请安装 Python 3.12+ 并加入 PATH')
        pause()
        return
    if not _FRONTEND_DIR.exists():
        err(f'[错误] 前端目录不存在: {_FRONTEND_DIR}')
        pause()
        return

    print()
    title('启动开发模式')
    section('步骤 1/4  互斥切换与端口清理')
    _stop_production_for_switch()
    _release_ports()
    msg('端口清理完成。')
    creationflags = subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0

    section('步骤 2/4  启动 Redis')
    if redis_running():
        msg('Redis 已在运行，跳过启动。')
    else:
        redis_exe, redis_conf = find_redis()
        if not redis_exe:
            warn('[警告] 未找到 Redis (C:\\Redis\\redis-server.exe)，部分功能不可用')
        else:
            cmd = [redis_exe] + ([redis_conf] if redis_conf else [])
            pwd = _env_value('REDIS_PASSWORD')
            if pwd:
                cmd += ['--requirepass', pwd]
            REDIS_PROC = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                                          creationflags=creationflags, text=False)
            ok_flag = False
            for _ in range(15):
                time.sleep(0.5)
                if redis_running():
                    ok_flag = True
                    break
            ok(f'Redis 启动成功 (PID: {REDIS_PROC.pid})' if ok_flag else '[警告] Redis 启动超时，请检查端口 6379')

    section('步骤 3/4  启动后端服务 (uvicorn)')
    env = os.environ.copy()
    env.update({'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1', 'PYTHONPATH': str(_PROJECT_DIR)})
    backend_cmd = [_PYTHON_EXE, '-u', '-m', 'uvicorn', 'fastapi_app.main:app', '--host', '0.0.0.0',
                   '--port', str(_API_PORT), '--log-level', 'info', '--reload', '--reload-dir', 'fastapi_app']
    log_file = open(_PROJECT_DIR / 'logs' / 'dev_backend.log', 'ab')
    DEV_BACKEND = subprocess.Popen(backend_cmd, cwd=str(_PROJECT_DIR), env=env,
                                   stdout=log_file, stderr=subprocess.STDOUT,
                                   creationflags=creationflags, text=False)
    msg(f'后端进程已启动 (PID: {DEV_BACKEND.pid})，日志: logs\\dev_backend.log')
    ready = False
    for i in range(30):
        time.sleep(1)
        if backend_ready():
            ready = True
            break
        if DEV_BACKEND.poll() is not None:
            break
    if not ready:
        err('[错误] 后端启动失败或健康检查未通过 (http://127.0.0.1:%d/api/health)' % _API_PORT)
        _taskkill(DEV_BACKEND.pid)
        DEV_BACKEND = None
        pause()
        return
    ok(f'后端健康检查通过 (http://127.0.0.1:{_API_PORT}/docs)')

    section('步骤 4/4  启动前端服务 (vite)')
    npm_cmd = 'npm.cmd' if _IS_WINDOWS else 'npm'
    fe_log = open(_PROJECT_DIR / 'logs' / 'dev_frontend.log', 'ab')
    DEV_FRONTEND = subprocess.Popen([npm_cmd, 'run', 'dev', '--', '--port', str(_WEB_PORT)],
                                    cwd=str(_FRONTEND_DIR), stdout=fe_log, stderr=subprocess.STDOUT,
                                    env={**os.environ, 'BACKEND_INTERNAL_URL': f'http://127.0.0.1:{_API_PORT}'},
                                    creationflags=creationflags, text=False)
    msg(f'前端进程已启动 (PID: {DEV_FRONTEND.pid})，日志: logs\\dev_frontend.log')
    ready = False
    for _ in range(60):
        time.sleep(1)
        if frontend_ready():
            ready = True
            break
        if DEV_FRONTEND.poll() is not None:
            break
    if not ready:
        err('[错误] 前端启动失败或健康检查未通过')
        if DEV_BACKEND and DEV_BACKEND.poll() is None:
            _taskkill(DEV_BACKEND.pid)
        if DEV_FRONTEND and DEV_FRONTEND.poll() is None:
            _taskkill(DEV_FRONTEND.pid)
        DEV_BACKEND, DEV_FRONTEND = None, None
        pause()
        return
    ok(f'前端就绪 (http://127.0.0.1:{_WEB_PORT})')
    DEV_RUNNING = True
    print()
    hr('=', W)
    print(_c('  ✔ 开发模式启动完成：后端 + 前端 + Redis 全部运行中', '32'))
    hr('=', W)
    pause()

def stop_dev():
    """停止开发模式：终止前后端进程树 + 释放端口 + 停止 Redis"""
    global DEV_BACKEND, DEV_FRONTEND, REDIS_PROC, DEV_RUNNING
    print()
    title('停止开发模式')
    section('终止服务进程')
    stopped_any = False
    for proc, name in ((DEV_BACKEND, '后端'), (DEV_FRONTEND, '前端')):
        if proc and proc.poll() is None:
            msg(f'正在终止{name}进程树 (PID: {proc.pid}) ...')
            _taskkill(proc.pid)
            with contextlib.suppress(Exception):
                proc.wait(timeout=3)
            stopped_any = True
    DEV_BACKEND, DEV_FRONTEND = None, None
    _release_ports()
    msg('已释放端口 5002 / 3000 / 6379。')
    if REDIS_PROC and REDIS_PROC.poll() is None:
        msg(f'正在停止 Redis (PID: {REDIS_PROC.pid}) ...')
        with contextlib.suppress(Exception):
            REDIS_PROC.terminate()
            REDIS_PROC.wait(timeout=3)
        REDIS_PROC = None
    if redis_running():
        _kill_port_process(_REDIS_PORT)
    DEV_RUNNING = False
    ok('开发模式已全部停止。' if stopped_any else '当前没有运行中的开发服务。')
    pause()

def restart_dev():
    stop_dev()
    print()
    msg('正在重新启动开发模式...')
    time.sleep(1)
    start_dev()

def emergency_stop():
    """紧急停止：终止开发/生产全部相关进程并释放端口"""
    print()
    title('紧急停止')
    warn('该操作将终止全部 ERP 相关进程并释放端口，确定继续吗？')
    choice = ask('  确认请输入 Y（大写），其他任意键取消: ')
    if choice.upper() != 'Y':
        msg('已取消。')
        pause()
        return
    global DEV_BACKEND, DEV_FRONTEND, REDIS_PROC, DEV_RUNNING
    section('终止开发模式进程')
    for proc, name in ((DEV_BACKEND, '后端'), (DEV_FRONTEND, '前端'), (REDIS_PROC, 'Redis')):
        if proc and proc.poll() is None:
            msg(f'终止 {name} (PID: {proc.pid}) ...')
            _taskkill(proc.pid)
            with contextlib.suppress(Exception):
                proc.wait(timeout=3)
    DEV_BACKEND, DEV_FRONTEND, REDIS_PROC = None, None, None
    DEV_RUNNING = False
    section('终止生产服务')
    for svc in (_SVC_API, _SVC_ARQ):
        if svc_state(svc) == 'RUNNING':
            subprocess.run(['sc', 'stop', svc], capture_output=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0)
            msg(f'已停止服务 {svc}')
    section('释放端口')
    _release_ports()
    ok('紧急停止完成：进程已终止，端口已释放。')
    pause()

# =====================================================================
# 动作：生产模式（NSSM）
# =====================================================================
def _run_capture(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0)
        return r.returncode, r.stdout.strip() + r.stderr.strip()
    except Exception as e:
        return -1, str(e)

def prod_install():
    nssm = find_nssm()
    if not nssm:
        err('[错误] 未找到 NSSM (C:\\nssm\\nssm.exe)，无法安装服务')
        pause()
        return
    env_extra = (f'PYTHONPATH={_PROJECT_DIR} PYTHONUTF8=1 PYTHONIOENCODING=utf-8 '
                 f'BACKEND_INTERNAL_URL=http://127.0.0.1:{_API_PORT}')
    for name, app in ((_SVC_API, _PYTHON_EXE), (_SVC_ARQ, _PYTHON_EXE)):
        if not app:
            err(f'[错误] 未找到 Python，无法注册 {name}')
            continue
        msg(f'注册服务 {name} ...')
        code, out = _run_capture([nssm, 'install', name, app])
        if code != 0:
            err(f'{name} 注册失败: {out}')
            continue
        params = ('-m', 'fastapi_app.run_prod', '--host', '0.0.0.0', '--port', str(_API_PORT)) if name == _SVC_API else ('-m', 'arq', 'fastapi_app.worker.WorkerSettings')
        _run_capture([nssm, 'set', name, 'AppParameters', ' '.join(params)])
        for key, val in (('AppDirectory', str(_PROJECT_DIR)),
                         ('AppStdout', str(_PROJECT_DIR / 'logs' / f'{name}.log')),
                         ('AppStderr', str(_PROJECT_DIR / 'logs' / f'{name}.log')),
                         ('AppRotateFiles', '1'), ('AppRotateBytes', '10485760'),
                         ('AppExit', 'Default Restart'), ('AppRestartDelay', '5000'),
                         ('Start', 'SERVICE_AUTO_START'), ('AppEnvironmentExtra', env_extra),
                         ('AppNoConsole', '1')):
            _run_capture([nssm, 'set', name, key, val])
        ok(f'{name} 安装完成（开机自启）')
    pause()

def prod_uninstall():
    for name in (_SVC_API, _SVC_ARQ):
        msg(f'卸载服务 {name} ...')
        _run_capture(['sc', 'stop', name])
        code, out = _run_capture(['sc', 'delete', name])
        if code == 0:
            ok(f'{name} 已卸载')
        else:
            warn(f'{name} 卸载失败: {out}')
    pause()

def prod_menu():
    while True:
        st = collect_hosting_status()
        print()
        title('生产模式服务管理 (NSSM)')
        table(['服务', '状态', '说明'],
              [(_SVC_API, '运行中' if st['api_running'] else '已停止', '后端 API · 开机自启 · 崩溃自愈'),
               (_SVC_ARQ, '运行中' if st['arq_state'] == 'RUNNING' else '已停止', '队列 Worker · 独立 NSSM 服务'),
               ('Redis', '运行中' if st['redis_ok'] else '已停止', '端口 %d' % _REDIS_PORT)])
        nssm = find_nssm()
        msg(f'NSSM: {nssm or "未找到 (C:\\nssm\\nssm.exe)"}')
        if st['detail']:
            d = st['detail']
            msg(f'状态文件: 后端[{d["backend"]}] ARQ[{d["arq"]}] 前端[{d["frontend"]}] 就绪[{d["ready"]}]')
        print()
        section('操作')
        print('  [1] 启动服务       [2] 停止服务       [3] 重启服务')
        print('  [4] 刷新状态       [5] 安装服务       [6] 卸载服务')
        print('  [0] 返回上级菜单')
        choice = ask('请输入选项: ')
        if choice == '1':
            subprocess.run(['sc', 'start', _SVC_API], capture_output=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0)
            subprocess.run(['sc', 'start', _SVC_ARQ], capture_output=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0)
            ok('已发送启动命令。')
            pause()
        elif choice == '2':
            subprocess.run(['sc', 'stop', _SVC_API], capture_output=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0)
            subprocess.run(['sc', 'stop', _SVC_ARQ], capture_output=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0)
            ok('已发送停止命令。')
            pause()
        elif choice == '3':
            for svc in (_SVC_API, _SVC_ARQ):
                subprocess.run(['sc', 'stop', svc], capture_output=True, timeout=30,
                               creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0)
            time.sleep(2)
            subprocess.run(['sc', 'start', _SVC_API], capture_output=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0)
            subprocess.run(['sc', 'start', _SVC_ARQ], capture_output=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0)
            ok('已发送重启命令。')
            pause()
        elif choice == '4':
            ok('状态已刷新。')
        elif choice == '5':
            prod_install()
        elif choice == '6':
            prod_uninstall()
        elif choice == '0':
            break
        else:
            warn('无效选项，请重新输入。')

# =====================================================================
# 动作：日志查看
# =====================================================================
def tail_file(path, lines=40):
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 8192))
            data = f.read()
        text = data.decode('utf-8', errors='replace')
        return text.splitlines()[-lines:]
    except Exception as e:
        return [f'[读取失败] {e}']

def logs_menu():
    log_dir = _PROJECT_DIR / 'logs'
    log_dir.mkdir(exist_ok=True)
    while True:
        print()
        title('运行日志查看')
        files = sorted(log_dir.glob('*.log'), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            msg('logs\\ 目录下暂无 .log 文件。')
            pause()
            return
        print(f'  logs\\ 目录共 {len(files)} 个日志文件：')
        print()
        for i, p in enumerate(files, 1):
            sz = p.stat().st_size
            mtime = time.strftime('%m-%d %H:%M', time.localtime(p.stat().st_mtime))
            print(f'  [{i:>2}] {pad(p.name, 40)}{sz / 1024:8.1f} KB   {mtime}')
        print()
        print('  [0] 返回上级菜单')
        choice = ask('请输入文件编号查看日志: ')
        if choice == '0':
            return
        if choice.isdigit() and 1 <= int(choice) <= len(files):
            view_log(files[int(choice) - 1])
        else:
            warn('无效选项，请重新输入。')

def view_log(path):
    while True:
        print()
        section(f'日志文件: {path.name} (最近 40 行)')
        lines = tail_file(path)
        for ln in lines:
            print('  ' + ln if ln else '')
        print()
        print('  [R] 刷新    [0] 返回')
        choice = ask('请输入: ')
        if choice.upper() == 'R':
            continue
        break

# =====================================================================
# 动作：环境信息 / 端口检查
# =====================================================================
def env_info():
    print()
    title('环境与配置信息')
    redis_exe, redis_conf = find_redis()
    table(['项目', '值'],
          [('Python 解释器', str(_PYTHON_EXE) or '未找到'),
           ('项目目录', str(_PROJECT_DIR)),
           ('前端目录', str(_FRONTEND_DIR)),
           ('后端端口', str(_API_PORT)),
           ('前端端口', str(_WEB_PORT)),
           ('Redis 端口', str(_REDIS_PORT)),
           ('Redis 可执行', str(redis_exe) or '未找到'),
           ('Redis 配置', str(redis_conf) or '无'),
           ('NSSM 路径', str(find_nssm()) or '未找到'),
           ('API 服务名', _SVC_API),
           ('ARQ 服务名', _SVC_ARQ),
           ('状态文件', str(_PROD_STATUS_FILE))])
    print()
    msg('提示: 以上路径/端口可在 server_manager.py 顶部常量中修改。')
    pause()

def port_check():
    print()
    title('端口占用检查')
    table(['端口', '用途', '占用进程 (PID / 名称)'],
          [(str(p), name, ', '.join(f'{pid}/{pname}' for pid, pname in _get_port_occupier(p)) or '空闲')
           for p, name in ((_API_PORT, '后端 API'), (_WEB_PORT, '前端 WEB'), (_REDIS_PORT, 'Redis'))])
    print()
    msg('如需释放端口，请使用 [8] 紧急停止，或手动结束对应进程。')
    pause()

# =====================================================================
# 动作：服务状态总览
# =====================================================================
def service_status():
    global DEV_RUNNING
    # 若进程句柄已结束但标志未复位，自动纠正
    if DEV_RUNNING and DEV_BACKEND and DEV_BACKEND.poll() is not None:
        DEV_RUNNING = False
    print()
    title('服务状态总览')
    print()
    section('开发模式')
    if DEV_RUNNING:
        rows = [('FastAPI 后端', '运行中', str(DEV_BACKEND.pid if DEV_BACKEND else '-'), str(_API_PORT)),
                ('Vite 前端', '运行中', str(DEV_FRONTEND.pid if DEV_FRONTEND else '-'), str(_WEB_PORT)),
                ('Redis', '运行中' if redis_running() else '异常', '-', str(_REDIS_PORT))]
    else:
        rows = [('FastAPI 后端', '已停止', '-', str(_API_PORT)),
                ('Vite 前端', '已停止', '-', str(_WEB_PORT)),
                ('Redis', '运行中' if redis_running() else '已停止', '-', str(_REDIS_PORT))]
    table(['服务', '状态', 'PID', '端口'], rows)
    print()
    section('生产模式 (NSSM)')
    st = collect_hosting_status()
    table(['服务', '状态', 'PID', '说明'],
          [(_SVC_API, '运行中' if st['api_running'] else '已停止',
            svc_pid(_SVC_API) if st['api_running'] else '-', '后端 API'),
           (_SVC_ARQ, '运行中' if st['arq_state'] == 'RUNNING' else '已停止',
            svc_pid(_SVC_ARQ) if st['arq_state'] == 'RUNNING' else '-', '队列 Worker')])
    if st['detail']:
        d = st['detail']
        msg(f"状态文件: 后端[{d['backend']}] ARQ[{d['arq']}] 前端[{d['frontend']}] 就绪[{d['ready']}]")
    print()
    if DEV_RUNNING:
        msg(f"  开发模式访问: API http://127.0.0.1:{_API_PORT}/docs | WEB http://127.0.0.1:{_WEB_PORT}")
    pause()

# =====================================================================
# 主菜单
# =====================================================================
def main_menu():
    while True:
        dev = '运行中' if DEV_RUNNING else '未运行'
        redis = '运行中' if redis_running() else '已停止'
        prod = '运行中' if svc_state(_SVC_API) == 'RUNNING' else '已停止'
        print()
        print('=' * W)
        print(_c('   __  ______  ____    _   ____    ____  ______  ____', '32'))
        print(_c('  / / / / __ \\/ __ \\  / | / / /   /  _/ /_  __/ / __ \\', '32'))
        print(_c(' / / / / /_/ / /_/ / /  |/ / /___  / /    / /   / /_/ /', '32'))
        print(_c('/_/_/ /\\____/\\____/ /_/|_/\\____/ /___/  /_/   / .___/', '32'))
        print(_c('                                  /_/         /_/    ', '32'))
        print('=' * W)
        print('              ERP 服务器管理器  ' + VERSION)
        print('=' * W)
        print('  开发模式: [%s]    Redis: [%s]    生产服务: [%s]' % (dev, redis, prod))
        print('  项目目录: %s' % _PROJECT_DIR)
        print('-' * W)
        print('  主菜单')
        print('-' * W)
        print('  [1] 查看服务状态         [6] 查看运行日志')
        print('  [2] 启动开发模式         [7] 环境与配置信息')
        print('  [3] 停止开发模式         [8] 端口占用检查')
        print('  [4] 重启开发模式         [9] 紧急停止 (全部进程)')
        print('  [5] 生产服务管理 (NSSM)  [0] 退出')
        print('-' * W)
        choice = ask('请输入选项: ')
        if choice == '1':
            service_status()
        elif choice == '2':
            start_dev()
        elif choice == '3':
            stop_dev()
        elif choice == '4':
            restart_dev()
        elif choice == '5':
            prod_menu()
        elif choice == '6':
            logs_menu()
        elif choice == '7':
            env_info()
        elif choice == '8':
            port_check()
        elif choice == '9':
            emergency_stop()
        elif choice == '0':
            break
        else:
            warn('无效选项，请重新输入。')

def main():
    if _IS_WINDOWS:
        with contextlib.suppress(Exception):
            os.system('title ERP 服务器管理器 v6.0 Console Edition')
    if not _ensure_single_instance() and '--force' not in sys.argv:
        print('已有一个 ERP 服务器管理器实例在运行。')
        print('请关闭其他实例后重试。')
        print()
        print('提示: 若确认无其他实例（如 GUI 卡死后残留互斥体），')
        print('可用  --force  参数强制启动（仅限调试场景）。')
        with contextlib.suppress(Exception):
            _activate_existing_window()
        sys.exit(0)
    print()
    print('ERP 服务器管理器 Console Edition 正在初始化...')
    time.sleep(0.6)
    try:
        main_menu()
    except KeyboardInterrupt:
        pass
    finally:
        print()
        print('感谢使用，再见。')
        with contextlib.suppress(Exception):
            input('按回车键退出窗口...')

if __name__ == '__main__':
    main()
