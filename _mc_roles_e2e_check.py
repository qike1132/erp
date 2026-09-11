# -*- coding: utf-8 -*-
"""物料计算器「多角色 SKU：单一总数量录入 + 按 BOM 作用域分组结果」端到端验证。

覆盖桌面端与移动端两条真实浏览器路径：
  1. 桌面端：搜产品 → 只出现 1 个数量输入 → 自动计算 → 出现 2 个作用域卡
  2. 移动端：顶部搜索触发器可打开弹层 → 添加产品 → 手点「计算」→ 同样 2 个作用域卡

前置：
  前端 dev server  http://127.0.0.1:5199
  临时后端          http://127.0.0.1:5102
验证对象：产品 20588「蛋仔派对》团子木鱼毛绒挂件盲盒」
         —— 作用域 = 默认BOM(role_id=None) + 该产品的角色 BOM（角色名取自生产数据）
"""
import json
import os
import pathlib
import sys

from playwright.sync_api import sync_playwright, Route, BrowserContext

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from fastapi_app.core.auth.token import create_access_token

FRONT = os.environ.get('MC_E2E_FRONT', 'http://127.0.0.1:5199')
BACK = os.environ.get('MC_E2E_BACK', 'http://127.0.0.1:5102')
KEYWORD = '团子木鱼'
TOTAL_QTY = 10
SHOT = pathlib.Path('evidence/mc_roles_e2e')
SHOT.mkdir(parents=True, exist_ok=True)

# 与 middleware 的 CSRF 校验一致：cookie 与 header 必须逐字节相等
TOKEN = create_access_token({'sub': '23'})
CSRF = 'e2e-csrf-9f3a1c77'
COOKIE_HDR = f'access_token={TOKEN}; fastapi_csrf_token={CSRF}'

results: list[tuple[str, bool, str]] = []
js_errors: list[str] = []


def check(name: str, ok: bool, detail: str = '') -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f' — {detail}' if detail else ''))
    results.append((name, ok, detail))


def build_context(browser, *, mobile: bool) -> BrowserContext:
    kwargs = dict(
        viewport={'width': 390, 'height': 844} if mobile else {'width': 1600, 'height': 950},
        device_scale_factor=2 if mobile else 1,
    )
    if mobile:
        kwargs['user_agent'] = (
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 '
            '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
        )
        kwargs['is_mobile'] = True
        kwargs['has_touch'] = True
    ctx = browser.new_context(**kwargs)
    ctx.add_cookies([
        {'name': 'access_token', 'value': TOKEN, 'domain': '127.0.0.1', 'path': '/'},
        {'name': 'fastapi_csrf_token', 'value': CSRF, 'domain': '127.0.0.1', 'path': '/'},
    ])
    ctx.add_init_script(
        "sessionStorage.setItem('fb_auth_user_snapshot_v1', "
        "JSON.stringify({id:23,username:'e2e-admin',is_super:true,factory:null,permissions:[]}));"
    )
    return ctx


def attach_routes(page) -> None:
    """把 /api/v1/** 原样转发到临时后端（Cookie 认证），并在页面上收集 JS 错误。"""

    def route_api(route: Route) -> None:
        headers = dict(route.request.headers)
        headers.pop('host', None)
        headers.pop('content-length', None)
        headers['cookie'] = COOKIE_HDR
        headers['x-csrf-token'] = CSRF
        target = route.request.url.replace(FRONT, BACK)
        try:
            resp = route.fetch(url=target, headers=headers)
            route.fulfill(response=resp)
        except Exception as exc:  # noqa: BLE001 — 代理失败必须显式暴露，不能静默放行
            route.fulfill(status=502, content_type='application/json',
                          body=json.dumps({'detail': f'e2e proxy error: {exc}'}))

    page.route('**/api/v1/**', route_api)
    page.on('pageerror', lambda e: js_errors.append(f'PAGEERROR: {e}'))
    page.on('console',
            lambda m: js_errors.append(f'CONSOLE: {m.text}') if m.type == 'error' else None)


# 空分类块由 v-show 隐藏（display:none），读快照时必须过滤，否则会把空块当成有数据


