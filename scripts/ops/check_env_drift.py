# scripts/ops/check_env_drift.py
"""环境变量漂移检查（S3：配置单一来源）。

背景
----
本仓库有四份 env 文件，但**只有项目根 .env 会被加载**：

  - .env                    ← 唯一被 `fastapi_app/core/config.py:10 load_dotenv()` 加载
  - .env.example            ← 模板（唯一被 git 跟踪的 env 文件）
  - .env.production         ← 不被加载、不随包分发（唯一读者是 scripts/switch_env.py）
  - config/.env.production  ← 随加密备份分发的灾备件
                              （services/backup/_constants.py:101）

实测（2026-09-30）：.env.production 缺模板 92 键、config/.env.production 缺 94 键，
含全部 BACKUP_*（约 70 个）。而 `core/config.py` 的 SettingsConfigDict 是
`extra="ignore"`，缺键会**静默走默认值**——最危险的是
BACKUP_ENCRYPTION_ENABLED 默认 true 而 BACKUP_ENCRYPTION_PASSWORD 缺失，
备份会静默降级为不加密（详见 docs/ops/2026-09-30-credential-rotation-runbook.md §2.3）。

本脚本只做**只读比对**，绝不改写任何 env 文件。

用法:
    python scripts/ops/check_env_drift.py          # 全量（本地；不存在的文件自动跳过）
    python scripts/ops/check_env_drift.py --ci     # 只比「代码引用 与 模板」，无 .env 也能跑
    python scripts/ops/check_env_drift.py --json
    python scripts/ops/check_env_drift.py --verbose

退出码:
    0: 无漂移
    1: 发现漂移
    2: 环境/解析异常
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[2]

TEMPLATE = PROJECT_ROOT / ".env.example"
# (路径, 说明, 缺模板键的严重级别)
#   .env 缺键 = 走代码默认值（合法，但需逐项评估）→ warn
#   两个 .env.production 缺键 = 灾备/参考件不完整，恢复时静默丢配置 → fail
TARGETS: tuple[tuple[Path, str, str], ...] = (
    (PROJECT_ROOT / ".env", "运行时唯一被加载（权威）", "warn"),
    (PROJECT_ROOT / ".env.production", "不被加载、不随包分发", "fail"),
    (PROJECT_ROOT / "config" / ".env.production", "随加密备份分发的灾备件", "fail"),
)

# 与 scripts/check_bom.py 的扫描口径保持一致，并排除非运行时目录。
EXCLUDE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".mypy_cache", ".ruff_cache", ".pytest_cache",
    ".archive", ".workbuddy", ".trae", ".superpowers", ".qoder",
    ".codeartsdoer", ".freebuff", ".reasonix", ".lean-ctx", ".resultverify",
    ".workbuddy-ai", ".arts", ".codebuddy", ".graphflow",
    "_qa_tmp", "_ops", "backups", "temp", "evidence", "static", "docs",
    "tests", "migrations", "graphflow-out", "logs",
}

KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=")
COMMENTED_KEY_RE = re.compile(r"^#\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")

# 代码里读取环境变量的常见写法。env_str/env_int/env_float/env_bool 是
# scripts/ops/watchdog.py 的取值辅助函数（键名以字面量传入）。
CODE_REFS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:os\.getenv|os\.environ\.get|environ\.get|getenv|"
        r"env_str|env_int|env_float|env_bool)\s*\(\s*[\"']([A-Z][A-Z0-9_]*)[\"']"
    ),
    re.compile(r"os\.environ\s*\[\s*[\"']([A-Z][A-Z0-9_]*)[\"']\s*\]"),
)

# 测试/脚本/宿主环境变量：不属于应用运行时配置，不参与模板漂移判定。
IGNORED_PREFIXES = (
    "TEST_", "STRESS_", "E2E_", "CONTRACT_", "ERP_SIM_", "PERF_",
    "BENCH_", "LOAD_", "QA_", "CI_", "GITHUB_", "PYTEST_",
)
IGNORED_KEYS = {
    # 脚本/宿主专用（非应用运行时配置）：
    #   API_BASE=scripts/perf_optimization/benchmark_core_ops.py:20
    #   API_HOST=start.py:67            NEW_ADMIN_PASSWORD=scripts/reset_admin_password.py:70
    #   PGDATA=scripts/pg_tune.py:37    ERP_*=scripts/build_and_release.py:40/41/106
    #   BO_E2E_FRONT=_beile_detail_align_check.py:22
    "API_BASE", "API_HOST", "BO_E2E_FRONT", "ERP_API_URL", "ERP_AUTH_TOKEN",
    "ERP_FRONTEND_URL", "NEW_ADMIN_PASSWORD", "PGDATA",
    "APPDATA", "COMSPEC", "COMPUTERNAME", "COVERAGE_FILE", "COVERAGE_MIN",
    "DISPLAY", "HOSTNAME", "LANG", "LC_ALL", "LOCALAPPDATA", "NUMBER_OF_PROCESSORS",
    "OS", "PATH", "PATHEXT", "PROCESSOR_ARCHITECTURE", "PROGRAMDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "PYTHONDONTWRITEBYTECODE", "PYTHONIOENCODING", "PYTHONPATH",
    "PYTHONUNBUFFERED", "PYTHONUTF8", "PYTHONWARNINGS", "SYSTEMDRIVE", "SYSTEMROOT",
    "TEMP", "TMP", "TZ", "USERDOMAIN", "USERNAME", "USERPROFILE", "VIRTUAL_ENV",
    "WINDIR", "CI",
}


def is_ignored(key: str) -> bool:
    return key in IGNORED_KEYS or key.startswith(IGNORED_PREFIXES)


def parse_env_file(path: Path) -> tuple[dict[str, str], set[str]]:
    """返回 (已声明键→值, 以注释形式出现的键)。"""
    declared: dict[str, str] = {}
    commented: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RuntimeError(f"无法读取 {path}: {exc}") from exc

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            match = COMMENTED_KEY_RE.match(line)
            if match:
                commented.add(match.group(1))
            continue
        match = KEY_RE.match(line)
        if match:
            key = match.group(1)
            value = line.split("=", 1)[1]
            # 去掉行尾注释（仅当 # 前有空白时，避免误伤值里的 #）
            value = re.split(r"\s+#", value, maxsplit=1)[0]
            declared[key] = value.strip()
    return declared, commented


def iter_py_files() -> list[Path]:
    files: list[Path] = []
    for path in PROJECT_ROOT.rglob("*.py"):
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        name = path.name
        if name.startswith("test_") or name == "conftest.py":
            continue
        files.append(path)
    return files


def scan_code_refs() -> dict[str, tuple[str, int]]:
    """扫描代码里的环境变量引用，返回 键 → (相对路径, 行号) 首次命中。"""
    refs: dict[str, tuple[str, int]] = {}
    for path in iter_py_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in CODE_REFS:
                for key in pattern.findall(line):
                    refs.setdefault(key, (rel, lineno))
    return refs


def build_report(ci_only: bool) -> dict[str, object]:
    if not TEMPLATE.exists():
        raise RuntimeError(f"模板不存在：{TEMPLATE}")
    template_keys, template_commented = parse_env_file(TEMPLATE)
    known = set(template_keys) | template_commented

    code_refs = scan_code_refs()
    code_keys = set(code_refs)

    sections: list[dict[str, object]] = []

    # A. 代码读取但模板未声明
    undocumented = sorted(
        k for k in code_keys if k not in known and not is_ignored(k)
    )
    sections.append(
        {
            "title": "代码读取但模板未声明",
            "level": "fail",
            "items": [f"{k}  ({code_refs[k][0]}:{code_refs[k][1]})" for k in undocumented],
            "keys": undocumented,
        }
    )

    # B. 模板中以注释形式存在（实际不生效，走默认值）
    commented_hits = sorted(k for k in code_keys if k in template_commented and k not in template_keys)
    sections.append(
        {
            "title": "模板中以注释形式存在（不生效，代码走默认值）",
            "level": "warn",
            "items": commented_hits,
            "keys": commented_hits,
        }
    )

    # C. 各目标 env 文件缺模板键 / 有模板外键
    if not ci_only:
        for path, desc, severity in TARGETS:
            if not path.exists():
                sections.append(
                    {
                        "title": f"{path.relative_to(PROJECT_ROOT).as_posix()}（{desc}）",
                        "level": "skip",
                        "items": ["文件不存在，跳过"],
                        "keys": [],
                    }
                )
                continue
            keys, _ = parse_env_file(path)
            missing = sorted(set(template_keys) - set(keys))
            extra = sorted(k for k in set(keys) - known if not is_ignored(k))
            sections.append(
                {
                    "title": f"{path.relative_to(PROJECT_ROOT).as_posix()} 缺模板键（{desc}）",
                    "level": severity,
                    "items": missing,
                    "keys": missing,
                }
            )
            sections.append(
                {
                    "title": f"{path.relative_to(PROJECT_ROOT).as_posix()} 有模板外键",
                    "level": "warn",
                    "items": extra,
                    "keys": extra,
                }
            )

    # D. 模板声明但代码从未读取（可能已废弃）
    never_read = sorted(
        k for k in template_keys if k not in code_keys and not is_ignored(k)
    )
    sections.append(
        {
            "title": "模板声明但代码未直接读取（可能废弃，也可能是脚本/外部消费）",
            "level": "warn",
            "items": never_read,
            "keys": never_read,
        }
    )

    total = sum(
        len(section["keys"]) for section in sections if section["level"] == "fail"
    )
    return {
        "template": str(TEMPLATE.relative_to(PROJECT_ROOT).as_posix()),
        "template_key_count": len(template_keys),
        "code_ref_count": len(code_keys),
        "sections": sections,
        "fail_count": total,
    }


def print_report(report: dict[str, object], *, verbose: bool) -> None:
    print("=" * 78)
    print("环境变量漂移检查（单一来源 = .env.example）")
    print("=" * 78)
    print(f"模板键数：{report['template_key_count']}    代码引用键数：{report['code_ref_count']}")
    print()
    sections = report["sections"]
    assert isinstance(sections, list)
    for section in sections:
        level = section["level"]
        keys = section["keys"]
        assert isinstance(keys, list)
        if level == "skip":
            print(f"  [跳过] {section['title']}")
            continue
        if not keys:
            if level == "fail":
                print(f"  [OK]   {section['title']}：无")
            continue
        marker = "!!" if level == "fail" else "??"
        print(f"  [{marker}] {section['title']}：{len(keys)} 处")
        limit = len(keys) if verbose else 12
        for item in keys[:limit]:
            print(f"         - {item}")
        if len(keys) > limit:
            print(f"         … 另有 {len(keys) - limit} 处（--verbose 查看全部）")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description="环境变量漂移检查（只读）")
    parser.add_argument("--ci", action="store_true", help="只比「代码引用 与 模板」，可移植")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--verbose", action="store_true", help="打印全部条目")
    args = parser.parse_args()

    try:
        report = build_report(ci_only=args.ci)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report, verbose=args.verbose)

    total = report["fail_count"]
    if total:
        print(f"[FAIL] 发现 {total} 处环境变量漂移（上方 !! 分类）")
        print("修复：把缺失键补进对应文件；模板只写占位值，真实值留在 .env。")
        return 1
    print("[PASS] 未发现环境变量漂移")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
