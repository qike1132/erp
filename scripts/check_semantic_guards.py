# scripts/check_semantic_guards.py
"""语义门禁：写接口授权 / 锁序 / 幂等（AST based）

为什么需要它
------------
原有 14 道门禁全部是**语法/风格**层面的（本文件是第 15 道）（长度、except 宽泛度、commit 位置…），
三类真正会出生产事故的问题一个都没有机器检查：

1. **写接口缺授权**：`fastapi_app/api/v1/router.py` 给所有业务路由统一注入了
   `Depends(get_current_user_id_write_strict)` —— 那只是**认证**（你是登录用户）。
   细粒度 RBAC（`require_permission` / `require_any_permission` / `require_superuser`）
   是每个端点自己写的，漏写不会有任何测试红：接口照样 200，只是任何登录用户
   都能改别人的数据。
2. **锁序反了**：多行锁必须全局统一顺序，某处「先锁 StockIn 再锁 Product」而
   别处「先 Product 后 StockIn」，两条路径命中同一 (product, stockin) 就互相等锁，
   PG 检出后回滚其一。这类缺陷只有在真实并发下才复现，代码读起来完全正常。
3. **建单接口无幂等**：下单/导入这类接口没有 `Idempotency-Key`，前端重试
   （超时重发、用户连点、网关重放）就会建出重复单。事后靠对账发现已经太晚。

本门禁**不修改业务代码**，只把存量登记进基线（`scripts/gate_baseline.json` 的
`semantic_guards`），新增即红。存量债要么修，要么显式豁免（见下）。

三项检查
--------
`authz_missing`
    扫描 `fastapi_app/api/v1/endpoints/**/*.py` 里的 `@router.post/put/patch/delete`。
    只要满足下列任一条件就算「有授权」：
      a. 函数签名参数默认值是 `Depends(require_permission/require_any_permission/require_superuser(...))`；
      b. 装饰器带 `dependencies=[Depends(require_*(...))]`；
      c. 函数体内出现 `require_*` 或 `resolve_production_write_scope` 调用。
    三条都不满足 → 记一条。**注意口径**：全局认证依赖不算授权，缺的是 RBAC。

`lock_order`
    同一个函数体内，「对 StockIn 取行锁」（`select(StockIn)...with_for_update()`，
    或局部变量承载的 StockIn 语句 `.with_for_update()`）出现在「对 Product 取锁」
    （`get_product_for_update(...)`）**之前** → 记一条。
    只报 `StockIn → Product` 这一个方向：反方向（Product → StockIn）是本仓统一
    约定，其余对象之间的顺序不做猜测（猜错的门禁只会被人关掉）。
    行内 `# lock-order-ok: <理由>` 可豁免（必须带理由）。

`idempotency_missing`
    `@router.post` 且**有效路径**（含 `router.py` 里的 prefix）命中建单/导入语义词
    （`orders` / `staging-orders` / `batch` / `ocr-import` / `purchase-center`）的函数，
    签名或函数体里都找不到 `Idempotency-Key` 头 / `idempotency` 字样 → 记一条。

为什么必须拼上 router.py 的 prefix
----------------------------------
下单入口是 `order.py` 里的 `@router.post("/create")`，前缀 `/orders` 配在
`router.py` 的 `include_router(..., prefix="/orders")`。只看装饰器字面量的话，
**最该被看住的那个接口恰好不含 `orders` 字样**——门禁会安静地漏掉它。

豁免清单 `scripts/allowed_semantic_guards.yaml`
-----------------------------------------------
每条必须有 `file` + `reason`（可再限定 `function` / `rule`）。**没有 reason 的条目
视为无效豁免**：在 stderr 告警，并且不生效（该违规照常上报）——否则"加一行空条目"
就成了关闭门禁的开关。

用法
----
    python scripts/check_semantic_guards.py                 # 文本报告
    python scripts/check_semantic_guards.py --json          # 机器可读（quality_gate 用）
    python scripts/check_semantic_guards.py <路径...>        # 覆盖扫描面（自检/调试）
    python scripts/check_semantic_guards.py --allowlist other.yaml

退出码
------
    0: 无违规（含全部命中豁免）
    1: 有违规
    2: 有文件 AST 解析失败，**或**扫描面为空

    解析失败必须判 2 而不是 0：解析不了的文件等于没被检查，静默当「无违规」
    就是假绿（与 check_bare_except.py 同口径）。扫描面为空同理——路径写错时
    「0 处违规」毫无意义。
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).parent.parent
ENDPOINTS_DIR = PROJECT_ROOT / "fastapi_app" / "api" / "v1" / "endpoints"
ROUTER_FILE = PROJECT_ROOT / "fastapi_app" / "api" / "v1" / "router.py"
DEFAULT_SCAN_DIRS = [PROJECT_ROOT / "fastapi_app"]
DEFAULT_ALLOWLIST = PROJECT_ROOT / "scripts" / "allowed_semantic_guards.yaml"
EXCLUDE_DIRS = {"__pycache__", "tests", "migrations"}

# 视为「写接口」的 HTTP 方法装饰器
WRITE_METHODS = {"post", "put", "patch", "delete"}

# 满足任一即认为端点声明了 RBAC（全局认证依赖不在此列，见模块 docstring）
REQUIRE_HELPERS = (
    "require_permission",
    "require_any_permission",
    "require_superuser",
)
# 函数体内出现的授权调用前缀 / 函数名
AUTHZ_CALL_PREFIX = "require_"
AUTHZ_CALL_EXTRA = ("resolve_production_write_scope",)
# `require_*` 家族里**不是授权**的成员：按前缀一律当授权会放过真缺口
# （例如只做了文件头校验的上传端点会被误判成「有权限」）。
# 授权工厂按约定都叫 require_*permission/require_superuser，故只排除具体这几个。
NON_AUTHZ_REQUIRE_HELPERS = frozenset(
    {
        "require_upload_magic",  # 文件魔数校验，失败抛 400，与授权无关
        "require_async_session_local",  # 取 sessionmaker，基础设施
        "require_async_engine",  # 取 engine，基础设施
    }
)

# 锁序检查涉及的两个锁入口
STOCKIN_LOCK_MODEL = "StockIn"
PRODUCT_LOCK_FUNC = "get_product_for_update"

# 建单/导入语义词（对**有效路径**做大小写不敏感的子串匹配）
IDEMPOTENCY_PATH_KEYWORDS = (
    "orders",
    "staging-orders",
    "batch",
    "ocr-import",
    "purchase-center",
)
IDEMPOTENCY_MARKER = "idempotency"

# 行内豁免标注（必须带理由）
LOCK_ORDER_OK_MARKERS = ("# lock-order-ok:",)


@dataclass(frozen=True)
class Violation:
    rule: str
    file: str
    line: int
    function: str
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# 有效路径解析：router.py 的 include_router(prefix=...) 必须参与拼接
# ---------------------------------------------------------------------------


def _module_prefix_map(router_file: Path = ROUTER_FILE) -> dict[str, str]:
    """返回 {端点模块名: URL 前缀}。

    只认 `from ...import <x>_router as <alias>` + `<api_router>.include_router(<alias>, prefix="/x")`
    这一对：本仓所有端点都走这条路（router.py 是唯一装配点）。解析不出来时返回空表，
    调用方退化成「只看装饰器字面量」——不会因此崩，只是覆盖面缩小。
    """
    if not router_file.is_file():
        return {}
    try:
        tree = ast.parse(router_file.read_text(encoding="utf-8"), filename=str(router_file))
    except (OSError, SyntaxError):
        return {}

    alias_to_module: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if not (node.module.endswith("endpoints") or ".endpoints." in node.module):
            continue
        for alias in node.names:
            if alias.name == "router" and alias.asname:
                # from ...endpoints.<mod> import router as <alias>
                alias_to_module[alias.asname] = node.module.rsplit(".", 1)[-1]
            elif alias.asname:
                # from ...endpoints import <mod> as <alias>（少见写法，一并兼容）
                alias_to_module[alias.asname] = alias.name

    prefixes: dict[str, str] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _call_attr(node.func) == "include_router"):
            continue
        if not node.args:
            continue
        target = node.args[0]
        if not isinstance(target, ast.Name):
            continue
        prefix = ""
        for keyword in node.keywords:
            if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant):
                if isinstance(keyword.value.value, str):
                    prefix = keyword.value.value
        module = alias_to_module.get(target.id)
        if module is not None and prefix:
            prefixes[module] = prefix
    return prefixes


def _call_attr(func: ast.expr) -> str | None:
    """取调用目标的属性名：`x.y(...)` / `y(...)` 都返回 `y`。"""
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _endpoint_module_key(rel_path: str, prefixes: dict[str, str]) -> str:
    """把端点文件路径映射到 router.py 里的模块名（包内子模块归到包名）。"""
    parts = Path(rel_path).parts
    try:
        index = parts.index("endpoints")
    except ValueError:
        return ""
    tail = parts[index + 1 :]
    if not tail:
        return ""
    if len(tail) == 1:
        return Path(tail[0]).stem
    # 包（backup/、purchase_center/）内部的子路由没有各自前缀，统一继承包前缀
    return tail[0]


# ---------------------------------------------------------------------------
# 三项检查的实现
# ---------------------------------------------------------------------------


def _is_write_route(decorator: ast.expr) -> tuple[bool, str]:
    """判断装饰器是否是 `@<x>.<post|put|patch|delete>(...)`，返回 (是否, 方法名)。"""
    if isinstance(decorator, ast.Call):
        attr = _call_attr(decorator.func)
        if attr in WRITE_METHODS:
            return True, attr
    return False, ""


def _route_path(decorator: ast.expr) -> str:
    """取装饰器里的路由路径字面量（位置参数或 path=）。"""
    if not isinstance(decorator, ast.Call):
        return ""
    candidates: list[ast.expr] = list(decorator.args[:1])
    for keyword in decorator.keywords:
        if keyword.arg == "path":
            candidates.append(keyword.value)
    for node in candidates:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
    return ""


def _is_authz_call_name(name: str) -> bool:
    """调用名是否代表授权判定（`require_*` 家族去掉非授权成员，+ 生产写范围解析）。"""
    if name in AUTHZ_CALL_EXTRA:
        return True
    if not name.startswith(AUTHZ_CALL_PREFIX):
        return False
    return name not in NON_AUTHZ_REQUIRE_HELPERS


def _depends_inner_names(node: ast.AST) -> set[str]:
    """收集 `Depends(...)` 内部引用到的依赖名。

    两种写法都要认：`Depends(require_permission("x"))`（Call）与
    `Depends(resolve_production_write_scope)`（直接引用函数对象，无调用）。
    """
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            attr = _call_attr(sub.func)
            if attr:
                names.add(attr)
        elif isinstance(sub, ast.Name):
            names.add(sub.id)
    return names


def _has_authz_dependency(node: ast.AST) -> bool:
    """该 AST 子树里是否有 `Depends(require_* / resolve_production_write_scope)`。

    按**前缀**认整族 `require_*`：本仓除 core/deps.py 的三个工厂外还有
    `backup/_deps.py` 的 `require_backup_permission`（内部转调 require_any_permission）。
    只认三个固定名字会把 16 个已按规范加权限的备份接口报成缺口，门禁随即被噪音淹掉。
    """
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        if _call_attr(sub.func) != "Depends":
            continue
        if any(_is_authz_call_name(name) for name in _depends_inner_names(sub)):
            return True
    return False


def _body_calls(body: list[ast.stmt]) -> set[str]:
    """函数体内出现的所有调用名（用于识别 require_* / resolve_production_write_scope）。"""
    names: set[str] = set()
    for stmt in body:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Call):
                attr = _call_attr(sub.func)
                if attr:
                    names.add(attr)
    return names


def check_authz(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    rel_path: str,
    *,
    module_prefix: str,
) -> list[Violation]:
    """检查单个函数是否是「写接口但缺 RBAC」。"""
    violations: list[Violation] = []
    for decorator in node.decorator_list:
        is_write, method = _is_write_route(decorator)
        if not is_write:
            continue
        route = module_prefix + _route_path(decorator)
        if _has_authz_dependency(node.args) or _has_authz_dependency(decorator):
            continue
        if any(_is_authz_call_name(name) for name in _body_calls(node.body)):
            continue
        violations.append(
            Violation(
                rule="authz_missing",
                file=rel_path,
                line=node.lineno,
                function=node.name,
                detail=f"{method.upper()} {route or '(无路径字面量)'} 未声明 RBAC 依赖",
            )
        )
    return violations


def _stockin_lock_names(body: list[ast.stmt]) -> set[str]:
    """收集函数里绑定过 `select(StockIn)...` 语句的局部变量名。

    `purchase_order_generate.py` 这类写法是 `stmt = select(StockIn)...` 之后
    `stmt.with_for_update()`，只看 with_for_update 的子表达式会漏掉它。
    """
    names: set[str] = set()
    for stmt in body:
        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            continue
        value = stmt.value
        if value is None:
            continue
        if not _mentions_name(value, STOCKIN_LOCK_MODEL):
            continue
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _mentions_name(node: ast.AST, name: str) -> bool:
    return any(isinstance(sub, ast.Name) and sub.id == name for sub in ast.walk(node))


def _lock_events(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """返回 (StockIn 加锁事件, Product 加锁事件)，每项是 (行号, 结束行号)。"""
    stockin_names = _stockin_lock_names(node.body)
    stockin_events: list[tuple[int, int]] = []
    product_events: list[tuple[int, int]] = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        attr = _call_attr(sub.func)
        end = getattr(sub, "end_lineno", None) or sub.lineno
        if attr == PRODUCT_LOCK_FUNC:
            product_events.append((sub.lineno, end))
        elif attr == "with_for_update":
            # `select(StockIn)...with_for_update()`：链式调用的子表达式里必须出现 StockIn
            receiver = sub.func.value if isinstance(sub.func, ast.Attribute) else None
            if receiver is not None and (
                _mentions_name(receiver, STOCKIN_LOCK_MODEL)
                or any(_mentions_name(receiver, name) for name in stockin_names)
            ):
                stockin_events.append((sub.lineno, end))
    return stockin_events, product_events


def _has_lock_order_ok(lines: list[str], spans: list[tuple[int, int]]) -> bool:
    """任一相关行内是否有带理由的 `# lock-order-ok:` 标注。"""
    for start, end in spans:
        for idx in range(max(start - 1, 0), min(end, len(lines))):
            text = lines[idx]
            if any(marker in text and text.split(marker, 1)[1].strip() for marker in LOCK_ORDER_OK_MARKERS):
                return True
    return False


def check_lock_order(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    rel_path: str,
    lines: list[str],
) -> list[Violation]:
    """检查单个函数内的 StockIn → Product 反序加锁。"""
    stockin_events, product_events = _lock_events(node)
    if not stockin_events or not product_events:
        return []
    first_stockin = min(stockin_events)
    first_product = min(product_events)
    if first_stockin[0] > first_product[0]:
        # 只报「StockIn 先、Product 后」这一个方向（本仓统一约定是 Product → StockIn）
        return []
    if _has_lock_order_ok(lines, [first_stockin, first_product]):
        return []
    return [
        Violation(
            rule="lock_order",
            file=rel_path,
            line=first_stockin[0],
            function=node.name,
            detail=(
                f"先锁 {STOCKIN_LOCK_MODEL}（L{first_stockin[0]}）后锁 Product"
                f"（L{first_product[0]}）；统一约定是 Product → {STOCKIN_LOCK_MODEL}"
            ),
        )
    ]


def _has_idempotency(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """签名或函数体里是否出现幂等相关标记（Idempotency-Key 头 / idempotency 字样）。"""
    scopes: list[ast.AST] = [node.args, *node.body]
    for scope in scopes:
        for sub in ast.walk(scope):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                if IDEMPOTENCY_MARKER in sub.value.lower():
                    return True
            elif (isinstance(sub, ast.Name) and IDEMPOTENCY_MARKER in sub.id.lower()) or (isinstance(sub, ast.Attribute) and IDEMPOTENCY_MARKER in sub.attr.lower()) or (isinstance(sub, ast.arg) and IDEMPOTENCY_MARKER in sub.arg.lower()):
                return True
    return False


def check_idempotency(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    rel_path: str,
    *,
    module_prefix: str,
) -> list[Violation]:
    """检查单个 POST 建单接口是否缺幂等键。"""
    for decorator in node.decorator_list:
        is_write, method = _is_write_route(decorator)
        # 幂等只对**创建**语义的 POST 有意义：PUT/PATCH/DELETE 本身按资源幂等
        if not is_write or method != "post":
            continue
        route = module_prefix + _route_path(decorator)
        lowered = route.lower()
        if not any(keyword in lowered for keyword in IDEMPOTENCY_PATH_KEYWORDS):
            continue
        if _has_idempotency(node):
            continue
        return [
            Violation(
                rule="idempotency_missing",
                file=rel_path,
                line=node.lineno,
                function=node.name,
                detail=f"POST {route} 无 Idempotency-Key 支持（重试会产生重复单）",
            )
        ]
    return []


# ---------------------------------------------------------------------------
# 文件级扫描
# ---------------------------------------------------------------------------


def scan_file(
    path: Path,
    rel_path: str,
    lines: list[str] | None = None,
    *,
    module_prefix: str = "",
    enable_authz: bool = True,
) -> tuple[list[Violation], str | None]:
    """扫描单个文件，返回 (违规列表, 解析错误)。"""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, OSError) as exc:
        return [], f"{exc.__class__.__name__}: {exc}"
    if lines is None:
        lines = source.splitlines()

    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if enable_authz:
            violations.extend(check_authz(node, rel_path, module_prefix=module_prefix))
        violations.extend(check_lock_order(node, rel_path, lines))
        violations.extend(check_idempotency(node, rel_path, module_prefix=module_prefix))
    return violations, None


def collect_py_files(scan_dirs: list[Path]) -> list[Path]:
    """收集待扫描的 .py 文件（显式传入文件时必须真的扫它，否则会假绿）。"""
    files: list[Path] = []
    for d in scan_dirs:
        if not d.exists():
            continue
        if d.is_file():
            if d.suffix == ".py" and not any(part in EXCLUDE_DIRS for part in d.parts):
                files.append(d)
            continue
        for p in d.rglob("*.py"):
            if any(part in EXCLUDE_DIRS for part in p.parts):
                continue
            files.append(p)
    return files


# ---------------------------------------------------------------------------
# 豁免清单
# ---------------------------------------------------------------------------


def load_allowlist(path: Path | None) -> list[dict[str, str]]:
    """加载豁免清单。**缺 reason 的条目视为无效**：stderr 告警且不生效。"""
    if path is None or not path.is_file():
        return []
    try:
        import yaml

        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError) as exc:
        print(f"[WARN] 豁免清单不可读/不可解析，按「无豁免」处理：{exc}", file=sys.stderr)
        return []

    raw_entries = payload.get("exemptions") if isinstance(payload, dict) else None
    if not isinstance(raw_entries, list):
        print(
            f"[WARN] 豁免清单 {path.name} 缺少 exemptions 列表，按「无豁免」处理",
            file=sys.stderr,
        )
        return []

    entries: list[dict[str, str]] = []
    for index, raw in enumerate(raw_entries, start=1):
        if not isinstance(raw, dict):
            print(f"[WARN] 第 {index} 条豁免不是映射，已忽略", file=sys.stderr)
            continue
        entry = {key: str(value) for key, value in raw.items() if value is not None}
        reason = entry.get("reason", "").strip()
        file_value = entry.get("file", "").strip()
        if not file_value:
            print(f"[WARN] 第 {index} 条豁免缺 file，已忽略", file=sys.stderr)
            continue
        if not reason:
            # 空理由豁免 = 无审计留痕的静默绕过，本脚本不接受
            print(
                f"[WARN] 第 {index} 条豁免 ({file_value}) 缺 reason，**视为无效豁免**（该违规照常上报）",
                file=sys.stderr,
            )
            continue
        entries.append(entry)
    return entries


def _norm(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def is_exempted(violation: Violation, entries: list[dict[str, str]]) -> bool:
    """违规是否命中豁免条目（file 必填；function / rule 可选收窄）。"""
    target = _norm(violation.file)
    for entry in entries:
        entry_file = _norm(entry.get("file", ""))
        if not entry_file or not (target == entry_file or target.endswith(entry_file)):
            continue
        if entry.get("function") and entry["function"] != violation.function:
            continue
        if entry.get("rule") and entry["rule"] != violation.rule:
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="语义门禁（授权 / 锁序 / 幂等）")
    parser.add_argument("paths", nargs="*", help="待扫描目录或文件（默认 fastapi_app）")
    parser.add_argument("--json", action="store_true", help="机器可读输出（quality_gate 用）")
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST,
        help="豁免清单 YAML（每条必须有 file + reason）",
    )
    args = parser.parse_args()

    explicit_paths = bool(args.paths)
    scan_dirs = [Path(p).resolve() for p in args.paths] or DEFAULT_SCAN_DIRS
    # 显式传路径（--probe-dir 自检 / 单文件调试）时三项检查都跑：
    # 探针目录不在 endpoints/ 下，若继续按默认口径限制授权检查就永远扫不到违规。
    prefixes = _module_prefix_map()

    files = collect_py_files(scan_dirs)
    if not files:
        print(
            f"[ERROR] 扫描面为空：{[str(p) for p in scan_dirs]} 下没有可扫描的 .py 文件"
            "（解析失败/路径写错都不等于「无违规」）",
            file=sys.stderr,
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "authz_missing": [],
                        "lock_order": [],
                        "idempotency_missing": [],
                        "total": 0,
                        "parse_errors": 0,
                        "scanned": 0,
                    },
                    ensure_ascii=False,
                )
            )
        return 2

    allowlist = load_allowlist(args.allowlist)

    all_violations: list[Violation] = []
    parse_errors: list[tuple[str, str]] = []
    for path in files:
        # 统一用 posix 分隔符：豁免清单是手写的（永远是 "/"），Windows 下若上报
        # 反斜杠路径，同一条豁免在本地与 CI 会有一个匹配不上。
        try:
            rel_path = path.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            rel_path = path.as_posix()
        module_key = _endpoint_module_key(rel_path, prefixes)
        in_endpoints = ENDPOINTS_DIR in path.parents
        violations, err = scan_file(
            path,
            rel_path,
            module_prefix=prefixes.get(module_key, ""),
            enable_authz=explicit_paths or in_endpoints,
        )
        if err is not None:
            parse_errors.append((rel_path, err))
            continue
        all_violations.extend(violations)

    effective = [v for v in all_violations if not is_exempted(v, allowlist)]

    buckets: dict[str, list[Violation]] = {
        "authz_missing": [],
        "lock_order": [],
        "idempotency_missing": [],
    }
    for violation in effective:
        buckets.setdefault(violation.rule, []).append(violation)

    if parse_errors:
        print(
            f"[WARN] {len(parse_errors)} 个文件 AST 解析失败（未检查，按失败处理）:",
            file=sys.stderr,
        )
        for rel_path, err in parse_errors[:10]:
            print(f"  {rel_path}: {err}", file=sys.stderr)

    if args.json:
        print(
            json.dumps(
                {
                    "authz_missing": [v.to_dict() for v in buckets["authz_missing"]],
                    "lock_order": [v.to_dict() for v in buckets["lock_order"]],
                    "idempotency_missing": [
                        v.to_dict() for v in buckets["idempotency_missing"]
                    ],
                    "total": len(effective),
                    "parse_errors": len(parse_errors),
                    "scanned": len(files),
                },
                ensure_ascii=False,
            )
        )
        if parse_errors:
            return 2
        return 0 if not effective else 1

    if not effective:
        print(
            f"[PASS] 语义门禁无新增问题（扫描 {len(files)} 个文件；豁免清单 "
            f"{len(allowlist)} 条）"
        )
        return 2 if parse_errors else 0

    print(
        f"[FAIL] 语义门禁发现 {len(effective)} 处问题"
        f"（授权 {len(buckets['authz_missing'])} / "
        f"锁序 {len(buckets['lock_order'])} / "
        f"幂等 {len(buckets['idempotency_missing'])}）:\n"
    )
    for rule, title in (
        ("authz_missing", "写接口缺 RBAC"),
        ("lock_order", "锁序反了（StockIn → Product）"),
        ("idempotency_missing", "建单接口缺幂等"),
    ):
        for violation in buckets[rule]:
            print(f"  {violation.file}:{violation.line} [{title}] {violation.function}()")
            print(f"    {violation.detail}")
        if buckets[rule]:
            print()
    return 2 if parse_errors else 1


if __name__ == "__main__":
    sys.exit(main())
