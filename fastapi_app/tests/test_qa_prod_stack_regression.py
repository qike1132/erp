"""QA 独立对抗性回归验证 —— 生产栈 7 缺陷修复（D1~D7）。

作者：QA（严过关）。本文件的断言**独立于**工程师所写测试，目的在**证伪**修复，
而非复述其结论。

安全约定（生产机兼开发机，禁止触碰在线服务）：
  * 绝不真实调用 _FrontendNginx._ensure_started / maybe_restart / start —— 其内部
    第一步 _kill_all() 会 `taskkill /F /T /IM nginx.exe`，会杀掉在线生产 nginx。
    本文件对所有会触发进程操作的路径（_kill_all / kill_tree / Popen / start）
    一律打桩。
  * 对在线服务的访问仅限只读 GET 健康端点（/nginx-health、/api/health）。
"""
from __future__ import annotations

import http.server
import json
import os
import re
import threading
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from fastapi_app.core import middleware as mw
from fastapi_app.core import prod_runner


# ===========================================================================
# 通用打桩工具
# ===========================================================================
class _Clock:
    """可推进的单调时钟，替换 prod_runner.time。"""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def monotonic(self) -> float:
        return self.t

    def sleep(self, _s: float = 0.0) -> None:
        return None

    def advance(self, dt: float) -> None:
        self.t += dt


class _AliveProc:
    """进程存活：poll() 恒 None。"""

    returncode = None

    def __init__(self, pid: int = 4321) -> None:
        self.pid = pid

    def poll(self) -> None:
        return None


class _DeadProc:
    """进程已退出：poll() 恒返回退出码。"""

    pid = 4321
    returncode = 1

    def poll(self) -> int:
        return 1


class _RaceProc:
    """探针期间进程死亡：入口 poll→None，复检 poll→退出码。

    复刻真实竞态：_probe_health 最长可耗时 ~10s，期间 uvicorn master 可能已死。
    """

    pid = 4321
    returncode = 1

    def __init__(self) -> None:
        self.n = 0

    def poll(self) -> int | None:
        self.n += 1
        return None if self.n == 1 else 1


def _mk_managed(proc, workers: int = 8) -> prod_runner._Managed:
    m = prod_runner._Managed(
        "后端(uvicorn)", ["x"], prod_runner.PROJECT_ROOT,
        health_url="http://127.0.0.1:5002/api/health", workers=workers,
    )
    m.proc = proc
    m.status = "ready"
    return m


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    import socket

    s = socket.socket()
    s.settimeout(1.0)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


# 在线服务可用性（本机生产机为真；无服务的 CI 上相关 live 用例自动跳过）
_NGINX_UP = _port_open(3000)
_BACKEND_UP = _port_open(5002)


# ===========================================================================
# D7 —— 纯函数 _should_restart 的真值表
# ===========================================================================
class TestD7ShouldRestartTruthTable:
    @pytest.mark.parametrize("consecutive,window", [
        (3, 90.0), (4, 90.0), (10, 120.0), (366, 99999.0),
    ])
    def test_alive_never_restarts(self, consecutive: int, window: float) -> None:
        """核心闸门：进程存活时，无论阈值多大都必须判否（=消掉 366 次误杀的形态）。"""
        assert prod_runner._should_restart(consecutive, window, proc_alive=True) is False

    def test_alive_extreme_values(self) -> None:
        assert prod_runner._should_restart(10 ** 6, 10 ** 9, proc_alive=True) is False

    def test_dead_and_thresholds_met(self) -> None:
        assert prod_runner._should_restart(3, 90.0, proc_alive=False) is True
        assert prod_runner._should_restart(4, 500.0, proc_alive=False) is True

    def test_dead_below_consecutive(self) -> None:
        assert prod_runner._should_restart(2, 10 ** 9, proc_alive=False) is False

    def test_dead_below_window(self) -> None:
        assert prod_runner._should_restart(10 ** 6, 89.999, proc_alive=False) is False

    def test_boundary_exact(self) -> None:
        # 恰好等于阈值应重启；差一点不重启。
        assert prod_runner._should_restart(3, 90.0, proc_alive=False) is True
        assert prod_runner._should_restart(3, 89.999999, proc_alive=False) is False
        assert prod_runner._should_restart(2, 90.0, proc_alive=False) is False


