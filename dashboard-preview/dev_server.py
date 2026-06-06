#!/usr/bin/env python3
"""
Live Sync 开发服务器 — 全项目实时同步

实时检测项目目录下所有文件的修改（HTML/CSS/JS/图片/配置等），
通过 WebSocket 自动推送刷新指令到浏览器，支持远程同步与冲突检测。

使用:  python dev_server.py [选项]
特性:
  1. 递归文件监听 — mtime快照 + 内容哈希双重检测
  2. 全类型文件覆盖 — HTML/CSS/JS/图片/配置/字体等
  3. 远程同步 — 本地→远程 rsync/scp 推送
  4. 自动刷新 — HTML/JS→整页刷新, CSS→热更新
  5. 冲突检测 — 哈希比对，多端修改时告警
  6. 低性能开销 — 防抖聚合，仅扫描变更文件
  7. 跨平台 — 纯Python，Windows/macOS/Linux
  8. 状态反馈 — 浏览器徽章 + 控制台日志 + 同步历史
"""

import asyncio
import gzip
import hashlib
import http.client
import http.server
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

import websockets
from websockets.asyncio.server import serve as ws_serve

# API代理配置 - 将前端的API请求转发到后端服务器
API_PROXY_TARGET = "192.168.0.95:5002"

ROOT_DIR = Path(__file__).parent.resolve()
SYNC_STATE_FILE = ROOT_DIR / '.sync_state.json'

DEFAULT_HTTP_PORT = 8080
DEFAULT_WS_PORT = 8081
SCAN_INTERVAL = 1.0
DEBOUNCE_SEC = 0.4
SKIP_DIRS = frozenset(
    {'.git', '__pycache__', 'node_modules', '.cache', 'venv', '.venv',
     '.idea', '.vscode', '.sync', 'dist', 'build'})
SKIP_FILES = frozenset({'.sync_state.json', '.DS_Store', 'Thumbs.db'})
WATCH_EXTENSIONS = frozenset({
    '.html', '.htm', '.css', '.js', '.mjs', '.ts', '.tsx', '.jsx',
    '.json', '.xml', '.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp',
    '.ico', '.woff', '.woff2', '.ttf', '.eot', '.map', '.webmanifest',
    '.yaml', '.yml', '.toml', '.md', '.txt'})

connected: set = set()
sync_history: list[dict] = []
sync_stats = {"total_syncs": 0, "last_sync": None, "conflicts": 0, "errors": 0}
remote_config = {"host": None, "path": None, "method": None}


