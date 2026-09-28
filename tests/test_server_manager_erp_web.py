"""server_manager.py 对 erp-web 的接入点静态断言(无 GUI 测试基建,以文本锁定)。"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "server_manager.py"
TEXT = SRC.read_text(encoding="utf-8")


def test_svc_web_constant() -> None:
    assert "_SVC_WEB = 'erp-web'" in TEXT


def test_five_tuples_extended() -> None:
    # 关键迭代/安装/停止/卸载/日志回灌点都出现三元组
    assert TEXT.count("(_SVC_API, _SVC_ARQ, _SVC_WEB)") >= 5, TEXT.count("(_SVC_API, _SVC_ARQ, _SVC_WEB)")


def test_install_flow_has_erp_web() -> None:
    assert "_nssm_install(nssm, _SVC_WEB" in TEXT


def test_frontend_external_rendering() -> None:
    assert "svcs.get('frontend') or {}" in TEXT
    assert "fe.get('status') == 'external'" in TEXT


def test_no_leftover_two_tuple_in_flows() -> None:
    flows = re.findall(r"for name in \(([^)]+)\):", TEXT)
    two = [f for f in flows if "_SVC_API" in f and "_SVC_WEB" not in f]
    assert not two, f"残留二元组: {two}"
