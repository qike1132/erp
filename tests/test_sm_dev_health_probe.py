"""dev_mode 健康探测回归锁（2026-10-16 事故：探测器自身坏掉，杀健康后端）。

背景
----
1dd4de90 把 dev_mode 两处探测从裸 `urllib.request.urlopen` 改成
`_HTTP_DIRECT.urlopen(...)` 想绕开系统代理（constants 已实证：代理转发
127.0.0.1 探测会间歇假失败）。但 `_HTTP_DIRECT` 是
`build_opener(ProxyHandler({}))` 的产物 —— **`OpenerDirector` 没有
`urlopen` 方法**（只有 `.open`，hosting_view.py:87 用的正是 .open）。
于是每次探测必抛 AttributeError，被外层的 `except Exception` 吞掉，
30 次探测耗尽 30s 全失败 → 判定「后端未就绪」→ `kill_process_tree`
杀掉一个**其实已经 startup complete 的健康后端**（2026-10-16 11:14 实测）。

本文件锁三件事：
1. 探测必须用**存在**的方法（.open）——AST 锁，禁止 .urlopen 回潮；
2. 探测必须用直连 opener（不允许回退裸 urllib.request.urlopen）——修 H1 的本意；
3. 行为级：用真 opener 探测真起真关的本地 HTTP 服务，证明「探测器能用」。

运行: python -m pytest tests/test_sm_dev_health_probe.py -q
"""
import ast
import http.server
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DM = ROOT / "server_manager" / "dev_mode.py"


def _func_src(name: str) -> str:
    src = DM.read_text(encoding="utf-8")
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"dev_mode.py 内未找到 {name}")


def test_health_probe_uses_open_not_urlopen():
    """核心锁：OpenerDirector 只有 .open —— .urlopen 每次必 AttributeError。"""
    for fn in ("start_dual_thread",):
        body = _func_src(fn)
        assert "_HTTP_DIRECT.urlopen" not in body, (
            "OpenerDirector 无 urlopen 方法；这是 2026-10-16 事故的直接原因")
        assert "_HTTP_DIRECT.open(" in body, f"{fn} 未用直连 opener 探测"


def test_both_probes_present():
    """后端与前端的探测点都在（漏一个 = 该侧启动判断失灵）。"""
    body = _func_src("start_dual_thread")
    assert body.count("_HTTP_DIRECT.open(") == 2, \
        f"应有后端+前端两处直连探测，实际 {body.count('_HTTP_DIRECT.open(')} 处"


def test_probe_does_not_use_proxied_urlopen():
    """H1 的本意：不得回退到吃系统代理的裸 urlopen。"""
    body = _func_src("start_dual_thread")
    for ln in body.splitlines():
        if "urlopen" in ln and "_HTTP_DIRECT" not in ln:
            stripped = ln.strip()
            if not stripped.startswith("#"):
                pytest.fail(f"仍走系统代理的裸 urlopen: {stripped}")


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, *a):  # 静默，避免污染 pytest 输出
        pass


@pytest.fixture()
def live_health_server():
    """起一个真本地 HTTP 服务（ephemeral 端口），用完即关。"""
    srv = http.server.HTTPServer(("127.0.0.1", 0), _HealthHandler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield port
    srv.shutdown()
    srv.server_close()


def test_probe_reaches_a_live_local_server(live_health_server):
    """行为级：直连 opener 探测本地活服务必须 200 —— 证明探测器自身可用。

    等价复刻事故场景：若此处用 .urlopen，本用例会 AttributeError。
    """
    from server_manager.constants import _HTTP_DIRECT
    with _HTTP_DIRECT.open(f"http://127.0.0.1:{live_health_server}/api/health", timeout=2) as resp:
        assert resp.status == 200


def test_direct_and_proxied_both_work_without_proxy(live_health_server):
    """本机无代理时两种 opener 都应通（排除「只有直连能通」的过度断言）。"""
    import urllib.request
    from server_manager.constants import _HTTP_DIRECT
    assert _HTTP_DIRECT.open(f"http://127.0.0.1:{live_health_server}/", timeout=2).status == 200
    assert urllib.request.urlopen(f"http://127.0.0.1:{live_health_server}/", timeout=2).status == 200
