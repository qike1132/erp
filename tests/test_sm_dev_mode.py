"""T5 包化回归锁：dev_mode 模块（开发模式双进程管理,自持进程/模式状态）。

只读文本,不 import UI 工具包 —— 保证 CI 可跑。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DM = ROOT / "server_manager" / "dev_mode.py"
APP = ROOT / "server_manager" / "app.py"


def test_module_exists_and_is_tk_free() -> None:
    text = DM.read_text(encoding="utf-8")
    assert "tkinter" not in text
    assert "from server_manager.app" not in text


def test_class_owns_state() -> None:
    text = DM.read_text(encoding="utf-8")
    assert "class DevModeOps" in text
    for attr in ("self.process", "self.frontend_process", "self.mode", "self.current_mode_key"):
        assert attr in text, f"DevModeOps 应自持 {attr}"


def test_single_terminate_primitive() -> None:
    """B4 回归锁随之迁移(T5):终止循环只应有一处(实现在 dev_mode)。"""
    text = DM.read_text(encoding="utf-8")
    assert "def terminate_dev_processes(" in text
    assert text.count("for proc, name in ((self._frontend_process") <= 0


def test_app_bridges_state() -> None:
    """app 侧必须以属性桥读写 dev_mode 的状态,否则 UI 崩溃检测会误判。"""
    text = APP.read_text(encoding="utf-8")
    for prop in ("def _mode(", "def _process(", "def _frontend_process("):
        assert prop in text, f"app.py 缺属性桥 {prop}"
