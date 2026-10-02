"""统一业务验证工具函数

消除各服务中重复的内联验证逻辑（数量范围、名称非空等），
提供统一的验证函数和错误消息格式。

P0-12 起同时承载上传文件魔数（文件头签名）校验：matches_upload_magic /
validate_upload_magic / require_upload_magic，供各上传端点复用 —— 历史上多处
上传端点只按扩展名判定，把任意文件改名为 .xlsx/.png 即可穿过校验直达解析器。
"""
import logging
from collections.abc import Callable, Sequence
from typing import Any

from fastapi import HTTPException

from fastapi_app.core.business_rules import MAX_QUANTITY, MIN_QUANTITY

logger = logging.getLogger(__name__)


def validate_quantity_range(
    quantity: int,
    field_name: str = "数量",
    min_val: int | None = None,
    max_val: int | None = None,
) -> int:
    """验证数量是否在有效范围内，通过则返回原值。

    Args:
        quantity: 待验证的数量
        field_name: 字段名称（用于错误消息）
        min_val: 最小值，默认使用业务规则常量
        max_val: 最大值，默认使用业务规则常量

    Raises:
        ValueError: 数量超出范围时抛出
    """
    lo = min_val if min_val is not None else MIN_QUANTITY
    hi = max_val if max_val is not None else MAX_QUANTITY
    if quantity < lo or quantity > hi:
        raise ValueError(f"{field_name}必须在 {lo}-{hi} 之间")
    return quantity


def validate_not_empty(value: Any, field_name: str = "字段") -> str:
    """验证字符串非空（去除空白后），通过则返回去除空白后的字符串。

    Raises:
        ValueError: 值为空时抛出
    """
    if value is None:
        raise ValueError(f"{field_name}不能为空")
    str_value = str(value).strip()
    if not str_value:
        raise ValueError(f"{field_name}不能为空")
    return str_value


# ===========================================================================
# 上传文件魔数（文件头签名）校验 —— P0-12
# ===========================================================================
# 组名即调用方传入的 allowed_sets 元素；大小写与前导点号不敏感
# （'.xlsx' / 'XLSX' / 'xlsx' 等价）。
MAGIC_SETS: dict[str, tuple[bytes, ...]] = {
    # OOXML（.xlsx/.xlsm/.docx…）本质是 ZIP 容器
    "xlsx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    "xlsm": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    "zip": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    # 旧版 Office（.xls/.doc/.ppt）是 OLE2 复合文档
    "xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    "ole": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    "doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    "pdf": (b"%PDF",),  # 常规起点；规范允许头出现在前 1024 字节内，精判见 _SPECIAL_MATCHERS
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
    "webp": (b"RIFF",),  # 容器头；真实签名 RIFF????WEBP 由 _SPECIAL_MATCHERS 精判
    "bmp": (b"BM",),
    "tiff": (b"II*\x00", b"MM\x00*"),
    "tif": (b"II*\x00", b"MM\x00*"),
    "gz": (b"\x1f\x8b",),
    "7z": (b"7z\xbc\xaf\x27\x1c",),
    "rar": (b"Rar!\x1a\x07",),
}

# 文本类格式没有固定魔数：改判「可解码 + 不含 NUL 字节」
TEXT_SETS = frozenset({"csv", "txt", "text"})
# JSON 只要求首个非空白字符是 { 或 [
JSON_SETS = frozenset({"json"})

# 无法用「偏移 0 前缀」表达的格式：用谓词精判，匹配时**优先于** MAGIC_SETS 的前缀表。
# 所有调用方都传入文件全量内容（见 require_upload_magic 的 docstring），故谓词可以安全
# 地看前若干个字节。MAGIC_SETS 里仍保留同名键，作为「已知格式登记表」。
_SPECIAL_MATCHERS: dict[str, Callable[[bytes], bool]] = {
    # WebP 的真实签名是 RIFF????WEBP。RIFF 是 WAV/AVI/WebP 共用的容器头，
    # 只比对前 4 字节会让改名为 .webp 的 .wav/.avi 通过。
    "webp": lambda head: head[:4] == b"RIFF" and head[8:12] == b"WEBP",
    # PDF 规范允许 %PDF 出现在文件头 1024 字节内任意位置（部分扫描/生成工具会写前导字节）；
    # 下游 PyMuPDF 能正常识别这类文件，只在偏移 0 比对会把它误判为「与扩展名不符」而跳过。
    "pdf": lambda head: b"%PDF" in head[:1024],
}


