"""prod_runner 瘦身后的契约:无 nginx 管理职责,探针只观察不重启。

全部打桩,绝不触碰真实服务(生产机即本机)。
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path

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
    """真跑 run() 主循环两轮:探针失败时循环继续、状态落盘、后端不被杀/不被重启。"""
    sup = prod_runner.Supervisor(4, 5002, 3000, with_arq=False)
    monkeypatch.setattr(prod_runner, "STATUS_FILE", tmp_path / "prod_runner.json")
    monkeypatch.setattr(prod_runner, "_is_redis_up", lambda p: True)
    monkeypatch.setattr(sup, "_frontend_probe_ok", lambda: False)

    class _FakeProc:
        pid = 4321
        returncode = None

        def poll(self) -> None:
            return None

    sup.backend.proc = _FakeProc()
    sup.backend.start = None  # type: ignore[assignment]  # 若被调用 → TypeError 即测试失败
    sup.backend.kill_tree = None  # type: ignore[method-assign]  # 同上
    monkeypatch.setattr(sup, "_rotate_logs_if_due", lambda: None)

    # run() 先 start_all 会真拉进程——桩掉 backend.start,只验证循环体
    monkeypatch.setattr(sup, "start_all", lambda: None)
    # sleep 计数器:第 3 次抛异常跳出 while True(真跑两轮)
    state = {"n": 0}

    class _StopLoopError(Exception):
        pass

    def _fake_sleep(_s: float) -> None:
        state["n"] += 1
        if state["n"] >= 3:
            raise _StopLoopError

    monkeypatch.setattr(prod_runner.time, "sleep", _fake_sleep)
    with contextlib.suppress(_StopLoopError):
        sup.run()
    # 循环真跑了 ≥2 轮(write_status 每轮调用,STATUS_FILE 已落盘)
    assert state["n"] >= 3
    data = json.loads((tmp_path / "prod_runner.json").read_text(encoding="utf-8"))
    assert data["frontend_ok"] is False
    assert data["services"]["frontend"]["status"] == "external"
    # 后端 FakeProc 存活:poll() 恒 None → 未被标记崩溃,更未被 kill/start
    assert sup.backend.proc is not None and sup.backend.proc.poll() is None


def test_rotate_logs_only_for_backend_and_arq() -> None:
    """_rotate_logs_if_due 只轮转后端/ARQ 自身日志,不再涉及 nginx。"""
    import inspect

    src = inspect.getsource(prod_runner.Supervisor._rotate_logs_if_due)
    assert "self.nginx" not in src
    assert "rotate_logs_if_needed" not in src  # _FrontendNginx 的方法,应无引用


def test_managed_rotate_log_actually_rotates(monkeypatch, tmp_path) -> None:
    """行为级:_Managed.rotate_log_if_needed 直调不抛且超阈值文件被轮转。

    回归锁(最终评审 C1):旧版调用点写的是已删除的 _rotate_file_copytruncate,
    而 slim 测试此前只有文本断言——该 NameError 每次轮转检查都炸且被主循环吞掉。
    """
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(prod_runner, "LOGS_DIR", logs)
    big = logs / "backend.out.log"
    big.write_bytes(b"x" * 2048)
    m = prod_runner._Managed("backend", ["cmd"], Path("."))
    m.rotate_log_if_needed(1024)
    assert big.read_bytes() == b""
    assert (logs / "backend.out.log.1").exists()


def test_supervisor_rotate_logs_due_rotates_backend_log(monkeypatch, tmp_path) -> None:
    """行为级:Supervisor._rotate_logs_if_due 直调,backend.out.log 超阈值被轮转。"""
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(prod_runner, "LOGS_DIR", logs)
    monkeypatch.setattr(prod_runner, "_log_rotate_bytes", lambda: 1024)  # 隔离真实 .env 的 50MB
    big = logs / "后端(uvicorn).out.log"  # _Managed 的 name 即 Supervisor 里的中文名
    big.write_bytes(b"y" * 2048)
    sup = prod_runner.Supervisor(4, 5002, 3000, with_arq=False)
    monkeypatch.setattr(sup, "_last_log_check", 0.0)
    sup._rotate_logs_if_due()
    assert big.read_bytes() == b""
    assert (logs / "后端(uvicorn).out.log.1").exists()
