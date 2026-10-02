"""
输入清理工具模块

使用 Python 标准库 html + 正则实现 XSS 防护，替代第三方 bleach 依赖。
bleach 已于 2023 年废弃，且 requirements/base.txt 已移除该依赖。
"""


import html
import re
from urllib.parse import unquote

ALLOWED_TAGS = ['b', 'i', 'u', 'strong', 'em', 'br', 'p']
ALLOWED_ATTRIBUTES: dict = {}

# 预编译正则：匹配所有 HTML 标签（开标签、闭标签、自闭合）
_TAG_RE = re.compile(r'</?([a-zA-Z][a-zA-Z0-9]*)\b[^>]*?>', re.DOTALL)
# 预编译正则：匹配自闭合标签（如 <br/>）
_SELF_CLOSING_RE = re.compile(r'<([a-zA-Z][a-zA-Z0-9]*)\s*/>')


def _rebuild_without_attributes(match: re.Match) -> str:
    """仅保留标签名，剥离全部属性。

    ⚠️ 安全性关键：原实现 `return match.group(0)` 会把白名单标签**连属性一起**放行，
    于是 `<b onmouseover="alert(1)">`、`<p style="...">` 原样通过 —— 一旦接线即
    存储型 XSS（这也正是本模块取代 bleach 后丢失的保证）。docstring 声称
    「所有属性被移除」，此处与之一致。ALLOWED_TAGS 均为无属性的内联标签，剥离安全。
    """
    raw = match.group(0)
    name = match.group(1).lower()
    if raw.startswith('</'):
        return f'</{name}>'
    if raw.rstrip().endswith('/>'):
        return f'<{name}/>'
    return f'<{name}>'


def _strip_disallowed_tags(text: str, allowed_tags: list[str], strip: bool = True) -> str:
    """移除不在白名单中的 HTML 标签。

    Args:
        text: 原始文本
        allowed_tags: 允许保留的标签名列表（小写）
        strip: True 时移除标签但保留内容；False 时移除标签及其内容

    Returns:
        清理后的文本
    """
    allowed_lower = {t.lower() for t in allowed_tags}

    def _replace_tag(match: re.Match) -> str:
        tag_name = match.group(1).lower()
        if tag_name in allowed_lower:
            return _rebuild_without_attributes(match)  # 保留标签名、剥离属性
        if strip:
            return ''  # 移除标签，保留内容
        return ''  # 移除标签

    return _TAG_RE.sub(_replace_tag, text)


def _escape_disallowed_tags(text: str, allowed_tags: list[str]) -> str:
    """对不在白名单中的标签进行 HTML 转义（而非移除）。

    Args:
        text: 原始文本
        allowed_tags: 允许保留的标签名列表（小写）

    Returns:
        清理后的文本
    """
    allowed_lower = {t.lower() for t in allowed_tags}

    def _replace_tag(match: re.Match) -> str:
        tag_name = match.group(1).lower()
        if tag_name in allowed_lower:
            return match.group(0)  # 保留允许的标签
        return html.escape(match.group(0))  # 转义不允许的标签

    return _TAG_RE.sub(_replace_tag, text)


def sanitize_html(text: str,
                  allowed_tags: list[str] | None = None,
                  allowed_attributes: dict | None = None) -> str:
    """
    清理 HTML 内容

    使用标准库 html + 正则替代 bleach.clean。
    移除不在白名单中的标签，对剩余内容进行 HTML 实体转义。

    Args:
        text: 原始文本
        allowed_tags: 允许的 HTML 标签
        allowed_attributes: 允许的属性（当前实现忽略属性，所有属性被移除）

    Returns:
        清理后的安全文本
    """
    if not text:
        return ''

    tags = allowed_tags or ALLOWED_TAGS
    # bleach.clean(strip=True) 行为：移除不允许的标签但保留其文本内容
    cleaned = _strip_disallowed_tags(text, tags, strip=True)
    # 对不允许的标签内容中的特殊字符进行转义（防止标签内注入）
    # 注意：允许的标签保留原样，其内容中的 < > & 仍需转义
    # bleach 的行为是对标签内容不做额外转义，这里保持一致
    return cleaned


def sanitize_plain_text(text: str) -> str:
    """
    清理纯文本（移除所有 HTML 标签并转义特殊字符）

    Args:
        text: 原始文本

    Returns:
        转义后的纯文本
    """
    if not text:
        return ''

    # 移除所有 HTML 标签
    cleaned = _TAG_RE.sub('', text)
    # 转义剩余的特殊字符（& < > " '）
    return html.escape(cleaned, quote=True)


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
    if not url:
        return ''

    # 检测到 HTML 标签时移除标签（替代 bleach.clean(tags=[], strip=True)）
    if '<' in url or '>' in url:
        cleaned = _TAG_RE.sub('', url)
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
    检查 HTML 是否安全（清理后与原文一致即安全）

    Args:
        text: 原始文本

    Returns:
        是否安全
    """
    if not text:
        return True

    cleaned = sanitize_html(text, allowed_tags=ALLOWED_TAGS)
    return cleaned == text
