"""
storage_service 图片处理变体（压缩主图 / 缩略图 / 模糊占位图 / 删除清理）测试。

背景（防止回归）：
- 2026-08-12 曾出现 `save_upload` 的布尔参数 `generate_thumbnail` 与模块级同名函数
  相互遮蔽，导致上传时 TypeError 崩溃、缩略图从未生成。集成用例覆盖该路径。
- 压缩后 storage_key 必须保持 `/` 分隔符（Windows 下 Path.with_suffix 会产出
  反斜杠，破坏 URL 与 S3 key），单测覆盖。

组织：
- 无标记 = 单元测试（仅依赖 Pillow，无数据库/存储后端）
- @pytest.mark.integration = 需要数据库（事务回滚隔离）+ 临时本地存储后端
"""
from __future__ import annotations

from io import BytesIO

import pytest
import pytest_asyncio

# 测试专用数据库（conftest 计算得出，与开发库 erp_system 隔离，避免种子数据污染）
from conftest import TEST_DATABASE_URL
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fastapi_app.services import storage_service as svc
from fastapi_app.shared_models.file_record import FileRecord

# ==================== 测试辅助 ====================


def _make_jpeg(width: int = 3000, height: int = 2000) -> bytes:
    """生成一张真实可解码的 JPEG（手机原图规模）"""
    buf = BytesIO()
    Image.new("RGB", (width, height), (180, 90, 40)).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _decode_webp(data: bytes) -> Image.Image:
    img = Image.open(BytesIO(data))
    assert img.format == "WEBP", f"期望 WebP，实际 {img.format}"
    img.load()
    return img


# ==================== 单元测试：纯函数 ====================


class TestMakeThumbnail:
    def test_downscales_to_max_400_and_webp(self):
        raw = _make_jpeg(3000, 2000)
        thumb = svc.make_thumbnail(raw)
        assert thumb is not None
        img = _decode_webp(thumb)
        assert max(img.size) <= 400
        assert len(thumb) < len(raw)

    def test_keeps_small_images(self):
        raw = _make_jpeg(100, 80)
        thumb = svc.make_thumbnail(raw)
        assert thumb is not None
        img = _decode_webp(thumb)
        assert max(img.size) <= 400

    def test_invalid_bytes_returns_none(self):
        assert svc.make_thumbnail(b"not an image") is None


class TestCompressImage:
    def test_downscales_to_max_1600_webp(self):
        raw = _make_jpeg(3000, 2000)
        comp = svc.compress_image(raw)
        assert comp is not None
        img = _decode_webp(comp)
        assert max(img.size) <= 1600

    def test_smaller_than_original(self):
        raw = _make_jpeg(3000, 2000)
        comp = svc.compress_image(raw)
        assert comp is not None
        assert len(comp) < len(raw)

    def test_invalid_bytes_returns_none(self):
        assert svc.compress_image(b"not an image") is None


class TestMakeBlurPlaceholder:
    def test_tiny_blur_placeholder(self):
        raw = _make_jpeg(3000, 2000)
        blur = svc.make_blur_placeholder(raw)
        assert blur is not None
        img = _decode_webp(blur)
        assert max(img.size) <= 32
        # 占位图应远小于缩略图
        assert len(blur) < len(svc.make_thumbnail(raw) or b"")

    def test_invalid_bytes_returns_none(self):
        assert svc.make_blur_placeholder(b"not an image") is None


class TestKeyDerivation:
    def test_variant_key_suffixes(self):
        key = "customer-sampling/20260812/abc123.jpg"
        assert svc.get_thumbnail_key(key) == "customer-sampling/20260812/abc123.jpg.thumb.webp"
        assert svc.get_blur_key(key) == "customer-sampling/20260812/abc123.jpg.blur.webp"

    def test_to_webp_key_keeps_forward_slashes(self):
        """回归：Windows 下曾用 Path.with_suffix 生成反斜杠 key，破坏 URL"""
        key = "customer-sampling/20260812/abc123.jpg"
        assert svc._to_webp_key(key) == "customer-sampling/20260812/abc123.webp"
        assert "\\" not in svc._to_webp_key(key)
        # 多级前缀 + 文件名无扩展名边界
        assert svc._to_webp_key("a/b/c.d/e.png") == "a/b/c.d/e.webp"


class TestNoParameterShadowing:
    """回归：save_upload 的布尔参数 generate_thumbnail 不得遮蔽模块函数"""

    def test_module_function_is_callable(self):
        assert callable(svc.make_thumbnail)
        assert callable(svc.make_blur_placeholder)
        # 原缺陷点：模块内函数与参数同名时，函数内调用会拿到布尔值
        import inspect

        sig = inspect.signature(svc.save_upload)
        param = sig.parameters["generate_thumbnail"]
        assert param.default is False
        assert svc.make_thumbnail.__name__ != "generate_thumbnail"