def scope_snapshot(page) -> list[dict]:
    """读取当前渲染出的作用域卡：名称 / 产品 / 数量 / 各分类条数（仅统计可见分类块）。"""
    return page.evaluate(
        """() => {
        const vis = el => el.offsetParent !== null;
        return Array.from(document.querySelectorAll('.mc-scope-card')).map(card => {
            const cats = {};
            card.querySelectorAll('.mc-category-block').forEach(b => {
                if (!vis(b)) return;
                const label = (b.querySelector('.mc-cat-label')?.textContent || '').trim();
                const count = (b.querySelector('.mc-cat-count')?.textContent || '').trim();
                cats[label] = count;
            });
            const prod = (card.querySelector('.mc-scope-product')?.textContent || '').trim();
            const qty = (card.querySelector('.mc-scope-qty')?.textContent || '').trim();
            return {
                name: (card.querySelector('.mc-scope-name')?.textContent || '').trim(),
                product: prod,
                qty,
                cats,
                // 只取标题 + 可见表格，避免把隐藏块的表头文字混进内容断言
                text: ([prod, qty].join(' ') + ' ' + Array.from(
                    card.querySelectorAll('.mc-category-block')).filter(vis)
                    .map(b => (b.textContent || '').replace(/\\s+/g, ' ').trim()).join(' ')).trim(),
            };
        });
        }""",
    )


def mobile_scope_snapshot(page) -> list[dict]:
    return page.evaluate(
        """() => {
        const vis = el => el.offsetParent !== null;
        return Array.from(document.querySelectorAll('.m-scope-card')).map(card => {
            const cats = [];
            card.querySelectorAll('.m-result-group').forEach(b => {
                if (!vis(b)) return;
                const label = (b.querySelector('.m-result-cat span')?.textContent || '').trim();
                if (label) cats.push(label);
            });
            const prod = (card.querySelector('.m-scope-product')?.textContent || '').trim();
            const qty = (card.querySelector('.m-scope-qty')?.textContent || '').trim();
            return {
                name: (card.querySelector('.m-scope-name')?.textContent || '').trim(),
                product: prod,
                qty,
                cats,
                text: ([prod, qty].join(' ') + ' ' + Array.from(
                    card.querySelectorAll('.m-result-group')).filter(vis)
                    .map(b => (b.textContent || '').replace(/\\s+/g, ' ').trim()).join(' ')).trim(),
            };
        });
        }""",
    )


def add_product_via_search(page, input_sel: str, item_sel: str) -> None:
    page.fill(input_sel, KEYWORD)
    page.wait_for_selector(item_sel, timeout=15000)
    page.click(item_sel)


