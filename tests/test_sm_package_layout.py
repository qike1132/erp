"""包化布局的静态断言(只读文本/路径,不 import tkinter,保证 CI 可跑)。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "server_manager"


def test_package_files_exist() -> None:
    for name in ("__init__.py", "constants.py", "action_gate.py", "widgets.py", "app.py"):
        assert (PKG / name).is_file(), f"缺少 server_manager/{name}"


def test_root_entry_is_thin_shim() -> None:
    text = (ROOT / "server_manager.py").read_text(encoding="utf-8")
    assert "from server_manager.app import main" in text
    assert len(text.splitlines()) <= 20, "根入口必须保持薄壳(≤20 行)"


def test_constants_hold_service_set() -> None:
    text = (PKG / "constants.py").read_text(encoding="utf-8")
    for sym in ("_SVC_API", "_SVC_ARQ", "_SVC_WEB", "_SVC_REDIS_CACHE", "_SVC_REDIS_BROKER", "_SVC_ALL"):
        assert sym in text, f"constants.py 缺 {sym}"


def test_widgets_and_gate_moved_out_of_app() -> None:
    app_text = (PKG / "app.py").read_text(encoding="utf-8")
    for cls in ("class RoundedButton", "class StatusBadge", "class ActionGate", "class _ActionCancelled"):
        assert cls not in app_text, f"{cls} 应已迁出 app.py"
    assert "class RoundedButton" in (PKG / "widgets.py").read_text(encoding="utf-8")
    assert "class ActionGate" in (PKG / "action_gate.py").read_text(encoding="utf-8")


def test_project_dir_probe_is_package_aware() -> None:
    """非冻结分支必须仍指向仓库根,而不是 server_manager/ 包目录。"""
    app_text = (PKG / "app.py").read_text(encoding="utf-8")
    assert "parents[1]" in app_text or "parent.parent" in app_text, \
        "包化后 _get_project_dir 的 __file__ 上溯层数未适配"
