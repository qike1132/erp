"""复现：物料计算器输入数量后前端不显示计算结果。

做法：真实浏览器（Edge）登录后打开 /material-calculator，
选一个有 BOM 的产品 → 输入数量 → 观察
  ① 网络请求（/purchase-center/calculate）是否发出、状态码、响应体
  ② 页面是否出现 .mc-scope-card
  ③ console 报错
不 mock 任何接口，直接打真实后端，拿到第一手证据。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from fastapi_app.core.auth.token import create_access_token  # noqa: E402

BASE = 'http://127.0.0.1:3000'
TOKEN = create_access_token({'sub': '23'})
CSRF = 'e2e-csrf-9f3a1c77'
SNAP = {'id': 23, 'username': 'admin', 'name': '管理员', 'is_super': True,
        'is_superuser': True, 'roles': ['admin'], 'permissions': ['*']}

calc_calls: list[dict] = []
console_msgs: list[str] = []
page_errors: list[str] = []


def main() -> None:
    with sync_playwright() as p:
        b = p.chromium.launch(channel='msedge', headless=True)
        ctx = b.new_context(viewport={'width': 1600, 'height': 900})
        ctx.add_cookies([
            {'name': 'access_token', 'value': TOKEN, 'domain': '127.0.0.1', 'path': '/'},
            {'name': 'fastapi_csrf_token', 'value': CSRF, 'domain': '127.0.0.1', 'path': '/'},
        ])
        ctx.add_init_script(
            f"sessionStorage.setItem('fb_auth_user_snapshot_v1', {json.dumps(json.dumps(SNAP))});")
        page = ctx.new_page()
        page.on('console', lambda m: console_msgs.append(f'[{m.type}] {m.text}'))
        page.on('pageerror', lambda e: page_errors.append(str(e)))

        def on_resp(r):
            if 'calculate' in r.url:
                body = ''
                try:
                    body = r.text()[:600]
                except Exception as exc:  # noqa: BLE001
                    body = f'<read fail: {exc}>'
                calc_calls.append({'url': r.url, 'status': r.status, 'body': body})

        page.on('response', on_resp)

        page.goto(f'{BASE}/material-calculator', wait_until='domcontentloaded')
        page.wait_for_timeout(3000)
        page.screenshot(path='evidence/mc_calc_repro/00_initial.png')

        print('=== 初始状态 ===')
        print('  .mc-scope-card 数 =', page.locator('.mc-scope-card').count())
        print('  .mc-product-item 数 =', page.locator('.mc-product-item').count())

        # 选第一个「有BOM」的产品（无 BOM 的项点击无效）
        prod = page.locator('.mc-product-item.has-bom, .mc-product-item:not(.disabled)').first
        print('  候选产品数:', prod.count())
        if prod.count():
            prod.click()
            page.wait_for_timeout(1200)
            page.screenshot(path='evidence/mc_calc_repro/01_after_select.png')
            print('  选后 .mc-order-item 行数 =', page.locator('.mc-order-item').count())

        # 输入数量
        qty = page.locator('.mc-qty-input').first
        if qty.count():
            qty.fill('10')
            page.wait_for_timeout(2500)
            page.screenshot(path='evidence/mc_calc_repro/02_after_qty.png')
            print('  输入数量后 .mc-scope-card 数 =', page.locator('.mc-scope-card').count())

        print('\n=== /calculate 请求 ===')
        if not calc_calls:
            print('  (无请求发出)')
        for c in calc_calls:
            print(f"  status={c['status']} url={c['url']}")
            print(f"  body={c['body']}")

        print('\n=== 页面错误 ===')
        for e in page_errors:
            print('  PAGEERROR:', e)
        print('\n=== console 中的 error/warning ===')
        for m in console_msgs:
            if m.startswith('[error]') or m.startswith('[warning]'):
                print('  ', m[:300])

        b.close()


if __name__ == '__main__':
    Path('evidence/mc_calc_repro').mkdir(parents=True, exist_ok=True)
    main()