def log(tag: str, msg: str):
    ts = time.strftime("%H:%M:%S")
    print(f"  [{tag}] {ts} {msg}", flush=True)


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('0.0.0.0', port))
            return False
        except OSError:
            return True


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def file_hash(filepath: str) -> str:
    h = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def load_sync_state() -> dict[str, dict]:
    if SYNC_STATE_FILE.exists():
        try:
            with open(SYNC_STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_sync_state(state: dict[str, dict]):
    try:
        with open(SYNC_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def build_snapshot() -> dict[str, dict]:
    snap = {}
    for dirpath, dirnames, filenames in os.walk(ROOT_DIR):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn in SKIP_FILES:
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, ROOT_DIR)
            ext = os.path.splitext(fn)[1].lower()
            if ext and ext not in WATCH_EXTENSIONS:
                continue
            try:
                stat = os.stat(full)
                snap[rel] = {"mtime": stat.st_mtime, "size": stat.st_size}
            except OSError:
                pass
    return snap


def find_changes(old: dict, new: dict) -> tuple[list[str], list[str], list[str]]:
    added = [k for k in new if k not in old]
    modified = []
    for k in new:
        if k in old and (new[k]["mtime"] != old[k]["mtime"] or new[k]["size"] != old[k]["size"]):
            modified.append(k)
    deleted = [k for k in old if k not in new]
    return added, modified, deleted


def detect_conflicts(modified_files: list[str], old_snap: dict, new_snap: dict) -> list[dict]:
    conflicts = []
    prev_state = load_sync_state()
    for f in modified_files:
        full = os.path.join(ROOT_DIR, f)
        current_hash = file_hash(full)
        if not current_hash:
            continue
        if f in prev_state:
            prev_hash = prev_state[f].get("hash", "")
            if prev_hash and prev_hash != current_hash:
                old_mtime = old_snap[f]["mtime"] if f in old_snap else 0
                new_mtime = new_snap[f]["mtime"] if f in new_snap else 0
                if abs(new_mtime - old_mtime) < 0.01:
                    continue
                conflicts.append({
                    "file": f,
                    "previous_hash": prev_hash[:8],
                    "current_hash": current_hash[:8],
                    "previous_mtime": prev_state[f].get("mtime", 0),
                    "current_mtime": new_mtime
                })
    return conflicts


def update_sync_state(files: list[str]):
    state = load_sync_state()
    for f in files:
        full = os.path.join(ROOT_DIR, f)
        h = file_hash(full)
        if h:
            state[f] = {"hash": h, "mtime": os.path.getmtime(full), "synced": time.time()}
    save_sync_state(state)


def categorize_files(files: list[str]) -> tuple[bool, bool, bool]:
    has_html = any(f.endswith(('.html', '.htm', '.js', '.mjs', '.ts', '.tsx', '.jsx')) for f in files)
    has_css = any(f.endswith('.css') for f in files)
    has_asset = any(not f.endswith(('.html', '.htm', '.css', '.js', '.mjs', '.ts'))
                    for f in files)
    return has_html, has_css, has_asset


def push_to_remote(files: list[str]) -> bool:
    if not remote_config["host"] or not remote_config["path"]:
        return False
    host = remote_config["host"]
    remote_path = remote_config["path"]
    method = remote_config.get("method") or "rsync"
    success = True
    for f in files:
        local = os.path.join(ROOT_DIR, f)
        if not os.path.exists(local):
            continue
        remote_file = f"{host}:{remote_path}/{f}"
        if method == "rsync":
            cmd = ["rsync", "-az", "--relative", local, remote_file]
        else:
            cmd = ["scp", "-q", local, remote_file]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=10, cwd=str(ROOT_DIR))
            if result.returncode != 0:
                log("REMOTE", f"推送失败: {f} → {remote_file}")
                success = False
            else:
                log("REMOTE", f"已推送: {f} → {host}")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            log("REMOTE", f"推送异常: {f} ({e})")
            success = False
    return success


