# scripts/check_vue_component_length.py
"""
Vue 组件行数检测脚本

统计 .vue 文件总行数，超过阈值（默认 400 行）视为巨型组件，
应拆分为子组件 + composables。

用法:
    python scripts/check_vue_component_length.py [--max-length 400] [路径...]
    python scripts/check_vue_component_length.py --json [路径...]   # 机器可读（门禁语义解析）

退出码:
    0: 未发现巨型组件
    1: 发现巨型组件

任务来源: .codeartsdoer/specs/code_quality_opt/tasks.md 1.3
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_SCAN_DIR = PROJECT_ROOT / "frontend-vite" / "src"
EXCLUDE_DIRS = {"node_modules", "dist", ".archive"}


@dataclass(frozen=True)
class Violation:
    file: str
    length: int

    def to_dict(self) -> dict:
        return asdict(self)


def scan_file(path: Path, max_length: int) -> Violation | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    length = len(lines)
    if length > max_length:
        return Violation(file=str(path.relative_to(PROJECT_ROOT)), length=length)
    return None


def collect_vue_files(scan_dir: Path) -> list[Path]:
    if not scan_dir.exists():
        return []
    # 显式传入单个 .vue 文件时必须真的扫它。
    # 否则 Path(file).rglob("*.vue") 返回空 → 静默 PASS（假绿），比报错更危险。
    if scan_dir.is_file():
        if scan_dir.suffix == ".vue" and not any(
            part in EXCLUDE_DIRS for part in scan_dir.parts
        ):
            return [scan_dir]
        return []
    return [
        p
        for p in scan_dir.rglob("*.vue")
        if not any(part in EXCLUDE_DIRS for part in p.parts)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Vue 组件行数检测")
    parser.add_argument("paths", nargs="*", help="待扫描目录")
    parser.add_argument("--max-length", type=int, default=400, help="组件最大行数阈值")
    parser.add_argument(
        "--json", action="store_true", help="机器可读输出（供 quality_gate.py 语义解析）"
    )
    args = parser.parse_args()

    scan_dir = Path(args.paths[0]).resolve() if args.paths else DEFAULT_SCAN_DIR
    files = collect_vue_files(scan_dir)

    violations: list[Violation] = []
    for f in files:
        v = scan_file(f, args.max_length)
        if v is not None:
            violations.append(v)

    if args.json:
        payload = {"violations": [asdict(v) for v in violations], "total": len(violations)}
        print(json.dumps(payload, ensure_ascii=False))
        return 0 if not violations else 1

    if not violations:
        print(f"[PASS] 未发现超过 {args.max_length} 行的 Vue 组件")
        return 0

    print(
        f"[FAIL] 发现 {len(violations)} 个巨型组件（>{args.max_length} 行）:\n"
    )
    for v in sorted(violations, key=lambda x: -x.length):
        print(f"  {v.file} = {v.length} 行")
    print()

    return 1


if __name__ == "__main__":
    sys.exit(main())
