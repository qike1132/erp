#!/usr/bin/env python
"""前端 API 端点与后端 OpenAPI 的契约真校验（P1-12）。

背景
----
前端 frontend-vite/src/api/*.ts 里声明的每个 /api/v1/... 端点，后端不一定真的提供。
此前没有任何门禁把两边对上：check-api-alignment.mjs 只管「移动端有没有绕过 API 层」，
check-route-alignment.mjs 只管前端路由。本脚本补上真正的端到端契约校验：把前端 API 层
真实调用的端点，与后端 fastapi_app.main:app.openapi() 的路径集合逐条比对。

判定规则
--------
1. 只断言字面量端点（如 get('/reports/order-logs')）；
2. 路径里带插值的模板端点（路径片段由变量拼接而成）只打印、不判定 ——
   前端在字符串里拼参数，静态无法可靠还原路径形状，硬判定会引入假阳性；
3. 命中 KNOWN_ABSENT 豁免表的端点打印 [WARN] 并附理由，不计入失败；
   --strict-allowlist 时「豁免条目已不再缺失」（僵尸条目）也判失败；
4. 注释先被剥离（按字符替换为空格，行号不变），注释里出现的伪端点不会造成假阳性。

退出码
------
0 = 所有字面量端点都能在后端 OpenAPI 里找到
1 = 存在后端不提供的端点（或 --strict-allowlist 下的僵尸豁免）
2 = 环境异常（前端 API 目录缺失、OpenAPI 生成失败、--openapi 文件不可解析）

用法
----
python scripts/check_openapi_frontend_alignment.py [--openapi spec.json] [--export spec.json]
       [--api-dir DIR] [--json] [--verbose] [--strict-allowlist]
"""
from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from bisect import bisect_right
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_API_DIR = PROJECT_ROOT / "frontend-vite" / "src" / "api"
API_PREFIX = "/api/v1"

_BT = chr(96)  # 反引号：前端模板字符串的定界符，源码里不直接写它
_QUOTE_SET = "'\"" + _BT
TEMPLATE_MARK = "$" + "{"

# 端点调用形态：可选的方法前缀（get<T>('/x')）＋ 引号字符串字面量，字面量以 / 开头。
_ENDPOINT_RE = re.compile(
    r"(?:\b(get|post|put|patch|delete|del|upload|download|head|options)\b\s*(?:<[^<>()]*>)?\s*\(\s*)?"
    r"([" + _QUOTE_SET + r"])"
    r"(/[^" + _QUOTE_SET + r"\s\\]{1,300})\2",
    re.IGNORECASE,
)

# 已登记的后端缺失端点（豁免表）。每条都必须写明出处与理由；后端补齐后必须删除本条。
# 2026-10-02（P1-12 follow-up）：表内唯一的豁免项 /api/v1/reports/customer-names 已随死端点
# 声明（frontend-vite/src/api/report.ts 的 customerNames）一并删除，本表据此清空并保持为空。
# 新增豁免必须附出处与理由，并在后端补齐（或前端删除死端点）后立即移除；
# --strict-allowlist 会把「已不再缺失」的僵尸条目判失败。
KNOWN_ABSENT: dict[str, str] = {}


class SpecError(RuntimeError):
    """无法取得后端 OpenAPI 规范。"""


class SourceError(RuntimeError):
    """前端 API 源码不可用。"""