def build_live_reload_js(ws_port: int) -> str:
    return r"""<script data-live-reload>
(function(){
var WS='ws://'+location.hostname+':""" + str(ws_port) + r"""',badge,logPanel,retry=1e3,maxR=1e4,history=[];
function B(s,detail){
if(!badge){badge=document.createElement('div');badge.id='__lr';badge.style.cssText='position:fixed;bottom:14px;right:14px;z-index:999999;padding:5px 12px;border-radius:12px;font-size:11px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-weight:600;letter-spacing:.3px;pointer-events:none;transition:all .3s ease;color:#fff;box-shadow:0 2px 10px rgba(0,0,0,.18);cursor:default';document.body.appendChild(badge);
badge.addEventListener('click',function(e){e.stopPropagation();toggleLog();});}
var m={connected:{bg:'#34c759',t:'\u25cf \u5b9e\u65f6\u540c\u6b65\u4e2d'},reconnecting:{bg:'#ff9500',t:'\u25cc \u91cd\u8fde\u4e2d...'},disconnected:{bg:'#ff3b30',t:'\u25cb \u8fde\u63a5\u65ad\u5f00'},reloading:{bg:'#007aff',t:'\u21bb \u6b63\u5728\u5237\u65b0...'},hotcss:{bg:'#af52de',t:'\u2668 CSS\u70ed\u66f4\u65b0'},conflict:{bg:'#ff3b30',t:'\u26a0 \u51b2\u7a81\u68c0\u6d4b'},syncing:{bg:'#5856d6',t:'\u2191 \u540c\u6b65\u4e2d...'},synced:{bg:'#34c759',t:'\u2713 \u540c\u6b65\u5b8c\u6210'}};
var st=m[s]||m.disconnected;badge.style.background=st.bg;badge.textContent=st.t+(detail?' '+detail:'');badge.style.opacity='1';
if(s==='reloading'||s==='hotcss'||s==='synced')setTimeout(function(){badge.style.opacity='0';},2500);
}
function addLog(type,msg){
var now=new Date();var ts=String(now.getHours()).padStart(2,'0')+':'+String(now.getMinutes()).padStart(2,'0')+':'+String(now.getSeconds()).padStart(2,'0');
history.unshift({ts:ts,type:type,msg:msg});if(history.length>50)history.pop();
if(logPanel)renderLog();
}
function toggleLog(){
if(logPanel){logPanel.remove();logPanel=null;return;}
logPanel=document.createElement('div');logPanel.id='__lr_log';
logPanel.style.cssText='position:fixed;bottom:50px;right:14px;z-index:999998;width:320px;max-height:280px;overflow-y:auto;background:rgba(28,28,30,0.95);border-radius:12px;padding:10px;font-size:11px;font-family:"JetBrains Mono",monospace;color:#e5e5e7;box-shadow:0 8px 32px rgba(0,0,0,.3);backdrop-filter:blur(20px)';
document.body.appendChild(logPanel);renderLog();
}
function renderLog(){
if(!logPanel)return;var h='<div style="font-weight:700;margin-bottom:6px;color:#aeaeb2">\u540c\u6b65\u65e5\u5fd7</div>';
history.forEach(function(e){var c=e.type==='error'?'#ff453a':e.type==='conflict'?'#ff9f0a':e.type==='sync'?'#30d158':'#8e8e93';
h+='<div style="padding:2px 0;border-bottom:1px solid rgba(255,255,255,.06)"><span style="color:#636366">'+e.ts+'</span> <span style="color:'+c+'">\u25cf</span> '+e.msg+'</div>';});
logPanel.innerHTML=h;
}
function C(){
var w=new WebSocket(WS);
w.onopen=function(){B('connected');retry=1e3;addLog('info','\u5df2\u8fde\u63a5\u5230\u540c\u6b65\u670d\u52a1');console.log('[LiveSync] \u5df2\u8fde\u63a5');};
w.onmessage=function(e){
try{var data=JSON.parse(e.data);}catch(ex){data={action:e.data};}
if(data.action==='reload'){B('reloading',data.files?data.files.join(', '):'');addLog('info','\u5237\u65b0: '+(data.files?data.files.join(', '):''));console.log('[LiveSync] \u6587\u4ef6\u53d8\u66f4\uff0c\u5237\u65b0\u9875\u9762');setTimeout(function(){location.reload();},80);}
else if(data.action==='css-reload'){B('hotcss');addLog('info','CSS\u70ed\u66f4\u65b0');console.log('[LiveSync] CSS\u53d8\u66f4\uff0c\u70ed\u66f4\u65b0');var ls=document.querySelectorAll('link[rel="stylesheet"]');ls.forEach(function(l){var u=new URL(l.href);u.searchParams.set('_lr',Date.now());l.href=u.toString();});}
else if(data.action==='conflict'){B('conflict',data.files?data.files.length+'个文件':'');addLog('conflict','\u51b2\u7a81: '+(data.files?data.files.join(', '):''));console.warn('[LiveSync] \u51b2\u7a81\u68c0\u6d4b:',data.files);}
else if(data.action==='synced'){B('synced');addLog('sync','\u8fdc\u7a0b\u540c\u6b65\u5b8c\u6210');}
else if(data.action==='sync-fail'){addLog('error','\u8fdc\u7a0b\u540c\u6b65\u5931\u8d25');}
};
w.onclose=function(){B('disconnected');addLog('error','\u65ad\u5f00\uff0c'+Math.round(retry/1e3)+'s\u540e\u91cd\u8fde');console.log('[LiveSync] \u65ad\u5f00');setTimeout(function(){B('reconnecting');C();},retry);retry=Math.min(retry*1.6,maxR);};
w.onerror=function(){w.close();};
}
if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',function(){setTimeout(C,300);});}else{setTimeout(C,300);}
})();
</script>
"""


