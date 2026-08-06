"""备份格式策略的存储抽象与本地实现。"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Protocol

from fastapi_app.services.backup.format_types import BackupChunk

logger = logging.getLogger(__name__)


class BackupStorage(Protocol):
    """备份分片存储抽象。

    策略通过此端口写入/读取 chunk，不直接操作文件系统。
    """

    async def write_chunk(
        self,
        backup_id: str,
        index: int,
        data: bytes,
    ) -> BackupChunk:
        """写入一个 chunk 并返回其元数据。"""
        ...

    async def read_chunk(
        self,
        backup_id: str,
        index: int,
    ) -> bytes:
        """读取一个 chunk 的内容。"""
        ...

    async def has_chunk(
        self,
        backup_id: str,
        index: int,
    ) -> bool:
        """检查 chunk 是否存在。"""
        ...

    async def list_chunk_indices(
        self,
        backup_id: str,
    ) -> list[int]:
        """列出某个备份的所有 chunk 索引。"""
        ...

    async def remove_backup(self, backup_id: str) -> None:
        """删除某个备份的所有数据。"""
        ...

    async def get_full_path(
        self,
        backup_id: str,
    ) -> Path | None:
        """如果存储保留了完整备份文件，返回其路径；否则返回 None。"""
        ...


class LocalBackupStorage:
    """本地磁盘备份存储实现。

    每个备份拥有独立目录，chunk 按索引命名存储。
    """

    def __init__(self, base_dir: Path | str) -> None:
        self._base_dir = Path(base_dir)

    def _backup_dir(self, backup_id: str) -> Path:
        return self._base_dir / backup_id

    def _chunk_path(self, backup_id: str, index: int) -> Path:
        return self._backup_dir(backup_id) / f"chunk_{index:08d}.bin"

    async def write_chunk(
        self,
        backup_id: str,
        index: int,
        data: bytes,
    ) -> BackupChunk:
        backup_dir = self._backup_dir(backup_id)
        backup_dir.mkdir(parents=True, exist_ok=True)
        chunk_path = self._chunk_path(backup_id, index)
        chunk_path.write_bytes(data)
        return BackupChunk(
            index=index,
            total=0,  # 由策略在后续填充
            size=len(data),
            checksum=hashlib.sha256(data).hexdigest(),
            storage_ref={"path": str(chunk_path)},
        )

    async def read_chunk(self, backup_id: str, index: int) -> bytes:
        chunk_path = self._chunk_path(backup_id, index)
        return chunk_path.read_bytes()

    async def has_chunk(self, backup_id: str, index: int) -> bool:
        return self._chunk_path(backup_id, index).exists()

    async def list_chunk_indices(self, backup_id: str) -> list[int]:
        backup_dir = self._backup_dir(backup_id)
        if not backup_dir.exists():
            return []
        indices = []
        for path in backup_dir.glob("chunk_*.bin"):
            try:
                index = int(path.stem.split("_")[1])
                indices.append(index)
            except (IndexError, ValueError):
                logger.warning("忽略异常命名的 chunk 文件: %s", path)
        return sorted(indices)

    async def remove_backup(self, backup_id: str) -> None:
        backup_dir = self._backup_dir(backup_id)
        if backup_dir.exists():
            import shutil

            shutil.rmtree(backup_dir)

    async def get_full_path(self, backup_id: str) -> Path | None:
        """本地存储不保留完整文件，只保留 chunk。"""
        return None
