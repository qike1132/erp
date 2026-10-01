"""备份格式策略：对外极简接口，内部流式实现。

默认格式：ZIP + manifest.json + 可选 AES-256-GCM 加密 + 固定大小 chunk。
兼容旧的 `.zip`、`.zip.enc`（裸密文）以及带 meta 前缀的加密格式。
"""

from __future__ import annotations

import io
import json
import logging
import os
import struct
import tempfile
import zipfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fastapi_app.services.backup.format_storage import BackupStorage
from fastapi_app.services.backup.format_types import (
    ArchiveEntry,
    BackupArtifact,
    BackupChunk,
    BackupInfo,
    PackOptions,
    RestoredBackupArchive,
    UnpackOptions,
)

logger = logging.getLogger(__name__)

# 默认配置，后续应从项目配置读取
DEFAULT_CHUNK_SIZE = 64 * 1024 * 1024  # 64 MB
DEFAULT_MAX_CHUNKS = 100
DEFAULT_COMPRESSION_LEVEL = 6
BACKUP_FORMAT_VERSION = "1.0"

# 加密配置引用
BACKUP_ENCRYPTION_PASSWORD = os.environ.get("BACKUP_ENCRYPTION_PASSWORD")
BACKUP_ENCRYPTION_KEY = os.environ.get("BACKUP_ENCRYPTION_KEY")


class BackupFormatError(Exception):
    """备份格式处理错误。"""


class ZipBackupArchiveView:
    """基于 zipfile 的 RestoredBackupArchive 实现。"""

    def __init__(self, zip_bytes: bytes, manifest: dict[str, Any]) -> None:
        self._zip_bytes = zip_bytes
        self._zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        self._manifest = manifest

    @property
    def manifest(self) -> dict[str, Any]:
        return self._manifest

    @property
    def members(self) -> list[str]:
        return self._zf.namelist()

    def read(self, name: str) -> bytes:
        return self._zf.read(name)

    def open(self, name: str) -> zipfile.ZipExtFile:
        return cast(zipfile.ZipExtFile, self._zf.open(name))

    def extract(self, name: str, dest: Path) -> Path:
        return Path(self._zf.extract(name, dest))

    def close(self) -> None:
        self._zf.close()

    def __enter__(self) -> ZipBackupArchiveView:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


class BackupFormatStrategy:
    """备份格式策略接口。

    子类只需实现 pack / unpack / inspect 三个方法。
    """

    async def pack(
        self,
        backup_id: str,
        entries: Sequence[ArchiveEntry],
        manifest: dict[str, Any],
        storage: BackupStorage,
        options: PackOptions | None = None,
    ) -> BackupArtifact:
        """把条目和 manifest 打包为带分片的备份产物。"""
        raise NotImplementedError

    async def unpack(
        self,
        backup_id: str,
        storage: BackupStorage,
        options: UnpackOptions | None = None,
    ) -> RestoredBackupArchive:
        """从存储中还原备份归档视图。"""
        raise NotImplementedError

    async def inspect(
        self,
        backup_id: str,
        storage: BackupStorage,
        options: UnpackOptions | None = None,
    ) -> BackupInfo:
        """获取备份元信息，不解压全部内容。"""
        raise NotImplementedError