class LiveReloadHandler(http.server.SimpleHTTPRequestHandler):
    ws_port = DEFAULT_WS_PORT

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT_DIR), **kwargs)

    def _send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS, PATCH')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-CSRF-Token, X-Requested-With')
        self.send_header('Access-Control-Allow-Credentials', 'true')
        self.send_header('Access-Control-Max-Age', '86400')

    def _proxy_request(self, method):
        try:
            target_url = API_PROXY_TARGET
            parsed = urllib.parse.urlparse('http://' + target_url + self.path)
            proxy_path = parsed.path
            if parsed.query:
                proxy_path += '?' + parsed.query

            headers = {}
            for key, value in self.headers.items():
                if key.lower() not in ('host', 'content-length', 'accept-encoding'):
                    headers[key] = value
            headers['Host'] = target_url
            headers['Accept-Encoding'] = 'identity'

            body = None
            content_length = self.headers.get('Content-Length')
            if content_length:
                body = self.rfile.read(int(content_length))

            conn = http.client.HTTPConnection(target_url, timeout=15)
            conn.request(method, proxy_path, body=body, headers=headers)
            response = conn.getresponse()

            raw_data = response.read()

            # 自动解压gzip/deflate响应
            content_encoding = None
            for key, value in response.getheaders():
                if key.lower() == 'content-encoding':
                    content_encoding = value.lower()
                    break

            try:
                if content_encoding == 'gzip':
                    raw_data = gzip.decompress(raw_data)
                elif content_encoding == 'deflate':
                    import zlib
                    raw_data = zlib.decompress(raw_data)
            except Exception:
                pass  # 解压失败则使用原始数据

            self.send_response(response.status)
            self._send_cors_headers()
            for key, value in response.getheaders():
                if key.lower() not in ('transfer-encoding', 'content-encoding', 'connection', 'content-length'):
                    self.send_header(key, value)
            self.send_header('Content-Length', str(len(raw_data)))
            self.end_headers()

            self.wfile.write(raw_data)
            conn.close()
            log("PROXY", f"{method} {self.path} -> {target_url} ({response.status})")
        except Exception as e:
            log("PROXY", f"代理失败: {method} {self.path} -> {e}")
            self.send_response(502)
            self.send_header('Content-Type', 'application/json')
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"success": False, "message": f"代理错误: {str(e)}"}).encode('utf-8'))

    def do_OPTIONS(self):
        if self.path.startswith('/api/'):
            self.send_response(204)
            self._send_cors_headers()
            self.end_headers()
            return
        super().do_OPTIONS()

    def do_GET(self):
        if self.path.startswith('/api/'):
            self._proxy_request('GET')
            return

        path = self.translate_path(self.path)
        ext = os.path.splitext(path)[1].lower()

        if os.path.isdir(path):
            index_path = os.path.join(path, 'index.html')
            if os.path.isfile(index_path):
                path = index_path
                ext = '.html'

        if ext == '.html':
            try:
                with open(path, 'rb') as f:
                    content = f.read()
            except OSError:
                self.send_error(404)
                return

            inject_js = build_live_reload_js(self.ws_port)
            content_str = content.decode('utf-8', errors='replace')
            injected = content_str.replace('</body>', inject_js + '\n</body>')
            if injected == content_str:
                injected = content_str.replace('</html>', inject_js + '\n</html>')

            body = injected.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            self.wfile.write(body)
            return

        if ext == '.css':
            try:
                with open(path, 'rb') as f:
                    content = f.read()
            except OSError:
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header('Content-Type', 'text/css; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(content)
            return

        super().do_GET()

    def do_POST(self):
        if self.path.startswith('/api/'):
            self._proxy_request('POST')
            return
        super().do_POST()

    def do_PUT(self):
        if self.path.startswith('/api/'):
            self._proxy_request('PUT')
            return
        super().do_PUT()

    def do_DELETE(self):
        if self.path.startswith('/api/'):
            self._proxy_request('DELETE')
            return
        super().do_DELETE()

    def do_PATCH(self):
        if self.path.startswith('/api/'):
            self._proxy_request('PATCH')
            return
        super().do_PATCH()

    def log_message(self, format, *args):
        msg = format % args
        if '200' in msg or '304' in msg:
            return
        log("HTTP", msg)


async def ws_handler(websocket):
    connected.add(websocket)
    remote = websocket.remote_address
    log("WS", f"浏览器已连接: {remote[0]}:{remote[1]}")
    try:
        async for _ in websocket:
            pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        connected.discard(websocket)
        log("WS", f"浏览器已断开: {remote[0]}:{remote[1]}")


async def broadcast_json(data: dict):
    if not connected:
        return
    msg = json.dumps(data, ensure_ascii=False)
    dead = set()
    for ws in list(connected):
        try:
            await ws.send(msg)
        except (websockets.exceptions.ConnectionClosed, OSError):
            dead.add(ws)
    connected.difference_update(dead)


async def broadcast_text(message: str):
    if not connected:
        return
    dead = set()
    for ws in list(connected):
        try:
            await ws.send(message)
        except (websockets.exceptions.ConnectionClosed, OSError):
            dead.add(ws)
    connected.difference_update(dead)


async def file_watcher():
    old_snap = build_snapshot()
    debounce_timer: asyncio.TimerHandle | None = None
    pending_files: list[str] = []

    def on_debounce():
        nonlocal debounce_timer, pending_files
        debounce_timer = None
        files = pending_files
        pending_files = []
        if not files:
            return

        conflicts = detect_conflicts(files, old_snap, build_snapshot())
        if conflicts:
            sync_stats["conflicts"] += len(conflicts)
            conflict_names = [c["file"] for c in conflicts]
            log("CONFLICT", f"检测到 {len(conflicts)} 个文件冲突: {', '.join(conflict_names[:5])}")
            for c in conflicts:
                log("CONFLICT", f"  {c['file']}: 旧哈希={c['previous_hash']} 新哈希={c['current_hash']}")
            asyncio.ensure_future(broadcast_json({
                "action": "conflict",
                "files": conflict_names,
                "details": conflicts
            }))

        has_html, has_css, has_asset = categorize_files(files)
        short = [os.path.basename(f) for f in files[:5]]

        if has_html:
            log("SYNC", f"HTML/JS变更 → 整页刷新: {', '.join(short)}")
            asyncio.ensure_future(broadcast_json({
                "action": "reload",
                "files": short,
                "type": "full"
            }))
        elif has_css:
            log("SYNC", f"CSS变更 → 热更新: {', '.join(short)}")
            asyncio.ensure_future(broadcast_json({
                "action": "css-reload",
                "files": short,
                "type": "hot"
            }))
        else:
            log("SYNC", f"资源变更 → 整页刷新: {', '.join(short)}")
            asyncio.ensure_future(broadcast_json({
                "action": "reload",
                "files": short,
                "type": "full"
            }))

        update_sync_state(files)

        sync_stats["total_syncs"] += 1
        sync_stats["last_sync"] = time.strftime("%H:%M:%S")

        sync_history.append({
            "time": time.strftime("%H:%M:%S"),
            "files": short,
            "conflicts": len(conflicts)
        })
        if len(sync_history) > 100:
            sync_history.pop(0)

        if remote_config["host"]:
            log("REMOTE", f"推送 {len(files)} 个文件到 {remote_config['host']}...")
            asyncio.ensure_future(broadcast_json({"action": "syncing"}))
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, push_to_remote, files)

    total_files = len(old_snap)
    log("WATCH", f"文件监听已启动（间隔: {SCAN_INTERVAL}s, 监听 {total_files} 个文件）")

    while True:
        await asyncio.sleep(SCAN_INTERVAL)
        try:
            new_snap = build_snapshot()
            added, modified, deleted = find_changes(old_snap, new_snap)
            changed = added + modified + deleted
            if changed:
                pending_files = list(set(pending_files) | set(changed))
                if debounce_timer:
                    debounce_timer.cancel()
                loop = asyncio.get_running_loop()
                debounce_timer = loop.call_later(DEBOUNCE_SEC, on_debounce)
            old_snap = new_snap
        except Exception as e:
            log("ERROR", f"扫描异常: {e}")


