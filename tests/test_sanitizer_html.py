"""utils/sanitizer 的 XSS 防护回归测试。

背景（2026-10-02 P6 审计）：本模块是 bleach 的替代品，唯一职责就是 XSS 防护。
原 `_strip_disallowed_tags` 对白名单标签 `return match.group(0)`（**连属性一起放行**），
而 docstring 声称「所有属性被移除」—— `<b onmouseover="alert(1)">` 会原样通过，
一旦接线即存储型 XSS。此文件钉住「白名单标签的属性必须被剥离」。
"""
import pytest

from utils.sanitizer import sanitize_html, sanitize_plain_text


@pytest.mark.parametrize('payload', [
    '<b onmouseover="alert(1)">x</b>',
    '<i onclick="alert(1)">x</i>',
    '<strong onfocus=alert(1) tabindex=1>x</strong>',
    '<p style="background:url(javascript:alert(1))">x</p>',
    '<em onmouseenter="alert(1)">x</em>',
])
def test_whitelisted_tags_strip_event_handlers_and_style(payload):
    out = sanitize_html(payload)
    lowered = out.lower()
    for bad in ('onmouseover', 'onclick', 'onfocus', 'onmouseenter', 'style=', 'javascript:'):
        assert bad not in lowered, f'属性未被剥离: {out!r}'


def test_whitelisted_tag_keeps_name_only():
    assert sanitize_html('<b class=x id=y>hi</b>') == '<b>hi</b>'
    assert sanitize_html('<br/>') == '<br/>'
    assert sanitize_html('<p style="color:red">t</p>') == '<p>t</p>'


def test_disallowed_tag_removed_content_kept():
    assert sanitize_html('<script>alert(1)</script>') == 'alert(1)'
    assert sanitize_html('<a href="javascript:alert(1)">link</a>') == 'link'


def test_plain_text_removes_all_tags():
    assert sanitize_plain_text('<b>a</b>&<i>b</i>') == 'a&amp;b'
