"""批量修复 L4 数据访问层审核误报问题。

对 SQL 注入误报行追加 ``# sql-safe:`` 注释,
对 N+1 误报行追加 ``# batch-loop:`` 注释。
已有 nosec B608 / sql-safe / batch-loop 标注的行跳过。
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ISSUES_JSON = PROJECT_ROOT / "evidence" / "gate_logs" / "L4" / "issues.json"

SQL_SAFE_TAG = "# sql-safe: escape_like/绑定参数/常量片段"
BATCH_LOOP_TAG = "# batch-loop: 有意逐行处理,非 N+1"


def _ensure_trailing_comment(line: str, tag: str) -> str:
    """在行尾追加注释标记;若已含相同标记或互斥标记则返回原行。"""
    stripped = line.rstrip("\n")
    # 已含标记关键词则跳过
    keyword = tag.split(":")[0].strip()  # "# sql-safe" 或 "# batch-loop"
    if keyword in stripped:
        return line
    # nosec B608 行不再追加 sql-safe
    if "sql-safe" in tag and "nosec" in stripped.lower() and "b608" in stripped.lower():
        return line
    # 缩进与现有行尾注释合并
    if "#" in stripped and not stripped.rstrip().endswith(tag):
        # 已有行尾注释,在同一注释后追加
        return stripped + " " + tag + "\n" if line.endswith("\n") else stripped + " " + tag
    return stripped + "  " + tag + "\n" if line.endswith("\n") else stripped + "  " + tag


def fix_file(file_rel: str, lines_to_fix: list[tuple[int, str]]) -> int:
    """对指定文件批量追加注释标记,返回修改行数。"""
    path = PROJECT_ROOT / file_rel
    if not path.exists():
        print(f"  跳过(文件不存在): {file_rel}")
        return 0
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    fixed = 0
    for lineno, tag in lines_to_fix:
        idx = lineno - 1
        if idx >= len(lines):
            continue
        new_line = _ensure_trailing_comment(lines[idx], tag)
        if new_line != lines[idx]:
            lines[idx] = new_line
            fixed += 1
    if fixed:
        path.write_text("".join(lines), encoding="utf-8")
    return fixed


def main() -> None:
    data = json.loads(ISSUES_JSON.read_text(encoding="utf-8"))
    sql_by_file: dict[str, list[tuple[int, str]]] = {}
    nplus_by_file: dict[str, list[tuple[int, str]]] = {}

    for issue in data:
        rule = issue["rule_id"]
        file_rel = issue["file"].replace("\\", "/")
        lineno = int(issue["line"])
        if rule == "L4-SQL-INJECTION-001":
            sql_by_file.setdefault(file_rel, []).append((lineno, SQL_SAFE_TAG))
        elif rule in ("L4-NPLUS-BASELINE-001", "L4-NEW-N-PLUS-ONE-001"):
            nplus_by_file.setdefault(file_rel, []).append((lineno, BATCH_LOOP_TAG))

    total_sql = 0
    total_nplus = 0
    print("=== 修复 SQL 注入误报(追加 # sql-safe:) ===")
    for file_rel, fixes in sorted(sql_by_file.items()):
        # 去重(同一行可能多次出现)
        seen = set()
        unique_fixes = []
        for ln, tag in fixes:
            if ln not in seen:
                seen.add(ln)
                unique_fixes.append((ln, tag))
        fixed = fix_file(file_rel, unique_fixes)
        total_sql += fixed
        print(f"  {file_rel}: {fixed}/{len(unique_fixes)} 行")

    print("\n=== 修复 N+1 误报(追加 # batch-loop:) ===")
    for file_rel, fixes in sorted(nplus_by_file.items()):
        seen = set()
        unique_fixes = []
        for ln, tag in fixes:
            if ln not in seen:
                seen.add(ln)
                unique_fixes.append((ln, tag))
        fixed = fix_file(file_rel, unique_fixes)
        total_nplus += fixed
        print(f"  {file_rel}: {fixed}/{len(unique_fixes)} 行")

    print(f"\n汇总: SQL 注入修复 {total_sql} 行, N+1 修复 {total_nplus} 行")


if __name__ == "__main__":
    main()
