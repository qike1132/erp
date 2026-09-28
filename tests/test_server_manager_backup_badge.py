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


def test_backup_badge_updated_in_service_stopped_branch() -> None:
    """回归锁(2026-09-28 用户实测):服务全停时备份徽章必须一起更新。

    旧实现:未运行分支只更新后端/ARQ/前端/就绪/Redis,漏了备份 →
    徽章保留上一次的绿色「正常(8h)」,在 ARQ 已停(备份不会跑)时显示假健康。
    """
    start = TEXT.index("if not data['api_running']:")
    end = TEXT.index("read_err = data['read_err']")
    branch = TEXT[start:end]
    assert "hosting_backup_badge" in branch, "服务未运行分支漏更新备份徽章 → 旧值滞留成假信号"


def test_backup_badge_not_left_stale_on_collect_error() -> None:
    """采集失败提前 return 前也必须先把备份徽章置为未知,避免旧值滞留。"""
    start = TEXT.index("if data.get('collect_error'):")
    seg = TEXT[start:start + 600]
    assert "hosting_backup_badge" in seg, "采集失败分支未重置备份徽章"
