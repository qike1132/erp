#!/usr/bin/env python3
r"""
Service 层事务提交检测脚本

扫描 fastapi_app/services/ 下所有 .py 文件，发现并报告 service 层函数中
直接使用 await db.commit() / await session.commit() 的代码位置。

允许的情况（见 ALLOWED_PATTERNS，逐行匹配后跳过）：
- 嵌套事务：await nested.commit()
- 独立短 session：await short_session.commit()
- 下划线开头的 session：await _session.commit()
- **整行**注释（形如 ^\s*#，例如被注释掉的旧代码）
- 测试文件（test_*.py）

**行内注释不是豁免**。2026-10-01 删掉了两条静默旁路：
- r"#.*commit\(" ：只要行内出现 “…commit(” 就整行跳过。实测从未命中过合法场景，
  却让 `await db.commit()  # 顺手 commit(一下)` 这类写法逃过门禁。
- r"#\s*independent[-_]transaction" ：与 docs/TRANSACTION_BOUNDARY_GUIDE.md §2.2
  「脚本**不会**因为该注释而跳过」直接矛盾，曾静默豁免 3 处真实提交。
例外标记仍然是行尾的 `# manual-tx: <理由>`，但它**只作为评审说明**，不改变判定
（例外必须持续可见，见 TRANSACTION_BOUNDARY_GUIDE.md §2.2）。

用法：
    python scripts/check_service_commit.py              # 人类可读报告
    python scripts/check_service_commit.py --json       # 机器可读（quality_gate.py 语义解析用）
    python scripts/check_service_commit.py --self-test  # 自检：制造违规并断言被检出

机器可读契约（--json）：stdout 恰好是一个 JSON 对象
    {"violations": [{"file": str, "line": int, "text": str}, ...], "total": int}
再加默认的人类可读输出与退出码保持原样（老调用方不受影响）。

退出码：
- 0：未发现非法 commit（或 --self-test 通过）
- 1：发现非法 commit（或 --self-test 失败）
- 2：环境异常（服务层目录缺失）
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVICES_DIR = PROJECT_ROOT / "fastapi_app" / "services"

# 失败提示引用的文档（docs/TRANSACTION_BOUNDARY_GUIDE.md 会回引本脚本，改路径要同步）
DOC_HINT = "docs/TRANSACTION_BOUNDARY_GUIDE.md"

# 允许的 commit 模式（忽略）。
# ⚠️ 这里**不得**再出现「行内注释即豁免」的宽规则：那是一条静默旁路，会把真实提交
# 连同注释一起放过（见模块 docstring 与 --self-test 用例 1/2）。
ALLOWED_PATTERNS = [
    r"nested\.commit\(",          # 嵌套事务
    r"short_session\.commit\(",   # 独立短 session
    r"_session\.commit\(",        # 下划线开头的 session
    r"^\s*#",                     # 整行注释（整行都是注释，不含可执行代码）
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


def scan_label(targets: list[Path]) -> str:
    """把扫描目标渲染成一行相对路径标签（供 --json 的 scan_dir 字段）。"""
    labels = []
    for target in targets:
        try:
            labels.append(target.relative_to(PROJECT_ROOT).as_posix())
        except ValueError:
            labels.append(target.as_posix())
    return ",".join(labels)


def scan_services(targets: list[Path] | None = None) -> list[tuple[str, int, str]]:
    """扫描服务层，返回 [(相对路径(POSIX), 行号, 行内容), ...]。

    targets 缺省为 [fastapi_app/services]；显式传入时用于自检/调试
    （quality_gate.py --probe-dir 会把范围换成临时目录）。
    """
    findings: list[tuple[str, int, str]] = []
    files: list[Path] = []
    for target in targets or [SERVICES_DIR]:
        if target.is_file():
            files.append(target)
        else:
            files.extend(sorted(target.rglob("*.py")))
    for py_file in files:
        if py_file.name.startswith("test_"):
            continue
        for lineno, line in find_suspicious_commits(py_file):
            try:
                rel = py_file.relative_to(PROJECT_ROOT).as_posix()
            except ValueError:
                rel = py_file.as_posix()
            findings.append((rel, lineno, line))
    return findings


def report_json(findings: list[tuple[str, int, str]], scan_dir: str) -> None:
    """机器可读输出：stdout 恰好一个 JSON 对象（quality_gate.py 只认它，不抠文本）。"""
    payload = {
        "violations": [
            {"file": file, "line": lineno, "text": text}
            for file, lineno, text in findings
        ],
        "total": len(findings),
        "scan_dir": scan_dir,
    }
    print(json.dumps(payload, ensure_ascii=False))


def report_human(findings: list[tuple[str, int, str]]) -> int:
    if not findings:
        print("[PASS] 未在 service 层发现非法 commit()")
        return 0

    print(f"[FAIL] 在 service 层发现 {len(findings)} 处非法 commit()：\n")
    for file, lineno, line in findings:
        print(f"  {file}:{lineno}: {line}")

    print(f"\n请按 {DOC_HINT} 规范进行改造。")
    return 1


# ---------------------------------------------------------------------------
# 自检（--self-test）：故意制造违规形态，断言「该报的报、不该报的不报」。
#
# 所有输出行都以 [SELFTEST] 开头，且**不出现** "[FAIL]" 字面量 —— 门禁 runner
# 历史上用 COUNT_RE = r"\[FAIL\][^\d]*(\d+)\s*(?:处|个)" 从子脚本 stdout 里
# 抠计数（P0-11 已删掉该正则，改为语义解析 --json），这里保持同样的形状约定：
# 任何按文本抠数的老工具都不会把自检行误读成「违规数」。
# ---------------------------------------------------------------------------

_RETIRED_PATTERNS = (
    r"#\s*independent[-_]transaction",
    r"#.*commit\(",
)


def _selftest_cases() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    with tempfile.TemporaryDirectory(prefix="csc-selftest-") as tmp:
        tmpdir = Path(tmp)

        def probe(name: str, body: str) -> Path:
            path = tmpdir / name
            path.write_text(body, encoding="utf-8")
            return path

        # 1) 行内 independent-transaction 不再豁免（本次删掉的旁路之一）
        found = find_suspicious_commits(
            probe(
                "probe_independent.py",
                "async def f(db):\n"
                "    await db.commit()  # independent-transaction; manual-tx: 旧写法\n",
            )
        )
        cases.append(
            ("行内 independent-transaction 不再豁免", len(found) == 1, f"命中 {len(found)} 处")
        )

        # 2) 行内出现 "commit(" 不再让整行豁免（删掉的宽规则）
        found = find_suspicious_commits(
            probe(
                "probe_inline_paren.py",
                "async def f(db):\n"
                "    await db.commit()  # 顺手 commit(一下)\n",
            )
        )
        cases.append(("行内含 commit( 不再豁免整行", len(found) == 1, f"命中 {len(found)} 处"))

        # 3) manual-tx 只是评审说明，不改变判定
        found = find_suspicious_commits(
            probe(
                "probe_manual_tx.py",
                "async def f(db):\n"
                "    await db.commit()  # manual-tx: 有正经理由也必须继续可见\n",
            )
        )
        cases.append(("manual-tx 标注不豁免（例外持续可见）", len(found) == 1, f"命中 {len(found)} 处"))

        # 4) 整行注释仍然豁免（不含可执行代码）
        found = find_suspicious_commits(
            probe(
                "probe_whole_line.py",
                "async def f(db):\n    # await db.commit()\n    return 1\n",
            )
        )
        cases.append(("整行注释仍豁免", not found, f"命中 {len(found)} 处"))

        # 5) 嵌套事务 / 独立短 session 仍然豁免
        found = find_suspicious_commits(
            probe(
                "probe_nested.py",
                "async def f(db, nested, short_session):\n"
                "    await nested.commit()\n"
                "    await short_session.commit()\n",
            )
        )
        cases.append(("nested / short_session 仍豁免", not found, f"命中 {len(found)} 处"))

        # 6) 行号必须准确（第 3 行）
        found = find_suspicious_commits(
            probe(
                "probe_lineno.py",
                "async def f(db):\n    await db.flush()\n    await db.commit()\n",
            )
        )
        lineno_ok = [lineno for lineno, _ in found] == [3]
        cases.append(("行号准确", lineno_ok, f"行号={[lineno for lineno, _ in found]}"))

    # 7) 退役的旁路模式不得回归
    retired = [p for p in ALLOWED_PATTERNS if p in _RETIRED_PATTERNS]
    cases.append(("退役的注释旁路未复活", not retired, f"复活={retired}"))

    # 8) 服务目录存在（否则真实扫描会静默为空 = 假绿）
    cases.append(
        (
            "服务层目录存在",
            SERVICES_DIR.is_dir(),
            SERVICES_DIR.relative_to(PROJECT_ROOT).as_posix(),
        )
    )

    return cases


def run_self_test() -> int:
    print("[SELFTEST] check_service_commit.py 自检")
    ok = True
    cases = _selftest_cases()
    for name, passed, detail in cases:
        flag = "PASS" if passed else "FAIL"
        suffix = f"（{detail}）" if detail else ""
        print(f"[SELFTEST] {flag} {name}{suffix}")
        ok = ok and passed
    print(f"[SELFTEST] {'全部通过' if ok else '存在失败项'}：{len(cases)} 项")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="service 层非法 commit() 检测（门禁）")
    parser.add_argument(
        "paths",
        nargs="*",
        help="待扫描目录/文件（缺省 fastapi_app/services；自检/调试时可覆盖）",
    )
    parser.add_argument(
        "--json", action="store_true", help="机器可读输出（供 quality_gate.py 语义解析）"
    )
    parser.add_argument(
        "--self-test", action="store_true", help="自检：制造违规并断言被检出"
    )
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    targets = [Path(p).resolve() for p in args.paths] or [SERVICES_DIR]
    missing = [t for t in targets if not t.exists()]
    if missing:
        message = f"路径不存在: {[str(t) for t in missing]}"
        if args.json:
            print(
                json.dumps(
                    {"violations": [], "total": 0, "error": message}, ensure_ascii=False
                )
            )
        else:
            print(message)
        return 2

    findings = scan_services(targets)
    if args.json:
        report_json(findings, scan_label(targets))
        return 1 if findings else 0
    return report_human(findings)


if __name__ == "__main__":
    sys.exit(main())