# ===========================================================================
# D7 —— poll() 状态机：存活绝不杀 / 死亡才重启 / 早期分支语义
# ===========================================================================
class TestD7PollStateMachine:
    def test_alive_proc_never_killed_over_long_failure(self, monkeypatch) -> None:
        """进程存活 + 探针连续失败 100 轮、窗口 500s：绝不能 kill_tree。"""
        clock = _Clock()
        monkeypatch.setattr(prod_runner, "time", clock)
        monkeypatch.setattr(prod_runner, "_http_ok", lambda *a, **k: False)
        m = _mk_managed(_AliveProc())
        killed: list[float] = []
        monkeypatch.setattr(m, "kill_tree", lambda: killed.append(clock.t))

        for _ in range(100):
            m.poll()
            clock.advance(5.0)  # 累计窗口 500s ≫ 90s

        assert killed == [], f"进程存活却被误杀于 t={killed}"
        assert m.status != "crashed"
        assert m.consecutive_health_fail == 100  # 计数持续累加而非被杀
        assert m.delay > 2.0  # 退避放宽

    def test_poll_passes_true_proc_alive_for_alive_proc(self, monkeypatch) -> None:
        """对抗点：即便纯函数正确，若 poll 传错 proc_alive 仍会误杀。"""
        clock = _Clock()
        monkeypatch.setattr(prod_runner, "time", clock)
        monkeypatch.setattr(prod_runner, "_http_ok", lambda *a, **k: False)
        captured: list[tuple] = []
        orig = prod_runner._should_restart

        def spy(c: int, w: float, a: bool) -> bool:
            captured.append((c, w, a))
            return orig(c, w, a)

        monkeypatch.setattr(prod_runner, "_should_restart", spy)
        m = _mk_managed(_AliveProc())
        monkeypatch.setattr(m, "kill_tree", lambda: None)
        for _ in range(5):
            m.poll()
            clock.advance(30.0)

        assert captured, "健康持续失败却未调用 _should_restart（闸门缺失？）"
        assert all(a is True for _, _, a in captured), f"proc_alive 传参错误: {captured}"

    def test_proc_dead_during_probe_triggers_restart(self, monkeypatch) -> None:
        """探针期间 master 死亡（复检为死 + 阈值满足）→ 安排重启（kill_tree + crashed）。"""
        clock = _Clock()
        monkeypatch.setattr(prod_runner, "time", clock)
        monkeypatch.setattr(prod_runner, "_http_ok", lambda *a, **k: False)
        m = _mk_managed(_RaceProc())
        killed = {"n": 0}
        monkeypatch.setattr(m, "kill_tree", lambda: killed.__setitem__("n", killed["n"] + 1))
        m.consecutive_health_fail = 2
        m.health_fail_start = clock.t - 200.0

        m.poll()

        assert killed["n"] == 1
        assert m.status == "crashed"
        assert m.next_start > 0

    def test_entry_dead_uses_early_branch_not_should_restart(self, monkeypatch) -> None:
        """踩坑澄清：入口即已死的进程走 early branch（_mark_crashed），**不经过**
        _should_restart。此为设计如此，不是缺陷。"""
        monkeypatch.setattr(prod_runner, "_http_ok", lambda *a, **k: False)
        m = _mk_managed(_DeadProc())
        killed = {"n": 0}
        monkeypatch.setattr(m, "kill_tree", lambda: killed.__setitem__("n", killed["n"] + 1))
        calls = {"n": 0}
        orig = prod_runner._should_restart

        def spy(c, w, a):
            calls["n"] += 1
            return orig(c, w, a)

        monkeypatch.setattr(prod_runner, "_should_restart", spy)
        m.poll()

        assert calls["n"] == 0, "入口已死应走 early branch"
        assert killed["n"] == 0, "入口已死无需 taskkill（进程本就不在）"
        assert m.status == "crashed"
        assert m.next_start > 0

    def test_mark_crashed_is_idempotent(self, monkeypatch) -> None:
        """重复排期防护：已 crashed 再调 _mark_crashed 不得重置 next_start/delay/step。"""
        clock = _Clock()
        monkeypatch.setattr(prod_runner, "time", clock)
        m = _mk_managed(_DeadProc())
        m.status = "running"
        m.delay = 2.0
        m.backoff_step = 0
        m.next_start = 0.0

        m._mark_crashed()
        snap = (m.next_start, m.delay, m.backoff_step, m.status)
        assert m.status == "crashed"
        assert m.next_start == clock.t + 2.0

        for _ in range(10):
            m._mark_crashed()

        assert (m.next_start, m.delay, m.backoff_step, m.status) == snap, (
            "_mark_crashed 非幂等：next_start 被反复重置 → 重启饥饿"
        )

    def test_maybe_restart_not_starved_by_repeated_poll(self, monkeypatch) -> None:
        """主循环每 3s 轮询一轮，进程已死。若每轮重置 next_start 将永不重启（饥饿）。
        修复后应在首轮退避 2s 后成功安排一次重启。"""
        clock = _Clock()
        monkeypatch.setattr(prod_runner, "time", clock)
        monkeypatch.setattr(prod_runner, "_http_ok", lambda *a, **k: False)
        m = _mk_managed(_DeadProc())
        m.status = "running"
        m.delay = 2.0
        started: list[float] = []
        monkeypatch.setattr(m, "start", lambda: started.append(clock.t))

        for _ in range(5):
            m.poll()             # 每轮判定已死 → _mark_crashed
            m.maybe_restart()    # next_start 到点则重启
            clock.advance(3.0)   # 主循环间隔 3s

        assert started, "已退出进程始终未被重启（重启饥饿）"


