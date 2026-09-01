"""配置操作 UseCase — 读 / 写 / 版本迁移（L2 修改需确认影响面）。"""

from __future__ import annotations

from server_manager_v8.domain import OpResult, StoragePort

__all__ = ['CONFIG_SCHEMA_VERSION', 'ConfigOpsUseCase']


CONFIG_SCHEMA_VERSION = 2


class ConfigOpsUseCase:
    def __init__(self, storage: StoragePort, defaults: dict) -> None:
        self._storage = storage
        self._defaults = defaults

    def load(self) -> dict:
        return self._storage.load()

    def migrate(self) -> OpResult:
        data = self._storage.load()
        migrated, changed = self._storage.migrate(data)
        if not changed:
            return OpResult.success(detail=f'已是 schema v{CONFIG_SCHEMA_VERSION}')
        result = self._storage.save(migrated)
        if not result.ok:
            return result
        return OpResult.success(detail='配置已从 v1 迁移到 v2 并落盘')

    def save(self, patch: dict) -> OpResult:
        """局部更新：patch 深合并到当前配置后原子写。"""
        from server_manager_v8.domain.config_schema import deep_merge

        current = self._storage.load()
        merged = deep_merge(current, patch)
        return self._storage.save(merged)

    def validate_port(self, port: int) -> OpResult:
        if not isinstance(port, int) or not 1 <= port <= 65535:
            return OpResult.failure(f'端口号非法: {port!r}')
        return OpResult.success()
