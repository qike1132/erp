# scripts/check_ts_module_length.py
"""前端 TS 模块 / composable 行数检测脚本

背景（2026-11-16 加）：`check_vue_component_length.py` 只量 `*.vue`，于是一条很自然的
规避路径一直敞着 —— 把巨型组件的逻辑"搬进 composable"就绕过了 400 行门禁。实测
`views/purchase/composables/useSummaryModal.ts` 已 1085 行、`useProductionEntry.ts` 904 行、
`useBeileOrders.ts` 717 行：巨型逻辑没被拆掉，只是换了个后缀。

本脚本量 `frontend-vite/src/**/*.ts`，阈值（默认 600）比 SFC 宽：composable 本来就承载
逻辑而不是模板，且带 docstring/类型标注。**不扫**：
- `src/types/**` 与 `*.d.ts`：`api.d.ts` 是从 OpenAPI 生成的产物（近 3000 行），
  手改它没有意义，量它只会制造噪音；
- `src/test/**`：测试文件的规模由用例本身决定，不该倒逼实现拆分。

用法:
    python scripts/check_ts_module_length.py [--max-length 600] [路径...]
    python scripts/check_ts_module_length.py --json [路径...]   # 机器可读（门禁语义解析）

退出码:
    0: 未发现超长模块
    1: 发现超长模块
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
EXCLUDE_DIRS = {"node_modules", "dist", ".archive", "types", "test", "__tests__"}


@dataclass(frozen=True)
class Violation:
    file: str
    length: int

    def to_dict(self) -> dict:
        return asdict(self)


def _excluded(path: Path) -> bool:
    if path.suffix == ".d.ts" or path.name.endswith(".d.ts"):
        return True
    return any(part in EXCLUDE_DIRS for part in path.parts)


def scan_file(path: Path, max_length: int) -> Violation | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if len(lines) > max_length:
        return Violation(file=str(path.relative_to(PROJECT_ROOT)), length=len(lines))
    return None


def collect_ts_files(scan_dir: Path) -> list[Path]:
    if not scan_dir.exists():
        return []
    # 显式传入单个文件时必须真的扫它：rglob 在文件路径上返回空 → 静默 PASS（假绿），
    # 比报错更危险（同 check_vue_component_length.py 的教训）。
    if scan_dir.is_file():
        if scan_dir.suffix == ".ts" and not _excluded(scan_dir):
            return [scan_dir]
        return []
    return [p for p in scan_dir.rglob("*.ts") if not _excluded(p)]


def main() -> int:
    parser = argparse.ArgumentParser(description="前端 TS 模块行数检测")
    parser.add_argument("paths", nargs="*", help="待扫描目录")
    parser.add_argument("--max-length", type=int, default=600, help="模块最大行数阈值")
    parser.add_argument(
        "--json", action="store_true", help="机器可读输出（供 quality_gate.py 语义解析）"
    )
    args = parser.parse_args()

    scan_dir = Path(args.paths[0]).resolve() if args.paths else DEFAULT_SCAN_DIR
    files = collect_ts_files(scan_dir)

    violations = [v for v in (scan_file(f, args.max_length) for f in files) if v is not None]

    if args.json:
        payload = {"violations": [asdict(v) for v in violations], "total": len(violations)}
        print(json.dumps(payload, ensure_ascii=False))
        return 0 if not violations else 1

    if not violations:
        print(f"[PASS] 未发现超过 {args.max_length} 行的 TS 模块")
        return 0

    print(f"[FAIL] 发现 {len(violations)} 个超长 TS 模块（>{args.max_length} 行）:\n")
    for v in sorted(violations, key=lambda x: -x.length):
        print(f"  {v.file} = {v.length} 行")
    print()

    return 1


if __name__ == "__main__":
    sys.exit(main())
