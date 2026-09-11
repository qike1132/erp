"""产品图片「粘贴上传」端到端验证：真实 Chromium + 真实系统剪贴板 + 真实 Ctrl+V。

覆盖场景：
  1. 新增表单粘贴 → 命中上传、文件名补齐扩展名、缩略图出现
  2. 编辑弹窗打开时粘贴 → 只上传到弹窗，底层表单不被误传
  3. 弹窗关闭后粘贴 → 回落到新增表单
  4. 纯文本粘贴 → 不被拦截，正常进入输入框

前置：dev server 运行在 127.0.0.1:5199（vite --port 5199）。
      也可用环境变量指向真实入口：PASTE_E2E_BASE=http://127.0.0.1:3000
"""
import base64
import json
import os
import pathlib
import re
import sys
import time

from playwright.sync_api import sync_playwright, Route

BASE = os.environ.get('PASTE_E2E_BASE', 'http://127.0.0.1:5199')
TARGET = f'{BASE}/product'
PNG_B64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
UPLOAD_URL = f'data:image/png;base64,{PNG_B64}'
SHOT_DIR = pathlib.Path('evidence/paste_e2e')
SHOT_DIR.mkdir(parents=True, exist_ok=True)

uploads: list[str] = []
js_errors: list[str] = []
failed: list[str] = []


def check(name: str, ok: bool, detail: str = '') -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f' — {detail}' if detail else ''))
    if not ok:
        failed.append(name)


def sent_filename(index: int) -> str:
    match = re.search(r'filename="([^"]*)"', uploads[index])
    return match.group(1) if match else ''


def _safe_post_head(request) -> str:
    """只取 multipart 头部（含 filename），避免解码二进制图片内容"""
    try:
        buf = request.post_data_buffer
    except Exception:
        return ''
    if not buf:
        return ''
    return buf[:1024].decode('latin-1', errors='replace')