# ==================== 桌面端 ====================
def run_desktop(browser) -> None:
    print('\n[桌面端] 单数量录入 + 按角色分组结果')
    ctx = build_context(browser, mobile=False)
    page = ctx.new_page()
    attach_routes(page)

    page.goto(f'{FRONT}/material-calculator', wait_until='domcontentloaded')
    page.wait_for_selector('.mc-search-input', timeout=30000)
    page.wait_for_timeout(500)

    check('进入 PC 端三列布局', page.locator('.mc-col-orders').count() == 1)

    add_product_via_search(page, '.mc-search-input', '.mc-dropdown-item')
    page.wait_for_selector('.mc-order-item', timeout=10000)

    line_count = page.locator('.mc-order-item').count()
    check('已选列表只生成 1 行（不按角色拆行）', line_count == 1, f'实际 {line_count} 行')
    qty_inputs = page.locator('.mc-order-item .mc-qty-input').count()
    check('只提供 1 个数量输入项', qty_inputs == 1, f'实际 {qty_inputs} 个')
    check('页面提示「总数量 / 按默认BOM+各角色计算」',
          '总数量' in (page.locator('.mc-order-hint').inner_text() or ''))

    page.fill('.mc-order-item .mc-qty-input', str(TOTAL_QTY))
    page.wait_for_timeout(1200)

    page.wait_for_selector('.mc-scope-card', timeout=15000)
    snaps = scope_snapshot(page)
    check('结果拆成 2 个作用域块', len(snaps) == 2, f'实际 {len(snaps)} 块')
    if len(snaps) == 2:
        check('第 1 块为默认BOM', snaps[0]['name'] == '默认BOM', snaps[0]['name'])
        # 角色名属生产数据，可能被改名（曾由「呼汇」改成「黄蛋」）→ 只断言"它是角色作用域"，
        # 不硬编码具体名字，避免数据变更造成假失败。
        check('第 2 块为角色作用域（非默认BOM）',
              snaps[1]['name'] != '默认BOM', snaps[1]['name'])
        check('两块都标注产品名与总数量 10 件',
              all(s['product'] and s['qty'] == f'{TOTAL_QTY} 件' for s in snaps),
              ' / '.join(f"{s['name']}:{s['qty']}" for s in snaps))
        check('默认BOM 分类齐全（填充1/面料7/辅料1）',
              snaps[0]['cats'] == {'填充类': '(1 项)', '面料类': '(7 项)', '辅料类': '(1 项)'},
              json.dumps(snaps[0]['cats'], ensure_ascii=False))
        check('角色作用域只含面料类 1 项',
              snaps[1]['cats'] == {'面料类': '(1 项)'},
              json.dumps(snaps[1]['cats'], ensure_ascii=False))
        # 每个作用域都按「总数量」计算：默认BOM 超柔 0.01×10=0.1；角色作用域 哈哈 1×10=10
        check('默认BOM 用量按总数量计算（超柔 0.1）',
              '超柔' in snaps[0]['text'] and '0.1 码' in snaps[0]['text'], snaps[0]['text'][:160])
        check('角色作用域同样按总数量计算（哈哈 10）',
              '哈哈' in snaps[1]['text'] and '10 码' in snaps[1]['text'], snaps[1]['text'][:160])

    page.screenshot(path=str(SHOT / 'desktop_grouped.png'), full_page=True)

    if len(snaps) == 2:
        # 逐个作用域单独截图，便于核对每个角色各自的 BOM 明细
        page.locator('.mc-scope-card').nth(0).screenshot(path=str(SHOT / 'desktop_scope_default.png'))
        page.locator('.mc-scope-card').nth(1).screenshot(path=str(SHOT / 'desktop_scope_role.png'))
        # 折叠状态按「作用域 + 分类」隔离：折叠默认BOM的面料类，不应连带收起角色作用域的面料类
        card0 = page.locator('.mc-scope-card').nth(0)
        card1 = page.locator('.mc-scope-card').nth(1)
        fabric0 = card0.locator('.mc-cat-fabric').locator('.mc-category-table')
        fabric1 = card1.locator('.mc-cat-fabric').locator('.mc-category-table')
        check('两块的面料类初始均展开', fabric0.is_visible() and fabric1.is_visible())
        card0.locator('.mc-cat-fabric > .mc-category-header').click()
        page.wait_for_timeout(400)
        check('折叠「默认BOM·面料类」后该表收起', not fabric0.is_visible())
        check('「角色作用域·面料类」不受联动影响（仍展开）', fabric1.is_visible())
        page.locator('.mc-result-content').screenshot(
            path=str(SHOT / 'desktop_collapse_isolation.png'))

    ctx.close()


