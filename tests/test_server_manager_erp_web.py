"""server_manager.py 对 erp-web 的接入点静态断言(无 GUI 测试基建,以文本锁定)。"""
from __future__ import annotations

import re
from pathlib import Path

# 2026-09-28 包化:实现已拆到 server_manager/ 包,本文件按"整包拼接"取文本,
# 这样 task 2-6 继续把代码拆去 service_ops/windows_ops/... 时无需再改本文件。
PKG = Path(__file__).resolve().parent.parent / "server_manager"
TEXT = "\n".join(p.read_text(encoding="utf-8") for p in sorted(PKG.glob("*.py")))


def test_svc_web_constant() -> None:
    assert "_SVC_WEB = 'erp-web'" in TEXT


def test_stop_paths_cover_erp_web() -> None:
    """停止路径必须覆盖 erp-web。

    2026-09-28 A 止血后,停止/重启/受管PID排除三条路径统一按 `_SVC_ALL` 迭代
    (该常量含 erp-web 与两个 Redis 服务),故不再数三元组字面量,改为直接断言机制。
    """
    assert "_SVC_WEB = 'erp-web'" in TEXT
    import re

    m = re.search(r"^_SVC_ALL = \((.+)\)$", TEXT, re.M)
    assert m and "_SVC_WEB" in m.group(1)
    for fn in ("_managed_service_pids", "_stop_managed_services", "_service_cmd_sync"):
        body = TEXT[TEXT.index(f"def {fn}") :][:1400]
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