class DefaultBackupFormatStrategy(BackupFormatStrategy):
    """默认备份格式策略实现。

    内部使用临时文件实现 ZIP 构建和加密，再通过 chunk 写入 storage，
    避免把整个备份一直保留在内存中。
    """

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_chunks: int = DEFAULT_MAX_CHUNKS,
        compression_level: int = DEFAULT_COMPRESSION_LEVEL,
        temp_dir: Path | str | None = None,
    ) -> None:
        self._chunk_size = chunk_size
        self._max_chunks = max_chunks
        self._compression_level = compression_level
        self._temp_dir = Path(temp_dir) if temp_dir else None

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    async def pack(
        self,
        backup_id: str,
        entries: Sequence[ArchiveEntry],
        manifest: dict[str, Any],
        storage: BackupStorage,
        options: PackOptions | None = None,
    ) -> BackupArtifact:
        options = options or PackOptions()
        chunk_size = options.chunk_size or self._chunk_size
        max_chunks = options.max_chunks or self._max_chunks
        compression_level = options.compression_level or self._compression_level
        password = self._resolve_password(options)
        do_encrypt = options.encrypt and password is not None

        with tempfile.TemporaryDirectory(dir=self._temp_dir) as tmp_dir:
            tmp_path = Path(tmp_dir)
            zip_path = tmp_path / "backup.zip"

            # 1. 构建 ZIP
            self._build_zip(zip_path, entries, manifest, compression_level)

            # 2. 可选加密
            if do_encrypt and password is not None:
                encrypted_path = tmp_path / "backup.zip.enc"
                self._encrypt_file(zip_path, encrypted_path, password)
                source_path = encrypted_path
            else:
                source_path = zip_path

            # 3. 分片写入 storage
            total_size = source_path.stat().st_size
            chunks = await self._write_chunks(
                backup_id,
                source_path,
                storage,
                chunk_size,
                max_chunks,
            )

        final_manifest = dict(manifest)
        final_manifest.update(
            {
                "version": BACKUP_FORMAT_VERSION,
                "backup_id": backup_id,
                "created_at": datetime.now(UTC).isoformat(),
                "zip_size": total_size,
                "encrypted": do_encrypt,
                "format_version": BACKUP_FORMAT_VERSION,
                "chunks": [
                    {
                        "index": c.index,
                        "total": c.total,
                        "size": c.size,
                        "checksum": c.checksum,
                    }
                    for c in chunks
                ],
            }
        )

        return BackupArtifact(
            backup_id=backup_id,
            total_size=total_size,
            encrypted=do_encrypt,
            format_version=BACKUP_FORMAT_VERSION,
            manifest=final_manifest,
            chunks=chunks,
        )

    async def unpack(
        self,
        backup_id: str,
        storage: BackupStorage,
        options: UnpackOptions | None = None,
    ) -> RestoredBackupArchive:
        options = options or UnpackOptions()
        password = self._resolve_password_for_unpack(options)

        # 1. 读取并合并所有 chunk
        raw_bytes = await self._read_and_combine_chunks(backup_id, storage)
        if not raw_bytes:
            raise BackupFormatError(f"备份 {backup_id} 没有可用数据")

        # 2. 如果需要则解密
        zip_bytes, encrypted = self._decrypt_if_needed(raw_bytes, password)

        # 3. 打开 ZIP 并读取 manifest
        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        except zipfile.BadZipFile as exc:
            if encrypted and not password:
                raise BackupFormatError("备份已加密，需要提供解密密码") from exc
            raise BackupFormatError("无法打开备份文件，可能已损坏或密码错误") from exc

        if "manifest.json" not in zf.namelist():
            zf.close()
            raise BackupFormatError("备份文件缺少 manifest.json")

        manifest = json.loads(zf.read("manifest.json"))
        zf.close()
        return ZipBackupArchiveView(zip_bytes, manifest)

    async def inspect(
        self,
        backup_id: str,
        storage: BackupStorage,
        options: UnpackOptions | None = None,
    ) -> BackupInfo:
        options = options or UnpackOptions()
        password = self._resolve_password_for_unpack(options)

        # 1. 读取并合并所有 chunk
        raw_bytes = await self._read_and_combine_chunks(backup_id, storage)
        if not raw_bytes:
            raise BackupFormatError(f"备份 {backup_id} 没有可用数据")

        # 2. 解密
        zip_bytes, encrypted = self._decrypt_if_needed(raw_bytes, password)

        # 3. 仅读取 manifest
        manifest_dict = self._read_manifest_from_zip_bytes(zip_bytes, encrypted and not password)

        chunks = manifest_dict.get("chunks", [])
        total_size = manifest_dict.get("zip_size", len(zip_bytes))
        chunk_size = manifest_dict.get("chunk_size", DEFAULT_CHUNK_SIZE)
        if chunks:
            chunk_size = chunks[0].get("size", chunk_size)

        return BackupInfo(
            total_size=total_size,
            total_chunks=len(chunks),
            chunk_size=chunk_size,
            encrypted=encrypted,
            format_version=manifest_dict.get("format_version"),
            manifest=manifest_dict,
        )

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _build_zip(
        self,
        zip_path: Path,
        entries: Sequence[ArchiveEntry],
        manifest: dict[str, Any],
        compression_level: int,
    ) -> None:
        """将条目和 manifest 写入 ZIP 文件。"""
        with zipfile.ZipFile(
            zip_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=compression_level,
        ) as zf:
            for entry in entries:
                if isinstance(entry.source, Path):
                    zf.write(entry.source, entry.arcname)
                else:
                    zf.writestr(entry.arcname, entry.source)

            manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            zf.writestr("manifest.json", manifest_bytes)

    def _encrypt_file(
        self,
        source_path: Path,
        dest_path: Path,
        password: str | bytearray,
    ) -> None:
        """加密文件。"""
        # ITER-1 T3：新写密文统一走分块格式（chunked-v1）。
        # 注意此处仍 read_bytes 整包读入（内存优化见 ITER-1 阶段 B 的流式切换）。
        from fastapi_app.core.backup_encryption import encrypt_backup_auto

        data = source_path.read_bytes()
        encrypted_bytes, meta_dict = encrypt_backup_auto(data, password)

        # 写入带 meta 前缀的加密格式：4-byte meta length + JSON meta + ciphertext
        meta_bytes = json.dumps(meta_dict, ensure_ascii=False).encode("utf-8")
        with dest_path.open("wb") as f:
            f.write(struct.pack(">I", len(meta_bytes)))
            f.write(meta_bytes)
            f.write(encrypted_bytes)

    def _decrypt_if_needed(
        self,
        data: bytes,
        password: str | bytearray | None,
    ) -> tuple[bytes, bool]:
        """如果数据是加密格式则解密，否则原样返回。

        支持两种格式：
        1. 旧版裸密文：直接调用 decrypt_backup
        2. 新版带 meta 前缀：4-byte meta length + JSON meta + ciphertext
        """
        from fastapi_app.core.backup_encryption import decrypt_backup

        if not data:
            return data, False

        # 尝试检测新版 meta 前缀
        if len(data) >= 4:
            meta_len = struct.unpack(">I", data[:4])[0]
            if 0 < meta_len <= 4096 and len(data) >= 4 + meta_len:
                try:
                    meta_bytes = data[4 : 4 + meta_len]
                    json.loads(meta_bytes)
                    encrypted_bytes = data[4 + meta_len :]
                    if password is None:
                        raise BackupFormatError("备份已加密，需要提供解密密码")
                    return decrypt_backup(encrypted_bytes, password), True
                except (json.JSONDecodeError, ValueError):
                    pass  # defensive: 异常静默处理,不影响主流程

        # 尝试作为旧版裸密文解密
        try:
            if password is None:
                # 未提供密码时，尝试直接打开 ZIP；若失败再报错
                try:
                    with zipfile.ZipFile(io.BytesIO(data)):
                        return data, False
                except zipfile.BadZipFile:
                    raise BackupFormatError("备份已加密，需要提供解密密码") from None
            decrypted = decrypt_backup(data, password)
            return decrypted, True
        except Exception as exc:  # broad-except: 备份/恢复容错，防止局部异常导致整体流程中断
            if isinstance(exc, BackupFormatError):
                raise
            # 解密失败，尝试直接作为 ZIP 打开
            try:
                with zipfile.ZipFile(io.BytesIO(data)):
                    return data, False
            except zipfile.BadZipFile:
                raise BackupFormatError("无法解密或打开备份文件，可能密码错误或文件损坏") from exc

    def _read_manifest_from_zip_bytes(
        self,
        zip_bytes: bytes,
        encrypted_without_password: bool,
    ) -> dict[str, Any]:
        """从 ZIP 字节中读取 manifest.json。"""
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                if "manifest.json" not in zf.namelist():
                    raise BackupFormatError("备份文件缺少 manifest.json")
                return json.loads(zf.read("manifest.json"))
        except zipfile.BadZipFile as exc:
            if encrypted_without_password:
                raise BackupFormatError("备份已加密，需要提供解密密码") from exc
            raise BackupFormatError("无法打开备份文件，可能已损坏或密码错误") from exc

    async def _write_chunks(
        self,
        backup_id: str,
        source_path: Path,
        storage: BackupStorage,
        chunk_size: int,
        max_chunks: int,
    ) -> list[BackupChunk]:
        """将文件按固定大小分片写入 storage。"""
        total_size = source_path.stat().st_size
        num_chunks = (total_size + chunk_size - 1) // chunk_size
        if num_chunks > max_chunks:
            raise BackupFormatError(
                f"备份文件太大，需要 {num_chunks} 个 chunk，超过最大限制 {max_chunks}"
            )

        chunks: list[BackupChunk] = []
        with source_path.open("rb") as f:
            index = 0
            while True:
                data = f.read(chunk_size)
                if not data:
                    break
                chunk = await storage.write_chunk(backup_id, index, data)
                chunks.append(chunk)
                index += 1

        # 回填 total
        total = len(chunks)
        return [
            BackupChunk(
                index=c.index,
                total=total,
                size=c.size,
                checksum=c.checksum,
                storage_ref=c.storage_ref,
            )
            for c in chunks
        ]

    async def _read_and_combine_chunks(
        self,
        backup_id: str,
        storage: BackupStorage,
    ) -> bytes:
        """从 storage 读取所有 chunk 并合并。"""
        indices = await storage.list_chunk_indices(backup_id)
        if not indices:
            return b""

        # 校验连续性
        expected = 0
        for idx in indices:
            if idx != expected:
                raise BackupFormatError(f"Chunk 索引不连续，期望 {expected}，实际 {idx}")
            expected += 1

        parts: list[bytes] = []
        for idx in indices:
            data = await storage.read_chunk(backup_id, idx)
            # TODO: 通过 storage 端口增加 checksum 校验
            parts.append(data)

        return b"".join(parts)

    def _resolve_password(self, options: PackOptions) -> str | bytearray | None:
        """解析打包时的加密密码。

        fail-safe：绝不生成一次性随机密钥。随机密钥一旦生成即无人能找回，
        会产出「永久不可还原」的加密备份（P0-1 已在 crypto.py/core.py 移除该
        缺陷，此处同样收敛为：无密码即不加密，由调用方显式决策）。
        """
        if not options.encrypt:
            return None
        if options.password is not None:
            return options.password
        if BACKUP_ENCRYPTION_PASSWORD:
            return BACKUP_ENCRYPTION_PASSWORD
        if BACKUP_ENCRYPTION_KEY:
            return BACKUP_ENCRYPTION_KEY
        return None

    def _resolve_password_for_unpack(self, options: UnpackOptions) -> str | bytearray | None:
        """解析解包时的加密密码。"""
        if options.password is not None:
            return options.password
        if BACKUP_ENCRYPTION_PASSWORD:
            return BACKUP_ENCRYPTION_PASSWORD
        if BACKUP_ENCRYPTION_KEY:
            return BACKUP_ENCRYPTION_KEY
        return None
