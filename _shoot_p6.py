"""渲染 v8 GUI 前端（浏览器 mock 模式）5 页 + 捕获 JS 错误。"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

HTML = pathlib.Path('server_manager_v8/presentation/web/index.html').resolve()
OUT = pathlib.Path('server_manager_v8/presentation/web/_shots')
OUT.mkdir(exist_ok=True)
errors = []

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_context(viewport={'width': 1500, 'height': 950}, device_scale_factor=1.5).new_page()
    page.on('pageerror', lambda e: errors.append(f'PAGEERROR: {e}'))
    page.on('console', lambda m: errors.append(f'CONSOLE-{m.type}: {m.text}') if m.type == 'error' else None)
    page.goto(HTML.as_uri(), wait_until='load')
    page.wait_for_timeout(1500)
    for name in ('overview', 'alerts', 'access', 'config', 'logs'):
        page.click(f'.nav__item[data-page="{name}"]')
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / f'gui_{name}.png'))
    b.close()

if errors:
    print('JS 错误:')
    for e in dict.fromkeys(errors):
        print(' -', e)
    sys.exit(1)
print('5 页截图完成 · 无 JS 错误')
