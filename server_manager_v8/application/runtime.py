"""运行时状态 — UseCase 共享的进程句柄登记表。

v6 的 GUI 持有 self._process / self._frontend_process / self._redis_process；
v8 的 UseCase 是短生命周期对象，进程句柄改由 RuntimeState 统一登记，
stop_all / switch_mode 据此清理。所有方法在编排线程调用（Application 层保证）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from server_manager_v8.domain import ProcessHandle

__all__ = ['RuntimeState']


@dataclass
class RuntimeState:
    """跨 UseCase 的进程句柄与模式上下文。"""

    handles: dict[str, ProcessHandle] = field(default_factory=dict)

    def register(self, key: str, handle: ProcessHandle) -> None:
        self.handles[key] = handle

    def get(self, key: str) -> ProcessHandle | None:
        return self.handles.get(key)

    def unregister(self, key: str) -> ProcessHandle | None:
        return self.handles.pop(key, None)

    def snapshot(self) -> dict[str, int]:
        """{服务键: PID} 快照，供 UI 展示与状态查询。"""
        return {key: h.pid for key, h in self.handles.items()}

    def clear(self) -> None:
        self.handles.clear()
