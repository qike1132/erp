#!/usr/bin/env python3
"""锁文件同步门禁：``requirements/<tier>.txt`` 改了必须重跑 ``uv pip compile`` 刷新 ``.lock``。

背景（评审 2026-10-11 B1）：Python 侧此前无锁文件、传递依赖不定版。现已入库
``requirements/{base,dev,test,ocr}.lock``（钉死全部传递依赖）。本门禁防锁**过期**——
改了 ``.txt`` 却没刷新 ``.lock`` 时响亮失败，而不是让锁悄悄与声明脱节。

判据是**版本钉死集**（``<pkg>==<ver>`` 行）是否一致，忽略 uv 生成的头部注释
（头部含输出路径，逐字节比对会假红）。

用法：
    python scripts/check_requirements_lock.py            # 默认 base dev test ocr
    python scripts/check_requirements_lock.py base dev   # 指定档
需要 ``uv`` 在 PATH（``uv pip compile`` 需联网解析）。
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys
from pathlib import Path

# 中文 Windows 的 stdout 是 cp936，打印中文/符号须显式 UTF-8（范式同其它门禁脚本）
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TIERS = ("base", "dev", "test", "ocr", "s3", "desktop", "migration")
# extras 也纳入比对（bar[baz]==2.0）；当前四份锁无 extras 行，防未来静默漏检
_PIN_RE = re.compile(r"^([A-Za-z0-9_.\-\[\]]+)==([^\s;]+)", re.MULTILINE)


def _pins(text: str) -> dict[str, str]:
    """抽取 ``<pkg>==<ver>`` 版本钉死集（忽略 uv 头部/``# via`` 注释）。"""
    return dict(_PIN_RE.findall(text))


def _compile(tier: str, txt: Path, out: Path, env: dict) -> str | None:
    try:
        # 平台口径必须钉死：锁是 Windows 产物（uvicorn[standard] 的 sys_platform marker
        # 会随平台引入/剔除 uvloop 与 colorama），CI 在 ubuntu 上跑，不钉则每次
        # fresh≠committed 必假红（评审 2026-10-11 二审 H1 实证）。
        r = subprocess.run(
            ["uv", "pip", "compile", str(txt), "-o", str(out), "--quiet",
             "--python-platform", "windows", "--python-version", "3.13"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=600, check=False, env=env,
        )
    except FileNotFoundError:
        print("[lock] 未找到 uv，请先安装（pip install uv / astral-sh/setup-uv）", file=sys.stderr)
        raise SystemExit(2) from None
    except subprocess.SubprocessError as e:
        print(f"[lock] {tier}: uv pip compile 调用失败: {e}", file=sys.stderr)
        return None
    if r.returncode != 0:
        print(f"[lock] {tier}: uv pip compile 失败: {(r.stderr or '').strip()[:300]}", file=sys.stderr)
        return None
    return out.read_text(encoding="utf-8")


def main(argv: list[str]) -> int:
    tiers = argv or list(DEFAULT_TIERS)
    # 本机 %TEMP% 与 uv 默认缓存目录（%LOCALAPPDATA%）对 D:\erp_system 下的进程有
    # 写入/删除限制（与 vitest/esbuild 同款坑），把 uv 的临时目录与缓存都指到仓内
    # 可写位置（缓存持久化以加速；临时目录跑完清掉）。
    tmp_root = ROOT / ".lockcheck-tmp"
    tmp_root.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "TMP": str(tmp_root), "TEMP": str(tmp_root), "TMPDIR": str(tmp_root),
        "UV_CACHE_DIR": str(ROOT / ".uv-cache"),
    }
    failed: list[str] = []
    unchecked: list[str] = []
    try:
        for tier in tiers:
            txt = ROOT / "requirements" / f"{tier}.txt"
            lock = ROOT / "requirements" / f"{tier}.lock"
            if not txt.exists() or not lock.exists():
                # 2026-10-11（N1 假绿洞）：缺锁必须算失败而不是跳过——此前走
                # continue + 无条件 return 0，新增依赖不生成 .lock 时 CI 永远绿，
                # 且打印「均一致」造成已校验的错觉。
                unchecked.append(tier)
                print(f"[lock] ✗ {tier}: 缺 {txt.name} 或 {lock.name}，未校验")
                continue
            fresh_text = _compile(tier, txt, tmp_root / f"{tier}.lock", env)
            if fresh_text is None:
                return 2
            fresh = _pins(fresh_text)
            committed = _pins(lock.read_text(encoding="utf-8"))
            if fresh == committed:
                print(f"[lock] {tier}.lock 与 {tier}.txt 一致（{len(fresh)} 个包）")
                continue
            added = sorted(set(fresh) - set(committed))
            removed = sorted(set(committed) - set(fresh))
            changed = sorted(k for k in set(fresh) & set(committed) if fresh[k] != committed[k])
            print(f"[lock] ✗ {tier}.lock 与 {tier}.txt 不同步：")
            if added:
                print(f"      新增 {added}")
            if removed:
                print(f"      移除 {removed}")
            if changed:
                print(f"      变更 {[(k, committed[k], fresh[k]) for k in changed]}")
            failed.append(tier)
    finally:
        import shutil
        shutil.rmtree(tmp_root, ignore_errors=True)

    if failed:
        print(
            "[lock] 失败：请刷新锁 —— "
            "uv pip compile requirements/<tier>.txt -o requirements/<tier>.lock"
        )
        return 1
    if unchecked:
        print(f"[lock] 失败：{unchecked} 缺 .lock，请生成 —— uv pip compile requirements/<tier>.txt -o requirements/<tier>.lock")
        return 1
    print(f"[lock] 通过：{tiers} 的 .lock 与 .txt 均一致")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
