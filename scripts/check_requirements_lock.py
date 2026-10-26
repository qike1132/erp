#!/usr/bin/env python3
"""锁文件同步门禁：保证 ``requirements/<tier>.lock`` 真的满足 ``<tier>.txt`` 的声明。

背景（评审 2026-10-11 B1）：Python 侧此前无锁文件、传递依赖不定版。现已入库
``requirements/{base,dev,test,ocr,s3,desktop,migration}.lock``（钉死全部传递依赖）。

**判据（2026-10-26 重写）**

原判据是「拿 ``.txt`` 重新解析一次，与已提交 ``.lock`` 逐包比对」。它的真实缺陷是把
**传递依赖**也算进判等：上游每发一个补丁（10-25 是 ``pytest-asyncio`` 1.4.0→1.4.1，
10-26 是 ``grpcio`` 1.84.1→1.85.0），7 个 tier 立刻同时"失配"，main 的 CI 无端变红，
而那次提交与依赖毫无关系 —— 门禁把「上游在动」误报成「人改错了」。

现在的判据只看**声明的直接依赖**是否被锁满足：

1. ``.txt`` 里声明了、锁里却没有 → **失败**（改了声明却没刷新锁，真正要拦的场景）；
2. ``.txt`` 钉了 ``==x.y`` 而锁里是别的版本 → **失败**；
3. ``.txt`` 用 ``>=`` / ``<`` / ``~=`` 等范围，锁里的版本不满足 → **失败**；
4. 锁里多出的包（传递依赖）→ 默认不判定；``--strict`` 时才与「重新解析」比对并报差异。

这样既保留了原本的意图（改了 ``.txt`` 必须刷新 ``.lock``），又不会因为上游补丁发布而随机变红。
``--strict`` 保留旧行为（需要 ``uv`` 联网解析），供 ``refresh-requirements-lock`` 工作流自检。

用法：
    python scripts/check_requirements_lock.py            # 默认 base dev test ocr s3 desktop migration
    python scripts/check_requirements_lock.py base dev   # 指定档
    python scripts/check_requirements_lock.py --strict   # 额外做「整树重新解析」比对（需 uv）
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


def _force_utf8_streams() -> None:
    """中文 Windows 的 stdout 是 cp936，打印中文/符号会乱码或抛 UnicodeEncodeError。

    只在**确实不是 UTF-8** 时替换：测试里 pytest 已把 stdout 换成 UTF-8 捕获对象，
    再包一层 TextIOWrapper 会在回收时关掉底层 buffer（``I/O operation on closed file``）。
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        buf = getattr(stream, "buffer", None)
        if stream is None or buf is None:
            continue
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding.startswith("utf8"):
            continue
        try:
            setattr(sys, name, io.TextIOWrapper(buf, encoding="utf-8"))
        except (ValueError, OSError):  # 已被关闭/被替换：保持原样即可
            continue


_force_utf8_streams()

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TIERS = ("base", "dev", "test", "ocr", "s3", "desktop", "migration")
# extras 也纳入比对（bar[baz]==2.0）
_PIN_RE = re.compile(r"^([A-Za-z0-9_.\-\[\]]+)==([^\s;]+)", re.MULTILINE)


def _pins(text: str) -> dict[str, str]:
    """抽取 ``<pkg>==<ver>`` 版本钉死集（忽略 uv 头部/``# via`` 注释）。"""
    return dict(_PIN_RE.findall(text))


def _canon_pins(text: str) -> dict[str, str]:
    """锁的规范化视图：``canonicalize_name`` → version（同名不同写法不会漏判）。"""
    out: dict[str, str] = {}
    for name, ver in _pins(text).items():
        out[canonicalize_name(name.split("[", 1)[0])] = ver
    return out


def _strip_comment(line: str) -> str:
    """去掉行尾注释（pip/uv 口径：``#`` 在行首或前面是空白时才算注释）。"""
    idx = line.find("#")
    while idx != -1:
        if idx == 0 or line[idx - 1].isspace():
            return line[:idx]
        idx = line.find("#", idx + 1)
    return line


def parse_declared(path: Path, seen: set[Path] | None = None) -> list[Requirement]:
    """解析 ``.txt`` 里**声明**的依赖（递归 ``-r`` 包含，忽略选项与注释）。"""
    seen = seen if seen is not None else set()
    resolved = path.resolve()
    if resolved in seen or not path.is_file():
        return []
    seen.add(resolved)
    declared: list[Requirement] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith(("-r ", "--requirement ")):
            include = line.split(None, 1)[1].strip()
            declared.extend(parse_declared(path.parent / include, seen))
            continue
        if line.startswith("-"):
            continue  # --index-url / -e / --no-binary 等选项与声明无关
        try:
            declared.append(Requirement(line))
        except InvalidRequirement:
            print(f"[lock] 警告: {path.name} 无法解析的行，已跳过: {line}", file=sys.stderr)
    return declared


