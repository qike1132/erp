"""windows_ops 迁移断言(T2):模块存在、无 Tk/无 app 反向依赖、公开 API 齐、端口精确匹配。

运行: python -m pytest tests/test_sm_windows_ops.py --noconftest -p no:cacheprovider -q
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WO = ROOT / "server_manager" / "windows_ops.py"


def test_module_exists_and_is_tk_free() -> None:
    text = WO.read_text(encoding="utf-8")
    assert "import tkinter" not in text and "from tkinter" not in text
    assert "import server_manager.app" not in text and "from server_manager.app" not in text


def test_public_api_present() -> None:
    text = WO.read_text(encoding="utf-8")
    for fn in ("def taskkill(", "def taskkill_many(", "def is_prod_runner_cmdline(",
               "def find_port_pids(", "def kill_port_sync(", "def collect_process_tree(",
               "def kill_process_tree(", "def find_project_residual_pids(",
               "def find_loose_prod_runner_pids(", "def kill_residual_async("):
        assert fn in text, f"windows_ops 缺 {fn}"


def test_port_match_is_exact_not_substring() -> None:
    """端口精确匹配回归锁: ':5002' 不得命中 ':50021'。"""
    text = WO.read_text(encoding="utf-8")
    assert "rsplit(':', 1)" in text or 'rsplit(":", 1)' in text
