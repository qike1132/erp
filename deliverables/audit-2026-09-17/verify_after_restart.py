"""重启后一键复验（只读，非提权即可跑）。

覆盖本轮两件事的落地判定：
  A) 备份健康页两条假告警（提交 7a547d9）是否消失
  B) NSSM AppEnvironmentExtra 修复（fix_nssm_appenv.ps1）是否生效
     —— 间接判据：PYTHONUTF8 生效后 erp-arq.log 新写入的中文不再乱码

用法（在 D:\\erp_system 下）：
    python deliverables/audit-2026-09-17/verify_after_restart.py

退出码：0 = 全部通过；1 = 有项目未通过（详情见输出）。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import timedelta
from pathlib import Path

ROOT = Path(r'D:\erp_system')
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

OUT: list[str] = []
W = OUT.append
FAILURES: list[str] = []

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
BASE = 'http://127.0.0.1:3000'


def cjk_ratio(s: str) -> int:
    return sum(1 for c in s if '\u4e00' <= c <= '\u9fff')


def section(title: str) -> None:
    W('')
    W('=' * 74)
    W(title)
    W('=' * 74)


# ---------------------------------------------------------------- A. 备份健康页
def check_backup_health() -> None:
    section('A) 备份健康页两条假告警（期望：全部消失）')
    try:
        from fastapi_app.core.auth.token import create_access_token
    except Exception as e:  # noqa: BLE001
        W(f'  [SKIP] 无法导入 create_access_token: {e!r}')
        return
    token = create_access_token({'sub': '23', 'username': 'admin'},
                                expires_delta=timedelta(minutes=10))
    req = urllib.request.Request(f'{BASE}/api/v1/backup/health')
    req.add_header('Authorization', f'Bearer {token}')
    req.add_header('Accept', 'application/json')
    req.add_header('Origin', 'http://192.168.0.95:3000')
    try:
        with _opener.open(req, timeout=30) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except Exception as e:  # noqa: BLE001
        W(f'  [FAIL] 请求异常: {type(e).__name__}: {e}')
        FAILURES.append('A: 请求异常')
        return

    W(f'  GET /api/v1/backup/health -> {status}')
    if status != 200:
        W(f'  [FAIL] 非 200，body={raw[:400]!r}')
        FAILURES.append(f'A: HTTP {status}')
        return

    d = json.loads(raw)
    checks = d.get('checks') or {}
    W(f'  总体 status = {d.get("status")!r}')
    W(f'  top-level issues = {json.dumps(d.get("issues"), ensure_ascii=False)}')

    # A-1 last_backup 不再 1970 / 不再超 24h
    lb = checks.get('last_backup') or {}
    msg = lb.get('message', '') or ''
    W(f'  last_backup = {lb.get("status")!r} / {msg!r}')
    if '1970' in msg or '超过24小时' in msg:
        W('    [FAIL] 仍报假告警（mtime 未生效或仍是旧代码）')
        FAILURES.append('A-1: last_backup 假告警未消失')
    else:
        W('    [PASS] 无假告警')

    # A-2 backup_integrity 文件名不再为空
    bi = checks.get('backup_integrity') or {}
    results = bi.get('results') or []
    names = [(r or {}).get('filename') for r in results]
    empty = [n for n in names if not (n or '').strip()]
    W(f'  backup_integrity = {bi.get("status")!r} / {bi.get("message")!r}')
    W(f'    抽样文件名 = {json.dumps(names, ensure_ascii=False)}')
    if not results:
        W('    [INFO] 无抽样结果，无法判定（可能备份目录为空）')
    elif empty:
        W(f'    [FAIL] 仍有 {len(empty)} 条空文件名')
        FAILURES.append('A-2: backup_integrity 文件名仍为空')
    else:
        W('    [PASS] 文件名均为真实值')

    issues = d.get('issues') or []
    fake = [i for i in issues if isinstance(i, str)
            and (i.strip() == '备份文件异常:' or '超过24小时' in i)]
    if fake:
        W(f'    [FAIL] 顶层 issues 仍含假告警: {fake}')
        FAILURES.append('A-3: 顶层 issues 仍有假告警')
    else:
        W('    [PASS] 顶层 issues 无假告警')


# ------------------------------------------------------- B. PYTHONUTF8 生效判据
def check_arq_encoding() -> None:
    section('B) PYTHONUTF8 是否生效（看 erp-arq.log 新写入的中文）')
    log = ROOT / 'logs' / 'erp-arq.log'
    if not log.is_file():
        W(f'  [SKIP] 日志不存在: {log}')
        return
    raw = log.read_bytes()
    text = raw.decode('utf-8', errors='replace')
    lines = text.splitlines()
    W(f'  文件 {log}  {len(raw) / 1024:.1f} KB / {len(lines)} 行')
    mtime = log.stat().st_mtime
    import datetime as _dt
    W(f'  最后写入 = {_dt.datetime.fromtimestamp(mtime):%Y-%m-%d %H:%M:%S}')

    def bad_ratio(seg: list[str]) -> tuple[int, int]:
        joined = '\n'.join(seg)
        return joined.count('\ufffd'), cjk_ratio(joined)

    head_bad, _ = bad_ratio(lines[:200])
    tail_seg = lines[-200:]
    tail_bad, tail_cjk = bad_ratio(tail_seg)
    W(f'  前 200 行 U+FFFD = {head_bad}')
    W(f'  后 200 行 U+FFFD = {tail_bad}（其中 CJK 字符 {tail_cjk} 个）')

    if head_bad > 0 and tail_bad == 0:
        W('    [PASS] 历史乱码在，新写入已干净 → PYTHONUTF8 已生效')
    elif tail_bad > 0:
        W('    [FAIL] 尾部仍有乱码 → PYTHONUTF8 仍未生效（服务是否已重启？）')
        FAILURES.append('B-1: erp-arq.log 尾部仍乱码')
    else:
        W('    [INFO] 全文件无乱码，无法区分「已是 UTF-8」与「恰好无中文」')

    W('  --- 最后 8 行原文（人工确认中文是否可读）---')
    for ln in lines[-8:]:
        W(f'    | {ln[:160]}')


# ------------------------------------------------------------- C. 进程树新鲜度
def check_process_tree() -> None:
    section('C) 进程树（看 uvicorn 是否已换成新 pid）')
    try:
        import psutil
    except Exception as e:  # noqa: BLE001
        W(f'  [SKIP] psutil 不可用: {e!r}')
        return
    import datetime as _dt

    # 判别 erp-prod 与 erp-arq：两者都是 nssm.exe → python.exe，只按「第一个
    # 有 python 子进程的 nssm」会误取到 erp-arq（实测取到 12208）。唯一可靠的
    # 区分点是 **只有 erp-prod 监督 nginx**（prod_runner 托管前端 nginx）。
    def tree_names(p) -> set[str]:
        return {k.name() for k in p.children(recursive=True)}

    candidates = []
    for p in psutil.process_iter(['pid', 'name']):
        try:
            if p.info['name'] != 'nssm.exe':
                continue
            names = tree_names(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if names:
            candidates.append((p, names))

    W('  发现 nssm 包裹进程：')
    for p, names in candidates:
        mark = '  <== erp-prod（含 nginx）' if 'nginx.exe' in names else ''
        W(f'      pid={p.pid:<7} 子树={sorted(names)}{mark}')

    svc = next((p for p, n in candidates if 'nginx.exe' in n), None)
    if svc is None:
        W('  [FAIL] 未找到 erp-prod 服务树（无任何 nssm 子树含 nginx.exe）')
        FAILURES.append('C-1: erp-prod 服务树缺失')
        return

    W(f'  判定 erp-prod 包裹 pid = {svc.pid}')
    pythons, nginxes = [], []
    for c in svc.children(recursive=True):
        try:
            nm = c.name()
            # 必须显式比 nginx.exe：子树里还有 conhost.exe，用 else 兜底会把
            # conhost 算进 nginx 计数（实测虚报成 27 个）。
            if nm not in ('python.exe', 'nginx.exe'):
                continue
            started = _dt.datetime.fromtimestamp(c.create_time())
            item = (c.pid, f'{started:%H:%M:%S}')
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        (pythons if nm == 'python.exe' else nginxes).append(item)
    W(f'  python.exe 数 = {len(pythons)}（期望 1 监督器 + 1 master + UVICORN_WORKERS worker）')
    for pid, t in sorted(pythons, key=lambda x: x[1]):
        W(f'      pid={pid:<7} 启动于 {t}')
    W(f'  nginx.exe 数 = {len(nginxes)}')
    for pid, t in sorted(nginxes, key=lambda x: x[1])[:3]:
        W(f'      pid={pid:<7} 启动于 {t}')

    # 监听 5002 的进程必须在这棵树里（否则说明有孤儿 worker 顶着端口，
    # 新 master 绑不上 → 崩溃循环；见 prod_runner.poll() 不调 kill_tree 的设计）
    owners = set()
    try:
        for c in psutil.net_connections(kind='tcp'):
            if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == 5002:
                owners.add(c.pid)
    except (psutil.AccessDenied, OSError) as e:
        W(f'  [INFO] net_connections 受限: {e!r}')
    tree_pids = {pid for pid, _t in pythons}
    W(f'  :5002 监听 pid = {sorted(owners)}')
    if owners and tree_pids and owners <= tree_pids:
        W('    [PASS] 5002 由本服务树内进程持有（无孤儿 worker 顶端口）')
    elif owners:
        W('    [WARN] 5002 持有者不在本树内 → 可能存在孤儿 worker，需人工确认')
        FAILURES.append('C-2: 5002 持有者不在服务树内（疑似孤儿 worker）')
    else:
        W('    [FAIL] 无人监听 5002 → 后端未起来')
        FAILURES.append('C-3: 5002 无监听')


def main() -> int:
    W('滨发 ERP · 重启后一键复验（只读）')
    W('对应提交 7a547d9 + fix_nssm_appenv.ps1 -Restart')
    # 分段容错：任何一段抛异常都不许吞掉整份报告（否则丢了另一段的证据）
    for name, fn in (('A', check_backup_health),
                     ('B', check_arq_encoding),
                     ('C', check_process_tree)):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            W('')
            W(f'  [{name}] 检查过程异常: {type(e).__name__}: {e}')
            FAILURES.append(f'{name}: 检查异常 {type(e).__name__}')

    section('结论')
    if FAILURES:
        W(f'  ❌ 未通过 {len(FAILURES)} 项：')
        for f in FAILURES:
            W(f'     - {f}')
    else:
        W('  ✅ 全部通过')

    txt = '\n'.join(OUT)
    out = ROOT / 'deliverables' / 'audit-2026-09-17' / 'verify_after_restart_result.txt'
    out.write_text(txt, encoding='utf-8')
    print(txt)
    print(f'\n(结果已写入 {out})')
    return 1 if FAILURES else 0


if __name__ == '__main__':
    raise SystemExit(main())
