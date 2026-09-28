"""server_manager.py 对 erp-web 的接入点静态断言(无 GUI 测试基建,以文本锁定)。"""
from __future__ import annotations

import ast
import re
from pathlib import Path

# 2026-09-28 包化:实现已拆到 server_manager/ 包,本文件按"整包拼接"取文本。
# ★ 修正(T4):凡用 ``TEXT.index(锚点)`` 切片的断言,在实现搬家后会命中同名的
#   瘦转发体(app.py 按 sorted(glob) 排在前面),断言虽仍绿但锁的是空壳。故锚点
#   已迁出的断言改用 ``_func_src(模块, 函数名)`` 按 AST 定位目标模块内函数体。
PKG = Path(__file__).resolve().parent.parent / "server_manager"
TEXT = "\n".join(p.read_text(encoding="utf-8") for p in sorted(PKG.glob("*.py")))


def _func_src(rel_path: str, name: str) -> str:
    """按 AST 取指定模块内某函数/方法的源码段(含缩进),不依赖 TEXT.index 顺序。"""
    src = (PKG / rel_path).read_text(encoding="utf-8")
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"{rel_path} 内未找到 {name}")


def test_svc_web_constant() -> None:
    assert "_SVC_WEB = 'erp-web'" in TEXT


def test_stop_paths_cover_erp_web() -> None:
    """停止路径必须覆盖 erp-web。

    2026-09-28 A 止血后,停止/重启/受管PID排除三条路径统一按 `_SVC_ALL` 迭代
    (该常量含 erp-web 与两个 Redis 服务),故不再数三元组字面量,改为直接断言机制。
    T4 包化后这三条路径的实现已迁 service_ops,按 AST 锁目标模块函数体。
    """
    assert "_SVC_WEB = 'erp-web'" in TEXT
    m = re.search(r"^_SVC_ALL = \((.+)\)$", TEXT, re.M)
    assert m and "_SVC_WEB" in m.group(1)
    for fn in ("managed_service_pids", "stop_managed_services", "service_cmd_sync"):
        body = _func_src("service_ops.py", fn)
        assert "for name in _SVC_ALL" in body, f"{fn} 未按 _SVC_ALL 迭代"


def test_install_flow_has_erp_web() -> None:
    assert "_nssm_install(nssm, _SVC_WEB" in TEXT


def test_frontend_external_rendering() -> None:
    assert "svcs.get('frontend') or {}" in TEXT
    assert "fe.get('status') == 'external'" in TEXT


def test_no_leftover_two_tuple_in_flows() -> None:
    flows = re.findall(r"for name in \(([^)]+)\):", TEXT)
    two = [f for f in flows if "_SVC_API" in f and "_SVC_WEB" not in f]
    assert not two, f"残留二元组: {two}"
