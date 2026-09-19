"""工作区卡顿审计（只读）。

用途：量化「用 AI 编码时卡」的两个可测量来源 —— ①宿主机的资源争抢，
②工作区里被反复遍历的噪音文件。全部为只读扫描，不删除、不移动任何文件。

产出可直接对比的基线数字，用于清理前后复测：
    python scripts/diag/workspace_perf_audit.py
    python scripts/diag/workspace_perf_audit.py --json > _audit_ws.json
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 会被文件遍历器反复走过、但不属于源码的目录名（任意层级匹配）
NOISE_NAMES = {
    ".mimosa", "node_modules", "__pycache__", ".git", ".venv", "venv",
    ".ruff_cache", ".mypy_cache", ".pytest_cache",
}
# 只统计体积、但不算噪音的目录（保留，仅报告）
REPORT_ONLY = {".workbuddy", "backups", ".archive", "temp", "dist", "dist-new"}


def walk_dir(path: str, skip: set[str] | None = None, max_depth: int | None = None):
    """返回 (文件数, 总字节)。skip 在任意层级生效。"""
    skip = skip or set()
    files = 0
    total = 0
    stack = [(path, 0)]
    while stack:
        cur, depth = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if e.name in skip:
                                continue
                            if max_depth is not None and depth + 1 > max_depth:
                                continue
                            stack.append((e.path, depth + 1))
                        elif e.is_file(follow_symlinks=False):
                            files += 1
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return files, total


def find_noise_dirs(root: str, max_depth: int = 6, cap: int = 60):
    """定位所有噪音目录实例，depth 有上限，避免自身变成慢操作。"""
    hits = []
    for dp, dns, _ in os.walk(root):
        if dp[len(root):].count(os.sep) > max_depth:
            dns[:] = []
            continue
        for d in dns:
            if d in NOISE_NAMES and d != ".git":
                hits.append(os.path.join(dp, d))
        dns[:] = [d for d in dns if d not in (".git", "node_modules", ".mimosa")]
        if len(hits) >= cap:
            break
    return hits


def scan_workspace():
    out = {"root": ROOT}
    root_entries = list(os.scandir(ROOT))
    root_files = [e for e in root_entries if e.is_file(follow_symlinks=False)]
    scratch = [e for e in root_files if e.name.startswith("_")]
    out["root_entries"] = len(root_entries)
    out["root_files"] = len(root_files)
    out["root_scratch_files"] = len(scratch)
    out["root_scratch_MB"] = round(sum(e.stat().st_size for e in scratch) / 2**20, 1)

    noise = []
    for p in find_noise_dirs(ROOT):
        n, b = walk_dir(p)
        noise.append({"path": os.path.relpath(p, ROOT), "files": n, "MB": round(b / 2**20, 1)})
    noise.sort(key=lambda x: -x["files"])
    out["noise_dirs"] = noise[:12]
    out["noise_dir_count"] = len(noise)
    out["noise_total_files"] = sum(x["files"] for x in noise)
    out["noise_total_MB"] = round(sum(x["MB"] for x in noise), 1)

    scanned_files, scanned_bytes = walk_dir(ROOT, skip=NOISE_NAMES)
    out["scannable_files"] = scanned_files
    out["scannable_MB"] = round(scanned_bytes / 2**20, 1)

    subs = []
    for e in root_entries:
        if e.is_dir(follow_symlinks=False) and e.name not in NOISE_NAMES:
            n, b = walk_dir(e.path, skip=NOISE_NAMES, max_depth=8)
            subs.append((e.name, n, round(b / 2**20, 1)))
    subs.sort(key=lambda x: -x[1])
    out["top_subdirs"] = subs[:10]
    return out


def git_state():
    out = {}
    for key, args in (("tracked_files", ["ls-files"]),
                      ("count_objects", ["count-objects", "-vH"])):
        try:
            # encoding="utf-8" 必需：本仓 core.quotePath=false，git 输出 UTF-8
            # 原始字节；中文 Windows 默认 cp936 解码会崩掉读取线程并使 stdout=None。
            r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=180)
            if key == "tracked_files":
                out[key] = len([l for l in r.stdout.splitlines() if l.strip()])
            else:
                out[key] = dict(l.split(": ", 1) for l in r.stdout.strip().splitlines() if ": " in l)
        except Exception as ex:  # 沙箱/超时下不给结论，但明确标注失败
            out[key] = f"ERR {ex}"
    return out


def host_state():
    """宿主机内存与高占用进程组。非 Windows 或取数失败时返回明确错误。"""
    out = {"cpu_cores": os.cpu_count()}
    if os.name != "nt":
        out["note"] = "host_state 仅实现 Windows 分支"
        return out
    import csv
    import ctypes
    import io

    class MEM(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    ms = MEM()
    ms.dwLength = ctypes.sizeof(MEM)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
        out["note"] = "GlobalMemoryStatusEx 失败"
        return out
    out["ram_total_GB"] = round(ms.ullTotalPhys / 2**30, 1)
    out["ram_avail_GB"] = round(ms.ullAvailPhys / 2**30, 1)
    out["ram_used_pct"] = ms.dwMemoryLoad

    try:
        r = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True,
                           text=True, timeout=120, encoding="mbcs", errors="replace")
        agg: dict[str, list] = {}
        for row in csv.reader(io.StringIO(r.stdout)):
            if len(row) < 5:
                continue
            try:
                kb = int(row[4].replace(",", "").replace("K", "").strip())
            except ValueError:
                continue
            a = agg.setdefault(row[0], [0, 0])
            a[0] += 1
            a[1] += kb
        tops = sorted(agg.items(), key=lambda kv: -kv[1][1])[:12]
        out["top_processes"] = [{"name": k, "n": v[0], "MB": round(v[1] / 1024)}
                                for k, v in tops]
        out["prod_stack_counts"] = {k: agg[k][0] for k in
                                    ("nginx.exe", "python.exe", "node.exe",
                                     "redis-server.exe", "nssm.exe", "postgres.exe")
                                    if k in agg}
    except Exception as ex:
        out["process_err"] = str(ex)
    return out


def render(data: dict) -> str:
    lines = []
    ws, g, h = data["workspace"], data["git"], data["host"]
    lines.append("== 宿主机 ==")
    if "ram_total_GB" in h:
        lines.append(f"  CPU {h['cpu_cores']} 核 | 内存 {h['ram_total_GB']}GB "
                     f"可用 {h['ram_avail_GB']}GB (已用 {h['ram_used_pct']}%)")
    for p in h.get("top_processes", []):
        lines.append(f"    {p['name']:<24} n={p['n']:<4} {p['MB']}MB")
    if h.get("prod_stack_counts"):
        lines.append(f"  生产栈实例数: {h['prod_stack_counts']}")
    lines.append("== 工作区 ==")
    lines.append(f"  根目录条目 {ws['root_entries']}，其中草稿文件 _* "
                 f"{ws['root_scratch_files']} 个 / {ws['root_scratch_MB']}MB")
    lines.append(f"  噪音目录 {ws['noise_dir_count']} 处，合计 "
                 f"{ws['noise_total_files']} 文件 / {ws['noise_total_MB']}MB")
    for n in ws["noise_dirs"][:8]:
        lines.append(f"    {n['path']:<46} {n['files']:>7} files  {n['MB']}MB")
    lines.append(f"  一次全仓遍历需走过 {ws['scannable_files']} 文件 / {ws['scannable_MB']}MB（已排除噪音目录）")
    lines.append("  最大子目录: " + ", ".join(f"{n}({c})" for n, c, _ in ws["top_subdirs"][:6]))
    lines.append("== Git ==")
    lines.append(f"  跟踪文件 {g.get('tracked_files')}")
    co = g.get("count_objects")
    if isinstance(co, dict):
        lines.append(f"  松散对象 {co.get('count')}，可打包 {co.get('prune-packable')}，"
                     f"pack {co.get('size-pack')}")
    return "\n".join(lines)


def main() -> int:
    with contextlib.suppress(Exception):  # 非 Windows 或非 UTF-8 控制台时忽略
        sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.time()
    data = {"workspace": scan_workspace(), "git": git_state(), "host": host_state(),
            "elapsed_s": None}
    data["elapsed_s"] = round(time.time() - t0, 1)
    if "--json" in sys.argv:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render(data))
        print(f"\n(扫描耗时 {data['elapsed_s']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
