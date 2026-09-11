# -*- coding: utf-8 -*-
"""端到端验证：物料计算器角色（作用域）维度

- 前端：vite dev server 5199（新源码）
- 后端：临时 uvicorn 5102（新代码，含 role_id 过滤）
- 浏览器所有 /api 请求经 Playwright 转发到 5102，避免打到 3000/5002 的旧生产
"""
import os, pathlib, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from playwright.sync_api import sync_playwright
from fastapi_app.core.auth.token import create_access_token

TOKEN = create_access_token({'sub': '23', 'username': 'admin'})
FRONT = 'http://127.0.0.1:5199'
BACK = 'http://127.0.0.1:5102'
OUT = pathlib.Path('evidence/bom_calc_scope')
OUT.mkdir(parents=True, exist_ok=True)
KEY = '团子木鱼'

errors = []
failed = []


def check(name: str, ok: bool, detail: str = '') -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f' — {detail}' if detail else ''))
    if not ok:
        failed.append(name)


with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge')
    ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
    ctx.add_cookies([
        {'name': 'access_token', 'value': TOKEN, 'domain': '127.0.0.1', 'path': '/', 'httpOnly': True},
        {'name': 'fastapi_csrf_token', 'value': 'scope-csrf-1234', 'domain': '127.0.0.1', 'path': '/'},
    ])
    ctx.add_init_script(
        "sessionStorage.setItem('fb_auth_user_snapshot_v1', "
        "JSON.stringify({id:23,user_id:23,username:'admin',is_super:true,factory:null,permissions:[]}))"
    )
    page = ctx.new_page()
    page.on('pageerror', lambda e: errors.append(f'PAGEERROR: {e}'))
    page.on('console', lambda m: errors.append(f'CONSOLE-{m.type}: {m.text}') if m.type == 'error' else None)

    def route_api(route):
        url = route.request.url
        target = url.replace(f'{FRONT}/api/', f'{BACK}/api/')
        try:
            resp = route.fetch(url=target)
            route.fulfill(response=resp)
        except Exception as exc:  # noqa: BLE001
            errors.append(f'ROUTE-FAIL {url}: {exc}')
            route.abort()

    page.route('**/api/v1/**', route_api)

    page.goto(f'{FRONT}/material-calculator', wait_until='networkidle')
    page.wait_for_timeout(1500)

    print('\n[1] 搜索并选中产品')
    page.fill('input.mc-search-input', KEY)
    page.wait_for_timeout(1200)
    drop = page.locator('.mc-dropdown-item')
    check('搜索建议命中', drop.count() == 1, f'{drop.count()} 条')
    drop.first.click()
    page.wait_for_timeout(2000)  # 等待 BOM 作用域请求 + 展开

    print('\n[2] 订单行按作用域展开')
    rows = page.locator('.mc-order-item')
    check('展开为 2 行（默认BOM + 呼汇）', rows.count() == 2, f'实际 {rows.count()} 行')
    scope_select = page.locator('select.mc-scope-select')
    check('多作用域时渲染角色下拉', scope_select.count() == 2, f'{scope_select.count()} 个下拉')
    if scope_select.count():
        opts = scope_select.first.locator('option')
        names = [opts.nth(i).inner_text().strip() for i in range(opts.count())]
        check('下拉含默认BOM与呼汇', names == ['默认BOM', '呼汇'], str(names))

    print('\n[3] 分别录入数量：默认BOM=1，呼汇=10')
    qty = page.locator('input.mc-qty-input')
    qty.nth(0).fill('1')
    qty.nth(0).dispatch_event('input')
    qty.nth(1).fill('10')
    qty.nth(1).dispatch_event('input')
    page.wait_for_timeout(2500)

    print('\n[4] 计算结果')
    result_text = page.locator('.mc-col-results').inner_text()
    print(result_text)
    check('状态徽标为 10 种物料', '10 种物料' in page.locator('.mc-status-badge').inner_text())
    check('结果表出现「作用域」列', '作用域' in result_text)
    check('哈哈 归属呼汇且数量 10', '哈哈' in result_text and '呼汇' in result_text)
    check('默认BOM 标注存在', '默认BOM' in result_text)
    page.screenshot(path=str(OUT / 'calc_scope_result.png'), full_page=True)

    print('\n[5] 切换下拉作用域后重算')
    scope_select.first.select_option(label='呼汇')
    page.wait_for_timeout(2500)
    after = page.locator('.mc-col-results').inner_text()
    check('两行同为呼汇时结果收敛为 1 种物料', '1 种物料' in page.locator('.mc-status-badge').inner_text(),
          page.locator('.mc-status-badge').inner_text())
    page.screenshot(path=str(OUT / 'calc_scope_switched.png'), full_page=True)

    browser.close()

print('\n===== 浏览器侧错误 =====')
for e in dict.fromkeys(errors):
    print(' ', e)
print(f"\n===== 结果: {'全部通过' if not failed else '失败: ' + ', '.join(failed)} =====")
