"""备份格式策略中的值对象与选项。"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ArchiveEntry:
    """待打包到备份归档中的单个条目。"""

    arcname: str
    source: Path | bytes


@dataclass(frozen=True)
class PackOptions:
    """打包选项。"""

    encrypt: bool = True
    password: str | bytearray | None = None
    chunk_size: int | None = None
    max_chunks: int | None = None
    compression_level: int | None = None


@dataclass(frozen=True)
class UnpackOptions:
    """解包选项。"""

    password: str | bytearray | None = None


@dataclass(frozen=True)
class BackupChunk:
    """备份分片信息。"""

    index: int
    total: int
    size: int
    checksum: str
    storage_ref: Any | None = None


@dataclass(frozen=True)
class BackupArtifact:
    """打包后的备份产物。"""

    backup_id: str
    total_size: int
    encrypted: bool
    format_version: str
    manifest: dict[str, Any]
    chunks: list[BackupChunk] = field(default_factory=list)


@dataclass(frozen=True)
class BackupInfo:
    """备份元信息（不展开完整内容）。"""

    total_size: int
    total_chunks: int
    chunk_size: int
    encrypted: bool
    format_version: str | None
    manifest: dict[str, Any] | None


@runtime_checkable
class RestoredBackupArchive(Protocol):
    """已解包的备份归档视图。

    不暴露具体 zipfile 实现，只提供最小读取接口。
    """

    @property
    def manifest(self) -> dict[str, Any]: ...

    @property
    def members(self) -> list[str]: ...

    def read(self, name: str) -> bytes: ...

    def open(self, name: str) -> zipfile.ZipExtFile: ...

    def extract(self, name: str, dest: Path) -> Path: ...

    def close(self) -> None: ...

    def __enter__(self) -> RestoredBackupArchive: ...

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None: ...