with sync_playwright() as p:
    # 本机未下载 playwright 专属内核，复用系统 Edge（Chromium 内核）
    browser = p.chromium.launch(channel='msedge')
    context = browser.new_context(viewport={'width': 1440, 'height': 900})
    context.grant_permissions(['clipboard-read', 'clipboard-write'], origin=BASE)
    page = context.new_page()
    page.on('pageerror', lambda e: js_errors.append(f'PAGEERROR: {e}'))
    page.on(
        'console',
        lambda m: js_errors.append(f'CONSOLE: {m.text}') if m.type == 'error' else None,
    )

    def route_api(route: Route) -> None:
        url = route.request.url
        if 'auth/upload' in url:
            uploads.append(_safe_post_head(route.request))
            route.fulfill(
                status=200,
                content_type='application/json',
                body=json.dumps({'success': True, 'url': UPLOAD_URL, 'filename': 'pasted.png', 'file_id': 1}),
            )
        elif '/auth/me' in url:
            route.fulfill(
                status=200,
                content_type='application/json',
                body=json.dumps({'success': True, 'user': {'id': 1, 'username': 'e2e', 'is_super': True, 'factory': None, 'permissions': []}}),
            )
        elif '/products/list' in url:
            route.fulfill(
                status=200,
                content_type='application/json',
                body=json.dumps({'items': [{'id': 1, 'name': 'E2E产品', 'barcode': '6900000000001', 'price': 9.9, 'image': None, 'factory': '东莞', 'current_stock': 3}], 'total': 1}),
            )
        elif 'nav-sections' in url or 'nav_sections' in url:
            route.fulfill(status=200, content_type='application/json', body='[]')
        else:
            route.fulfill(status=200, content_type='application/json', body=json.dumps({'success': True, 'items': [], 'total': 0}))

    page.route('**/api/v1/**', route_api)
    page.add_init_script(
        "sessionStorage.setItem('fb_auth_user_snapshot_v1', "
        "JSON.stringify({id:1,username:'e2e',is_super:true,factory:null,permissions:[]}));"
    )

    def write_clipboard_image() -> None:
        page.evaluate(
            """async (b64) => {
                const bin = atob(b64);
                const arr = new Uint8Array(bin.length);
                for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
                await navigator.clipboard.write([new ClipboardItem({ 'image/png': new Blob([arr], { type: 'image/png' }) })]);
            }""",
            PNG_B64,
        )

    def write_clipboard_text(text: str) -> None:
        page.evaluate('async (t) => { await navigator.clipboard.writeText(t) }', text)

    def wait_uploads(count: int, timeout: float = 8000) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if len(uploads) >= count:
                return True
            page.wait_for_timeout(150)
        return False

    page.goto(TARGET, wait_until='domcontentloaded')
    page.wait_for_selector('.pd-droppable', timeout=20000)
    page.wait_for_timeout(800)
    left_zone = page.locator('.pd-droppable').first
    page.screenshot(path=str(SHOT_DIR / '1_initial.png'))

    # ---------- 场景 1：新增表单粘贴 ----------
    print('\n[场景 1] 新增表单区域粘贴图片')
    write_clipboard_image()
    page.keyboard.press('Control+V')
    check('剪贴板图片触发了上传请求', wait_uploads(1), f'实际 {len(uploads)} 次')
    if uploads:
        name = sent_filename(0)
        check('提交文件名扩展名合法（后端按扩展名白名单校验）', bool(re.search(r'\.(png|jpe?g|gif)$', name, re.I)), name)
    page.wait_for_timeout(600)
    check('新增表单出现缩略图', left_zone.locator('.pd-thumb-preview').count() == 1)
    page.screenshot(path=str(SHOT_DIR / '2_form_paste.png'))

    # ---------- 场景 2：编辑弹窗打开时粘贴 ----------
    print('\n[场景 2] 编辑弹窗打开时粘贴（应只命中弹窗）')
    page.click('.pd-act-edit')
    page.wait_for_selector('.edit-modal-dialog', timeout=10000)
    page.wait_for_timeout(500)
    baseline = len(uploads)
    write_clipboard_image()
    page.keyboard.press('Control+V')
    check('弹窗内粘贴触发上传', wait_uploads(baseline + 1), f'新增 {len(uploads) - baseline} 次')
    page.wait_for_timeout(600)
    dialog = page.locator('.edit-modal-dialog')
    check('弹窗内出现缩略图', dialog.locator('.pd-thumb-preview').count() == 1)
    check('弹窗打开时仅上传一次（底层表单未重复接收）', len(uploads) == baseline + 1, f'累计 {len(uploads)} 次')
    page.screenshot(path=str(SHOT_DIR / '3_dialog_paste.png'))

    # ---------- 场景 3：弹窗关闭后回落到表单 ----------
    print('\n[场景 3] 关闭弹窗后粘贴（应回落到新增表单）')
    page.click('.edit-modal-dialog .bom-modal-close')
    page.wait_for_timeout(500)
    baseline = len(uploads)
    write_clipboard_image()
    page.keyboard.press('Control+V')
    check('弹窗关闭后粘贴被表单接收', wait_uploads(baseline + 1), f'新增 {len(uploads) - baseline} 次')
    page.wait_for_timeout(600)

    # ---------- 场景 4：纯文本粘贴不被拦截 ----------
    print('\n[场景 4] 纯文本粘贴（不应拦截、不应触发上传）')
    baseline = len(uploads)
    write_clipboard_text('E2E文本粘贴')
    name_input = page.locator('input[name="product-name"]').first
    name_input.click()
    page.keyboard.press('Control+V')
    page.wait_for_timeout(800)
    check('文本正常进入输入框', name_input.input_value() == 'E2E文本粘贴', f'实际 "{name_input.input_value()}"')
    check('文本粘贴未触发上传', len(uploads) == baseline, f'新增 {len(uploads) - baseline} 次')
    page.screenshot(path=str(SHOT_DIR / '4_text_paste.png'))

    # ---------- 场景 5：无文件名的剪贴板图片（部分浏览器/来源不提供文件名）----------
    print('\n[场景 5] 无文件名剪贴板图片 → 按 MIME 兜底补名')
    baseline = len(uploads)
    page.evaluate(
        """async (b64) => {
            const bin = atob(b64);
            const arr = new Uint8Array(bin.length);
            for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
            const dt = new DataTransfer();
            dt.items.add(new File([arr], '', { type: 'image/png' }));
            const evt = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
            document.dispatchEvent(evt);
            window.__pastePrevented = evt.defaultPrevented;
        }""",
        PNG_B64,
    )
    check('无文件名图片被接收', wait_uploads(baseline + 1), f'新增 {len(uploads) - baseline} 次')
    if len(uploads) > baseline:
        name = sent_filename(baseline)
        check('已按 MIME 补名为 pasted-*.png', bool(re.match(r'^pasted-\d+\.png$', name)), name)
    check('粘贴默认行为被阻止', page.evaluate('window.__pastePrevented') is True)

    browser.close()

print(f'\n上传请求累计 {len(uploads)} 次')
if js_errors:
    print('前端 JS 错误:')
    for e in dict.fromkeys(js_errors):
        print('  -', e)
if failed:
    print(f'失败 {len(failed)} 项: ' + '; '.join(failed))
    sys.exit(1)
print('全部通过 · 截图见 evidence/paste_e2e/')
