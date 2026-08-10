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
    """对 URL 进行安全校验。

    规则：
    1. 空值直接返回空字符串。
    2. 以 / 开头的相对路径（如 /static/uploads/xxx.png）放行，
       同时阻止路径遍历攻击（如 /static/../../../etc/passwd）。
    3. 以已知安全协议（http/https/mailto/tel/ftp）开头的绝对 URL 放行。
    4. 其他协议一律拒绝，包括 URL 编码伪装的危险协议。
    """
    from urllib.parse import unquote

    if not url:
        return ''

    # 仅在检测到 HTML 标签时才使用 bleach，纯路径直接跳过以节省开销
    if '<' in url or '>' in url:
        cleaned = bleach.clean(url, tags=[], attributes={}, strip=True)
    else:
        cleaned = url

    stripped = cleaned.strip()
    if not stripped:
        return ''

    # 相对路径：以 / 开头且不包含协议分隔符 ":"
    # 注意：排除 "//" 开头的协议相对 URL（如 //evil.com），浏览器会解析为 http/https
    if stripped.startswith('/') and ':' not in stripped:
        if stripped.startswith('//'):
            return ''
        # 防御路径遍历攻击
        if '..' in stripped.split('/'):
            return ''
        return cleaned

    # URL 解码后再检查 scheme，防止 %3A（即 :）等编码绕过
    decoded = unquote(stripped)
    colon_pos = decoded.find(':')
    if colon_pos > 0:
        scheme = decoded[:colon_pos].lower()
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
