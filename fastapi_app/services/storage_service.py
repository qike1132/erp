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
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi_app.core.circuit_breaker import CircuitBreakerOpenError, get_breaker
from fastapi_app.core.config import settings
from fastapi_app.core.logger import get_logger

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
        except Exception:  # broad-except: 服务层容错，记录异常并返回安全默认值
            try:
                self._client.create_bucket(Bucket=self.bucket)
                logger.info("S3 bucket 已自动创建: %s", self.bucket)
            except Exception as e:  # broad-except: 服务层容错，记录异常并返回安全默认值
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
        """删除 S3 文件，通过熔断器保护"""
        breaker = get_breaker("s3_delete")

        async def _do_delete() -> None:
            def _delete() -> None:
                self._client.delete_object(Bucket=self.bucket, Key=key)
            await asyncio.to_thread(_delete)

        await breaker.call(_do_delete)

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
    date_prefix = datetime.now(UTC).strftime("%Y%m%d")
    key = f"{prefix}{date_prefix}/{uuid.uuid4().hex}.{ext}" if prefix else f"{date_prefix}/{uuid.uuid4().hex}.{ext}"
    return key


def _guess_content_type(filename: str) -> str:
    ctype, _ = mimetypes.guess_type(filename)
    return ctype or "application/octet-stream"


# 缩略图变体后缀（追加到原 storage_key 后，URL 派生无需额外元数据）
_THUMBNAIL_SUFFIX = ".thumb.webp"
_THUMBNAIL_MAX_SIZE = 400
_THUMBNAIL_QUALITY = 80

# 低质量模糊占位图（blur-up）：32px + 低质量，体积仅几百字节，
# 列表滚动时先显示模糊图再淡入清晰缩略图，避免白块闪烁
_BLUR_SUFFIX = ".blur.webp"
_BLUR_MAX_SIZE = 32
_BLUR_QUALITY = 20

# 主图压缩参数（上传时同步压缩，避免原图过大导致列表/详情解码卡顿）
_FULL_MAX_SIZE = 1600
_FULL_QUALITY = 82


def _open_image(content: bytes):
    """PIL 打开图片字节流；失败返回 None"""
    from io import BytesIO

    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow 未安装，无法处理图片")
        return None
    try:
        # 服务端处理受信用户上传（原图已通过大小/类型校验），
        # 放宽解压炸弹阈值，避免大尺寸扫描件被误判拒绝
        Image.MAX_IMAGE_PIXELS = 200_000_000
        return Image.open(BytesIO(content))
    except Exception as e:  # broad-except: 服务层容错，记录异常并返回安全默认值
        logger.warning("图片解码失败: %s", e)
        return None


def _image_to_rgb(img):
    """转为 RGB 丢弃 alpha，WebP/JPEG 编码更稳定（不改动原图，返回新对象或原对象）"""
    return img.convert("RGB") if img.mode not in ("RGB", "L") else img


def _resize_to_max(img, max_size: int):
    """等比缩放（最长边 <= max_size），返回新对象或原对象"""
    w, h = img.size
    if max(w, h) > max_size:
        scale = max_size / max(w, h)
        return img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
    return img


def _encode_webp(img, quality: int, method: int) -> bytes:
    """WebP 编码为字节流"""
    from io import BytesIO

    buf = BytesIO()
    img.save(buf, format="WEBP", quality=quality, method=method)
    return buf.getvalue()


def _thumbnail_from_image(img, max_size: int = _THUMBNAIL_MAX_SIZE, quality: int = _THUMBNAIL_QUALITY) -> bytes | None:
    """基于已解码 Image 生成 400px WebP 缩略图；失败返回 None"""
    try:
        return _encode_webp(_resize_to_max(_image_to_rgb(img), max_size), quality, method=4)
    except Exception as e:  # broad-except: 服务层容错，记录异常并返回安全默认值
        logger.warning("缩略图生成失败: %s", e)
        return None


def _blur_from_image(img, max_size: int = _BLUR_MAX_SIZE, quality: int = _BLUR_QUALITY) -> bytes | None:
    """基于已解码 Image 生成 32px WebP 模糊占位图；失败返回 None"""
    try:
        return _encode_webp(_resize_to_max(_image_to_rgb(img), max_size), quality, method=6)
    except Exception as e:  # broad-except: 服务层容错，记录异常并返回安全默认值
        logger.warning("模糊占位图生成失败: %s", e)
        return None


