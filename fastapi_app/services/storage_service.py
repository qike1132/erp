"""
对象存储服务抽象层

P2-1：将 static/uploads 迁移至 MinIO/S3 对象存储，数据库仅存元数据。
支持两种后端：
  - local：保持现有本地文件系统行为，文件保存在 static/uploads/
  - s3：上传到兼容 S3 的对象存储（MinIO / AWS S3 / 阿里云 OSS 等）
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi_app.core.config import settings
from fastapi_app.core.logger import get_logger
from fastapi_app.core.circuit_breaker import circuit, CircuitBreakerOpenError, get_breaker

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOCAL_UPLOAD_DIR = PROJECT_ROOT / "static" / "uploads"


class StorageBackend(ABC):
    """存储后端抽象"""

    @abstractmethod
    async def upload(self, key: str, content: bytes, content_type: str | None = None) -> str:
        """上传文件并返回可访问 URL 或 key"""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """删除文件"""

    @abstractmethod
    def get_url(self, key: str) -> str:
        """获取文件公开访问 URL"""


class LocalStorageBackend(StorageBackend):
    """本地文件系统存储（向后兼容）"""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or LOCAL_UPLOAD_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def upload(self, key: str, content: bytes, content_type: str | None = None) -> str:
        target = self.base_dir / key
        target.parent.mkdir(parents=True, exist_ok=True)

        def _write() -> None:
            target.write_bytes(content)

        await asyncio.to_thread(_write)
        return f"/static/uploads/{key}"

    async def delete(self, key: str) -> None:
        target = self.base_dir / key
        if target.exists():
            await asyncio.to_thread(target.unlink)

    def get_url(self, key: str) -> str:
        return f"/static/uploads/{key}"


class S3StorageBackend(StorageBackend):
    """S3 / MinIO 对象存储"""

    def __init__(self):
        import boto3
        from botocore.config import Config

        endpoint = settings.S3_ENDPOINT
        self.bucket = settings.S3_BUCKET
        self.public_url = settings.S3_PUBLIC_URL.rstrip("/") if settings.S3_PUBLIC_URL else ""

        client_kwargs: dict[str, Any] = {
            "service_name": "s3",
            "region_name": settings.S3_REGION,
            "aws_access_key_id": settings.S3_ACCESS_KEY,
            "aws_secret_access_key": settings.S3_SECRET_KEY,
            "config": Config(
                s3={"addressing_style": "path" if endpoint else "auto"},
                retries={"max_attempts": 3, "mode": "adaptive"},
            ),
        }
        if endpoint:
            client_kwargs["endpoint_url"] = endpoint

        self._client = boto3.client(**client_kwargs)
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except Exception:
            try:
                self._client.create_bucket(Bucket=self.bucket)
                logger.info("S3 bucket 已自动创建: %s", self.bucket)
            except Exception as e:
                logger.warning("S3 bucket 创建失败（可能已存在或无权限）: %s", e)

    async def upload(self, key: str, content: bytes, content_type: str | None = None) -> str:
        """上传文件到 S3，通过熔断器保护

        使用 breaker.call() 接入熔断器，避免装饰器在实例方法上的副作用。
        """
        breaker = get_breaker("s3_upload")
        extra_args: dict[str, Any] = {}
        if content_type:
            extra_args["ContentType"] = content_type

        async def _do_upload() -> str:
            def _put() -> None:
                self._client.put_object(Bucket=self.bucket, Key=key, Body=content, **extra_args)
            await asyncio.to_thread(_put)
            return self.get_url(key)

        return await breaker.call(_do_upload)

    async def delete(self, key: str) -> None:
        def _delete() -> None:
            self._client.delete_object(Bucket=self.bucket, Key=key)

        await asyncio.to_thread(_delete)

    def get_url(self, key: str) -> str:
        if self.public_url:
            return f"{self.public_url}/{key}"
        endpoint = settings.S3_ENDPOINT.rstrip("/")
        return f"{endpoint}/{self.bucket}/{key}"


_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """获取当前配置的存储后端（单例）"""
    global _backend
    if _backend is None:
        storage_type = settings.STORAGE_TYPE.lower()
        if storage_type == "s3":
            _backend = S3StorageBackend()
        else:
            _backend = LocalStorageBackend()
        logger.info("存储后端初始化: %s", storage_type)
    return _backend


def _generate_key(filename: str, prefix: str = "") -> str:
    """生成唯一存储 key"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    date_prefix = datetime.now(timezone.utc).strftime("%Y%m%d")
    key = f"{prefix}{date_prefix}/{uuid.uuid4().hex}.{ext}" if prefix else f"{date_prefix}/{uuid.uuid4().hex}.{ext}"
    return key


def _guess_content_type(filename: str) -> str:
    ctype, _ = mimetypes.guess_type(filename)
    return ctype or "application/octet-stream"


async def save_upload(
    content: bytes,
    original_filename: str,
    db,
    uploader_id: int | None = None,
    prefix: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """保存上传文件到对象存储并写入元数据

    返回 {"id": ..., "url": ..., "storage_key": ..., "size": ...}
    """
    from fastapi_app.shared_models.file_record import FileRecord

    storage = get_storage()
    key = _generate_key(original_filename, prefix=prefix)
    content_type = _guess_content_type(original_filename)

    url = await storage.upload(key, content, content_type=content_type)

    record = FileRecord(
        original_filename=original_filename,
        storage_key=key,
        bucket=settings.S3_BUCKET if settings.STORAGE_TYPE.lower() == "s3" else "local",
        storage_type=settings.STORAGE_TYPE.lower(),
        size=len(content),
        content_type=content_type,
        uploader_id=uploader_id,
        extra=json.dumps(extra, ensure_ascii=False) if extra else None,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)

    logger.info(
        "文件已上传",
        file_id=record.id,
        storage_type=record.storage_type,
        size=record.size,
        key=record.storage_key,
    )
    return {
        "id": record.id,
        "url": url,
        "storage_key": record.storage_key,
        "size": record.size,
        "content_type": record.content_type,
    }


async def delete_upload(record_id: int, db) -> bool:
    """删除文件（对象存储 + 元数据）"""
    from fastapi_app.shared_models.file_record import FileRecord

    record = await db.get(FileRecord, record_id)
    if record is None:
        return False

    storage = get_storage()
    await storage.delete(record.storage_key)
    await db.delete(record)
    await db.flush()
    logger.info("文件已删除", file_id=record.id, key=record.storage_key)
    return True


async def get_upload_url(record_id: int, db) -> str | None:
    """获取文件访问 URL"""
    from fastapi_app.shared_models.file_record import FileRecord

    record = await db.get(FileRecord, record_id)
    if record is None:
        return None

    storage = get_storage()
    return storage.get_url(record.storage_key)
