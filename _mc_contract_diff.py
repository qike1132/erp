"""对比「运行中的 5002（陈旧）」与「临时 5102（当前源码）」的 /calculate 响应契约。

手法：在浏览器内走同源路径 `/api/v1/...` 发请求（避开 CORS），
用 page.route 把请求临时改写到目标端口，只取响应 JSON 判契约。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from fastapi_app.core.auth.token import create_access_token  # noqa: E402

TOKEN = create_access_token({'sub': '23'})
CSRF = 'e2e-csrf-9f3a1c77'
SNAP = {'id': 23, 'username': 'admin', 'name': '管理员', 'is_super': True,
        'is_superuser': True, 'roles': ['admin'], 'permissions': ['*']}

PRODUCT_ID = 20588
QTY = 10


def probe(page, port: int) -> dict:
    pattern = '**/api/v1/purchase-center/calculate'
    captured: dict = {}

    def handler(route):
        req = route.request
        headers = dict(req.headers)
        headers.pop('host', None)
        headers.pop('content-length', None)
        resp = route.fetch(url=req.url.replace('127.0.0.1:3000', f'127.0.0.1:{port}'),
                           headers=headers, method='POST', data=req.post_data)
        captured['status'] = resp.status
        captured['body'] = resp.text()
        route.fulfill(response=resp)

    page.route(pattern, handler)
    page.evaluate(
        """async ([pid, qty, csrf]) => {
            await fetch('/api/v1/purchase-center/calculate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
                body: JSON.stringify({ orders: [{ product_id: pid, quantity: qty }] }),
            }).then(r => r.text());
        }""",
        [PRODUCT_ID, QTY, CSRF],
    )
    page.unroute(pattern)
    return captured


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
        page.goto('http://127.0.0.1:3000/', wait_until='domcontentloaded')
        page.wait_for_timeout(1500)

        for label, port in [('运行中 5002（陈旧进程）', 5002),
                            ('临时 5102（当前源码）', 5102)]:
            r = probe(page, port)
            try:
                d = json.loads(r.get('body', '{}'))
            except Exception:  # noqa: BLE001
                d = {}
            print(f'\n=== {label} ===')
            print(f"  HTTP {r.get('status')}")
            print(f"  顶层 keys: {sorted(d.keys())}")
            print(f"  含 groups（新契约）: {'groups' in d}")
            print(f"  含 filling（旧契约）: {'filling' in d}")
            if 'groups' in d:
                print(f"  groups 长度: {len(d['groups'])}")
                for g in d['groups'][:3]:
                    print(f"    - role_id={g.get('role_id')} role_name={g.get('role_name')} "
                          f"qty={g.get('quantity')} "
                          f"fabric={len(g.get('fabric') or [])}")
            print(f"  body 片段: {r.get('body', '')[:200]}")

        b.close()


if __name__ == '__main__':
    main()
