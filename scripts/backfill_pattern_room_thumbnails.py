"""
为已有「打样项目」产品图生成 WebP 缩略图（历史数据回填）。

背景
----
2026-08-12 之前上传的产品图只保存了原图，未生成 .thumb.webp 缩略图。
列表页 <img> 请求缩略图 URL 会 404，随后回退加载数 MB 的手机原图，
导致滚动列表时浏览器持续解码大图而严重卡顿。

本脚本为所有 customer_sampling_project.product_image_file_id 指向的
FileRecord 生成缩略图（storage_key + ".thumb.webp"），幂等可重复执行：
- 已存在缩略图的文件跳过
- 无法解码/文件缺失的图片跳过并计数

支持 local / s3 两种存储后端（复用 storage_service 的存储后端配置）。

用法（在项目根目录执行，自动读取 .env）：
    python scripts/backfill_pattern_room_thumbnails.py            # 正式执行
    python scripts/backfill_pattern_room_thumbnails.py --dry-run  # 仅统计不写入
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from fastapi_app.core.config import settings  # noqa: E402
from fastapi_app.services.storage_service import (  # noqa: E402
    LocalStorageBackend,
    get_blur_key,
    get_storage,
    get_thumbnail_key,
    make_blur_placeholder,
    make_thumbnail,
)
from fastapi_app.shared_models.customer_sampling import CustomerSamplingProject  # noqa: E402
from fastapi_app.shared_models.file_record import FileRecord  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_pattern_room_thumbnails")


def _is_local() -> bool:
    return settings.STORAGE_TYPE.lower() != "s3"


def _s3_client():
    import boto3
    from botocore.config import Config

    client_kwargs = {
        "service_name": "s3",
        "region_name": settings.S3_REGION,
        "aws_access_key_id": settings.S3_ACCESS_KEY,
        "aws_secret_access_key": settings.S3_SECRET_KEY,
        "config": Config(
            s3={"addressing_style": "path" if settings.S3_ENDPOINT else "auto"},
            retries={"max_attempts": 2, "mode": "adaptive"},
        ),
    }
    if settings.S3_ENDPOINT:
        client_kwargs["endpoint_url"] = settings.S3_ENDPOINT
    return boto3.client(**client_kwargs)


def _variant_exists(storage_key: str, variant_key: str) -> bool:
    if _is_local():
        return (LocalStorageBackend().base_dir / variant_key).exists()
    client = _s3_client()
    try:
        client.head_object(Bucket=settings.S3_BUCKET, Key=variant_key)
        return True
    except Exception:
        return False


def _read_original(storage_key: str) -> bytes | None:
    if _is_local():
        path = LocalStorageBackend().base_dir / storage_key
        if not path.exists():
            return None
        return path.read_bytes()
    client = _s3_client()
    try:
        resp = client.get_object(Bucket=settings.S3_BUCKET, Key=storage_key)
        return resp["Body"].read()
    except Exception as e:
        logger.warning("读取 S3 原图失败 key=%s: %s", storage_key, e)
        return None


async def main(dry_run: bool) -> int:
    engine = create_async_engine(settings.ASYNC_DATABASE_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    storage = get_storage()

    async with session_factory() as db:
        result = await db.execute(
            select(CustomerSamplingProject.product_image_file_id)
            .where(CustomerSamplingProject.product_image_file_id.is_not(None))
        )
        file_ids = sorted({row[0] for row in result.all()})
        if not file_ids:
            logger.info("没有需要回填的产品图片记录。")
            await engine.dispose()
            return 0

        records_result = await db.execute(select(FileRecord).where(FileRecord.id.in_(file_ids)))
        records = records_result.scalars().all()
        logger.info("项目关联图片文件 %d 个（去重后 %d 个 FileRecord）", len(file_ids), len(records))

    thumb_skip = 0
    thumb_gen = 0
    blur_skip = 0
    blur_gen = 0
    failed = 0
    missing = 0

    for record in records:
        key = record.storage_key
        if not key:
            failed += 1
            continue
        content: bytes | None = None
        # 缩略图
        thumb_key = get_thumbnail_key(key)
        if not _variant_exists(key, thumb_key):
            if content is None:
                content = _read_original(key)
            if content is None:
                logger.warning("原图缺失，跳过: file_id=%s key=%s", record.id, key)
                missing += 1
                continue
            thumb = make_thumbnail(content)
            if thumb is None:
                logger.warning("缩略图生成失败，跳过: file_id=%s key=%s", record.id, key)
                failed += 1
                continue
            if dry_run:
                logger.info("[dry-run] 待生成缩略图: file_id=%s %s", record.id, thumb_key)
                thumb_gen += 1
            else:
                try:
                    await storage.upload(thumb_key, thumb, content_type="image/webp")
                    thumb_gen += 1
                    logger.info("已生成缩略图: file_id=%s %s (原 %d B -> 缩略图 %d B)",
                                record.id, thumb_key, len(content), len(thumb))
                except Exception as e:
                    logger.error("缩略图上传失败: file_id=%s key=%s: %s", record.id, key, e)
                    failed += 1
        else:
            thumb_skip += 1

        # 模糊占位图（blur-up）
        blur_key = get_blur_key(key)
        if not _variant_exists(key, blur_key):
            if content is None:
                content = _read_original(key)
            if content is None:
                missing += 1
                continue
            blur = make_blur_placeholder(content)
            if blur is None:
                logger.warning("模糊占位图生成失败，跳过: file_id=%s key=%s", record.id, key)
                failed += 1
                continue
            if dry_run:
                logger.info("[dry-run] 待生成模糊占位图: file_id=%s %s", record.id, blur_key)
                blur_gen += 1
            else:
                try:
                    await storage.upload(blur_key, blur, content_type="image/webp")
                    blur_gen += 1
                    logger.info("已生成模糊占位图: file_id=%s %s (%d B)", record.id, blur_key, len(blur))
                except Exception as e:
                    logger.error("模糊占位图上传失败: file_id=%s key=%s: %s", record.id, key, e)
                    failed += 1
        else:
            blur_skip += 1

    await engine.dispose()

    logger.info(
        "回填完成：共 %d 个文件，缩略图跳过 %d/生成 %d，模糊占位图跳过 %d/生成 %d，失败 %d，原图缺失 %d%s",
        len(records), thumb_skip, thumb_gen, blur_skip, blur_gen, failed, missing,
        "（dry-run，未写入）" if dry_run else "",
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="回填打样项目产品图缩略图")
    parser.add_argument("--dry-run", action="store_true", help="仅统计不写入")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(dry_run=args.dry_run)))
