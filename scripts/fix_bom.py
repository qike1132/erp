# scripts/fix_bom.py
"""批量剥离 .py 文件的 UTF-8 BOM（check_bom.py 的配套修复工具）。

用法:
    python scripts/fix_bom.py              # 剥离全仓
    python scripts/fix_bom.py path ...     # 只处理指定路径
    python scripts/fix_bom.py --dry-run    # 只列出将要修改的文件
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOM = b"\xef\xbb\xbf"

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from check_bom import iter_py_files


def main() -> int:
    parser = argparse.ArgumentParser(description="剥离 .py 的 UTF-8 BOM")
    parser.add_argument("paths", nargs="*", help="待处理路径，默认全仓")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    roots = [Path(p).resolve() for p in args.paths] or [PROJECT_ROOT]
    changed: list[str] = []
    for path in iter_py_files(roots):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if data[:3] != BOM:
            continue
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        changed.append(rel)
        if not args.dry_run:
            path.write_bytes(data[3:])

    verb = "将剥离" if args.dry_run else "已剥离"
    print(f"[OK] {verb} {len(changed)} 个文件的 BOM")
    for rel in sorted(changed):
        print(f"  {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
