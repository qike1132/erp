"""T4 包化回归锁:service_ops 模块(NSSM/sc 服务操作层)。

只读文本,不 import UI 工具包 —— 保证 CI 可跑。A/B 两组回归锁(停止范围、
环境变量逐元素写入、解码器唯一、轮询原语唯一)随实现迁移至此。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SO = ROOT / "server_manager" / "service_ops.py"


def test_module_exists_and_is_tk_free() -> None:
    text = SO.read_text(encoding="utf-8")
    assert "tkinter" not in text
    assert "from server_manager.app" not in text


def test_public_api_present() -> None:
    text = SO.read_text(encoding="utf-8")
    for m in ("def find_nssm(", "def run_capture(", "def decode_output(", "def svc_state(",
              "def wait_service(", "def stop_managed_services(", "def managed_service_pids(",
              "def service_cmd_sync(", "def nssm_install(", "def ensure_production_stopped("):
        assert m in text, f"ServiceOps 缺 {m}"


def test_stop_paths_use_svc_all() -> None:
    """A 的回归锁随之迁移:停止/重启/受管 PID 排除仍按 _SVC_ALL 迭代。"""
    text = SO.read_text(encoding="utf-8")
    assert text.count("for name in _SVC_ALL") >= 3


def test_env_written_elementwise() -> None:
    """A 的回归锁随之迁移:AppEnvironmentExtra 逐元素写入。"""
    text = SO.read_text(encoding="utf-8")
    assert "isinstance(val, list)" in text


def test_single_decoder_and_poll() -> None:
    """B 的回归锁随之迁移:解码器唯一、轮询原语唯一。"""
    text = SO.read_text(encoding="utf-8")
    assert text.count("gb18030") <= 1
    assert "def wait_service(" in text
    app = (ROOT / "server_manager" / "app.py").read_text(encoding="utf-8")
    assert "deadline = time.monotonic()" not in app or app.count("deadline = time.monotonic()") <= 1
