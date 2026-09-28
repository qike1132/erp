"""server_manager.py 备份徽章接入的静态断言(无 GUI 测试基建,以文本锁定)。"""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "server_manager.py"
TEXT = SRC.read_text(encoding="utf-8")


def test_backup_badge_widget_exists() -> None:
    assert "hosting_backup_badge = StatusBadge(" in TEXT


def test_backup_badge_is_rendered() -> None:
    assert "_detail(self.hosting_backup_badge" in TEXT
    assert "data.get('backup')" in TEXT


def test_hosting_collects_backup_block() -> None:
    """采集阶段必须去取 /api/health 的 backup 块(渲染阶段不做 IO)。"""
    assert "data['backup'] = {}" in TEXT
    assert "payload.get('backup')" in TEXT


def test_local_probe_bypasses_proxy() -> None:
    """本机探针必须绕开系统代理——prod_runner 曾因代理转发 127.0.0.1 导致误判重启。"""
    assert "ProxyHandler({})" in TEXT
    assert "_HTTP_DIRECT.open(" in TEXT


def test_collect_does_not_fetch_with_plain_urlopen() -> None:
    """采集路径不得用裸 urlopen(会被系统代理截走);应走 _HTTP_DIRECT。"""
    seg = TEXT[TEXT.index("def _collect_hosting_data"):TEXT.index("def _apply_hosting_data")]
    assert "_HTTP_DIRECT.open(" in seg
    assert "urllib.request.urlopen(" not in seg
