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


class TestTransparencyPreserved:
    """透明底图片不得被压成黑底（2026-10-09 带图模板导入暴露）。

    原实现无条件 ``convert('RGB')``，PIL 把 alpha=0 的像素按**黑色**填充 ——
    电商抠图（透明底 PNG）在产品列表里整块变黑。三个变体都必须保留 alpha。
    """

    @staticmethod
    def _transparent_png(size=(60, 60)) -> bytes:
        """四周全透明、中间一块不透明的红方块"""
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        for x in range(20, 40):
            for y in range(20, 40):
                img.putpixel((x, y), (255, 0, 0, 255))
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_thumbnail_keeps_alpha(self):
        img = _decode_webp(svc.make_thumbnail(self._transparent_png()))
        assert "A" in img.getbands(), "缩略图丢失了透明通道"
        assert img.convert("RGBA").getpixel((0, 0))[3] == 0, "角落应是全透明而非黑块"

    def test_compressed_main_keeps_alpha(self):
        img = _decode_webp(svc.compress_image(self._transparent_png()))
        assert "A" in img.getbands(), "主图丢失了透明通道"
        assert img.convert("RGBA").getpixel((0, 0))[3] == 0

    def test_blur_keeps_alpha(self):
        img = _decode_webp(svc.make_blur_placeholder(self._transparent_png()))
        assert "A" in img.getbands(), "模糊占位图丢失了透明通道"

    def test_opaque_jpeg_gains_no_alpha(self):
        """本就不透明的图不该凭空多出一层 alpha（无谓增大体积）"""
        img = _decode_webp(svc.make_thumbnail(_make_jpeg(100, 80)))
        assert "A" not in img.getbands()


class TestPixelBudget:
    """解码像素预算（2026-11-16 审计 Medium：上传图片没有解码像素预算）。

    拦哪种错：把 Pillow 的 MAX_IMAGE_PIXELS 抬到 2 亿（等于关掉解压炸弹防线），
    并且只在**解码之后**才发现图片过大。一张 20000x20000 的 1-bit PNG 头部只有
    几十字节，解码却要 ~1.6GB 内存 —— 一次上传即可把进程打挂。
    """

    @staticmethod
    def _png_declaring(width: int, height: int) -> bytes:
        """声明 width×height 的最小 PNG（约 70 字节，无真实像素数据）。

        这种文件正是攻击形态：体积几十字节、声明尺寸巨大，任何「先解码再判断」的
        实现都会在解码时才吃满内存。必须带一个 IDAT 分块 —— 只给 IHDR 时 Pillow 认
        不出这是 PNG，就测不到像素预算那条路径了。
        """
        import struct
        import zlib

        def _chunk(tag: bytes, payload: bytes) -> bytes:
            crc = struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
            return struct.pack(">I", len(payload)) + tag + payload + crc

        ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)  # 8bit 灰度
        return (
            b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(b"\x00" * 64))
            + _chunk(b"IEND", b"")
        )

    def test_declared_huge_png_raises_business_error(self):
        """声明 4 亿像素的 70 字节 PNG 必须被拒，且异常是**业务异常**（端点能映射 4xx）。"""
        from fastapi_app.core.exceptions import BusinessError

        assert issubclass(svc.ImagePixelBudgetExceededError, BusinessError)
        with pytest.raises(svc.ImagePixelBudgetExceededError):
            svc._open_image(self._png_declaring(20000, 20000))

    def test_thumbnail_generation_refuses_over_budget_png(self):
        """预算必须能在对外入口（缩略图生成）挡住，而不是只在私有函数里生效。

        1 亿像素：低于 Pillow 的炸弹阈值（2×上限），走本模块自己的预算判定。
        """
        with pytest.raises(svc.ImagePixelBudgetExceededError):
            svc.make_thumbnail(self._png_declaring(10000, 10000))

    def test_normal_phone_photo_still_accepted(self):
        """1200 万像素（手机拍照常见）必须放行 —— 预算不能伤到正常业务。"""
        img = svc._open_image(_make_jpeg(4000, 3000))
        assert img is not None
        img.close()

    def test_pillow_bomb_threshold_not_relaxed(self):
        """回归点：MAX_IMAGE_PIXELS 不得再被抬到 2 亿。"""
        svc._open_image(_make_jpeg(10, 10))
        from PIL import Image

        assert Image.MAX_IMAGE_PIXELS == svc._MAX_IMAGE_PIXELS
        assert svc._MAX_IMAGE_PIXELS <= 89_478_485  # Pillow 默认量级


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


class TestLocalBackendUrlConsistency:
    """upload 的返回值必须与 get_url 同口径（回归 N-1）。

    本地后端的 upload 曾返回裸路径 '/static/uploads/<key>'，而 get_url 返回签发 URL；
    S3 后端的 upload 一直是 `return self.get_url(key)`。两者不一致导致上传响应里的 url
    不带 st/s 参数，nginx secure_link 生效后前端拿它立刻预览会 403。
    """

    async def test_upload_matches_get_url_when_signing_enabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv('UPLOAD_URL_SIGNING_SECRET', 's3cret')
        backend = svc.LocalStorageBackend(base_dir=tmp_path)

        uploaded = await backend.upload('20261002/a.webp', b'x', 'image/webp')

        assert uploaded == backend.get_url('20261002/a.webp')
        assert 'st=' in uploaded and 's=' in uploaded

    async def test_upload_returns_plain_path_when_signing_disabled(self, tmp_path, monkeypatch):
        monkeypatch.delenv('UPLOAD_URL_SIGNING_SECRET', raising=False)
        backend = svc.LocalStorageBackend(base_dir=tmp_path)

        uploaded = await backend.upload('20261002/a.webp', b'x', 'image/webp')

        assert uploaded == '/static/uploads/20261002/a.webp'


class TestDeleteStorageKeys:
    """补偿删除（savepoint 回滚后删已落盘图片）必须真的删掉文件。

    导入路径登记的是**入库用的相对路径** `/static/uploads/<key>`，而对象存储里的
    key 是 `<key>`。LocalStorageBackend.delete 用 `base_dir / key` 定位文件，
    `Path` 遇到以 '/' 开头的右操作数会丢掉 base_dir ⇒ 补偿删除永远打空，
    回滚行的图片全部留成孤儿（Z04-R2 的补偿形同虚设）。
    """

    async def test_deletes_file_when_given_upload_relative_path(self, tmp_storage):
        key = '20261021/orphan.png'
        main = tmp_storage.base_dir / key
        thumb = tmp_storage.base_dir / svc.get_thumbnail_key(key)
        blur = tmp_storage.base_dir / svc.get_blur_key(key)
        for p in (main, thumb, blur):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'x')

        await svc.delete_storage_keys([f'/static/uploads/{key}'])

        assert not main.exists()
        assert not thumb.exists()
        assert not blur.exists()

    async def test_deletes_file_when_given_raw_key(self, tmp_storage):
        key = '20261021/raw.png'
        main = tmp_storage.base_dir / key
        main.parent.mkdir(parents=True, exist_ok=True)
        main.write_bytes(b'x')

        await svc.delete_storage_keys([key])

        assert not main.exists()

    async def test_backend_failure_does_not_raise(self, tmp_storage, monkeypatch):
        """删除失败只告警：异常不得冒泡打断导入主流程（docstring 的承诺）。"""

        async def boom(_key):
            raise RuntimeError('存储后端炸了')

        monkeypatch.setattr(tmp_storage, 'delete', boom)

        await svc.delete_storage_keys(['20261021/x.png'])


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