def _compress_from_image(img, max_size: int = _FULL_MAX_SIZE, quality: int = _FULL_QUALITY) -> bytes | None:
    """基于已解码 Image 压缩主图（最长边 <=1600px，WebP q82）；失败返回 None"""
    try:
        return _encode_webp(_resize_to_max(_image_to_rgb(img), max_size), quality, method=4)
    except Exception as e:  # broad-except: 服务层容错，记录异常并返回安全默认值
        logger.warning("主图压缩失败: %s", e)
        return None


def make_thumbnail(content: bytes, max_size: int = _THUMBNAIL_MAX_SIZE, quality: int = _THUMBNAIL_QUALITY) -> bytes | None:
    """生成 WebP 缩略图字节流（最长边不超过 max_size，等比缩放）

    仅供列表场景使用，原图仍保留。失败返回 None（调用方应回退原图）。
    注意：不能命名为 generate_thumbnail，避免与 save_upload 的同名布尔参数冲突。
    """
    img = _open_image(content)
    if img is None:
        return None
    try:
        return _thumbnail_from_image(img, max_size, quality)
    finally:
        img.close()


def compress_image(content: bytes, max_size: int = _FULL_MAX_SIZE, quality: int = _FULL_QUALITY) -> bytes | None:
    """压缩主图：最长边不超过 max_size，统一转 WebP（q82）

    上传时对原始照片/截图执行，将数 MB 的手机原图压缩为适合详情展示的体积。
    失败返回 None（调用方保留原图，不阻断上传）。
    """
    img = _open_image(content)
    if img is None:
        return None
    try:
        return _compress_from_image(img, max_size, quality)
    finally:
        img.close()


def get_thumbnail_key(storage_key: str) -> str:
    """根据原图 storage_key 派生缩略图 storage_key（追加固定后缀）"""
    return f"{storage_key}{_THUMBNAIL_SUFFIX}"


def get_blur_key(storage_key: str) -> str:
    """根据原图 storage_key 派生模糊占位图 storage_key（追加固定后缀）"""
    return f"{storage_key}{_BLUR_SUFFIX}"


def make_blur_placeholder(content: bytes, max_size: int = _BLUR_MAX_SIZE, quality: int = _BLUR_QUALITY) -> bytes | None:
    """生成 32px WebP 低质量模糊占位图（blur-up）

    体积通常 300-800 字节，作为列表缩略图的渐进式加载占位。
    失败返回 None（调用方跳过，前端回退骨架屏）。
    """
    img = _open_image(content)
    if img is None:
        return None
    try:
        return _blur_from_image(img, max_size, quality)
    finally:
        img.close()


def _to_webp_key(storage_key: str) -> str:
    """将存储 key 的扩展名替换为 .webp（主图压缩后使用）

    纯字符串操作保持 / 分隔符（Windows 下 Path.with_suffix 会产出反斜杠，破坏 URL/S3 key）。
    """
    head, _, tail = storage_key.rpartition("/")
    stem, _, _ext = tail.rpartition(".")
    return f"{head}/{stem}.webp" if head else f"{stem}.webp"


def _generate_image_variants(content: bytes) -> tuple[bytes | None, bytes | None, bytes | None, bool]:
    """同步生成缩略图 + 模糊占位图 + 主图压缩（CPU 密集型，供 asyncio.to_thread 调用）

    - 解码一次，三个变体复用同一 Image 对象（避免每个变体重复解码原图）
    - 上传内容已是 ≤1600px 的 WebP（前端已压缩）时跳过主图重压缩：
      重编码既耗时又几乎不缩小体积，属于冗余操作。

    返回 (thumb_bytes, blur_bytes, compressed, is_webp)；
    compressed 为 None 表示主图无需替换；is_webp 表示上传内容本身是 WebP（用于修正元数据）。
    """
    img = _open_image(content)
    if img is None:
        return None, None, None, False
    try:
        w, h = img.size
        is_webp = content[:4] == b"RIFF"
        already_optimized = is_webp and max(w, h) <= _FULL_MAX_SIZE and len(content) <= 2 * 1024 * 1024
        thumb = _thumbnail_from_image(img)
        blur = _blur_from_image(img)
        compressed = None if already_optimized else _compress_from_image(img)
        return thumb, blur, compressed, is_webp
    finally:
        img.close()


