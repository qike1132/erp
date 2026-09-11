# -*- coding: utf-8 -*-
"""探针：真实浏览器打开产品页 BOM 配置弹窗，抓取「录入页看到的 BOM」"""
import os, pathlib, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from playwright.sync_api import sync_playwright
from fastapi_app.core.auth.token import create_access_token

TOKEN = create_access_token({'sub': '23', 'username': 'admin'})
BASE = 'http://127.0.0.1:3000'
OUT = pathlib.Path('evidence/bom_calc_probe')
OUT.mkdir(parents=True, exist_ok=True)
KEY = '团子木鱼'

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

    page.goto(f'{BASE}/product', wait_until='networkidle')
    page.wait_for_timeout(1500)
    print('URL:', page.url)

    # 搜索目标产品
    inp = page.locator('.pd-col-actions input')
    inp.fill(KEY)
    inp.press('Enter')
    page.wait_for_timeout(2000)

    rows = page.locator('table tbody tr')
    print('表格行数:', rows.count())
    target = None
    for i in range(rows.count()):
        txt = rows.nth(i).inner_text()
        if KEY in txt:
            target = rows.nth(i)
            print('命中行:', txt.replace('\n', ' | '))
            break
    if target is None:
        print('!! 未找到目标产品行')
        page.screenshot(path=str(OUT / 'product_list.png'), full_page=True)
        browser.close()
        sys.exit(1)

    target.locator('.pd-act-bom').click()
    page.wait_for_timeout(2000)

    modal = page.locator('.bom-modal-dialog')
    print('\n弹窗可见:', modal.is_visible())

    # 角色 chip 列表
    chips = page.locator('.bom-role-chip')
    print('角色 chip:', [chips.nth(i).inner_text().strip() for i in range(chips.count())])
    print('当前激活 chip:', page.locator('.bom-role-chip.active').inner_text().strip())

    for cat_label in ('面料类', '填充类', '辅料类'):
        page.locator(f'.bom-tab-v2:has-text("{cat_label}")').click()
        page.wait_for_timeout(400)
        summary = page.locator('.bom-summary-text').inner_text().strip()
        cnt = page.locator('.bom-summary-count').inner_text().strip()
        print(f'\n[{cat_label}] 汇总 = {summary} | {cnt}')
        for i in range(rows.count()):
            pass
        tbl = page.locator('.bom-table-v2 tbody tr')
        for i in range(tbl.count()):
            cells = tbl.nth(i).locator('input, select')
            vals = [cells.nth(j).input_value() for j in range(cells.count())]
            print('    ', vals)
    page.screenshot(path=str(OUT / 'product_bom_default_role.png'), full_page=True)

    # 切到「默认BOM」作用域再看一遍
    if page.locator('.bom-role-chip:has-text("默认BOM")').count():
        page.locator('.bom-role-chip:has-text("默认BOM")').click()
        page.wait_for_timeout(400)
        print('\n===== 切到「默认BOM」作用域 =====')
        for cat_label in ('面料类', '填充类', '辅料类'):
            page.locator(f'.bom-tab-v2:has-text("{cat_label}")').click()
            page.wait_for_timeout(400)
            summary = page.locator('.bom-summary-text').inner_text().strip()
            cnt = page.locator('.bom-summary-count').inner_text().strip()
            print(f'\n[{cat_label}] 汇总 = {summary} | {cnt}')
            tbl = page.locator('.bom-table-v2 tbody tr')
            for i in range(tbl.count()):
                cells = tbl.nth(i).locator('input, select')
                vals = [cells.nth(j).input_value() for j in range(cells.count())]
                print('    ', vals)
        page.screenshot(path=str(OUT / 'product_bom_default_scope.png'), full_page=True)
    else:
        print('\n!! 未出现「默认BOM」chip')

    browser.close()

print('\n===== 浏览器侧错误 =====')
for e in dict.fromkeys(errors):
    print(' ', e)
