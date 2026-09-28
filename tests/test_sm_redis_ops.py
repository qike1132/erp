"""T3 包化回归锁：redis_ops 模块（探活/启停,自持 redis_process 状态）。

只读文本,不 import tkinter —— 保证 CI 可跑。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RO = ROOT / "server_manager" / "redis_ops.py"


def test_module_exists_and_is_tk_free() -> None:
    text = RO.read_text(encoding="utf-8")
    assert "tkinter" not in text
    assert "from server_manager.app" not in text


def test_class_and_state_owner() -> None:
    text = RO.read_text(encoding="utf-8")
    assert "class RedisOps" in text
    for m in ("def ping(", "def is_redis_running(", "def is_broker_running(",
              "def redis_service_state(", "def start_redis(", "def ensure_redis_broker(",
              "def stop_redis(", "def get_env_value("):
        assert m in text, f"RedisOps 缺 {m}"
    assert "self.redis_process" in text, "redis_process 应由 RedisOps 自持"


def test_resp_single_implementation() -> None:
    text = RO.read_text(encoding="utf-8")
    assert text.count("sock.sendall") == 3, "RESP 报文应只此一处(B2 回归锁)"