# ==================== 集成测试：save_upload / delete_upload ====================


@pytest_asyncio.fixture
async def storage_db():
    """function-scoped 数据库会话（主库 + 外层事务回滚隔离），复用 test_customer_sampling_service 模式"""
    from fastapi_app.shared_models import Base

    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with engine.connect() as conn:
            trans = await conn.begin()
            session_factory = async_sessionmaker(
                bind=conn, class_=AsyncSession, expire_on_commit=False,
            )
            async with session_factory() as session:
                try:
                    yield session
                finally:
                    await session.close()
            await trans.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
def tmp_storage(tmp_path, monkeypatch):
    """将存储后端单例替换为临时目录，测试文件不落盘到 static/uploads"""
    backend = svc.LocalStorageBackend(base_dir=tmp_path)
    monkeypatch.setattr(svc, "_backend", backend)
    return backend


@pytest.mark.integration
class TestSaveUploadVariants:
    async def test_generate_thumbnail_flag_creates_all_variants(self, storage_db, tmp_storage):
        """回归主路径：generate_thumbnail=True 时主图压缩 + 缩略图 + 模糊占位图全部生成"""
        raw = _make_jpeg(3000, 2000)
        res = await svc.save_upload(
            content=raw,
            original_filename="product-photo.jpg",
            db=storage_db,
            prefix="customer-sampling/",
            generate_thumbnail=True,
        )
        await storage_db.commit()

        assert res["thumbnail_url"] is not None
        assert res["url"] is not None
        # 主图应被压缩为 WebP 且扩展名改为 .webp
        assert res["storage_key"].endswith(".webp")
        assert res["content_type"] == "image/webp"
        assert "\\" not in res["storage_key"], "storage_key 不允许反斜杠"

        base = tmp_storage.base_dir
        assert (base / res["storage_key"]).exists()
        assert (base / svc.get_thumbnail_key(res["storage_key"])).exists()
        assert (base / svc.get_blur_key(res["storage_key"])).exists()

        # FileRecord 已写入
        record = await storage_db.get(FileRecord, res["id"])
        assert record is not None
        assert record.storage_key == res["storage_key"]

    async def test_without_flag_stores_original_only(self, storage_db, tmp_storage):
        """generate_thumbnail=False（其他上传场景）时保持原样，不生成变体"""
        raw = _make_jpeg(3000, 2000)
        res = await svc.save_upload(
            content=raw,
            original_filename="plain.png",
            db=storage_db,
            prefix="other/",
            generate_thumbnail=False,
        )
        await storage_db.commit()

        assert res["thumbnail_url"] is None
        assert res["storage_key"].endswith(".png")
        base = tmp_storage.base_dir
        assert (base / res["storage_key"]).exists()
        assert not (base / svc.get_thumbnail_key(res["storage_key"])).exists()

    async def test_delete_upload_removes_main_and_variants(self, storage_db, tmp_storage):
        """删除记录时同步清理缩略图与模糊占位图，避免孤儿文件"""
        res = await svc.save_upload(
            content=_make_jpeg(3000, 2000),
            original_filename="del-me.jpg",
            db=storage_db,
            prefix="customer-sampling/",
            generate_thumbnail=True,
        )
        await storage_db.commit()

        base = tmp_storage.base_dir
        main = base / res["storage_key"]
        thumb = base / svc.get_thumbnail_key(res["storage_key"])
        blur = base / svc.get_blur_key(res["storage_key"])
        assert main.exists() and thumb.exists() and blur.exists()

        ok = await svc.delete_upload(res["id"], storage_db)
        await storage_db.commit()

        assert ok is True
        assert not main.exists()
        assert not thumb.exists()
        assert not blur.exists()
        record = await storage_db.execute(
            select(FileRecord.id).where(FileRecord.id == res["id"])
        )
        assert record.scalar_one_or_none() is None

    async def test_delete_missing_variants_does_not_raise(self, storage_db, tmp_storage):
        """历史文件（无变体）删除时缺失变体应被忽略"""
        res = await svc.save_upload(
            content=_make_jpeg(800, 600),
            original_filename="legacy.jpg",
            db=storage_db,
            prefix="customer-sampling/",
            generate_thumbnail=False,
        )
        await storage_db.commit()
        # 变体本就不存在，删除不应抛错
        ok = await svc.delete_upload(res["id"], storage_db)
        await storage_db.commit()
        assert ok is True
