#!/usr/bin/env python3
"""
Service 层事务提交检测脚本

扫描 fastapi_app/services/ 下所有 .py 文件，发现并报告 service 层函数中
直接使用 await db.commit() / await session.commit() 的代码位置。

允许的情况（会被忽略）：
- 嵌套事务：await nested.commit()
- 独立短 session：await short_session.commit()
- 编号生成器中的 commit
- 注释行
- 测试文件

退出码：
- 0：未发现非法 commit
- 1：发现非法 commit
"""

import io
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVICES_DIR = PROJECT_ROOT / "fastapi_app" / "services"

# 允许的 commit 模式（忽略）
ALLOWED_PATTERNS = [
    r"nested\.commit\(",                 # 嵌套事务
    r"short_session\.commit\(",          # 独立短 session
    r"_session\.commit\(",               # 下划线开头的 session
    r"#.*commit\(",                      # 注释行
    r"^\s*#",                            # 整行注释
    r"#\s*independent[-_]transaction",   # 标记为独立事务
]

# 可疑的 commit 模式
SUSPICIOUS_PATTERNS = [
    r"await\s+db\.commit\(\)",
    r"await\s+session\.commit\(\)",
    r"db\.commit\(\)",
    r"session\.commit\(\)",
]


def is_allowed(line: str) -> bool:
    return any(re.search(pattern, line) for pattern in ALLOWED_PATTERNS)


def find_suspicious_commits(file_path: Path) -> list[tuple[int, str]]:
    issues = []
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"无法读取文件 {file_path}: {e}")
        return issues

    for lineno, line in enumerate(content.splitlines(), start=1):
        if is_allowed(line):
            continue
        for pattern in SUSPICIOUS_PATTERNS:
            if re.search(pattern, line):
                issues.append((lineno, line.strip()))
                break
    return issues


def main() -> int:
    if not SERVICES_DIR.exists():
        print(f"目录不存在: {SERVICES_DIR}")
        return 1

    all_issues: list[tuple[Path, int, str]] = []
    for py_file in sorted(SERVICES_DIR.rglob("*.py")):
        if py_file.name.startswith("test_"):
            continue
        issues = find_suspicious_commits(py_file)
        for lineno, line in issues:
            all_issues.append((py_file, lineno, line))

    if not all_issues:
        print("[PASS] 未在 service 层发现非法 commit()")
        return 0

    print(f"[FAIL] 在 service 层发现 {len(all_issues)} 处非法 commit()：\n")
    for file_path, lineno, line in all_issues:
        relative = file_path.relative_to(PROJECT_ROOT)
        print(f"  {relative}:{lineno}: {line}")

    print("\n请按 docs/TRANSACTION_BOUNDARY_GUIDE.md 规范进行改造。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
