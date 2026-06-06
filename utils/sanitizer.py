"""
输入清理工具模块
使用bleach防止XSS攻击
"""


import bleach

ALLOWED_TAGS = ['b', 'i', 'u', 'strong', 'em', 'br', 'p']
ALLOWED_ATTRIBUTES = {}


def sanitize_html(text: str,
                  allowed_tags: list[str] | None = None,
                  allowed_attributes: dict | None = None) -> str:
    """
    清理HTML内容

    Args:
        text: 原始文本
        allowed_tags: 允许的HTML标签
        allowed_attributes: 允许的属性

    Returns:
        清理后的安全文本
    """
    if not text:
        return ''

    tags = allowed_tags or ALLOWED_TAGS
    attrs = allowed_attributes or ALLOWED_ATTRIBUTES

    return bleach.clean(
        text,
        tags=tags,
        attributes=attrs,
        strip=True
    )


def sanitize_plain_text(text: str) -> str:
    """
    清理纯文本（移除所有HTML）

    Args:
        text: 原始文本

    Returns:
        纯文本
    """
    if not text:
        return ''

    return bleach.clean(text, tags=[], strip=True)


SAFE_URL_SCHEMES = {'http', 'https', 'mailto', 'tel', 'ftp'}


def sanitize_url(url: str) -> str:
    if not url:
        return ''

    cleaned = bleach.clean(url, tags=[], attributes={}, strip=True)

    stripped = cleaned.strip()
    colon_pos = stripped.find(':')
    if colon_pos > 0:
        scheme = stripped[:colon_pos].lower()
        if scheme not in SAFE_URL_SCHEMES:
            return ''

    return cleaned


def is_safe_html(text: str) -> bool:
    """
    检查HTML是否安全

    Args:
        text: 原始文本

    Returns:
        是否安全
    """
    if not text:
        return True

    cleaned = bleach.clean(text, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True)
    return cleaned == text