_http_server = None


def start_http(http_port: int, ws_port: int):
    global _http_server
    LiveReloadHandler.ws_port = ws_port
    try:
        _http_server = http.server.HTTPServer(('0.0.0.0', http_port), LiveReloadHandler)
    except OSError as e:
        log("ERROR", f"HTTP 端口 {http_port} 启动失败: {e}")
        os._exit(1)

    local_ip = get_local_ip()
    log("HTTP", f"静态服务已启动: http://localhost:{http_port}")
    if local_ip != '127.0.0.1':
        log("HTTP", f"局域网访问:    http://{local_ip}:{http_port}")
    _http_server.serve_forever()


async def run(http_port: int, ws_port: int):
    print('=' * 60, flush=True)
    print('  Live Sync 开发服务器', flush=True)
    print('  文件变更 → 自动检测 → 浏览器实时刷新 → 远程同步', flush=True)
    print('=' * 60, flush=True)

    http_thread = threading.Thread(target=start_http, args=(http_port, ws_port), daemon=False)
    http_thread.start()
    await asyncio.sleep(0.5)

    try:
        async with ws_serve(
            ws_handler, '0.0.0.0', ws_port, ping_interval=20, ping_timeout=10, compression=None
        ):
            log("WS", f"WebSocket 已启动: ws://localhost:{ws_port}")
            print('-' * 60, flush=True)
            print('  状态徽章:', flush=True)
            print('    ● 绿色 = 实时同步中', flush=True)
            print('    ◌ 黄色 = 重连中', flush=True)
            print('    ○ 红色 = 连接断开 / 冲突检测', flush=True)
            print('    ↻ 蓝色 = 正在刷新', flush=True)
            print('    ♨ 紫色 = CSS热更新', flush=True)
            print('    ↑ 靛色 = 远程同步中', flush=True)
            print('    ✓ 绿色 = 同步完成', flush=True)
            print('  点击徽章查看同步日志', flush=True)
            if remote_config["host"]:
                print(f'  远程同步: {remote_config["host"]}:{remote_config["path"]}', flush=True)
            print('  按 Ctrl+C 停止服务', flush=True)
            print('=' * 60, flush=True)

            local_ip = get_local_ip()
            print(f'\n  >>> 浏览器打开: http://{local_ip}:{http_port}/\n', flush=True)

            await file_watcher()
    except OSError as e:
        log("ERROR", f"WebSocket 端口 {ws_port} 启动失败: {e}")
        print(f'  请使用 --ws-port 指定其他端口', flush=True)
        os._exit(1)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Live Sync 开发服务器')
    parser.add_argument('--port', type=int, default=DEFAULT_HTTP_PORT,
                        help=f'HTTP 端口 (默认: {DEFAULT_HTTP_PORT})')
    parser.add_argument('--ws-port', type=int, default=DEFAULT_WS_PORT,
                        help=f'WebSocket 端口 (默认: {DEFAULT_WS_PORT})')
    parser.add_argument('--remote', type=str, default=None,
                        help='远程同步目标 (格式: user@host:/path)')
    parser.add_argument('--sync-method', type=str, choices=['rsync', 'scp'], default='rsync',
                        help='远程同步方式 (默认: rsync)')
    args = parser.parse_args()

    if args.remote:
        try:
            host_part, path_part = args.remote.split(':', 1)
            remote_config["host"] = host_part
            remote_config["path"] = path_part
            remote_config["method"] = args.sync_method
        except ValueError:
            print('  [ERROR] --remote 格式错误，应为 user@host:/path', flush=True)
            sys.exit(1)

    for label, port in [('HTTP', args.port), ('WebSocket', args.ws_port)]:
        if is_port_in_use(port):
            print(f'  [ERROR] {label} 端口 {port} 已被占用', flush=True)
            print(f'  请使用 --{"port" if label == "HTTP" else "ws-port"} 指定其他端口', flush=True)
            sys.exit(1)

    try:
        asyncio.run(run(args.port, args.ws_port))
    except KeyboardInterrupt:
        print('\n  服务已停止', flush=True)
    finally:
        if _http_server:
            _http_server.shutdown()
        if SYNC_STATE_FILE.exists():
            try:
                SYNC_STATE_FILE.unlink()
            except OSError:
                pass