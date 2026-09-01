"""配置存储适配器 — 实现 domain.ports.StoragePort。

迁移来源（server_manager.py v6）：
    - ``_load_app_config`` / ``_save_app_config`` → load / save
升级：
    - 损坏文件备份为 ``*.corrupt-<ts>``（不再静默丢弃，v6 是裸 except-pass）
    - 原子写（先写临时文件再 os.replace，防写入中断损坏配置）
    - schema 版本迁移（v1 扁平 → v2 分组嵌套，见 v8 方案 §3.6）
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from server_manager_v8.domain import OpResult
from server_manager_v8.domain.config_schema import SCHEMA_VERSION, deep_merge, migrate_v1_to_v2

__all__ = ['SCHEMA_VERSION', 'JsonConfigStorage', 'deep_merge', 'migrate_v1_to_v2']


class JsonConfigStorage:
    """JSON 配置文件读写（原子写 + 损坏备份 + 版本迁移）。"""

    def __init__(self, path: str | Path, defaults: dict) -> None:
        self.path = Path(path)
        self.defaults = defaults
        self.last_error = ''  # 最近一次加载告警（损坏备份等），供 UI 展示

    def load(self) -> dict:
        if not self.path.is_file():
            return dict(self.defaults)
        try:
            stored = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            self._backup_corrupt(reason=f'{type(exc).__name__}: {exc}')
            return dict(self.defaults)
        if not isinstance(stored, dict):
            self._backup_corrupt(reason='顶层不是 JSON 对象')
            return dict(self.defaults)
        migrated, changed = self.migrate(stored)
        if changed:
            self.save(migrated)  # 迁移后立即落盘
        return deep_merge(self.defaults, migrated)

    def save(self, data: dict) -> OpResult:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + '.tmp')
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            os.replace(tmp, self.path)  # 原子替换
        except OSError as exc:
            return OpResult.failure(f'配置写入失败: {exc}', detail=str(exc))
        return OpResult.success(detail=str(self.path))

    def migrate(self, data: dict) -> tuple[dict, bool]:
        """版本迁移（v1 → v2）。"""
        return migrate_v1_to_v2(data)

    # ---- 内部 ----

    def _backup_corrupt(self, reason: str) -> None:
        """损坏文件不静默丢弃：备份为 .corrupt-<ts> 并回报。"""
        ts = time.strftime('%Y%m%d_%H%M%S')
        backup = self.path.with_suffix(self.path.suffix + f'.corrupt-{ts}')
        try:
            os.replace(self.path, backup)
        except OSError:
            backup = None
        # 备份结果通过 last_error 回报（load 返回 dict 无法携带）
        self.last_error = f'配置文件损坏（{reason}），已备份到 {backup or "（备份失败）"}'
