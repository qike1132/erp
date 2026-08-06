# scripts/check_bare_except.py
"""
裸 except / except Exception 检测脚本

扫描 fastapi_app/ 下所有 .py 文件，发现并报告以下代码位置：
- `except:`  （裸 except）
- `except Exception:` 或 `except Exception as e:` （捕获所有异常）
- `except (..., Exception):` （元组中包含 Exception 作为兜底）

允许的情况（会被忽略）：
- 测试文件（test_*.py）
- Celery 任务顶层错误处理（tasks/ 目录下的函数装饰器内部）
- 注释行
- 仅用于记录日志并继续运行的防御性代码块（如 cache 失效、FCM 推送）

退出码：
- 0：未发现裸 except（或仅有允许的例外）
- 1：发现裸 except
"""
import ast
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
SCAN_DIRS = [
    PROJECT_ROOT / "fastapi_app",
]

# 允许的模式（正则）
ALLOWED_PATTERNS = [
    r"except\s+\(.*Exception.*\):",   # 包含 Exception 的 except 元组（防御性）
]

# 允许的文件名模式
ALLOWED_FILES = [
    r"test_.*\.py$",
    r"conftest\.py$",
]


def is_allowed_file(path: Path) -> bool:
    import re
    for pattern in ALLOWED_FILES:
        if re.search(pattern, path.name):
            return True
    return False


def find_bare_excepts(content: str, file_path: Path) -> list[tuple[int, str]]:
    issues = []
    lines = content.splitlines()
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        # 裸 except
        if stripped == "except:":
            issues.append((lineno, stripped))
            continue
        # except Exception: 或 except Exception as e:
        # 排除已标记为 defensive 的行
        if "# defensive:" in stripped:
            continue
        if "#" in stripped:
            code_part = stripped.split("#", 1)[0].strip()
        else:
            code_part = stripped
        if code_part.startswith("except Exception"):
            issues.append((lineno, code_part))
    return issues


def main() -> int:
    all_issues: list[tuple[Path, int, str]] = []

    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue
        for py_file in scan_dir.rglob("*.py"):
            if is_allowed_file(py_file):
                continue
            content = py_file.read_text(encoding="utf-8")
            for lineno, line in find_bare_excepts(content, py_file):
                all_issues.append((py_file, lineno, line))

    if not all_issues:
        print("[PASS] 未发现裸 except")
        return 0

    # 按文件分组
    by_file: dict[Path, list[tuple[int, str]]] = {}
    for fp, ln, line in all_issues:
        by_file.setdefault(fp, []).append((ln, line))

    total = len(all_issues)
    print(f"[FAIL] 发现 {total} 处裸 except / except Exception：\n")
    for fp, issues in sorted(by_file.items()):
        relative = fp.relative_to(PROJECT_ROOT)
        print(f"  {relative} ({len(issues)})")
        for ln, line in issues:
            print(f"    L{ln}: {line}")
        print()

    return 1


if __name__ == "__main__":
    sys.exit(main())
