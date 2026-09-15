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
- 行内含已文档化豁免标注的代码（**必须附理由，空标记不算**）：
  - `# defensive: <理由>`       启动/关闭容错
  - `# broad-except: <理由>`    已审计的宽泛兜底
  - ruff 风格 `noqa: BLE001 - <理由>`（blind-except）
  - ruff 风格 `noqa: S110 - <理由>`（try-except-pass 静默降级）

退出码:
    0: 未发现违规（或仅命中白名单）
    1: 发现违规

任务来源: .codeartsdoer/specs/code_quality_opt/tasks.md 1.4
"""
from __future__ import annotations

import argparse
import ast
import io
import re
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


# 已文档化的豁免标注。**必须带理由**：仅写标记不写原因仍视为违规，
# 避免"加个空标记就绕过门禁"。
_EXEMPT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"#\s*defensive:\s*\S"),
    re.compile(r"#\s*broad-except:\s*\S"),
    # ruff 风格：noqa 指令 + " - <理由>"（BLE001 / S110）
    re.compile(r"noqa:\s*[A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*\s*-\s*\S"),
)


def _is_documented(line_text: str) -> bool:
    """行内是否带有可审计的豁免说明（须附理由）。"""
    return any(pattern.search(line_text) for pattern in _EXEMPT_PATTERNS)


class BroadExceptVisitor(ast.NodeVisitor):
    def __init__(self, file_path: Path, source: str) -> None:
        self.file_path = file_path
        self.lines = source.splitlines()
        self.violations: list[Violation] = []

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        kind = _except_kind(node)
        if kind is not None:
            line_text = self.lines[node.lineno - 1] if node.lineno - 1 < len(self.lines) else ""
            if not _is_documented(line_text):
                self.violations.append(
                    Violation(
                        file=str(self.file_path.relative_to(PROJECT_ROOT)),
                        line=node.lineno,
                        except_type=kind,
                    )
                )
        self.generic_visit(node)


def scan_file(path: Path) -> tuple[list[Violation], str | None]:
    """返回 (违规列表, 解析错误)。

    解析失败必须显式上报——静默返回空会让"有语法错误的文件"被报告为
    "无违规"（假绿），而这类文件恰恰最需要被拦住。
    """
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, OSError) as exc:
        return [], str(exc)
    visitor = BroadExceptVisitor(path, source)
    visitor.visit(tree)
    return visitor.violations, None


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
        # 显式传入文件路径时必须真的扫它。
        # 否则 Path(file).rglob("*.py") 返回空 → 静默 PASS（假绿），比报错更危险。
        if d.is_file():
            if d.suffix == ".py" and not is_test_file(d) and not any(
                part in EXCLUDE_DIRS for part in d.parts
            ):
                files.append(d)
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

    # 显式传了路径却一个文件都没扫到，多半是路径写错（或传了非 .py 文件）。
    # 静默 PASS 会造成"假绿"，这里必须让人看见。
    if args.paths and not files:
        print(
            f"[WARN] 传入的路径未匹配到任何可扫描的 .py 文件：{[str(p) for p in args.paths]}",
            file=sys.stderr,
        )

    all_violations: list[Violation] = []
    parse_errors: list[tuple[str, str]] = []
    for f in files:
        violations, err = scan_file(f)
        if err is not None:
            parse_errors.append((str(f.relative_to(PROJECT_ROOT)), err))
            continue
        all_violations.extend(violations)

    if parse_errors:
        print(
            f"[WARN] {len(parse_errors)} 个文件解析失败（已跳过，不计入违规）:", file=sys.stderr
        )
        for rel, err in parse_errors[:10]:
            print(f"  {rel}: {err}", file=sys.stderr)

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
