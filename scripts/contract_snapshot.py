"""接口契约快照工具：录制 / 比对后端响应结构，拦住契约漂移。

为什么需要它
------------
本项目出现过这类事故：前端 3000 是最新源码，后端 5002 是几小时前的旧进程，
响应里少了字段 → **前端不报错、页面静默空白**。没有契约比对时，这种问题只能靠人眼发现。

设计原则
--------
1. **不存响应体**：快照只保存 HTTP 状态码 + 结构签名（键路径与类型），
   避免把真实业务数据（客户名、产品名、金额）提交进 git。
   需要比对具体取值时，用配置里的 `value_checks` 白名单显式登记。
2. **结构优先**：数组只取首个元素做代表，不比对条数（条数随数据变化）。
3. **变体键标记**：`request_id` / `*_at` 这类每次都变的键标记为 `<volatile>`，
   仍参与"键是否存在"的比对，但不参与取值比对。
4. **不比对取值**：默认只比对状态码 + 结构。结构变了 = 契约变了，一定有下游风险。
5. **变更类端点需 Origin**：配置里 `method: POST` + `body` 的端点会被如实发出；
   由于它们受 CSRF 保护，携带 Bearer 的请求会自动附 `Origin`（`--origin`，需在
   后端 CORS 白名单内），否则生产环境会被中间件 403。

用法
----
    python scripts/contract_snapshot.py --list                 # 列出配置的端点
    python scripts/contract_snapshot.py --record               # 录制基线（改动前）
    python scripts/contract_snapshot.py --check                # 比对（改动后 / CI）
    python scripts/contract_snapshot.py --check --json          # 机器可读结果
    python scripts/contract_snapshot.py --check --only products_list customers_list

退出码：0 = 一致；1 = 有漂移；2 = 环境/鉴权错误（保守失败）
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "tests" / "contract" / "endpoints.yaml"
DEFAULT_SNAPSHOT_DIR = PROJECT_ROOT / "tests" / "contract" / "snapshots"
DEFAULT_BASE_URL = "http://127.0.0.1:5002"
SCHEMA_VERSION = 1
TOKEN_CACHE = PROJECT_ROOT / "_tok.txt"


# ============================================================
# 配置
# ============================================================
@dataclass
class Endpoint:
    name: str
    path: str
    method: str = "GET"
    query: dict[str, Any] = field(default_factory=dict)
    body: Any = None  # POST 等变更类端点的 JSON 请求体（GET 为 None）
    auth: bool = True


@dataclass
class Config:
    endpoints: list[Endpoint]
    unstable_keys: list[str]
    max_depth: int
    value_checks: list[str]


def load_config(path: Path) -> Config:
    if not path.exists():
        raise FileNotFoundError(f"找不到契约配置：{path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    endpoints = []
    for item in raw.get("endpoints") or []:
        if not item.get("name") or not item.get("path"):
            raise ValueError(f"端点配置缺少 name/path：{item}")
        endpoints.append(
            Endpoint(
                name=item["name"],
                path=item["path"],
                method=(item.get("method") or "GET").upper(),
                query=item.get("query") or {},
                body=item.get("body"),
                auth=bool(item.get("auth", True)),
            )
        )
    return Config(
        endpoints=endpoints,
        unstable_keys=list(raw.get("unstable_keys") or []),
        max_depth=int(raw.get("max_depth") or 6),
        value_checks=list(raw.get("value_checks") or []),
    )


# ============================================================
# 鉴权
# ============================================================
def resolve_token(explicit: str | None) -> str | None:
    """按 显式参数 → 环境变量 → **现铸** → 缓存文件 的顺序取 token。

    顺序很重要：`_tok.txt` 里的 token 会过期，优先用缓存会得到一排静默的 401。
    现铸成本很低（两次 DB 查询），所以优先现铸。
    """
    import os

    if explicit:
        return explicit
    env_token = os.environ.get("CONTRACT_TOKEN")
    if env_token:
        return env_token
    fresh = mint_token()
    if fresh:
        return fresh
    if TOKEN_CACHE.exists():
        cached = TOKEN_CACHE.read_text(encoding="utf-8").strip()
        if cached:
            print("[WARN] 现铸失败，回退使用 _tok.txt 缓存（可能已过期）", file=sys.stderr)
            return cached
    return None


def mint_token() -> str | None:
    """直接铸一个管理员 token（不经过登录接口，无密码依赖）。"""
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from sqlalchemy import create_engine, text

        from fastapi_app.core.auth.token import create_access_token
        from fastapi_app.core.config import settings

        engine = create_engine(settings.DATABASE_URL)
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT id FROM \"user\" WHERE username='admin'")
            ).fetchone()
        if row is None:
            return None
        return create_access_token({"sub": str(row[0])})
    except Exception as exc:  # broad-except: 铸 token 失败时应降级为"仅测无鉴权端点"而非崩溃
        print(f"[WARN] 铸 token 失败（{type(exc).__name__}: {exc}），将只比对无需鉴权的端点", file=sys.stderr)
        return None


# ============================================================
# 结构签名
# ============================================================
def _type_name(value: Any) -> str:
    if isinstance(value, bool):  # 必须在 int 之前，bool 是 int 的子类
        return "bool"
    if value is None:
        return "null"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return type(value).__name__


def is_unstable(key: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(key, pat) for pat in patterns)


def shape_signature(
    value: Any,
    unstable: list[str],
    max_depth: int,
    prefix: str = "",
    depth: int = 0,
    out: set[str] | None = None,
) -> list[str]:
    """返回排序后的 '键路径:类型' 集合。数组以其首个元素为代表。"""
    if out is None:
        out = set()
    label = prefix or "<root>"
    if depth > max_depth:
        out.add(f"{label}:<depth-limit>")
        return sorted(out)

    if isinstance(value, dict):
        if not value:
            out.add(f"{label}:object{{}}")
        for key, sub in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if is_unstable(str(key), unstable):
                out.add(f"{path}:<volatile>")
            else:
                shape_signature(sub, unstable, max_depth, path, depth + 1, out)
    elif isinstance(value, (list, tuple)):
        if not value:
            out.add(f"{label}:array[0]")
        else:
            shape_signature(value[0], unstable, max_depth, f"{prefix}[]", depth + 1, out)
    else:
        out.add(f"{label}:{_type_name(value)}")
    return sorted(out)


def dig(value: Any, dotted: str) -> Any:
    """按点分路径取值，路径中使用 [] 表示数组首元素。"""
    cur = value
    for part in dotted.split("."):
        if part.endswith("[]"):
            part = part[:-2]
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and cur:
            cur = cur[0].get(part) if isinstance(cur[0], dict) else None
        else:
            return None
        if cur is None:
            return None
    return cur


# ============================================================
# 请求与快照
# ============================================================
def build_client(base_url: str, timeout: float) -> httpx.Client:
    # trust_env=False 是关键：本机存在 HTTP_PROXY，会把 127.0.0.1 也代理走 → 502
    return httpx.Client(base_url=base_url, timeout=timeout, trust_env=False)


def fetch(client: httpx.Client, ep: Endpoint, headers: dict[str, str]) -> tuple[int, Any, str]:
    """返回 (状态码, 解析后的 JSON 或 None, 错误信息)。

    变更类端点（POST 等）会携带配置里的 JSON ``body``；纯 GET 端点 ``body`` 为
    ``None``，不改变既有行为。
    """
    try:
        resp = client.request(
            ep.method,
            ep.path,
            params=ep.query or None,
            json=ep.body if ep.body is not None else None,
            headers=headers,
        )
    except httpx.HTTPError as exc:
        return 0, None, f"{type(exc).__name__}: {exc}"
    if resp.status_code >= 400:
        return resp.status_code, None, resp.text[:200]
    try:
        return resp.status_code, resp.json(), ""
    except ValueError:
        return resp.status_code, None, "响应不是合法 JSON"


def make_snapshot(ep: Endpoint, status: int, body: Any, cfg: Config) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "name": ep.name,
        "method": ep.method,
        "path": ep.path,
        "query": ep.query,
        "auth": ep.auth,
        "http_status": status,
        "shape": shape_signature(body, cfg.unstable_keys, cfg.max_depth),
        "value_checks": {path: dig(body, path) for path in cfg.value_checks},
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _shape_map(shape: list[str]) -> dict[str, str]:
    """把 '键路径:类型' 列表还原为 {路径: 类型}。"""
    out: dict[str, str] = {}
    for item in shape:
        path, _, typ = item.rpartition(":")
        out[path] = typ
    return out


# ============================================================
# 容差规则 —— 避免数据波动造成误报
#
# 契约门禁最容易死于"误报太多、没人看"。以下两种形态本质是"录制时数据恰好如此"，
# 不代表结构约定，因此不参与比对（但键本身仍会被记录）：
#   1. 类型为 null   ：首元素该字段恰好为 null，不代表它一定是 null
#   2. 空数组 array[0]：录制时数组为空，无法得知元素结构
# 对应的"反向"情况（实际为空、基线有结构）同样容忍。
# ============================================================
def _tolerant_paths(shape_map: dict[str, str]) -> list[str]:
    return [p for p, t in shape_map.items() if t in ("null", "array[0]")]


def _is_tolerated(path: str, tolerant: list[str]) -> bool:
    return any(path == p or path.startswith(f"{p}[]") or path.startswith(f"{p}.") for p in tolerant)


def diff_snapshot(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    if expected.get("http_status") != actual.get("http_status"):
        status_diff = [f"状态码 {expected.get('http_status')} → {actual.get('http_status')}"]
    else:
        status_diff = []

    exp = _shape_map(expected.get("shape") or [])
    act = _shape_map(actual.get("shape") or [])
    tolerant = _tolerant_paths(exp) + _tolerant_paths(act)

    diffs = list(status_diff)
    for path in sorted(set(exp) - set(act)):
        if not _is_tolerated(path, tolerant):
            diffs.append(f"字段消失: {path}:{exp[path]}")
    for path in sorted(set(act) - set(exp)):
        if not _is_tolerated(path, tolerant):
            diffs.append(f"新增字段: {path}:{act[path]}")
    for path in sorted(set(exp) & set(act)):
        if exp[path] != act[path] and exp[path] != "null" and act[path] != "null":
            diffs.append(f"类型变化: {path} {exp[path]} → {act[path]}")

    for key, exp_val in (expected.get("value_checks") or {}).items():
        act_val = (actual.get("value_checks") or {}).get(key)
        if exp_val != act_val:
            diffs.append(f"取值变化 {key}: {exp_val!r} → {act_val!r}")
    return diffs


# ============================================================
# 命令
# ============================================================
def run_record(args, cfg: Config, endpoints: list[Endpoint]) -> int:
    headers = _auth_headers(args, cfg)
    written = 0
    args.snapshot_dir.mkdir(parents=True, exist_ok=True)
    with build_client(args.base_url, args.timeout) as client:
        for ep in endpoints:
            status, body, err = fetch(client, ep, headers)
            if err:
                print(f"  [ERROR] {ep.name:<34} {status or '-'} {err}")
                continue
            snap = make_snapshot(ep, status, body, cfg)
            (args.snapshot_dir / f"{ep.name}.json").write_text(
                json.dumps(snap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            written += 1
            print(f"  [OK]    {ep.name:<34} {status}  shape={len(snap['shape'])} 键")
    print(f"\n已录制 {written}/{len(endpoints)} 个快照 → {args.snapshot_dir}")
    return 0 if written == len(endpoints) else 2


def _auth_headers(args, cfg: Config) -> dict[str, str]:
    headers: dict[str, str] = {}
    if any(ep.auth for ep in cfg.endpoints):
        token = resolve_token(args.token)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    # 变更类请求（POST 等）受 CSRF 保护：携带 Bearer 的请求需附一个后端 CORS
    # 白名单内的 Origin，否则生产环境 CSRF 中间件会直接 403。仅当存在非 GET 端点时
    # 才附带，避免污染纯只读录制的请求头。
    if any(ep.method != "GET" for ep in cfg.endpoints):
        headers["Origin"] = args.origin
    return headers


def run_check(args, cfg: Config, endpoints: list[Endpoint]) -> int:
    headers = _auth_headers(args, cfg)
    results: list[dict[str, Any]] = []
    with build_client(args.base_url, args.timeout) as client:
        for ep in endpoints:
            snap_path = args.snapshot_dir / f"{ep.name}.json"
            if not snap_path.exists():
                results.append({"name": ep.name, "status": "missing-snapshot", "diffs": ["无快照文件"]})
                continue
            expected = json.loads(snap_path.read_text(encoding="utf-8"))
            status, body, err = fetch(client, ep, headers)
            if err:
                results.append(
                    {"name": ep.name, "status": "error", "http_status": status, "diffs": [err]}
                )
                continue
            actual = make_snapshot(ep, status, body, cfg)
            diffs = diff_snapshot(expected, actual)
            results.append(
                {
                    "name": ep.name,
                    "status": "drift" if diffs else "match",
                    "http_status": status,
                    "diffs": diffs,
                }
            )

    drifted = [r for r in results if r["status"] in ("drift", "missing-snapshot")]
    errored = [r for r in results if r["status"] == "error"]

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "check",
                    "base_url": args.base_url,
                    "total": len(results),
                    "matched": sum(1 for r in results if r["status"] == "match"),
                    "drifted": len(drifted),
                    "errored": len(errored),
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for r in results:
            mark = {"match": "[OK]   ", "drift": "[DRIFT]", "error": "[ERROR]",
                    "missing-snapshot": "[NOSNAP]"}[r["status"]]
            print(f"  {mark} {r['name']}")
            for d in r["diffs"]:
                print(f"           └─ {d}")
        print(
            f"\n合计 {len(results)}：一致 {len(results) - len(drifted) - len(errored)}，"
            f"漂移 {len(drifted)}，错误 {len(errored)}"
        )

    if errored:
        return 2
    return 1 if drifted else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="接口契约快照录制/比对")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--record", action="store_true", help="录制基线快照")
    mode.add_argument("--check", action="store_true", help="与基线比对")
    mode.add_argument("--list", action="store_true", help="列出配置的端点")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--only", nargs="*", help="只处理指定端点名")
    parser.add_argument("--token", help="显式 Bearer token")
    parser.add_argument(
        "--origin",
        default="http://localhost",
        help="变更类请求附带的 Origin 头（需在后端 CORS 白名单内，供 CSRF 校验）",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"[ERROR] 读取配置失败：{exc}", file=sys.stderr)
        return 2

    endpoints = [e for e in cfg.endpoints if not args.only or e.name in args.only]
    if not endpoints:
        print("[ERROR] 过滤后没有可处理的端点", file=sys.stderr)
        return 2

    if args.list:
        print(f"共 {len(endpoints)} 个端点（配置：{args.config}）")
        for ep in endpoints:
            print(f"  {ep.name:<34} {ep.method} {ep.path}  auth={ep.auth}  q={ep.query or '{}'}")
        return 0

    # --json 模式下 stdout 必须是**纯 JSON**（机器消费方会直接 json.loads），
    # 因此把人类可读的前导信息改走 stderr。
    info = (lambda m: print(m, file=sys.stderr)) if args.json else print
    info(f"目标 {args.base_url}  端点 {len(endpoints)} 个  模式 {'录制' if args.record else '比对'}")
    if args.record:
        return run_record(args, cfg, endpoints)
    return run_check(args, cfg, endpoints)


if __name__ == "__main__":
    raise SystemExit(main())
