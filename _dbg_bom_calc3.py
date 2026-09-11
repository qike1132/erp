# -*- coding: utf-8 -*-
"""诊断 3：走真实 HTTP 接口对比『录入页 BOM』与『计算器 BOM』（含中间件与缓存）"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

import urllib.request

from fastapi_app.core.auth.token import create_access_token

TOKEN = create_access_token({'sub': '23', 'username': 'admin'})
BASE = 'http://127.0.0.1:5002/api/v1'
PID = 20588


def call(method, path, body=None):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        headers={
            'Authorization': f'Bearer {TOKEN}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        },
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:500]


print('=' * 72)
print('【A】录入页 BOM 接口  GET /purchase-center/product/{id}/bom')
print('=' * 72)
st, res = call('GET', f'/purchase-center/product/{PID}/bom')
print('HTTP', st)
if isinstance(res, dict):
    print('roles =', (res.get('product') or {}).get('roles'))
    mats = res.get('materials') or []
    print(f'materials 共 {len(mats)} 条')
    for m in mats:
        print(f"  id={m.get('id')!s:<6} role_id={m.get('role_id')!s:<6} cat={m.get('category')!r:<12} "
              f"name={m.get('material_name')!r:<16} usage={m.get('unit_usage')} unit={m.get('unit')!r}")
else:
    print(res)

print()
print('=' * 72)
print('【B】计算器接口  POST /purchase-center/calculate')
print('=' * 72)
st, res = call('POST', '/purchase-center/calculate', {'orders': [{'product_id': PID, 'quantity': 1}]})
print('HTTP', st)
if isinstance(res, dict):
    n = 0
    for cat in ('filling', 'fabric', 'accessory', 'packaging'):
        arr = res.get(cat) or []
        n += len(arr)
        print(f'  [{cat}] {len(arr)} 条')
        for r in arr:
            print(f"     name={r.get('material_name')!r:<16} spec={r.get('specification')!r:<8} "
                  f"qty={r.get('total_quantity')} unit={r.get('unit')!r} sup={r.get('supplier_name')!r}")
    print(f'  合计 {n} 条')
else:
    print(res)

print()
print('=' * 72)
print('【C】计算器产品列表口径  GET /purchase-center/products?per_page=200&simple=true')
print('=' * 72)
st, res = call('GET', '/purchase-center/products?per_page=200&simple=true')
print('HTTP', st)
if isinstance(res, dict):
    ps = res.get('products') or res.get('items') or []
    print(f'返回 {len(ps)} 个产品；目标产品在列表中的记录：')
    for p in ps:
        if p.get('id') == PID:
            print('  ', {k: p.get(k) for k in ('id', 'name', 'barcode', 'has_bom')})
    hit = [p for p in ps if p.get('id') == PID]
    if not hit:
        print('  !! 目标产品不在返回列表中（可能被 per_page=200 截断）')
        names = [p for p in ps if '木鱼' in (p.get('name') or '') or '蛋仔' in (p.get('name') or '')]
        print('  名称含蛋仔/木鱼的记录:', [(p.get('id'), p.get('name'), p.get('has_bom')) for p in names])
else:
    print(res)