def _magic_set_names(allowed_sets: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(allowed_sets, str):
        return (allowed_sets,)
    return tuple(allowed_sets)


def _normalize_magic_set(name: str) -> str:
    """组名归一化：'.XLSX' -> 'xlsx'。"""
    return name.strip().lower().lstrip(".")


def magic_signature(head_bytes: bytes, length: int = 12) -> str:
    """把文件头渲染成可读签名（hex + ascii），仅用于日志与错误消息。"""
    head = bytes(head_bytes[:length])
    hex_view = head.hex() if head else "(empty)"
    ascii_view = "".join(chr(b) if 32 <= b < 127 else "." for b in head)
    return f"hex={hex_view} ascii={ascii_view!r}"


# 文本里允许出现的控制字符：制表/换行/回车
_TEXT_CONTROL_ALLOWED = frozenset({0x09, 0x0A, 0x0D})


def _looks_like_text(head_bytes: bytes) -> bool:
    if not head_bytes or b"\x00" in head_bytes:
        return False
    # 仅「可 UTF-8 解码」不足以排除二进制：被改名为 .csv 的 zip 文件头同样是
    # 合法字符序列，故再拒掉制表/换行/回车之外的控制字符。
    if any(b < 0x20 and b not in _TEXT_CONTROL_ALLOWED for b in head_bytes):
        return False
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            head_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
        return True
    return False


def _looks_like_json(head_bytes: bytes) -> bool:
    stripped = head_bytes.lstrip(b"\xef\xbb\xbf \t\r\n")
    return bool(stripped) and stripped[:1] in (b"{", b"[")


def matches_upload_magic(head_bytes: bytes, allowed_sets: str | Sequence[str]) -> bool:
    """文件头是否匹配任一允许的格式组；True = 通过。

    Args:
        head_bytes: 文件内容或前若干字节（只读头部，传全量内容也安全）
        allowed_sets: 允许的格式组名，如 'xlsx' / ('xlsx', 'xlsm') / 'pdf'
    """
    for raw_name in _magic_set_names(allowed_sets):
        name = _normalize_magic_set(raw_name)
        if name in TEXT_SETS:
            if _looks_like_text(head_bytes):
                return True
        elif name in JSON_SETS:
            if _looks_like_json(head_bytes):
                return True
        else:
            special = _SPECIAL_MATCHERS.get(name)
            if special is not None:
                if special(head_bytes):
                    return True
                continue
            for signature in MAGIC_SETS.get(name, ()):
                if head_bytes[: len(signature)] == signature:
                    return True
    return False


def _describe_sets(allowed_sets: str | Sequence[str]) -> str:
    return "、".join(_normalize_magic_set(n) for n in _magic_set_names(allowed_sets))


def validate_upload_magic(head_bytes: bytes, allowed_sets: str | Sequence[str]) -> None:
    """校验文件头，不匹配时 raise ValueError（纯函数，便于单测）。

    需要 HTTP 语义（400 + 日志）的端点请用 require_upload_magic()。
    """
    if matches_upload_magic(head_bytes, allowed_sets):
        return
    raise ValueError(
        f"文件内容与扩展名不匹配（期望 {_describe_sets(allowed_sets)}，实际 {magic_signature(head_bytes)}）"
    )


def require_upload_magic(
    head_bytes: bytes,
    allowed_sets: str | Sequence[str],
    *,
    filename: str = "",
    detail: str | None = None,
) -> None:
    """上传端点用：文件头不匹配时记录签名并 raise HTTPException(400)。

    Args:
        head_bytes: 文件内容（函数内部只读头部，传全量内容安全）
        allowed_sets: 允许的格式组名，如 'xlsx' / ('zip', 'ole') / 'json'
        filename: 原始文件名，仅用于日志
        detail: 自定义 400 详情（默认给出期望格式与实际签名）
    """
    if matches_upload_magic(head_bytes, allowed_sets):
        return
    readable = _describe_sets(allowed_sets)
    logger.warning(
        "上传文件魔数校验失败: filename=%s 期望=%s %s",
        filename or "<unknown>",
        readable,
        magic_signature(head_bytes),
    )
    raise HTTPException(
        status_code=400,
        detail=detail or f"文件内容与扩展名不匹配（期望 {readable} 格式），可能不是有效的文件",
    )
