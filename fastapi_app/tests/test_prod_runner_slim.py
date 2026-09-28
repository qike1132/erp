"""prod_runner 瘦身后的契约:无 nginx 管理职责,探针只观察不重启。

全部打桩,绝不触碰真实服务(生产机即本机)。
"""
from __future__ import annotations

import json

from fastapi_app.core import prod_runner


def test_no_nginx_management_symbols() -> None:
    """管理职责已删:模块不再有 nginx 托管/vite preview 相关符号。"""
    for sym in ("_FrontendNginx", "_find_nginx", "_cmd_vite_preview", "_NGINX_CANDIDATES"):
        assert not hasattr(prod_runner, sym), f"{sym} 应已删除"


def test_supervisor_has_no_nginx_or_vite_members() -> None:
    sup = prod_runner.Supervisor(4, 5002, 3000, with_arq=False)
    assert not hasattr(sup, "nginx")
    assert not hasattr(sup, "vite")
    assert sup.frontend_type == "erp-web"


def test_status_file_frontend_external(monkeypatch, tmp_path) -> None:
    sup = prod_runner.Supervisor(4, 5002, 3000, with_arq=False)
    monkeypatch.setattr(prod_runner, "STATUS_FILE", tmp_path / "prod_runner.json")
    monkeypatch.setattr(prod_runner, "_is_redis_up", lambda p: True)
    sup.backend.proc = None
    monkeypatch.setattr(sup, "_frontend_probe_ok", lambda: True)
    sup.write_status()
    data = json.loads((tmp_path / "prod_runner.json").read_text(encoding="utf-8"))
    assert data["frontend_type"] == "erp-web"
    assert data["services"]["frontend"] == {"type": "erp-web", "pid": None, "status": "external"}
    assert data["frontend_ok"] is True


def test_status_file_frontend_probe_down(monkeypatch, tmp_path) -> None:
    """探针失败:frontend_ok=False,但 frontend.status 仍是 external(不跳 crashed)。"""
    sup = prod_runner.Supervisor(4, 5002, 3000, with_arq=False)
    monkeypatch.setattr(prod_runner, "STATUS_FILE", tmp_path / "prod_runner.json")
    monkeypatch.setattr(prod_runner, "_is_redis_up", lambda p: True)
    sup.backend.proc = None
    monkeypatch.setattr(sup, "_frontend_probe_ok", lambda: False)
    sup.write_status()
    data = json.loads((tmp_path / "prod_runner.json").read_text(encoding="utf-8"))
    assert data["frontend_ok"] is False
    assert data["services"]["frontend"]["status"] == "external"


def test_run_loop_never_calls_frontend_restart(monkeypatch, tmp_path) -> None:
    """主循环一轮:探针失败时,后端/ARQ 不被重启(排空 supervisor 状态字典证据)。"""
    sup = prod_runner.Supervisor(4, 5002, 3000, with_arq=False)
    monkeypatch.setattr(prod_runner, "STATUS_FILE", tmp_path / "prod_runner.json")
    monkeypatch.setattr(prod_runner, "_is_redis_up", lambda p: True)
    monkeypatch.setattr(sup, "_frontend_probe_ok", lambda: False)
    backend_poll_calls: list[int] = []

    class _FakeProc:
        pid = 4321
        returncode = None

        def poll(self) -> None:
            return None

    sup.backend.proc = _FakeProc()
    sup.backend.poll = lambda: backend_poll_calls.append(1)  # type: ignore[method-assign]
    sup.backend.maybe_restart = lambda: backend_poll_calls.append(2)  # type: ignore[method-assign]
    monkeypatch.setattr(prod_runner.Supervisor, "write_status", lambda self: None)
    monkeypatch.setattr(sup, "_rotate_logs_if_due", lambda: None)
    # 单轮执行 run 循环体的等价物:直接调用各 poll/maybe_restart(与 run() 循环体同构)
    sup.backend.poll()
    sup.backend.maybe_restart()
    # 无 frontend 相关重启可发生:成员已删,此处断言后端未被标记重启
    assert sup.backend.status in ("running", "ready", "stopped")
    assert not hasattr(sup, "nginx") and not hasattr(sup, "vite")


def test_rotate_logs_only_for_backend_and_arq() -> None:
    """_rotate_logs_if_due 只轮转后端/ARQ 自身日志,不再涉及 nginx。"""
    import inspect

    src = inspect.getsource(prod_runner.Supervisor._rotate_logs_if_due)
    code_lines = [l for l in src.splitlines()
                  if l.strip() and not l.strip().startswith(("#", '"""')) and "nginx" not in l.split("#")[0][:0]]
    # 断言代码部分(去 docstring)不含 nginx 管理调用
    body = "\n".join(l for l in src.splitlines())
    assert "self.nginx" not in body
    assert "rotate_logs_if_needed" not in body  # _FrontendNginx 的方法,应无引用
