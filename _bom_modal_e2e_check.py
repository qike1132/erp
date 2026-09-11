"""BOM 表配置弹窗「关闭路径」端到端验证：真实 Chromium + 真实坐标点击。

验证目标（需求）：禁止点击遮罩层/弹窗外空白关闭 BOM 配置弹窗；
仅允许 ① 弹窗内关闭按钮 ② 底部「取消」按钮 ③ 保存成功后自动关闭。

覆盖场景：
  1. 点击遮罩左侧空白带   → 弹窗必须保持打开，且命中目标确为遮罩层本身
  2. 点击遮罩右下角空白带 → 弹窗必须保持打开
  3. 弹窗内正文空白处点击 → 弹窗必须保持打开（不得误关）
  4. 编辑中的物料在遮罩连点后仍在（回归用户真实痛点：误触丢失配置）
  5. Esc 键               → 弹窗必须保持打开
  6. 弹窗内关闭按钮       → 正常关闭
  7. 底部「取消」按钮     → 正常关闭
  8. 保存 BOM 成功        → 自动关闭

前置：dev server 运行在 127.0.0.1:5199（npx vite --port 5199 --host 127.0.0.1）。
"""
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright, Route

BASE = 'http://127.0.0.1:5199'
TARGET = f'{BASE}/product'
SHOT_DIR = pathlib.Path('evidence/bom_modal_e2e')
SHOT_DIR.mkdir(parents=True, exist_ok=True)

BOM_URL_MARK = '/purchase-center/product/1/bom'
OVERLAY = '.pd-overlay:has(.bom-modal-dialog)'
DIALOG = '.bom-modal-dialog'

saved_payloads: list[dict] = []
js_errors: list[str] = []
failed: list[str] = []


def check(name: str, ok: bool, detail: str = '') -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f' — {detail}' if detail else ''))
    if not ok:
        failed.append(name)


def hit_target_is_overlay(page) -> tuple[bool, str]:
    """确认坐标处的最顶层元素确实是遮罩层本身（而非被弹窗或其它浮层覆盖）"""
    return page.evaluate(
        """([x, y]) => {
            const el = document.elementFromPoint(x, y);
            if (!el) return [false, 'null'];
            const overlay = el.classList && el.classList.contains('pd-overlay');
            const inDialog = !!el.closest('.bom-modal-dialog');
            return [overlay && !inDialog, el.className || el.tagName];
        }""",
        [20, 540],
    )


