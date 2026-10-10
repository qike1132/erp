"""xlsx_cell_images - 单元测试

覆盖从 WPS 工作簿提取「单元格图片」（DISPIMG）的逻辑：
- parse_dispimg_id：从单元格公式里抠出图片 ID
- guess_image_extension：按魔数推断扩展名
- extract_cell_images：cellimages.xml + rels + media 三件套的解析与容错
"""
from __future__ import annotations

import zipfile

import pytest

from fastapi_app.services.xlsx_cell_images import (
    extract_cell_images,
    guess_image_extension,
    parse_dispimg_id,
)

PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
JPEG_BYTES = b'\xff\xd8\xff\xe0' + b'\x00' * 16
GIF_BYTES = b'GIF89a' + b'\x00' * 8
WEBP_BYTES = b'RIFF\x00\x00\x00\x00WEBP' + b'\x00' * 8

CELL_IMAGES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<etc:cellImages xmlns:etc="http://www.wps.cn/officeDocument/2017/etCustomData" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<etc:cellImage><xdr:pic><xdr:nvPicPr><xdr:cNvPr id="2" name="ID_AAA111"/>'
    '</xdr:nvPicPr><xdr:blipFill><a:blip r:embed="rId1"/></xdr:blipFill></xdr:pic></etc:cellImage>'
    '<etc:cellImage><xdr:pic><xdr:nvPicPr><xdr:cNvPr id="3" name="ID_BBB222"/>'
    '</xdr:nvPicPr><xdr:blipFill><a:blip r:embed="rId2"/></xdr:blipFill></xdr:pic></etc:cellImage>'
    '<etc:cellImage><xdr:pic><xdr:nvPicPr><xdr:cNvPr id="4" name="ID_CCC333"/>'
    '</xdr:nvPicPr><xdr:blipFill><a:blip r:embed="rId404"/></xdr:blipFill></xdr:pic></etc:cellImage>'
    '</etc:cellImages>'
)

RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
    'Target="media/image1.png"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
    'Target="../media/image2.jpeg"/>'
    '</Relationships>'
)


def _build_workbook(tmp_path, *, cell_images_xml=CELL_IMAGES_XML, rels_xml=RELS_XML,
                    media: dict | None = None, with_cellimages: bool = True):
    """按 WPS 的存放约定拼一个最小 xlsx。"""
    path = tmp_path / 'book.xlsx'
    media = media if media is not None else {'xl/media/image1.png': PNG_BYTES, 'media/image2.jpeg': JPEG_BYTES}
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('[Content_Types].xml', '<Types/>')
        if with_cellimages:
            zf.writestr('xl/cellimages.xml', cell_images_xml)
            zf.writestr('xl/_rels/cellimages.xml.rels', rels_xml)
        for name, data in media.items():
            zf.writestr(name, data)
    return str(path)


class TestParseDispimgId:
    def test_extracts_id_from_formula(self):
        assert parse_dispimg_id('=DISPIMG("ID_72B27CC9A06A4306AABB5E28C6037F7D",1)') == 'ID_72B27CC9A06A4306AABB5E28C6037F7D'

    def test_tolerates_case_and_spaces(self):
        assert parse_dispimg_id('=dispimg( "ID_abc123" , 1 )') == 'ID_abc123'

    @pytest.mark.parametrize('value', [None, 123, '', '普通文本', '=A1+B1'])
    def test_non_dispimg_returns_none(self, value):
        assert parse_dispimg_id(value) is None


class TestGuessImageExtension:
    @pytest.mark.parametrize(('data', 'expected'), [
        (PNG_BYTES, 'png'),
        (JPEG_BYTES, 'jpg'),
        (GIF_BYTES, 'gif'),
        (WEBP_BYTES, 'webp'),
        (b'not an image', None),
    ])
    def test_by_magic_bytes(self, data, expected):
        assert guess_image_extension(data) == expected


class TestExtractCellImages:
    def test_extracts_all_referenced_images(self, tmp_path):
        """rId→Target 映射与 ID→rId 映射都正确串起来"""
        images = extract_cell_images(_build_workbook(tmp_path))
        assert set(images) == {'ID_AAA111', 'ID_BBB222'}
        assert images['ID_AAA111'] == PNG_BYTES
        assert images['ID_BBB222'] == JPEG_BYTES

    def test_relative_parent_target_is_resolved(self, tmp_path):
        """Target 写成 ../media/... 时也能落到正确成员"""
        images = extract_cell_images(_build_workbook(tmp_path))
        assert images['ID_BBB222'] == JPEG_BYTES

    def test_dangling_relationship_is_skipped(self, tmp_path):
        """rId 在 rels 里不存在 → 跳过该图，不抛异常"""
        images = extract_cell_images(_build_workbook(tmp_path))
        assert 'ID_CCC333' not in images

    def test_missing_media_member_is_skipped(self, tmp_path):
        """rels 指向的 media 不在包里 → 跳过该图"""
        path = _build_workbook(tmp_path, media={'xl/media/image1.png': PNG_BYTES})
        images = extract_cell_images(path)
        assert set(images) == {'ID_AAA111'}

    def test_workbook_without_cell_images_returns_empty(self, tmp_path):
        """普通 xlsx（无 cellimages.xml）返回空字典"""
        assert extract_cell_images(_build_workbook(tmp_path, with_cellimages=False)) == {}

    def test_broken_zip_returns_empty(self, tmp_path):
        """损坏/非 zip 文件不应抛异常"""
        path = tmp_path / 'broken.xlsx'
        path.write_bytes(b'not a zip at all')
        assert extract_cell_images(str(path)) == {}

    def test_blank_rels_returns_empty(self, tmp_path):
        """rels 为空时不应继续尝试解析"""
        path = _build_workbook(tmp_path, rels_xml='<Relationships/>')
        assert extract_cell_images(path) == {}
