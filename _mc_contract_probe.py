"""物料计算器契约探针：判断 5002 上跑的是「新契约(groups)」还是「GitHub 旧契约(filling/fabric/...)」。

用法：
    <python> _mc_contract_probe.py

判据（二选一，任一命中即可判定）：
  1. OpenAPI 里 MaterialCalculateResponse 的 properties
  2. 实际调用 /api/v1/purchase-center/calculate 返回的顶层键

注意：沙箱有 HTTP 代理，必须禁用 requests 的 trust_env，否则 127.0.0.1 会走代理返回误导性 502。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime

import requests

BASE = 'http://127.0.0.1:5002'
URL_OPENAPI = f'{BASE}/api/openapi.json'
URL_CALC = f'{BASE}/api/v1/purchase-center/calculate'

SESSION = requests.Session()
SESSION.trust_env = False  # 绕开沙箱 HTTP 代理


def port_owner(port: int) -> str:
    """返回监听该端口的进程 PID + 启动时间。"""
    out = subprocess.run(
        ['netstat', '-ano'], capture_output=True, text=True, encoding='gbk', errors='ignore'
    ).stdout
    pid = None
    for line in out.splitlines():
        if f':{port}' in line and 'LISTENING' in line:
            pid = line.split()[-1]
            break
    if not pid:
        return f'端口 {port} 无监听'
    ps = subprocess.run(
        ['powershell', '-NoProfile', '-Command',
         f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CreationDate"],
        capture_output=True, text=True, encoding='utf-8', errors='ignore',
    ).stdout.strip()
    m = re.search(r'(\d{14})', ps.replace('/Date(', '').replace(')/', ''))
    ts = datetime.strptime(m.group(1), '%Y%m%d%H%M%S').strftime('%Y-%m-%d %H:%M:%S') if m else '未知'
    return f'PID={pid}  启动于 {ts}'


def main() -> int:
    print('=== 5002 归属 ===')
    print(' ', port_owner(5002))
    print()

    # ---- 1) OpenAPI ----
    print('=== OpenAPI: MaterialCalculateResponse ===')
    contract_openapi = None
    try:
        r = SESSION.get(URL_OPENAPI, timeout=10)
        if r.status_code == 200:
            props = (
                r.json()
                .get('components', {})
                .get('schemas', {})
                .get('MaterialCalculateResponse', {})
                .get('properties', {})
            )
            keys = sorted(props.keys())
            print('  HTTP=200  键 =', keys)
            contract_openapi = 'NEW(groups)' if 'groups' in keys else 'OLD(github)'
        else:
            print('  HTTP =', r.status_code, '(OpenAPI 需鉴权或不可达)')
    except Exception as e:  # noqa: BLE001
        print('  异常:', e)

    # ---- 2) 实调 ----
    print()
    print('=== 实调 /calculate ===')
    sys.path.insert(0, '.')
    try:
        from fastapi_app.core.auth.token import create_access_token  # type: ignore

        token = create_access_token({'sub': '23'})
    except Exception as e:  # noqa: BLE001
        print('  无法生成 token:', e)
        return 2

    try:
        r = SESSION.post(
            URL_CALC,
            json={'orders': [{'product_id': 1, 'quantity': 1}]},
            headers={
                'Authorization': f'Bearer {token}',
                'X-CSRF-Token': token,
                'Content-Type': 'application/json',
            },
            cookies={'access_token': token, 'fastapi_csrf_token': token},
            timeout=20,
        )
        print('  HTTP =', r.status_code)
        if r.status_code == 200:
            keys = sorted(r.json().keys())
            print('  顶层键 =', keys)
            live = 'NEW(groups)' if 'groups' in keys else 'OLD(github)'
        else:
            print('  响应片段 =', r.text[:300])
            live = '未知'
    except Exception as e:  # noqa: BLE001
        print('  异常:', e)
        live = '未知'

    print()
    print('=== 结论 ===')
    if contract_openapi:
        print('  OpenAPI 判定 :', contract_openapi)
    print('  实调判定     :', live)
    expect_old = ('OLD(github)' in [contract_openapi, live]) or live == 'OLD(github)'
    if live == 'OLD(github)':
        print('  ✅ 后端已是 GitHub 旧契约，与 dist 前端一致，页面可正常使用')
        return 0
    print('  ⚠️  后端仍是新契约(groups)。源码已回滚但进程未重载 → 需重启 erp-prod 服务')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