with sync_playwright() as p:
    # 本机未下载 playwright 专属内核，复用系统 Edge（Chromium 内核）
    browser = p.chromium.launch(channel='msedge')
    context = browser.new_context(viewport={'width': 1920, 'height': 1080})
    page = context.new_page()
    page.on('pageerror', lambda e: js_errors.append(f'PAGEERROR: {e}'))
    page.on(
        'console',
        lambda m: js_errors.append(f'CONSOLE: {m.text}') if m.type == 'error' else None,
    )

    def route_api(route: Route) -> None:
        url = route.request.url
        method = route.request.method
        if BOM_URL_MARK in url:
            if method == 'POST':
                try:
                    saved_payloads.append(json.loads(route.request.post_data or '{}'))
                except Exception:
                    saved_payloads.append({})
                route.fulfill(
                    status=200,
                    content_type='application/json',
                    body=json.dumps({'success': True}),
                )
            else:
                route.fulfill(
                    status=200,
                    content_type='application/json',
                    body=json.dumps({'success': True, 'product': {'roles': []}, 'materials': []}),
                )
        elif '/auth/me' in url:
            route.fulfill(
                status=200,
                content_type='application/json',
                body=json.dumps(
                    {'success': True, 'user': {'id': 1, 'username': 'e2e', 'is_super': True, 'factory': None, 'permissions': []}}
                ),
            )
        elif '/products/list' in url:
            route.fulfill(
                status=200,
                content_type='application/json',
                body=json.dumps(
                    {
                        'items': [
                            {
                                'id': 1,
                                'name': 'E2E产品',
                                'barcode': '6900000000001',
                                'price': 9.9,
                                'image': None,
                                'factory': '东莞',
                                'current_stock': 3,
                            }
                        ],
                        'total': 1,
                    }
                ),
            )
        elif 'nav-sections' in url or 'nav_sections' in url:
            route.fulfill(status=200, content_type='application/json', body='[]')
        else:
            route.fulfill(
                status=200,
                content_type='application/json',
                body=json.dumps({'success': True, 'items': [], 'total': 0}),
            )

    page.route('**/api/v1/**', route_api)
    page.add_init_script(
        "sessionStorage.setItem('fb_auth_user_snapshot_v1', "
        "JSON.stringify({id:1,username:'e2e',is_super:true,factory:null,permissions:[]}));"
    )

    def open_bom() -> None:
        page.click('.pd-act-bom')
        page.wait_for_selector(DIALOG, timeout=10000)
        page.wait_for_timeout(500)

    def visible() -> bool:
        return page.locator(DIALOG).is_visible()

    page.goto(TARGET, wait_until='domcontentloaded')
    page.wait_for_selector('.pd-act-bom', timeout=20000)
    page.wait_for_timeout(800)

    # ---------- 场景 1：遮罩左侧空白带 ----------
    print('\n[场景 1] 点击遮罩左侧空白带（弹窗外）')
    open_bom()
    ok_hit, cls = hit_target_is_overlay(page)
    check('点击坐标命中遮罩层本身（非弹窗/其它浮层）', ok_hit, str(cls))
    page.locator(OVERLAY).click(position={'x': 20, 'y': 540})
    page.wait_for_timeout(600)
    check('弹窗保持打开', visible())
    page.screenshot(path=str(SHOT_DIR / '1_mask_left_click.png'))

    # ---------- 场景 2：遮罩右下角空白带 ----------
    print('\n[场景 2] 点击遮罩右下角空白带（弹窗外）')
    page.locator(OVERLAY).click(position={'x': 1900, 'y': 1060})
    page.wait_for_timeout(600)
    check('弹窗保持打开', visible())
    page.screenshot(path=str(SHOT_DIR / '2_mask_corner_click.png'))

    # ---------- 场景 3 + 4：编辑中连点遮罩，配置不丢 ----------
    print('\n[场景 3/4] 编辑物料后连点遮罩，「未保存配置」必须仍在')
    page.locator('.bom-btn-add-v2').click()
    page.wait_for_timeout(400)
    rows = page.locator('.bom-table-v2 tbody tr')
    check('添加物料后表格出现', rows.count() == 1, f'实际 {rows.count()} 行')
    page.fill('input[name="material-name"]', 'E2E面料')
    page.fill('input[name="specification"]', '40支')
    page.fill('input[name="supplier-name"]', 'E2E供应商')
    page.wait_for_timeout(300)
    # 弹窗内正文空白处点击（弹窗底边内侧，避开所有控件）
    page.locator('.bom-modal-footer').click(position={'x': 120, 'y': 10})
    page.locator(OVERLAY).click(position={'x': 20, 'y': 540})
    page.locator(OVERLAY).click(position={'x': 1900, 'y': 1060})
    page.wait_for_timeout(600)
    check('弹窗保持打开', visible())
    name_val = page.locator('input[name="material-name"]').input_value()
    spec_val = page.locator('input[name="specification"]').input_value()
    check(
        '编辑中的物料未丢失',
        name_val == 'E2E面料' and spec_val == '40支',
        f'名称="{name_val}" 规格="{spec_val}"',
    )
    page.screenshot(path=str(SHOT_DIR / '3_after_mask_clicks_data_kept.png'))

    # ---------- 场景 5：Esc 键 ----------
    print('\n[场景 5] Esc 键（不得关闭）')
    page.keyboard.press('Escape')
    page.wait_for_timeout(600)
    check('弹窗保持打开', visible())

    # ---------- 场景 6：弹窗内关闭按钮 ----------
    print('\n[场景 6] 弹窗内关闭按钮（应关闭）')
    page.click(f'{DIALOG} .bom-modal-close')
    page.wait_for_timeout(600)
    check('弹窗已关闭', not visible())

    # ---------- 场景 7：底部「取消」按钮 ----------
    print('\n[场景 7] 底部「取消」按钮（应关闭）')
    open_bom()
    check('重新打开成功', visible())
    page.click(f'{DIALOG} .bom-btn-cancel')
    page.wait_for_timeout(600)
    check('弹窗已关闭', not visible())

    # ---------- 场景 8：保存成功自动关闭 ----------
    print('\n[场景 8] 保存 BOM 成功（应自动关闭）')
    open_bom()
    page.locator('.bom-btn-add-v2').click()
    page.wait_for_timeout(400)
    page.fill('input[name="material-name"]', 'E2E面料')
    page.fill('input[name="specification"]', '40支')
    page.fill('input[name="supplier-name"]', 'E2E供应商')
    page.wait_for_timeout(300)
    page.click(f'{DIALOG} .bom-btn-save')
    page.wait_for_timeout(1200)
    check('保存请求已发出', len(saved_payloads) == 1, f'实际 {len(saved_payloads)} 次')
    check('保存成功后弹窗关闭', not visible())
    page.screenshot(path=str(SHOT_DIR / '4_saved_and_closed.png'))

    browser.close()

print(f'\n保存请求累计 {len(saved_payloads)} 次')
if js_errors:
    print('前端 JS 错误:')
    for e in dict.fromkeys(js_errors):
        print('  -', e)
if failed:
    print(f'失败 {len(failed)} 项: ' + '; '.join(failed))
    sys.exit(1)
print('全部通过 · 截图见 evidence/bom_modal_e2e/')