def _rel(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def strip_comments(src: str) -> str:
    """把注释字符替换成空格（保留换行，长度不变），使后续匹配的行号与原文一致。"""
    out = list(src)
    i = 0
    n = len(src)
    quote = ""
    while i < n:
        ch = src[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in _QUOTE_SET:
            quote = ch
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            nxt = src[i + 1]
            if nxt == "/":
                while i < n and src[i] != "\n":
                    out[i] = " "
                    i += 1
                continue
            if nxt == "*":
                out[i] = " "
                out[i + 1] = " "
                i += 2
                while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                    if src[i] != "\n":
                        out[i] = " "
                    i += 1
                if i < n:
                    out[i] = " "
                    out[i + 1] = " "
                    i += 2
                continue
        i += 1
    return "".join(out)


def normalize_endpoint(raw: str) -> str | None:
    """把源码里的端点字符串规范成 OpenAPI 路径形状；返回 None 表示不是端点。"""
    if not raw.startswith("/"):
        return None
    path = raw.split("?", 1)[0].split("#", 1)[0]
    path = re.sub(r"\$\{[^}]*\}", "{param}", path)
    if not path.startswith(API_PREFIX):
        path = API_PREFIX + path
    if path.endswith("/") and path != API_PREFIX:
        path = path.rstrip("/")
    if len(path) <= len(API_PREFIX) + 1:
        return None
    if "." in path.rsplit("/", 1)[-1]:
        # 形如 /api/v1/foo.py 的字符串是文件路径，不是接口
        return None
    return path


def iter_ts_files(api_dir: Path) -> list[Path]:
    if not api_dir.is_dir():
        raise SourceError("前端 API 目录不存在: " + str(api_dir))
    files = sorted(p for p in api_dir.rglob("*.ts") if p.is_file())
    if not files:
        raise SourceError("前端 API 目录下没有 .ts 文件: " + str(api_dir))
    return files


def extract_endpoints(api_dir: Path) -> tuple[list[dict], list[dict]]:
    """返回 (字面量端点, 模板端点)，每条形如 {file, line, method, raw, endpoint}。"""
    literals: list[dict] = []
    templates: list[dict] = []
    for path in iter_ts_files(api_dir):
        text = path.read_text(encoding="utf-8", errors="replace")
        stripped = strip_comments(text)
        newlines = [i for i, ch in enumerate(stripped) if ch == "\n"]
        rel = _rel(path)
        for match in _ENDPOINT_RE.finditer(stripped):
            raw = match.group(3)
            method = (match.group(1) or "").upper() or None
            if method is None and not raw.startswith(API_PREFIX):
                # 裸字符串必须自带 /api/v1 前缀，否则可能只是普通 UI 路径，不能当端点
                continue
            endpoint = normalize_endpoint(raw)
            if endpoint is None:
                continue
            item = {
                "file": rel,
                "line": bisect_right(newlines, match.start()) + 1,
                "method": method,
                "raw": raw,
                "endpoint": endpoint,
            }
            (templates if TEMPLATE_MARK in raw else literals).append(item)
    literals.sort(key=lambda it: (it["file"], it["line"]))
    templates.sort(key=lambda it: (it["file"], it["line"]))
    return literals, templates


def build_spec() -> dict:
    """按当前代码现算 OpenAPI（import 期间的日志一律重定向到 stderr，保持 stdout 干净）。"""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    try:
        with contextlib.redirect_stdout(sys.stderr):
            import fastapi_app.main as app_main

            spec = app_main.app.openapi()
    except Exception as exc:  # noqa: BLE001 - 任何 import/生成失败都属环境异常
        raise SpecError(
            "无法生成 OpenAPI（import fastapi_app.main 失败）: " + type(exc).__name__ + ": " + str(exc)
        ) from exc
    return spec


def load_spec_file(path: Path) -> dict:
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SpecError("无法解析 --openapi 文件 " + str(path) + ": " + type(exc).__name__ + ": " + str(exc)) from exc
    if not isinstance(spec, dict):
        raise SpecError("--openapi 文件不是 JSON 对象: " + str(path))
    return spec


def spec_paths(spec: dict) -> set[str]:
    paths = spec.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise SpecError("OpenAPI 规范里没有 paths（空规范无法校验契约）")
    return {str(p) for p in paths}


def audit(literals: list[dict], backend: set[str], allowlist: dict[str, str]) -> dict:
    missing = []
    for item in literals:
        if item["endpoint"] in backend:
            continue
        reason = allowlist.get(item["endpoint"])
        entry = dict(item)
        entry["allowlisted"] = reason is not None
        entry["reason"] = reason
        missing.append(entry)
    allowlisted = [m for m in missing if m["allowlisted"]]
    unallowlisted = [m for m in missing if not m["allowlisted"]]
    stale = sorted(p for p in allowlist if p in backend)
    return {"missing": missing, "allowlisted": allowlisted, "unallowlisted": unallowlisted, "stale": stale}


def render_human(report: dict, templates: list[dict], verbose: bool) -> None:
    print("=== 前端端点 / 后端 OpenAPI 契约检查 ===")
    print("后端 OpenAPI 路径数: " + str(report["backendPaths"]))
    print("前端字面量端点: " + str(report["frontendLiteral"]))
    print("前端模板端点: " + str(report["frontendTemplate"]) + "（仅列出，不判定）")
    for item in report["allowlisted"]:
        print("[WARN] 已登记豁免（后端未实现）: " + str(item["endpoint"]))
        print("       出处: " + str(item["file"]) + ":" + str(item["line"]))
        print("       理由: " + str(item["reason"]))
    for path in report["staleAllowlist"]:
        print("[WARN] 豁免条目已失效（后端已提供该端点，请从 KNOWN_ABSENT 删除）: " + path)
    if verbose:
        for item in templates:
            print("  [模板] " + str(item["file"]) + ":" + str(item["line"]) + " " + str(item["endpoint"]))
    problems = list(report["unallowlisted"])
    if report["status"] == "fail":
        for path in report["staleAllowlist"]:
            if path not in [p["endpoint"] for p in problems]:
                problems.append({"file": "<KNOWN_ABSENT>", "line": 0, "method": None, "endpoint": path})
    if problems:
        print("[FAIL] 发现 " + str(len(problems)) + " 个前端端点在后端 OpenAPI 中不存在:")
        for item in problems:
            print(
                "  "
                + str(item["file"])
                + ":"
                + str(item["line"])
                + "  "
                + str(item["method"] or "--")
                + " "
                + str(item["endpoint"])
            )
        print("请让后端提供该路由（或在前端删除死端点）；确需豁免时在 KNOWN_ABSENT 登记理由。")
        return
    print("[PASS] 所有前端字面量端点均能在后端 OpenAPI 中找到（豁免 " + str(len(report["allowlisted"])) + " 条）。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="前端 API 端点与后端 OpenAPI 契约校验")
    parser.add_argument("--openapi", type=Path, default=None, help="改用已导出的 openapi.json（离线校验）")
    parser.add_argument("--export", type=Path, default=None, help="把本次使用的 OpenAPI 规范写到该文件")
    parser.add_argument("--api-dir", type=Path, default=DEFAULT_API_DIR, help="前端 API 层目录（默认 frontend-vite/src/api）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出（机器可读）")
    parser.add_argument("--verbose", action="store_true", help="额外打印全部模板端点")
    parser.add_argument(
        "--strict-allowlist",
        action="store_true",
        help="豁免条目变成僵尸（后端已提供该端点）时判失败",
    )
    args = parser.parse_args(argv)

    report: dict = {
        "status": "pass",
        "apiDir": _rel(args.api_dir),
        "specSource": "app.openapi()" if args.openapi is None else _rel(args.openapi),
        "backendPaths": 0,
        "frontendLiteral": 0,
        "frontendTemplate": 0,
        "missing": [],
        "allowlisted": [],
        "unallowlisted": [],
        "staleAllowlist": [],
    }

    try:
        literals, templates = extract_endpoints(args.api_dir)
        spec = load_spec_file(args.openapi) if args.openapi is not None else build_spec()
        backend = spec_paths(spec)
    except (SpecError, SourceError) as exc:
        report["status"] = "error"
        report["error"] = str(exc)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        print("[ERROR] " + str(exc), file=sys.stderr)
        return 2

    if args.export is not None:
        args.export.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = audit(literals, backend, KNOWN_ABSENT)
    report.update(
        {
            "backendPaths": len(backend),
            "frontendLiteral": len(literals),
            "frontendTemplate": len(templates),
            "missing": result["missing"],
            "allowlisted": result["allowlisted"],
            "unallowlisted": result["unallowlisted"],
            "staleAllowlist": result["stale"],
        }
    )
    failed = bool(result["unallowlisted"]) or (args.strict_allowlist and bool(result["stale"]))
    report["status"] = "fail" if failed else "pass"

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        render_human(report, templates, args.verbose)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
