"""端口清理 UseCase（L2 高危：二次确认列影响面）。"""

from __future__ import annotations

from server_manager_v8.domain import OpResult, ProcessPort

__all__ = ['KillPortUseCase']


class KillPortUseCase:
    def __init__(self, process: ProcessPort) -> None:
        self._process = process

    def run(self, port: int) -> OpResult:
        if not 1 <= port <= 65535:
            return OpResult.failure(f'端口号非法: {port}')
        result = self._process.kill_port(port, rounds=3)
        if result.partial:
            return OpResult.failure(
                f'端口 {port} 仍有残留进程: {result.survivors}',
                detail='请手动检查或稍后重试',
            )
        if not result.killed_pids:
            return OpResult.success(detail=f'端口 {port} 无占用')
        return OpResult.success(
            detail=f'端口 {port} 已清理 {len(result.killed_pids)} 个进程',
        )