async def _upload_with_fallback(storage: StorageBackend, key: str, content: bytes, content_type: str) -> str:
    """上传文件；S3 熔断时降级到本地存储"""
    try:
        return await storage.upload(key, content, content_type=content_type)
    except CircuitBreakerOpenError as e:
        logger.warning("S3 存储熔断中，降级到本地存储: %s", e)
        local_backend = LocalStorageBackend()
        return await local_backend.upload(key, content, content_type=content_type)


async def save_upload(
    content: bytes,
    original_filename: str,
    db,
    uploader_id: int | None = None,
    prefix: str = "",
    extra: dict[str, Any] | None = None,
    generate_thumbnail: bool = False,
) -> dict[str, Any]:
    """保存上传文件到对象存储并写入元数据

    返回 {"id": ..., "url": ..., "storage_key": ..., "size": ...}
    若 generate_thumbnail=True：
      - 主图同步压缩（最长边 ≤ 1600px，WebP q82，压缩后更小才替换原图）
      - 额外生成 400px WebP 缩略图供列表使用，返回 {"thumbnail_url": ...}（生成失败则为 None）
      - 生成 32px WebP 模糊占位图（blur-up），由派生 URL 提供
    """
    from fastapi_app.shared_models.file_record import FileRecord

    storage = get_storage()
    key = _generate_key(original_filename, prefix=prefix)
    content_type = _guess_content_type(original_filename)
    thumbnail_url: str | None = None

    # 图片处理：先基于原始字节生成缩略图 + 模糊占位图（质量最好），再压缩主图
    # CPU 密集的 PIL 处理放入线程池，避免阻塞事件循环
    if generate_thumbnail and content_type and content_type.startswith("image/"):
        thumb_bytes, blur_bytes, compressed, is_webp_content = await asyncio.to_thread(
            _generate_image_variants, content
        )
        if compressed is not None and len(compressed) < len(content):
            # 压缩后的 WebP 更小 → 替换为主图（扩展名同步改为 .webp）
            key = _to_webp_key(key)
            content = compressed
            content_type = "image/webp"
        elif is_webp_content:
            # 上传内容本身是 WebP（前端已压缩）：修正元数据，避免 .jpg 等文件名存成错误 content_type
            content_type = "image/webp"
        if thumb_bytes is not None:
            thumb_key = get_thumbnail_key(key)
            thumbnail_url = await _upload_with_fallback(storage, thumb_key, thumb_bytes, "image/webp")
        if blur_bytes is not None:
            blur_key = get_blur_key(key)
            await _upload_with_fallback(storage, blur_key, blur_bytes, "image/webp")

    url = await _upload_with_fallback(storage, key, content, content_type)
    storage_type_override = settings.STORAGE_TYPE.lower()

    record = FileRecord(
        original_filename=original_filename,
        storage_key=key,
        bucket=settings.S3_BUCKET if storage_type_override == "s3" else "local",
        storage_type=storage_type_override,
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
        content_type=record.content_type,
        has_thumbnail=thumbnail_url is not None,
    )
    return {
        "id": record.id,
        "url": url,
        "storage_key": record.storage_key,
        "size": record.size,
        "content_type": record.content_type,
        "thumbnail_url": thumbnail_url,
    }


async def delete_upload(record_id: int, db) -> bool:
    """删除文件（对象存储 + 元数据，含缩略图变体）"""
    from fastapi_app.shared_models.file_record import FileRecord

    record = await db.get(FileRecord, record_id)
    if record is None:
        return False

    storage = get_storage()
    try:
        await storage.delete(record.storage_key)
    except CircuitBreakerOpenError as e:
        logger.warning("S3 存储熔断中，跳过对象删除（元数据仍会删除）: %s", e)
    # 顺带清理缩略图与模糊占位图变体（历史文件可能不存在，缺失时忽略）
    for variant_key in (get_thumbnail_key(record.storage_key), get_blur_key(record.storage_key)):
        try:
            await storage.delete(variant_key)
        except CircuitBreakerOpenError as e:
            logger.warning("S3 存储熔断中，跳过变体删除: %s", e)
        except OSError:
            pass  # 本地变体不存在，忽略; defensive: 异常静默处理,不影响主流程
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
