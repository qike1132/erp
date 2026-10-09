# scripts/check_bom.py
"""UTF-8 BOM 检测脚本（门禁）。

为什么需要它
------------
带 BOM 的 .py 在 CPython 里**能正常 import**（PEP 263 允许 UTF-8 BOM），
所以 CI 的 pytest / ruff 都不会报错。但任何以文本方式读源码再 `ast.parse()`
的工具都会以

    SyntaxError: invalid non-printable character U+FEFF

失败，并且通常是**静默跳过**该文件——门禁看不见它。

实测（2026-09-30）：全仓 18 个 .py 带 BOM，其中 scripts/prod_audit/ 下 8 个
（含 orchestrator.py、layers/__init__.py），也就是**仓库自带的审计框架自身
无法被 AST 工具审计**；另有 tests/qa/__init__.py 影响 pytest 收集期的 AST 检查。

用法:
    python scripts/check_bom.py             # 扫描全仓 .py
    python scripts/check_bom.py path ...    # 只扫描指定路径

退出码:
    0: 未发现 BOM
    1: 发现以 UTF-8 BOM 开头的 .py
    2: 参数/环境异常
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

# 原地改编码，不要写 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)`：重绑会让旧
# wrapper 被 GC 并关闭**共享的**底层 buffer，殃及同一进程里后续的写入（尤其本模块被
# `fix_bom` 导入时，两次重绑必触发 `ValueError: I/O operation on closed file`）。
# 非文本流（被重定向/被测试框架捕获）时保持原样。
with contextlib.suppress(AttributeError, ValueError, OSError):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOM = b"\xef\xbb\xbf"

# 与 scripts/quality_gate.py 的扫描口径保持一致：只跳生成物与依赖目录。
EXCLUDE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".mypy_cache", ".ruff_cache", ".pytest_cache",
    ".archive", ".workbuddy", ".trae", ".superpowers",
}


def iter_py_files(roots: list[Path]):
    for root in roots:
        if root.is_file():
            if root.suffix == ".py":
                yield root
            continue
        for path in root.rglob("*.py"):
            if any(part in EXCLUDE_DIRS for part in path.parts):
                continue
            yield path


def has_bom(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(3) == BOM
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="检测以 UTF-8 BOM 开头的 .py 文件")
    parser.add_argument("paths", nargs="*", help="待扫描路径，默认全仓")
    args = parser.parse_args()

    roots = [Path(p).resolve() for p in args.paths] or [PROJECT_ROOT]
    hits = sorted(
        p.relative_to(PROJECT_ROOT).as_posix()
        for p in iter_py_files(roots)
        if has_bom(p)
    )

    if not hits:
        print("[PASS] 未发现以 UTF-8 BOM 开头的 .py")
        return 0

    print(f"[FAIL] 发现 {len(hits)} 处 .py 以 UTF-8 BOM 开头（ast.parse 会静默跳过）：\n")
    for rel in hits:
        print(f"  {rel}")
    print()
    print("修复：python scripts/fix_bom.py          # 批量剥离 BOM")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
