# -*- coding: utf-8 -*-
"""移动端物料计算器：确认本次改动未引入渲染/引用错误"""
import os, pathlib, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from playwright.sync_api import sync_playwright
from fastapi_app.core.auth.token import create_access_token

TOKEN = create_access_token({'sub': '23', 'username': 'admin'})
FRONT = 'http://127.0.0.1:5199'
BACK = 'http://127.0.0.1:5102'
OUT = pathlib.Path('evidence/bom_calc_scope')

errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge')
    ctx = browser.new_context(**p.devices['iPhone 13'])
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
    page.route('**/api/v1/**', lambda route: route.fulfill(response=route.fetch(url=route.request.url.replace(f'{FRONT}/api/', f'{BACK}/api/'))))

    page.goto(f'{FRONT}/material-calculator', wait_until='networkidle')
    page.wait_for_timeout(2000)
    body = page.locator('.m-page').inner_text()
    print('URL:', page.url)
    print('页面文本:', body.replace('\n', ' | ')[:200])
    print('渲染移动端布局:', page.locator('.m-page').count() == 1)
    page.screenshot(path=str(OUT / 'mobile_calculator.png'))
    browser.close()

print('\n===== 浏览器侧错误 =====')
print('  (无)' if not errors else '')
for e in dict.fromkeys(errors):
    print(' ', e)
