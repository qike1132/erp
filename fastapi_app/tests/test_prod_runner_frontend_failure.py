"""生产栈「假成功」缺陷链修复的回归测试（D1 / D2 / D3）。

背景（2026-09-17 字节级取证）：
    本应由 NSSM 服务 erp-prod 拉起 prod_runner 托管 uvicorn(5002, 多 worker)
    + ARQ + nginx(3000 服务 frontend-vite/dist)，实际退化成 Vite dev server(:3000)
    + 单 worker dev 后端(:5002)，nginx 进程数为 0，但 logs/prod_runner.json 仍宣称
    frontend.status="running" —— 系统无法发现自己坏了。

本文件锁定三处根因修复：
  - D1 `_http_ok` 增加响应体校验：:3000 由 Vite SPA fallback 对任意路径返回
    `200 + index.html` 时，前端探针必须判否；
  - D2 `_ensure_started` 探测全败必须如实置 crashed + 退避，不得无条件置 running；
  - D3 `write_status` 不得谎报 frontend 的 status/pid。

全部经打桩，绝不真的启动 / 停止任何 nginx 或后台服务。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from fastapi_app.core import prod_runner


# ---------------------------------------------------------------------------
# 打桩工具
# ---------------------------------------------------------------------------
class _FakeResp:
    """模拟 urllib 响应对象（支持 with 与 read(n)）。"""

    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            return self._body
        return self._body[:n]

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *exc) -> bool:
        return False


class _FakeOpener:
    """替换 prod_runner._OPENER_DIRECT，按预设响应返回。"""

    def __init__(self, resp: _FakeResp):
        self._resp = resp

    def open(self, url: str, timeout: float | None = None):  # noqa: ARG002
        return self._resp


class _FakeTime:
    """替换 prod_runner.time，消除 5s 真实等待并固定 monotonic。"""

    FIXED = 1000.0

    def sleep(self, *_args) -> None:
        return None

    def monotonic(self) -> float:
        return self.FIXED


class _AliveProc:
    """模拟存活子进程（poll() 返回 None）。"""

    def __init__(self, pid: int = 4321):
        self.pid = pid

    def poll(self) -> int | None:
        return None


# 真实的 nginx /nginx-health 响应体（参照 config/nginx-windows.conf:148-153）
_NGINX_HEALTH_BODY = b'{"status":"ok","service":"nginx"}'
# Vite dev server 的 SPA fallback：对任意路径 200 + index.html
_SPA_FALLBACK_BODY = (
    b'<!doctype html><html><head><title>ERP</title></head>'
    b'<body><div id="app"></div>'
    b'<script type="module" src="/src/main.ts"></script></body></html>'
)


# ---------------------------------------------------------------------------
# D1：_http_ok 响应体校验
# ---------------------------------------------------------------------------
class TestHttpOkExpectSubstr:
    def test_without_expect_substr_backward_compatible(self, monkeypatch):
        """不传 expect_substr 时行为与修复前一致：只看状态码（后端/ARQ 探针依赖）。"""
        monkeypatch.setattr(
            prod_runner, "_OPENER_DIRECT",
            _FakeOpener(_FakeResp(200, _SPA_FALLBACK_BODY)),
        )
        assert prod_runner._http_ok("http://127.0.0.1:5002/api/health") is True

    def test_expect_substr_rejects_spa_fallback(self, monkeypatch):
        """nginx 缺席、:3000 由 Vite SPA fallback 返回 200+HTML → 必须判否。"""
        monkeypatch.setattr(
            prod_runner, "_OPENER_DIRECT",
            _FakeOpener(_FakeResp(200, _SPA_FALLBACK_BODY)),
        )
        assert prod_runner._http_ok(
            "http://127.0.0.1:3000/nginx-health",
            expect_substr='"service":"nginx"',
        ) is False

    def test_expect_substr_accepts_real_nginx_health(self, monkeypatch):
        monkeypatch.setattr(
            prod_runner, "_OPENER_DIRECT",
            _FakeOpener(_FakeResp(200, _NGINX_HEALTH_BODY)),
        )
        assert prod_runner._http_ok(
            "http://127.0.0.1:3000/nginx-health",
            expect_substr='"service":"nginx"',
        ) is True

    def test_non_200_rejected(self, monkeypatch):
        monkeypatch.setattr(
            prod_runner, "_OPENER_DIRECT",
            _FakeOpener(_FakeResp(503, _NGINX_HEALTH_BODY)),
        )
        assert prod_runner._http_ok(
            "http://127.0.0.1:3000/nginx-health",
            expect_substr='"service":"nginx"',
        ) is False


# ---------------------------------------------------------------------------
# D1：_FrontendNginx.alive() 走带子串校验的探针
# ---------------------------------------------------------------------------
class TestFrontendNginxAlive:
    def test_alive_false_on_spa_fallback_200(self, monkeypatch):
        """核心场景：:3000 上不是 nginx 而是 Vite dev server → alive() 必须 False。"""
        monkeypatch.setattr(
            prod_runner, "_OPENER_DIRECT",
            _FakeOpener(_FakeResp(200, _SPA_FALLBACK_BODY)),
        )
        fe = prod_runner._FrontendNginx(Path("nginx.exe"), 3000)
        assert fe.alive() is False

    def test_alive_true_on_real_nginx_health(self, monkeypatch):
        monkeypatch.setattr(
            prod_runner, "_OPENER_DIRECT",
            _FakeOpener(_FakeResp(200, _NGINX_HEALTH_BODY)),
        )
        fe = prod_runner._FrontendNginx(Path("nginx.exe"), 3000)
        assert fe.alive() is True


# ---------------------------------------------------------------------------
# D2：_ensure_started 探测全败不得假成功
# ---------------------------------------------------------------------------
def _prep_frontend(monkeypatch, tmp_path, http_ok: bool) -> prod_runner._FrontendNginx:
    """构造一个不接触真实 nginx/taskkill 的 _FrontendNginx。"""
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    monkeypatch.setattr(prod_runner, "LOGS_DIR", logs)
    monkeypatch.setattr(prod_runner, "time", _FakeTime())
    monkeypatch.setattr(prod_runner, "_http_ok", lambda *a, **k: http_ok)
    monkeypatch.setattr(prod_runner.subprocess, "Popen", lambda *a, **k: _AliveProc())
    fe = prod_runner._FrontendNginx(Path("nginx.exe"), 3000)
    monkeypatch.setattr(fe, "_kill_all", lambda: None)  # 禁止真实 taskkill / nginx -s stop
    return fe


class TestEnsureStarted:
    def test_marks_crashed_when_nginx_absent(self, monkeypatch, tmp_path):
        """修复前：探测全败仍无条件置 running（假成功）。修复后必须 crashed + 退避。"""
        fe = _prep_frontend(monkeypatch, tmp_path, http_ok=False)
        try:
            fe._ensure_started()
        finally:
            fe._close_spawn_log()  # 释放 spawn 日志句柄，避免句柄泄漏 / ResourceWarning
        assert fe.status == "crashed"
        assert fe.next_start > 0
        assert fe.delay == 10.0  # 5.0 → min(5.0 * 2, 30.0)

    def test_marks_running_on_success(self, monkeypatch, tmp_path):
        fe = _prep_frontend(monkeypatch, tmp_path, http_ok=True)
        try:
            fe._ensure_started()
        finally:
            fe._close_spawn_log()
        assert fe.status == "running"
        assert fe.delay == 5.0

    def test_failure_dumps_error_log_tail(self, monkeypatch, tmp_path, capsys):
        """失败分支必须打印 nginx-error.log 尾部——缺陷链里唯一能自我说明的通道。"""
        fe = _prep_frontend(monkeypatch, tmp_path, http_ok=False)
        err_log = prod_runner.LOGS_DIR / "nginx-error.log"
        err_log.write_text(
            'nginx: [emerg] bind() to 0.0.0.0:3000 failed (10013: 权限)\n',
            encoding="utf-8",
        )
        try:
            fe._ensure_started()
        finally:
            fe._close_spawn_log()
        out = capsys.readouterr().out
        assert "nginx-error.log 尾部" in out
        assert "bind() to 0.0.0.0:3000 failed" in out

    def test_failure_without_error_log_is_safe(self, monkeypatch, tmp_path, capsys):
        """nginx-error.log 不存在时读日志必须异常安全，不得抛出。"""
        fe = _prep_frontend(monkeypatch, tmp_path, http_ok=False)
        try:
            fe._ensure_started()
        finally:
            fe._close_spawn_log()
        out = capsys.readouterr().out
        assert "nginx-error.log" in out  # 打印「无 nginx-error.log」提示
        assert fe.status == "crashed"


# ---------------------------------------------------------------------------
# D3：write_status 可观测性
# ---------------------------------------------------------------------------
def _build_supervisor(monkeypatch, tmp_path, http_ok: bool) -> prod_runner.Supervisor:
    monkeypatch.setattr(prod_runner, "_find_nginx", lambda: Path("nginx.exe"))
    monkeypatch.setattr(prod_runner, "_is_redis_up", lambda *_: False)
    monkeypatch.setattr(prod_runner, "_http_ok", lambda *a, **k: http_ok)
    monkeypatch.setattr(prod_runner, "STATUS_FILE", tmp_path / "prod_runner.json")
    return prod_runner.Supervisor(workers=4, api_port=5002, web_port=3000, with_arq=False)


class TestWriteStatusFrontendObservability:
    def test_no_false_running_when_nginx_down(self, monkeypatch, tmp_path):
        """nginx 未运行时不谎报 status="running"、pid 非空。"""
        sup = _build_supervisor(monkeypatch, tmp_path, http_ok=False)
        sup.nginx.status = "running"  # 注入被污染的陈旧状态，验证落盘不被其蒙蔽
        sup.write_status()

        data = json.loads(prod_runner.STATUS_FILE.read_text(encoding="utf-8"))
        fe = data["services"]["frontend"]
        assert fe["type"] == "nginx"
        assert fe["status"] != "running"
        assert fe["pid"] is None
        assert data["frontend_ok"] is False
        # ready 字段语义保持不变（仅由后端决定）
        assert data["ready"] is False

    def test_reports_frontend_ok_when_nginx_alive(self, monkeypatch, tmp_path):
        sup = _build_supervisor(monkeypatch, tmp_path, http_ok=True)
        sup.nginx.proc = _AliveProc(pid=7777)
        sup.write_status()

        data = json.loads(prod_runner.STATUS_FILE.read_text(encoding="utf-8"))
        fe = data["services"]["frontend"]
        assert fe["status"] == "running"
        assert fe["pid"] == 7777
        assert data["frontend_ok"] is True

    def test_frontend_ok_field_present_even_without_frontend(self, monkeypatch, tmp_path):
        """vite 回退分支同样需暴露 frontend_ok（字段始终存在）。"""
        monkeypatch.setattr(prod_runner, "_find_nginx", lambda: None)
        monkeypatch.setattr(prod_runner, "_is_redis_up", lambda *_: False)
        monkeypatch.setattr(prod_runner, "_http_ok", lambda *a, **k: False)
        monkeypatch.setattr(prod_runner, "STATUS_FILE", tmp_path / "prod_runner.json")
        sup = prod_runner.Supervisor(workers=4, api_port=5002, web_port=3000, with_arq=False)
        sup.write_status()
        data = json.loads(prod_runner.STATUS_FILE.read_text(encoding="utf-8"))
        assert data["frontend_type"] == "vite"
        assert data["frontend_ok"] is False


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
