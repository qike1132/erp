"""SPA 入口 CSP 收紧的**可验证前提**：页面里不得有内联脚本/内联事件处理器（M-2）。

背景：给 SPA 入口发头的是 nginx 的 `config/security-headers.conf`，其 CSP 的
`script-src` 带 `'unsafe-inline'`（后端 `core/middleware.py` 的严格 CSP 只作用于
API 响应），实战意义是"前端页面没有第二道防线"。收紧的前提是产物里确实没有内联
脚本 —— 初版**有**（`#app-loading` 的 8 秒失败兜底 + 内联 `onclick`），所以那一步
此前做不了；现在已把兜底脚本外置为 `/app-loading-fallback.js`。

本文件锁住三条不变量，防止"收紧后又被加回内联脚本"：
1. `frontend-vite/index.html` 里没有无 `src` 的 `<script>`；
2. 没有内联事件处理器（`onclick=` 等）；
3. nginx CSP 的 `script-src` 不含 `'unsafe-inline'`。

刻意保留项：`style-src` 仍允许 `'unsafe-inline'` —— 加载指示器是**内联关键 CSS**，
首屏前必须生效（见 index.html 的 `<style>`），把它外置会引入 FOUC。
"""
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INDEX_HTML = _REPO_ROOT / 'frontend-vite' / 'index.html'
_SECURITY_HEADERS = _REPO_ROOT / 'config' / 'security-headers.conf'
_FALLBACK_JS = _REPO_ROOT / 'frontend-vite' / 'public' / 'app-loading-fallback.js'

_SCRIPT_TAG_RE = re.compile(r'<script\b[^>]*>', re.IGNORECASE)
_INLINE_HANDLER_RE = re.compile(r'\son[a-z]+\s*=', re.IGNORECASE)
_CSP_RE = re.compile(r'Content-Security-Policy\s+"([^"]+)"', re.IGNORECASE)


def _csp_directive(name: str) -> str:
    conf = _SECURITY_HEADERS.read_text(encoding='utf-8')
    match = _CSP_RE.search(conf)
    assert match, 'security-headers.conf 里找不到 Content-Security-Policy 头'
    for directive in match.group(1).split(';'):
        if directive.strip().startswith(name):
            return directive.strip()
    return ''


# ---------------------------------------------------------------------------
# index.html 侧
# ---------------------------------------------------------------------------

def test_index_html_has_no_inline_script():
    html = _INDEX_HTML.read_text(encoding='utf-8')
    inline = [tag for tag in _SCRIPT_TAG_RE.findall(html) if 'src=' not in tag.lower()]
    assert inline == [], f'index.html 仍有内联 <script>（CSP 收紧后会静默失效）: {inline}'


def test_index_html_has_no_inline_event_handler():
    html = _INDEX_HTML.read_text(encoding='utf-8')
    hits = _INLINE_HANDLER_RE.findall(html)
    assert hits == [], f'index.html 仍有内联事件处理器（CSP 收紧后不会触发）: {hits}'


def test_loading_fallback_script_is_external_and_present():
    """兜底脚本必须外置存在，且自身不含内联事件处理器。"""
    assert _FALLBACK_JS.is_file(), f'兜底脚本不存在: {_FALLBACK_JS}'
    js = _FALLBACK_JS.read_text(encoding='utf-8')
    assert 'addEventListener' in js, '兜底脚本的"重新加载"按钮应通过 addEventListener 绑定'
    assert not _INLINE_HANDLER_RE.search(js), '兜底脚本里不能有内联事件处理器'


# ---------------------------------------------------------------------------
# nginx CSP 侧
# ---------------------------------------------------------------------------

def test_nginx_csp_script_src_forbids_inline():
    script_src = _csp_directive('script-src')
    assert script_src, 'CSP 里缺少 script-src 指令'
    assert "'self'" in script_src
    assert "'unsafe-inline'" not in script_src, f'script-src 仍允许内联脚本: {script_src}'


def test_nginx_csp_style_src_keeps_unsafe_inline_by_design():
    """内联关键 CSS 是刻意保留的（首屏加载指示器）。"""
    assert "'unsafe-inline'" in _csp_directive('style-src')
