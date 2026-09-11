# -*- coding: utf-8 -*-
"""探针：真实浏览器打开物料计算器，选中目标产品并抓取渲染结果"""
import json, os, pathlib, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from playwright.sync_api import sync_playwright
from fastapi_app.core.auth.token import create_access_token

TOKEN = create_access_token({'sub': '23', 'username': 'admin'})
BASE = 'http://127.0.0.1:3000'
OUT = pathlib.Path('evidence/bom_calc_probe')
OUT.mkdir(parents=True, exist_ok=True)
NAME = '蛋仔派对》团子木鱼毛绒挂件盲盒'

errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge')
    ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
    ctx.add_cookies([
        {'name': 'access_token', 'value': TOKEN, 'domain': '127.0.0.1', 'path': '/', 'httpOnly': True},
        {'name': 'fastapi_csrf_token', 'value': 'probe-csrf-1234', 'domain': '127.0.0.1', 'path': '/'},
    ])
    ctx.add_init_script(
        "sessionStorage.setItem('fb_auth_user_snapshot_v1', "
        "JSON.stringify({id:23,user_id:23,username:'admin',is_super:true,factory:null,permissions:[]}))"
    )
    page = ctx.new_page()
    page.on('pageerror', lambda e: errors.append(f'PAGEERROR: {e}'))
    page.on('console', lambda m: errors.append(f'CONSOLE-{m.type}: {m.text}') if m.type == 'error' else None)
    page.on('response', lambda r: errors.append(f'HTTP {r.status} {r.url}') if (r.status >= 400 and '/api/' in r.url) else None)

    page.goto(f'{BASE}/material-calculator', wait_until='networkidle')
    page.wait_for_timeout(1500)
    print('URL:', page.url)

    # 通过搜索下拉选中目标产品
    page.fill('input.mc-search-input', '团子木鱼')
    page.wait_for_timeout(1200)
    drop = page.locator('.mc-dropdown-item')
    print('搜索建议条数:', drop.count())
    for i in range(drop.count()):
        print('  建议', i, repr(drop.nth(i).inner_text().replace('\n', ' | ')))
    if drop.count() == 0:
        print('!! 未出现搜索建议')
    else:
        drop.first.click()
        page.wait_for_timeout(800)

    # 设置数量 = 1
    qty = page.locator('input.mc-qty-input')
    print('已选产品行数:', qty.count())
    if qty.count():
        qty.first.fill('1')
        qty.first.dispatch_event('input')
    page.wait_for_timeout(2500)

    res = page.locator('.mc-col-results')
    print('\n===== 计算结果列渲染文本 =====')
    print(res.inner_text())
    page.screenshot(path=str(OUT / 'calculator_result.png'), full_page=True)

    print('\n===== 页面状态徽标 =====')
    print(page.locator('.mc-status-badge').inner_text() if page.locator('.mc-status-badge').count() else '(无)')

    browser.close()

print('\n===== 浏览器侧错误 / 4xx =====')
for e in dict.fromkeys(errors):
    print(' ', e)
