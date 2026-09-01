"""备份操作 UseCase — 创建 / 恢复（依赖注入，P7 接入 fastapi_app.services.backup）。

D2 决策（默认）：P7 经后端 API 调用备份服务，避免把后端依赖打进管理器 EXE。
P4 阶段以注入的 callable 为契约，测试用 Fake 覆盖；恢复为 L3 极高危（键入操作名+原因）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from server_manager_v8.domain import OpResult

__all__ = ['BackupOpsUseCase', 'BackupSpec']

BackupFn = Callable[[dict], OpResult]


@dataclass(frozen=True)
class BackupSpec:
    """备份参数。"""

    target_dir: str = ''
    encrypt: bool = True
    comment: str = ''


class BackupOpsUseCase:
    """备份编排。backup_fn / restore_fn 由容器注入（P7 接后端或本地实现）。"""

    def __init__(
        self,
        backup_fn: BackupFn | None = None,
        restore_fn: BackupFn | None = None,
    ) -> None:
        self._backup_fn = backup_fn
        self._restore_fn = restore_fn

    def create(self, spec: BackupSpec, reason: str = '') -> OpResult:
        if self._backup_fn is None:
            return OpResult.failure('备份后端未配置（P7 阶段接入）')
        return self._backup_fn(spec.__dict__)

    def restore(self, backup_id: str, reason: str = '') -> OpResult:
        """恢复会覆盖现有数据（L3 极高危，reason 强校验由守卫完成）。"""
        if not backup_id:
            return OpResult.failure('backup_id 不能为空')
        if self._restore_fn is None:
            return OpResult.failure('恢复后端未配置（P7 阶段接入）')
        return self._restore_fn({'backup_id': backup_id, 'reason': reason})
