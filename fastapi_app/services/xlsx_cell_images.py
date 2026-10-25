"""从 Excel 工作簿中提取「单元格图片」（WPS DISPIMG）。

WPS 表格把「插入到单元格」的图片集中存放在 ``xl/cellimages.xml``，单元格公式写作
``=DISPIMG("ID_xxx",1)`` 引用它；图片字节在 ``xl/media/`` 下，由
``xl/_rels/cellimages.xml.rels`` 建立 ``rId → 文件`` 的关联。本模块把
「图片 ID → 图片字节」取出来，供批量导入把图片随产品一并落库。

**为什么用正则而不是 XML 解析器**：结构固定且由 WPS 生成 —— ``<etc:cellImage>``
块内必有 ``name="ID_.."`` 与 ``r:embed="rIdN"``，逐块提取即可，无需完整 DOM。
正则**不解析实体**，天然免疫 XXE 与 billion-laughs；stdlib 的 ElementTree 会被本仓
bandit/ruff 的 S314 拦下，为这点固定结构引入 defusedxml 依赖也不划算。
"""
from __future__ import annotations

import logging
import posixpath
import re
import zipfile

logger = logging.getLogger(__name__)

#: 单元格图片引用的 ID 前缀（WPS 固定用 ID_ 开头）
_IMAGE_ID_PREFIX = 'ID_'

#: 单元格公式 ``=DISPIMG("ID_xxx",1)``；容错大小写与空白
_DISPIMG_RE = re.compile(r'DISPIMG\(\s*"(' + _IMAGE_ID_PREFIX + r'[0-9A-Za-z_]+)"', re.IGNORECASE)

#: ``<etc:cellImage>`` 块（非贪婪，跨行）
_CELL_IMAGE_BLOCK_RE = re.compile(r'<etc:cellImage\b.*?</etc:cellImage>', re.DOTALL)
_IMAGE_ID_ATTR_RE = re.compile(r'\bname="(' + _IMAGE_ID_PREFIX + r'[0-9A-Za-z_]+)"')
_EMBED_ATTR_RE = re.compile(r'\br:embed="([^"]+)"')

#: ``<Relationship .../>`` 标签及其 Id/Target 属性（属性顺序不保证，故分开取）
_RELATIONSHIP_TAG_RE = re.compile(r'<Relationship\b[^>]*?/?>')
_REL_ID_RE = re.compile(r'\bId="([^"]+)"')
_REL_TARGET_RE = re.compile(r'\bTarget="([^"]+)"')

#: 解压后的图片总量上限。上传文件本身已受 MAX_BATCH_UPLOAD_SIZE 限制，
#: 但 zip 的压缩比可以极高（zip bomb），故对解压总量再设一道闸门。
MAX_EXTRACTED_IMAGE_BYTES = 64 * 1024 * 1024


def parse_dispimg_id(cell_value: object) -> str | None:
    """从单元格值中取出 DISPIMG 引用的图片 ID；不是该形式时返回 None。

    产品导入模板的「图片」列由 WPS 写成 ``=DISPIMG("ID_xxx",1)``，polars/openpyxl
    读到的都是这串公式文本本身（不是图片），故在此按前缀把 ID 抠出来。
    """
    if not isinstance(cell_value, str):
        return None
    match = _DISPIMG_RE.search(cell_value)
    return match.group(1) if match else None


def guess_image_extension(data: bytes) -> str | None:
    """按魔数推断图片扩展名；无法识别返回 None（调用方应跳过该图）。"""
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return 'gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    return None


def extract_cell_images(xlsx_path: str) -> dict[str, bytes]:
    """提取工作簿内全部单元格图片，返回 ``{图片ID: 图片字节}``。

    工作簿不含单元格图片（普通 xlsx、或图片是浮动对象而非单元格图片）时返回空字典，
    不抛异常 —— 图片缺失不应阻断整批产品导入。

    Args:
        xlsx_path: 上传文件落盘后的临时路径。

    Returns:
        dict[str, bytes]: 图片 ID → 图片字节。解压总量超过
            :data:`MAX_EXTRACTED_IMAGE_BYTES` 时放弃提取并返回空字典。
    """
    # M5（2026-10-25）：统一 ZIP 前置预算（成员数/压缩比/解压总量）。图片总量
    # 的 64MiB 上限只看 cellimages 关联的媒体成员；本闸门兜住关系/XML 等其余成员。
    # 放进主 try（契约：任何失败都返回空 dict，不阻断导入主流程）。
    from fastapi_app.services.xlsx_budget import XlsxBudgetError, assert_zip_budget

    try:
        try:
            assert_zip_budget(xlsx_path)
        except XlsxBudgetError as exc:
            logger.warning('单元格图片提取前置预算未通过: %s', exc)
            return {}
        with zipfile.ZipFile(xlsx_path) as zf:
            names = set(zf.namelist())
            if 'xl/cellimages.xml' not in names:
                return {}
            rid_to_target = _parse_relationships(_read_member(zf, 'xl/_rels/cellimages.xml.rels'))
            if not rid_to_target:
                return {}
            cell_images_xml = _read_member(zf, 'xl/cellimages.xml')
            return _collect_images(zf, names, cell_images_xml, rid_to_target)
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        logger.warning('单元格图片提取失败: %s', exc)
        return {}


def _collect_images(
    zf: zipfile.ZipFile, names: set[str], cell_images_xml: str, rid_to_target: dict[str, str],
) -> dict[str, bytes]:
    """按 ``<etc:cellImage>`` 块把 ID 映射到图片字节，并守住解压总量。"""
    result: dict[str, bytes] = {}
    total = 0
    for block in _CELL_IMAGE_BLOCK_RE.findall(cell_images_xml):
        id_match = _IMAGE_ID_ATTR_RE.search(block)
        embed_match = _EMBED_ATTR_RE.search(block)
        if not id_match or not embed_match:
            continue
        target = rid_to_target.get(embed_match.group(1))
        if not target:
            continue
        member = _resolve_member(target)
        if member not in names:
            continue
        total += zf.getinfo(member).file_size
        if total > MAX_EXTRACTED_IMAGE_BYTES:
            logger.warning('单元格图片解压总量超过 %d 字节，放弃提取', MAX_EXTRACTED_IMAGE_BYTES)
            return {}
        result[id_match.group(1)] = zf.read(member)
    return result


def _parse_relationships(rels_xml: str) -> dict[str, str]:
    """解析 ``.rels``，返回 ``{rId: Target}``。"""
    mapping: dict[str, str] = {}
    for tag in _RELATIONSHIP_TAG_RE.findall(rels_xml):
        rel_id = _REL_ID_RE.search(tag)
        target = _REL_TARGET_RE.search(tag)
        if rel_id and target:
            mapping[rel_id.group(1)] = target.group(1)
    return mapping


def _resolve_member(target: str) -> str:
    """把 rels 里的 Target 解析为 zip 内的成员路径（相对 ``xl/``，可为 ``../``）。"""
    if target.startswith('/'):
        return target.lstrip('/')
    return posixpath.normpath(posixpath.join('xl', target))


def _read_member(zf: zipfile.ZipFile, member: str) -> str:
    """读取 zip 成员并解码为文本；缺成员时返回空串。"""
    try:
        return zf.read(member).decode('utf-8', errors='replace')
    except KeyError:
        return ''
