"""prod_runner 瘦身后的契约:无 nginx 管理职责,探针只观察不重启。

全部打桩,绝不触碰真实服务(生产机即本机)。
"""
from __future__ import annotations

import contextlib
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

    # 退出通道必须挂在循环**真正使用**的机制上：4791eac2（F4-7 让 Ctrl+C 能退出主循环）
    # 把 `time.sleep(3)` 换成 `self._stop.wait(3)`，桩 time.sleep 就此失效 —— 循环
    # 再也收不到 _StopLoopError，`while not self._stop.is_set()` 永远为真，
    # 本用例会无限跑下去（PR #2 的 CI test job 因此挂了 2 小时以上，
    # 而正常全量只需 ~9 分钟）。`_stop.wait` 在 try/except 之外，异常仍能逃出去。
    def _fake_wait(_s: float) -> bool:
        state["n"] += 1
        if state["n"] >= 3:
            raise _StopLoopError
        return False

    monkeypatch.setattr(sup._stop, "wait", _fake_wait)
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


def test_supervisor_rotate_logs_due_uses_shared_policy(monkeypatch, tmp_path) -> None:
    """行为级：_rotate_logs_if_due 读共享策略（config/log_policy.json）并轮转超限日志。

    这里把策略文件路径指向临时配置，等价于验证「阈值来自共享策略而非本模块常量」。
    """
    from utils.log_rotation import LogPolicy

    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(prod_runner, "LOGS_DIR", logs)
    # 直接桩接策略读取：策略文件以 MB 为粒度持久化，而这里要用 1KB 阈值才便宜。
    monkeypatch.setattr(prod_runner, "load_log_policy",
                        lambda path=None: LogPolicy(rotate_bytes=1024))
    big = logs / "后端(uvicorn).out.log"  # _Managed 的 name 即 Supervisor 里的中文名
    big.write_bytes(b"y" * 2048)
    sup = prod_runner.Supervisor(4, 5002, 3000, with_arq=False)
    monkeypatch.setattr(sup, "_last_log_check", 0.0)
    sup._rotate_logs_if_due()
    assert big.read_bytes() == b""
    assert (logs / "后端(uvicorn).out.log.1").exists()
