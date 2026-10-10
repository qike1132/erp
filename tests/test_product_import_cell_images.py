"""产品导入的「图片」列（WPS 单元格图片）—— 端到端验证

用户提供的模板把产品图片以 WPS「单元格图片」的形式放在「图片」列：单元格公式写作
``=DISPIMG("ID_x",1)``，图片字节并不在单元格里，而是集中在工作簿的
``xl/cellimages.xml``（见 ``services/xlsx_cell_images.py``）。本文件直接拿**仓库里
发布的模板文件**跑一次真实导入，证明图片确实经 storage_service 落库并写进
``product.image`` —— 而不是像以前那样整列被忽略。

本文件走真实测试库（conftest 的 test_engine 由 Base.metadata.create_all 建表）。
存储后端被换成 tmp_path 下的 LocalStorageBackend，避免往生产的 static/uploads 写测试文件。
"""
import io
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from fastapi_app.services import batch_import_service, storage_service
from fastapi_app.shared_models import Product

TEMPLATE = Path(__file__).resolve().parent.parent / 'static' / 'files' / '统一导入模板.xlsx'


class _Upload:
    """满足 ``schemas.batch.ExcelUpload`` 协议的最小上传对象。"""

    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self._buf = io.BytesIO(content)

    async def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)


def _storage_key(image_field: str) -> str:
    """product.image → 磁盘上的相对路径（兼容带签名与裸 key 两种形态）。"""
    return image_field.split('?', 1)[0].removeprefix('/static/uploads/')


def test_shipped_template_is_a_real_wps_cell_image_workbook():
    """发布的模板必须真的带单元格图片 —— 否则用户按模板填的图会静默丢失。"""
    from fastapi_app.services.xlsx_cell_images import extract_cell_images

    images = extract_cell_images(str(TEMPLATE))
    assert len(images) == 2, f'模板应含 2 张示例图，实际 {len(images)}'


async def test_import_template_products_carry_images(async_db_session, tmp_path, monkeypatch):
    """上传模板 → 2 个产品落库，且每个都带上了自己的图片。"""
    monkeypatch.setattr(
        storage_service, '_backend', storage_service.LocalStorageBackend(base_dir=tmp_path),
    )
    upload = _Upload(TEMPLATE.name, TEMPLATE.read_bytes())

    result = await batch_import_service.import_products_service(async_db_session, upload)

    assert result.success, result.message
    assert result.imported == 2, result.message

    rows = (await async_db_session.execute(select(Product))).scalars().all()
    imported = [p for p in rows if p.name.startswith('3寸MINI FAMILY')]
    assert len(imported) == 2, [p.name for p in rows]
    for product in imported:
        assert product.image, f'{product.name} 未导入图片'
        path = tmp_path / _storage_key(product.image)
        assert path.is_file(), f'{product.name} 的图片文件不存在: {product.image}'
        # 模板里的图是透明底抠图，压缩后必须仍带 alpha —— 早期实现会把它压成黑底
        with Image.open(path) as img:
            assert 'A' in img.getbands(), f'{product.name} 的图片丢了透明通道（会显示成黑底）'