# ==================== 移动端 ====================
def run_mobile(browser) -> None:
    print('\n[移动端] 搜索触发器 + 手点计算 + 分组结果')
    ctx = build_context(browser, mobile=True)
    page = ctx.new_page()
    attach_routes(page)

    page.goto(f'{FRONT}/material-calculator', wait_until='domcontentloaded')
    page.wait_for_selector('.m-search-trigger', timeout=30000)

    check('移动端进入移动布局', page.locator('.m-nav-btn').count() == 1)
    check('顶部为可点击搜索触发器（可打开弹层）',
          page.locator('.m-search-trigger').is_visible())

    page.click('.m-search-trigger')
    page.wait_for_selector('.m-sheet-body .m-search-input', timeout=8000)
    page.wait_for_timeout(400)

    # 弹层内搜索并添加
    sheet_input = page.locator('.m-sheet-body .m-search-input').first
    sheet_input.fill(KEYWORD)
    page.wait_for_selector('.m-list-item', timeout=15000)
    page.click('.m-list-item')
    page.wait_for_timeout(500)

    check('已选列表只生成 1 行（不按角色拆行）', page.locator('.m-calc-item').count() == 1,
          f"实际 {page.locator('.m-calc-item').count()} 行")
    check('只提供 1 个数量输入项', page.locator('.m-calc-item .m-qty-input').count() == 1)
    check('页面提示「总数量 / 按默认BOM+各角色计算」',
          '总数量' in (page.locator('.m-hint').inner_text() or ''))

    # 回归：右上角全局通知铃铛是 fixed 悬浮层，不能盖住导航栏的「计算」按钮
    overlap = page.evaluate(
        """() => {
            const btn = document.querySelector('.m-nav-btn');
            const bell = document.querySelector('.m-nb-root');
            if (!btn) return { err: 'no calc button' };
            if (!bell) return { ok: true, noBell: true };
            const a = btn.getBoundingClientRect(), b = bell.getBoundingClientRect();
            const x = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
            const y = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
            return { ok: x * y === 0, overlapArea: Math.round(x * y) };
        }""",
    )
    check('「计算」按钮与通知铃铛无重叠', overlap.get('ok') is True,
          json.dumps(overlap, ensure_ascii=False))
    # 用真实点击（非 force）验证：若仍被悬浮层遮挡，Playwright 会命中间隔层而失败
    page.locator('.m-nav-btn').click(timeout=8000)
    check('「计算」按钮可被真实点击（无遮挡）', True)

    page.fill('.m-calc-item .m-qty-input', str(TOTAL_QTY))
    # 自动重算：改数量后无需手点导航栏「计算」，结果区应自行出现
    page.wait_for_selector('.m-scope-card', timeout=10000)
    check('改数量后自动重算（无需手点「计算」）', page.locator('.m-scope-card').count() == 2,
          f"实际 {page.locator('.m-scope-card').count()} 块")
    # 手点「计算」仍可用（保留显式触发入口）
    page.locator('.m-nav-btn').click()
    page.wait_for_timeout(1200)

    page.wait_for_selector('.m-scope-card', timeout=15000)
    snaps = mobile_scope_snapshot(page)
    check('结果拆成 2 个作用域块', len(snaps) == 2, f'实际 {len(snaps)} 块')
    if len(snaps) == 2:
        check('第 1 块为默认BOM', snaps[0]['name'] == '默认BOM', snaps[0]['name'])
        # 角色名属生产数据，可能被改名（曾由「呼汇」改成「黄蛋」）→ 只断言"它是角色作用域"，
        # 不硬编码具体名字，避免数据变更造成假失败。
        check('第 2 块为角色作用域（非默认BOM）',
              snaps[1]['name'] != '默认BOM', snaps[1]['name'])
        check('两块都标注总数量 10 件',
              all(s['qty'] == f'{TOTAL_QTY} 件' for s in snaps),
              ' / '.join(f"{s['name']}:{s['qty']}" for s in snaps))
        check('默认BOM 含填充/面料/辅料三类',
              all(k in ' '.join(snaps[0]['cats']) for k in ('填充类', '面料类', '辅料类')),
              ' '.join(snaps[0]['cats']))
        check('角色作用域只含面料类', '面料类' in ' '.join(snaps[1]['cats'])
              and '填充类' not in ' '.join(snaps[1]['cats']),
              ' '.join(snaps[1]['cats']))
        # 每个作用域都按「总数量」计算：默认BOM 超柔 0.01×10=0.1；角色作用域 哈哈 1×10=10
        check('默认BOM 用量按总数量计算（超柔 0.1）',
              '超柔' in snaps[0]['text'] and '0.1 码' in snaps[0]['text'], snaps[0]['text'][:160])
        check('角色作用域同样按总数量计算（哈哈 10）',
              '哈哈' in snaps[1]['text'] and '10 码' in snaps[1]['text'], snaps[1]['text'][:160])

    page.screenshot(path=str(SHOT / 'mobile_grouped.png'), full_page=True)
    ctx.close()


with sync_playwright() as p:
    # 本机无 playwright 专属内核，复用系统 Edge
    browser = p.chromium.launch(channel='msedge')
    try:
        run_desktop(browser)
        run_mobile(browser)
    finally:
        browser.close()

failed = [n for n, ok, _ in results if not ok]
print(f'\n共 {len(results)} 项断言，失败 {len(failed)} 项')
if js_errors:
    print('前端 JS 错误:')
    for e in dict.fromkeys(js_errors):
        print('  -', e)
if failed:
    print('失败项: ' + '; '.join(failed))
    sys.exit(1)
print(f'全部通过 · 截图见 {SHOT}/')