# ===========================================================================
# D1 —— 探针假阳性拦截（live，动手构造，非仅读代码）
# ===========================================================================
class _SpaFallbackHandler(http.server.BaseHTTPRequestHandler):
    """模拟 Vite dev server：对任意路径返回 200 + HTML（SPA fallback）。"""

    def do_GET(self) -> None:
        body = (b"<!doctype html><html><head><title>ERP</title></head>"
                b"<body><div id='app'></div></body></html>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a) -> None:  # 静音
        return None


@pytest.fixture
def spa_fallback_port():
    """起临时 SPA fallback 服务（随机空闲端口）；用后必收。"""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SpaFallbackHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield port
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


class TestD1ProbeFalsification:
    def test_spa_fallback_rejected_only_with_expect_substr(self, spa_fallback_port) -> None:
        """构造 200+HTML 的服务：不带子串校验→True（旧行为误判）；带→False（修复生效）。"""
        url = f"http://127.0.0.1:{spa_fallback_port}/nginx-health"
        assert prod_runner._http_ok(url) is True, "旧行为应仅凭状态码判真（对照）"
        assert prod_runner._http_ok(url, expect_substr='"service":"nginx"') is False

    @pytest.mark.skipif(not _NGINX_UP, reason="在线 nginx :3000 不可用（live 用例跳过）")
    def test_real_nginx_health_contains_marker_live(self) -> None:
        """实测在线 nginx /nginx-health 响应体确含标记串。"""
        with prod_runner._OPENER_DIRECT.open(
            "http://127.0.0.1:3000/nginx-health", timeout=5
        ) as r:
            body = r.read(4096).decode("utf-8", errors="replace")
        assert '"service":"nginx"' in body, f"真实 nginx 健康体不含标记: {body!r}"

    @pytest.mark.skipif(not _NGINX_UP, reason="在线 nginx :3000 不可用（live 用例跳过）")
    def test_no_false_negative_on_real_nginx(self) -> None:
        """反向验证：带子串校验必须仍判真——只挡假阳性却否定真服务是更糟的回归。"""
        assert prod_runner._http_ok(
            "http://127.0.0.1:3000/nginx-health",
            expect_substr='"service":"nginx"',
        ) is True

    @pytest.mark.skipif(not _BACKEND_UP, reason="在线后端 :5002 不可用（live 用例跳过）")
    def test_backward_compatible_backend_probe_live(self) -> None:
        """既有调用方形态（不传 expect_substr）对后端 /api/health 必须仍为真。"""
        assert prod_runner._http_ok("http://127.0.0.1:5002/api/health") is True

    def test_frontend_alive_false_on_spa_fallback(self, spa_fallback_port, monkeypatch) -> None:
        """_FrontendNginx.alive() 走带子串校验的探针 → 对 SPA fallback 判否。"""
        fe = prod_runner._FrontendNginx(Path("nginx.exe"), spa_fallback_port)
        assert fe.alive() is False


# ===========================================================================
# D2 —— _ensure_started 探测全败不得假成功（打桩，禁真实 taskkill）
# ===========================================================================
def _prep_frontend(monkeypatch, tmp_path, http_ok: bool) -> prod_runner._FrontendNginx:
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    monkeypatch.setattr(prod_runner, "LOGS_DIR", logs)
    monkeypatch.setattr(prod_runner, "time", _Clock())
    monkeypatch.setattr(prod_runner, "_http_ok", lambda *a, **k: http_ok)
    monkeypatch.setattr(prod_runner.subprocess, "Popen", lambda *a, **k: _AliveProc())
    fe = prod_runner._FrontendNginx(Path("nginx.exe"), 3000)
    monkeypatch.setattr(fe, "_kill_all", lambda: None)  # 严禁真实 taskkill nginx.exe
    return fe


class TestD2EnsureStarted:
    def test_all_probes_fail_marks_crashed_not_running(self, monkeypatch, tmp_path) -> None:
        fe = _prep_frontend(monkeypatch, tmp_path, http_ok=False)
        try:
            fe._ensure_started()
        finally:
            fe._close_spawn_log()
        assert fe.status == "crashed", "探测全败仍置 running（假成功未修复）"
        assert fe.next_start > 0
        assert fe.delay == 10.0  # 5.0 → min(10.0, 30.0)

    def test_probe_ok_marks_running(self, monkeypatch, tmp_path) -> None:
        fe = _prep_frontend(monkeypatch, tmp_path, http_ok=True)
        try:
            fe._ensure_started()
        finally:
            fe._close_spawn_log()
        assert fe.status == "running"
        assert fe.delay == 5.0

    def test_failure_dumps_error_log_tail(self, monkeypatch, tmp_path, capsys) -> None:
        fe = _prep_frontend(monkeypatch, tmp_path, http_ok=False)
        (prod_runner.LOGS_DIR / "nginx-error.log").write_text(
            "nginx: [emerg] bind() to 0.0.0.0:3000 failed (10013)\n", encoding="utf-8"
        )
        try:
            fe._ensure_started()
        finally:
            fe._close_spawn_log()
        out = capsys.readouterr().out
        assert "nginx-error.log 尾部" in out
        assert "bind() to 0.0.0.0:3000 failed" in out


# ===========================================================================
# D3 —— write_status 不谎报前端状态，且 ready 语义不变
# ===========================================================================
def _build_supervisor(monkeypatch, tmp_path, http_ok: bool, has_nginx: bool = True):
    monkeypatch.setattr(
        prod_runner, "_find_nginx",
        (lambda: Path("nginx.exe")) if has_nginx else (lambda: None),
    )
    monkeypatch.setattr(prod_runner, "_is_redis_up", lambda *_: False)
    monkeypatch.setattr(prod_runner, "_http_ok", lambda *a, **k: http_ok)
    monkeypatch.setattr(prod_runner, "STATUS_FILE", tmp_path / "prod_runner.json")
    return prod_runner.Supervisor(workers=4, api_port=5002, web_port=3000, with_arq=False)


class TestD3WriteStatus:
    def test_no_false_running_when_nginx_down(self, monkeypatch, tmp_path) -> None:
        sup = _build_supervisor(monkeypatch, tmp_path, http_ok=False)
        sup.nginx.status = "running"  # 注入被污染的陈旧状态，验证落盘不被蒙蔽
        sup.write_status()
        data = json.loads(prod_runner.STATUS_FILE.read_text(encoding="utf-8"))
        fe = data["services"]["frontend"]
        assert fe["type"] == "nginx"
        assert fe["status"] != "running"
        assert fe["pid"] is None
        assert data["frontend_ok"] is False

    def test_reports_ok_and_pid_when_nginx_alive(self, monkeypatch, tmp_path) -> None:
        sup = _build_supervisor(monkeypatch, tmp_path, http_ok=True)
        sup.nginx.proc = _AliveProc(pid=7777)
        sup.write_status()
        data = json.loads(prod_runner.STATUS_FILE.read_text(encoding="utf-8"))
        fe = data["services"]["frontend"]
        assert fe["status"] == "running"
        assert fe["pid"] == 7777
        assert data["frontend_ok"] is True

    def test_ready_semantics_unchanged_backend_only(self, monkeypatch, tmp_path) -> None:
        """ready 语义必须仍只看后端；前端新增 frontend_ok 不得渗入 ready。"""
        sup = _build_supervisor(monkeypatch, tmp_path, http_ok=False)
        sup.backend.status = "ready"
        sup.nginx.status = "crashed"
        sup.write_status()
        data = json.loads(prod_runner.STATUS_FILE.read_text(encoding="utf-8"))
        assert data["ready"] is True, "ready 前端缺失时被错误置否（语义被改）"
        assert data["frontend_ok"] is False

    def test_frontend_ok_field_present_in_vite_fallback(self, monkeypatch, tmp_path) -> None:
        sup = _build_supervisor(monkeypatch, tmp_path, http_ok=False, has_nginx=False)
        sup.write_status()
        data = json.loads(prod_runner.STATUS_FILE.read_text(encoding="utf-8"))
        assert data["frontend_type"] == "vite"
        assert "frontend_ok" in data
        assert data["frontend_ok"] is False


# ===========================================================================
# D4 —— _spawn 保存句柄 + spawn 日志留痕（不触发 _kill_all）
# ===========================================================================
class TestD4Spawn:
    def test_spawn_saves_handle_and_writes_log(self, monkeypatch, tmp_path) -> None:
        logs = tmp_path / "logs"
        logs.mkdir()

        class _FakePopen:
            def __init__(self, *a, **k):
                self.pid = 12345

            def poll(self):
                return None

        monkeypatch.setattr(prod_runner, "LOGS_DIR", logs)
        monkeypatch.setattr(prod_runner.subprocess, "Popen", _FakePopen)
        fe = prod_runner._FrontendNginx(Path("nginx.exe"), 3000)
        fe._spawn()
        try:
            assert fe.proc is not None
            assert fe.pid == 12345
            assert fe._spawn_logf is not None
            assert (logs / "nginx-spawn.out.log").is_file()
        finally:
            fe._close_spawn_log()

    def test_spawn_failure_is_logged_not_silent(self, monkeypatch, tmp_path, capsys) -> None:
        logs = tmp_path / "logs"
        logs.mkdir()

        def _boom(*a, **k):
            raise OSError("boom")

        monkeypatch.setattr(prod_runner, "LOGS_DIR", logs)
        monkeypatch.setattr(prod_runner.subprocess, "Popen", _boom)
        fe = prod_runner._FrontendNginx(Path("nginx.exe"), 3000)
        fe._spawn()
        assert fe.proc is None
        assert "派生 nginx 进程失败" in capsys.readouterr().out


# ===========================================================================
# D5 —— gzip：默认启用 / 显式关闸 / 生产环境仍启用 / os 已导入
# ===========================================================================
_BIG = "x" * 5000  # ≫ minimum_size(1000)


def _gzip_app() -> FastAPI:
    app = FastAPI()

    @app.get("/big")
    async def big():
        return {"data": _BIG}

    @app.get("/tiny")
    async def tiny():
        return {"ok": True}

    mw._setup_gzip(app)
    return app


async def _hit(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.get(path, headers={"Accept-Encoding": "gzip"})


class TestD5Gzip:
    def test_middleware_module_imports_os(self) -> None:
        """修复引入 os.getenv；若漏 import，后端下次重启将 NameError 起不来。"""
        assert hasattr(mw, "os"), "middleware.py 缺少 os 导入（改完就炸）"
        assert mw.os is os

    async def test_gzip_default_on_for_big_body(self, monkeypatch) -> None:
        monkeypatch.delenv("APP_GZIP_DISABLED", raising=False)
        resp = await _hit(_gzip_app(), "/big")
        assert resp.status_code == 200
        assert resp.headers.get("content-encoding") == "gzip"
        assert resp.headers.get("vary") == "Accept-Encoding"

    async def test_gzip_enabled_even_in_production_env(self, monkeypatch) -> None:
        """核心：模拟生产环境（APP_ENV=production），压缩必须仍开启。"""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.delenv("APP_GZIP_DISABLED", raising=False)
        assert mw.settings.is_production is True, "APP_ENV=production 未生效，测试前提不成立"
        resp = await _hit(_gzip_app(), "/big")
        assert resp.headers.get("content-encoding") == "gzip", "生产环境 gzip 被跳过（D5 未修复）"

    async def test_gzip_disabled_by_explicit_env(self, monkeypatch) -> None:
        monkeypatch.setenv("APP_GZIP_DISABLED", "true")
        resp = await _hit(_gzip_app(), "/big")
        assert resp.status_code == 200
        assert resp.headers.get("content-encoding") is None

    async def test_tiny_body_not_compressed_by_design(self, monkeypatch) -> None:
        """澄清：minimum_size=1000，51B 的 /api/health 本就不压缩（设计行为，非缺陷）。"""
        monkeypatch.delenv("APP_GZIP_DISABLED", raising=False)
        resp = await _hit(_gzip_app(), "/tiny")
        assert resp.headers.get("content-encoding") is None


# ===========================================================================
# D6 —— PWA 两个 vite 配置文件：API 条目 NetworkOnly 且二者等价
# ===========================================================================
_FRONTEND = prod_runner.FRONTEND_DIR
_PAIR_RE = re.compile(r"urlPattern:\s*(\S+),\s*handler:\s*'([A-Za-z]+)'")


def _read(fname: str) -> str:
    return (_FRONTEND / fname).read_text(encoding="utf-8")


def _pairs(text: str) -> list[tuple[str, str]]:
    return _PAIR_RE.findall(text)


def _api_handler(text: str) -> str | None:
    """语义化提取 `/api/` 路径条目的 handler。

    判别用原始子串 `\\/api\\/`（即配置里的 `/\\/api\\//i`），避免误命中
    `googleapis`（其中亦含 "api" 字样）等无关条目。
    """
    for pattern, handler in _pairs(text):
        if "\\/api\\/" in pattern:
            return handler
    return None


class TestD6ViteConfigConsistency:
    @pytest.mark.parametrize("fname", ["vite.config.ts", "vite.config.js"])
    def test_api_url_pattern_is_network_only(self, fname: str) -> None:
        handler = _api_handler(_read(fname))
        assert handler is not None, f"{fname}: 未找到 /api/ 的 runtimeCaching 条目"
        assert handler == "NetworkOnly", f"{fname}: /api/ handler={handler}（应为 NetworkOnly）"

    @pytest.mark.parametrize("fname", ["vite.config.ts", "vite.config.js"])
    def test_no_caching_handlers_as_code(self, fname: str) -> None:
        """以 `handler: 'X'` 精确匹配代码，避免误伤注释里的同名字样。"""
        text = _read(fname)
        for bad in ("StaleWhileRevalidate", "NetworkFirst"):
            assert f"handler: '{bad}'" not in text, f"{fname}: 仍存在 handler '{bad}'（缓存陈旧数据）"
            assert f'handler: "{bad}"' not in text, f"{fname}: 仍存在 handler \"{bad}\""

    def test_two_configs_equivalent_on_caching(self) -> None:
        """vite.config.js 是 .ts 门禁产物且 Vite 优先加载 .js；二者 API 条目必须一致。"""
        ts_text = _read("vite.config.ts")
        js_text = _read("vite.config.js")
        ts = _pairs(ts_text)
        js = _pairs(js_text)
        assert ts == js, f"两文件 runtimeCaching 不一致:\n ts={ts}\n js={js}"
        assert _api_handler(ts_text) == "NetworkOnly"
        assert _api_handler(js_text) == "NetworkOnly"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
