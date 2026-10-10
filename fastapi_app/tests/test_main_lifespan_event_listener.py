"""lifespan 必须启动跨进程领域事件监听器的回归测试。

背景（2026-10-10 评审 P0-2）：start_event_listener()（订阅 Redis
domain_events 频道，把跨 worker 事件分发给进程内订阅者）全仓无人调用
—— 8 worker 部署下，非发起 worker 收不到 STOCK_OUT_CREATED 等事件，
其 L1 缓存不失效、连在其上的 WebSocket 客户端收不到推送。

修法：main.py lifespan 把 start_event_listener() 挂进 background_tasks
（现有 shutdown 的 cancel+gather 自动覆盖关停）。
"""
import ast
from pathlib import Path

_MAIN = Path(__file__).resolve().parents[1] / "main.py"


def test_lifespan_starts_domain_event_listener():
    """main.py 必须以 create_task 启动 start_event_listener 并纳入 background_tasks。"""
    tree = ast.parse(_MAIN.read_text(encoding="utf-8"))

    # 收集 lifespan 内所有被 create_task 的协程名 + start_event_listener 的来源 import
    created: list[str] = []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "create_task":
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
                created.append(arg.func.id)
        if isinstance(node, ast.ImportFrom) and node.module and "domain_events" in node.module:
            imports.extend(a.name for a in node.names)

    assert "start_event_listener" in created, (
        "main.py lifespan 未启动 start_event_listener —— 跨 worker 领域事件"
        "（缓存失效/WebSocket 推送）在多 worker 下失效"
    )
    assert "start_event_listener" in imports