def check_declared(tier: str, txt: Path, lock: Path) -> tuple[list[str], int]:
    """比对「声明 vs 锁」，返回 (失败项列表, 声明条数)。"""
    commits = _canon_pins(lock.read_text(encoding="utf-8"))
    failures: list[str] = []
    declared = parse_declared(txt)
    for req in declared:
        name = canonicalize_name(req.name)
        locked = commits.get(name)
        if locked is None and req.marker is not None:
            # 平台/环境标记依赖（如 sys_platform=='linux'）在 windows 口径的锁里本就不出现
            continue
        if locked is None:
            failures.append(f"未锁定: {req.name}（{tier}.txt 声明了，{tier}.lock 里没有）")
            continue
        if not req.specifier:
            continue
        try:
            spec = SpecifierSet(str(req.specifier))
            ok = spec.contains(Version(locked), prereleases=True)
        except (InvalidSpecifier, InvalidVersion):
            failures.append(f"无法判定: {req.name} 的约束 {req.specifier} / 锁内版本 {locked}")
            continue
        if not ok:
            failures.append(f"版本不满足: {req.name} 需要 {req.specifier}，锁内是 {locked}")
    return failures, len(declared)


def _compile(tier: str, txt: Path, out: Path, env: dict) -> str | None:
    # 2026-10-11（P2-15 实证）：uv 0.12.5 的解析有「锁继承」行为——输出文件已存在时
    # 会以旧内容为解析锚定、保持原版本不升级；fresh 就不再是 txt 的独立解析结果，
    # 与 committed 比对会出现「永远同步」的假绿。故每次先删输出，逼出全新解析。
    if out.exists():
        out.unlink()
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
        print("[lock] 未找到 uv，--strict 需要它：pip install uv", file=sys.stderr)
        raise SystemExit(2) from None
    except subprocess.SubprocessError as e:
        print(f"[lock] {tier}: uv pip compile 调用失败: {e}", file=sys.stderr)
        return None
    if r.returncode != 0:
        print(f"[lock] {tier}: uv pip compile 失败: {(r.stderr or '').strip()[:300]}", file=sys.stderr)
        return None
    return out.read_text(encoding="utf-8")


def _strict_drift(tier: str, txt: Path, lock: Path, tmp_root: Path, env: dict) -> list[str]:
    """``--strict``：整棵依赖树是否与一次全新解析一致（会因上游补丁发布而差异）。"""
    fresh_text = _compile(tier, txt, tmp_root / f"{tier}.lock", env)
    if fresh_text is None:
        raise SystemExit(2)
    fresh = _pins(fresh_text)
    committed = _pins(lock.read_text(encoding="utf-8"))
    added = sorted(set(fresh) - set(committed))
    removed = sorted(set(committed) - set(fresh))
    changed = sorted(k for k in set(fresh) & set(committed) if fresh[k] != committed[k])
    if not (added or removed or changed):
        return []
    lines = ["整树与重新解析不一致（上游可能已发版）"]
    if added:
        lines.append(f"新增 {added}")
    if removed:
        lines.append(f"移除 {removed}")
    if changed:
        lines.append(f"变更 {[(k, committed[k], fresh[k]) for k in changed]}")
    return lines


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    tiers = [a for a in argv if not a.startswith("-")] or list(DEFAULT_TIERS)
    # 本机 %TEMP% 与 uv 默认缓存目录对 D:\erp_system 下的进程有写入限制（与 vitest 同款坑），
    # 把 uv 的临时目录与缓存都指到仓内可写位置。目录带 PID：并发跑两个门禁实例时
    # 各自的 unlink/rmtree 不会互删（OCR 评审 2026-10-11 Low-4）。
    tmp_root = ROOT / f".lockcheck-tmp-{os.getpid()}"
    env = {
        **os.environ,
        "TMP": str(tmp_root), "TEMP": str(tmp_root), "TMPDIR": str(tmp_root),
        "UV_CACHE_DIR": str(ROOT / ".uv-cache"),
    }
    failures: list[str] = []
    unchecked: list[str] = []
    if strict:
        tmp_root.mkdir(exist_ok=True)
    try:
        for tier in tiers:
            txt = ROOT / "requirements" / f"{tier}.txt"
            lock = ROOT / "requirements" / f"{tier}.lock"
            if not txt.exists() or not lock.exists():
                # 缺锁必须算失败而不是跳过——否则新增依赖不生成 .lock 时 CI 永远绿，
                # 且打印「均一致」造成已校验的错觉（2026-10-11 N1 假绿洞）。
                unchecked.append(tier)
                print(f"[lock] ✗ {tier}: 缺 {txt.name} 或 {lock.name}，未校验")
                continue
            tier_failures, n_declared = check_declared(tier, txt, lock)
            n_locked = len(_canon_pins(lock.read_text(encoding="utf-8")))
            if tier_failures:
                print(f"[lock] ✗ {tier}.lock 不满足 {tier}.txt 的声明：")
                for item in tier_failures:
                    print(f"      {item}")
                failures.extend(f"{tier}: {item}" for item in tier_failures)
                continue
            print(f"[lock] {tier}.lock 满足 {tier}.txt 的声明"
                  f"（声明 {n_declared} 项 / 锁内 {n_locked} 个包）")
            if strict:
                drift = _strict_drift(tier, txt, lock, tmp_root, env)
                if drift:
                    print(f"[lock] ✗ {tier} {drift[0]}")
                    for extra in drift[1:]:
                        print(f"      {extra}")
                    failures.append(f"{tier}: 整树漂移")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    if failures:
        print(
            "[lock] 失败：请刷新锁 —— "
            "uv pip compile requirements/<tier>.txt -o requirements/<tier>.lock"
        )
        return 1
    if unchecked:
        print(f"[lock] 失败：{unchecked} 缺 .lock，请生成 —— "
              f"uv pip compile requirements/<tier>.txt -o requirements/<tier>.lock")
        return 1
    mode = "（strict：整树一致）" if strict else ""
    print(f"[lock] 通过：{tiers} 的 .lock 均满足 .txt 声明{mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
