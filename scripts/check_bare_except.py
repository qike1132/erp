# scripts/check_bare_except.py
"""
裸 except / except Exception 检测脚本（AST based）

扫描 fastapi_app/ 下所有 .py 文件，AST 识别以下模式：
- `except:`  （裸 except）
- `except Exception:` / `except Exception as e:` （捕获所有异常）
- `except (..., Exception, ...):` （元组中包含 Exception 作为兜底）

允许的情况（白名单）：
- 测试文件（test_*.py / conftest.py）
- 白名单配置文件中显式豁免的 file:line 或 file
- 行内含 `# defensive:` 标注的防御性代码（启动/关闭容错）

退出码:
    0: 未发现违规（或仅命中白名单）
    1: 发现违规

任务来源: .codeartsdoer/specs/code_quality_opt/tasks.md 1.4
"""
from __future__ import annotations

import argparse
import ast
import io
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_SCAN_DIRS = [PROJECT_ROOT / "fastapi_app"]
EXCLUDE_DIRS = {"__pycache__"}

# 默认白名单文件（桌面壳等非 Web 路径）
DEFAULT_WHITELIST = PROJECT_ROOT / "scripts" / "allowed_broad_except.yaml"


@dataclass(frozen=True)
class Violation:
    file: str
    line: int
    except_type: str

    def to_dict(self) -> dict:
        return asdict(self)


def _except_kind(handler: ast.ExceptHandler) -> str | None:
    """返回该 except 的风险类型，无风险返回 None。"""
    typ = handler.type
    if typ is None:
        return "bare except"
    if isinstance(typ, ast.Name) and typ.id == "Exception":
        return "except Exception"
    if isinstance(typ, ast.Tuple):
        for elt in typ.elts:
            if isinstance(elt, ast.Name) and elt.id == "Exception":
                return "except (..., Exception)"
    return None


class BroadExceptVisitor(ast.NodeVisitor):
    def __init__(self, file_path: Path, source: str) -> None:
        self.file_path = file_path
        self.lines = source.splitlines()
        self.violations: list[Violation] = []

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        kind = _except_kind(node)
        if kind is not None:
            # 行内含 # defensive: 或 # broad-except: 标注则豁免
            # defensive: 启动/关闭容错；broad-except: 已审计的宽泛 except（附原因）
            line_text = self.lines[node.lineno - 1] if node.lineno - 1 < len(self.lines) else ""
            if "# defensive:" not in line_text and "# broad-except:" not in line_text:
                self.violations.append(
                    Violation(
                        file=str(self.file_path.relative_to(PROJECT_ROOT)),
                        line=node.lineno,
                        except_type=kind,
                    )
                )
        self.generic_visit(node)


def scan_file(path: Path) -> list[Violation]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    visitor = BroadExceptVisitor(path, source)
    visitor.visit(tree)
    return visitor.violations


def load_whitelist(yaml_path: Path | None) -> set[str]:
    if yaml_path is None or not yaml_path.exists():
        return set()
    whitelist: set[str] = set()
    for raw in yaml_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        whitelist.add(line)
    return whitelist


def is_whitelisted(v: Violation, whitelist: set[str]) -> bool:
    return f"{v.file}:{v.line}" in whitelist or v.file in whitelist


def is_test_file(path: Path) -> bool:
    name = path.name
    return name.startswith("test_") or name == "conftest.py"


def collect_py_files(scan_dirs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for d in scan_dirs:
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            if any(part in EXCLUDE_DIRS for part in p.parts):
                continue
            if is_test_file(p):
                continue
            files.append(p)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="裸/宽泛 except 检测（AST）")
    parser.add_argument("paths", nargs="*", help="待扫描目录")
    parser.add_argument(
        "--whitelist",
        type=Path,
        default=DEFAULT_WHITELIST,
        help="白名单配置文件",
    )
    args = parser.parse_args()

    scan_dirs = [Path(p).resolve() for p in args.paths] or DEFAULT_SCAN_DIRS
    whitelist = load_whitelist(args.whitelist)
    files = collect_py_files(scan_dirs)

    all_violations: list[Violation] = []
    for f in files:
        all_violations.extend(scan_file(f))

    real = [v for v in all_violations if not is_whitelisted(v, whitelist)]

    if not real:
        print("[PASS] 未发现裸/宽泛 except（白名单与 defensive 标注已豁免）")
        return 0

    by_file: dict[str, list[Violation]] = {}
    for v in real:
        by_file.setdefault(v.file, []).append(v)

    print(f"[FAIL] 发现 {len(real)} 处裸/宽泛 except（{len(by_file)} 个文件）:\n")
    for fp, vs in sorted(by_file.items()):
        print(f"  {fp} ({len(vs)})")
        for v in vs:
            print(f"    L{v.line}: {v.except_type}")
        print()

    return 1


if __name__ == "__main__":
    sys.exit(main())
