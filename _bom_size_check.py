"""BOM 表配置弹窗「尺寸恒定」回归（修复后守卫）。

背景：弹窗原先 `max-height:90vh` + 默认 `height:auto` + body 仅 `min-height:500px`，
导致物料 1 条时约 663px、20 条时约 810px，视觉上「一会大一会小」。

尺寸契约：外框恒定，内容溢出走内部滚动。
    .bom-modal-dialog { height:90vh; min-height:680px; max-height:90vh }
    .bom-modal-body   { flex:1 1 auto; min-height:0; overflow-y:auto }

断言：
1. 弹窗宽/高/垂直位置在 0/1/5/20 条物料下完全一致
2. 高度不超出视口 90%
3. 20 条时 body 内部滚动（而非撑大弹窗）
4. 1 条时不滚动但弹窗不塌陷
5. 空态与 1 条时内容区高度一致（无塌陷感）

用法：
    python _bom_size_check.py
    BOM_SIZE_BASE=http://127.0.0.1:5199 python _bom_size_check.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get('BOM_SIZE_BASE', 'http://127.0.0.1:3000')

sys.path.insert(0, str(Path(__file__).parent))
from fastapi_app.core.auth.token import create_access_token  # noqa: E402

TOKEN = create_access_token({'sub': '23'})
CSRF = 'e2e-csrf-9f3a1c77'
SNAP = {'id': 23, 'username': 'admin', 'name': '管理员', 'is_super': True,
        'is_superuser': True, 'roles': ['admin'], 'permissions': ['*']}

results: list[str] = []
failures: list[str] = []


def check(label: str, ok: bool, actual) -> None:
    line = f"{'PASS' if ok else 'FAIL'} | {label} | 实际={actual}"
    (results if ok else failures).append(line)
    print(line)


def materials(n: int) -> list[dict]:
    return [{
        'id': 900000 + i, 'material_name': f'测试物料{i + 1}',
        'specification': f'规格-{i + 1}', 'unit': '码',
        'supplier_name': f'供应商{i + 1}', 'unit_usage': 1.0 + i,
        'remark': '', 'category': 'fabric', 'role_id': None,
    } for i in range(n)]


def probe(page, n: int) -> dict:
    payload = {'success': True,
               'product': {'id': 20588, 'name': f'产品{n}', 'roles': []},
               'materials': materials(n)}
    pattern = '**/api/v1/**/product/*/bom'
    page.route(pattern, lambda r: r.fulfill(
        status=200, content_type='application/json',
        body=json.dumps(payload, ensure_ascii=False)))
    page.locator('.pd-act-bom').first.click()
    page.wait_for_timeout(900)
    m = page.evaluate("""() => {
        const box = el => { if (!el) return null; const b = el.getBoundingClientRect();
            return { w: Math.round(b.width), h: Math.round(b.height),
                     top: Math.round(b.top), bottom: Math.round(b.bottom) }; };
        const d = document.querySelector('.bom-modal-dialog');
        const body = document.querySelector('.bom-modal-body');
        const area = document.querySelector('.bom-content-area');
        const vh = window.innerHeight;
        return {
            dialog: box(d), body: box(body), area: box(area),
            viewportH: vh,
            bodyScrollH: body ? body.scrollHeight : null,
            bodyClientH: body ? body.clientHeight : null,
            bodyScrollable: body ? body.scrollHeight > body.clientHeight + 1 : null,
        };
    }""")
    try:
        page.locator('.bom-modal-close').click(timeout=3000)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(400)
    page.unroute(pattern)
    return m


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
        page.goto(f'{BASE}/product', wait_until='domcontentloaded')
        page.wait_for_timeout(2500)

        data = {}
        for n in (0, 1, 5, 20):
            data[n] = probe(page, n)
            d, bd = data[n]['dialog'], data[n]['body']
            print(f'  {n:>2} 条 → dialog={d["w"]}x{d["h"]} top={d["top"]} '
                  f'bodyScroll={data[n]["bodyScrollH"]}/{data[n]["bodyClientH"]} '
                  f'scrollable={data[n]["bodyScrollable"]}')

        heights = {n: v['dialog']['h'] for n, v in data.items()}
        widths = {n: v['dialog']['w'] for n, v in data.items()}
        tops = {n: v['dialog']['top'] for n, v in data.items()}

        check('弹窗宽度恒定（不随物料数变化）', len(set(widths.values())) == 1, widths)
        check('弹窗高度恒定（不随物料数变化）', len(set(heights.values())) == 1, heights)
        check('弹窗垂直位置恒定（不上下跳动）', len(set(tops.values())) == 1, tops)

        vh = data[20]['viewportH']
        check('弹窗高度未超出视口 90%（h<=0.9*vh+2）',
              heights[20] <= 0.9 * vh + 2, f'h={heights[20]} vh={vh}')

        check('20 条物料时 body 内部滚动（而非撑大弹窗）',
              data[20]['bodyScrollable'] is True,
              f'{data[20]["bodyScrollH"]}/{data[20]["bodyClientH"]}')

        check('1 条物料时 body 不滚动但弹窗不塌陷',
              data[1]['bodyScrollable'] is False and heights[1] == heights[20],
              f'scrollable={data[1]["bodyScrollable"]} h={heights[1]}')

        check('空态与 1 条时内容区下沿一致（无塌陷感）',
              data[0]['area']['h'] == data[1]['area']['h'],
              f"empty={data[0]['area']['h']} one={data[1]['area']['h']}")

        b.close()

    print('\n' + '=' * 70)
    print(f'共 {len(results) + len(failures)} 项断言，失败 {len(failures)} 项')
    for f in failures:
        print('  ' + f)
    if failures:
        sys.exit(1)


if __name__ == '__main__':
    main()
