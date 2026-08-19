"""L5 API 契约与版本兼容审核层执行器。

前后端对齐脚本执行 / 契约快照录制与对比 / 错误码统一审查 / 版本兼容审查。

约束:
    - 复用存量 ``frontend-vite/scripts/check-api-alignment.mjs``
      与 ``check-route-alignment.mjs``
    - 契约快照基于实际 HTTP 请求录制,归档至 ``evidence/contract_snapshots/``
    - v2 不得破坏 v1 契约,v2 新接口须标注版本与迁移说明

任务来源: ``.codeartsdoer/specs/prod_code_review/tasks.md`` 第 6 节。
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from scripts.prod_audit.base.issue_builder import IssueBuilder
from scripts.prod_audit.base.layer_base import (
    AuditContext,
    AuditIssue,
    EvidenceType,
    LayerBase,
    LayerResult,
    LayerStatus,
    Severity,
)

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
"""项目根目录(``D:\\erp_system``)。"""

FRONTEND_DIR: Path = PROJECT_ROOT / "frontend-vite"
"""前端工作目录。"""

FASTAPI_APP_DIR: Path = PROJECT_ROOT / "fastapi_app"
ENDPOINTS_V1_DIR: Path = FASTAPI_APP_DIR / "api" / "v1" / "endpoints"
ENDPOINTS_V2_DIR: Path = FASTAPI_APP_DIR / "api" / "v2" / "endpoints"
FRONTEND_SRC_DIR: Path = FRONTEND_DIR / "src"

DEFAULT_OWNER: str = "api-contract-reviewer"
DEFAULT_DUE_DATE: str = "2026-09-30"

# 子进程超时(秒): node 对齐脚本 / HTTP 录制
_TOOL_TIMEOUT: int = 300
_HTTP_TIMEOUT: int = 30

# 前后端对齐脚本路径
_API_ALIGNMENT_SCRIPT: Path = FRONTEND_DIR / "scripts" / "check-api-alignment.mjs"
_ROUTE_ALIGNMENT_SCRIPT: Path = FRONTEND_DIR / "scripts" / "check-route-alignment.mjs"

# 核心接口契约快照清单(用于录制与对比)
_CORE_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("GET", "/api/v1/orders"),
    ("GET", "/api/v1/purchase-plan"),
    ("GET", "/api/v1/purchase-orders"),
    ("GET", "/api/v1/customer-sampling"),
    ("GET", "/api/v1/dashboard/stats"),
    ("GET", "/api/v1/stock/inventory"),
)

# 统一错误响应须含字段
_REQUIRED_ERROR_FIELDS: frozenset[str] = frozenset({"code", "message", "detail"})

# 允许的 HTTP 状态码白名单
# 200/201/204: 成功类  400/401/403/404/422/409/416: 客户端错误类
# 202: 已接受(异步任务)  303: 重定向  429: 限流  500/503/504: 服务端错误类
_ALLOWED_STATUS_CODES: frozenset[int] = frozenset({
    200, 201, 202, 204, 303,
    400, 401, 403, 404, 409, 416, 422, 429,
    500, 503, 504,
})

# 裸字符串异常模式(raise ValueError("...") / raise Exception("..."))
_RAW_EXCEPTION_RE = re.compile(
    r"raise\s+\w*Exception\w*\(\s*[\"'][^\"']*[\"']\s*\)"
)

# FastAPI 路由装饰器
_ROUTE_DECORATOR_RE = re.compile(
    r"@\w+\.(get|post|put|patch|delete)\s*\(\s*[\"']([^\"']+)[\"']"
)

# 前端 API 调用模式: axios.get('/api/v1/...') / fetch('/api/v1/...') / request.get(...)
_FRONTEND_API_CALL_RE = re.compile(
    r"(?:axios|fetch|request|http|api)\s*(?:\.\w+|\()\s*[\"']([\"'\/]?api\/v\d+[^\"']*)[\"']"
)

# 同名但用途不同的 Schema 豁免列表(前后端各自独立定义, 不构成契约差异)
# key: Schema 名称, value: 豁免原因
_SCHEMA_NAME_EXEMPTIONS: frozenset[str] = frozenset({
    "MonthlySummary",  # 前端为月报汇总, 后端为生产计划月度汇总, 用途不同
    "ActionResponse",  # 后端多模块各自定义通用操作响应, 字段集不同属正常
})


class L5ApiContract(LayerBase):
    """L5 API 契约与版本兼容审核层执行器。

    聚合 4 个子检查:
        - 路由对齐(前后端 API/路由一致)
        - Schema 一致性(Pydantic 响应模型 vs 前端 TypeScript 接口)
        - 错误码统一(统一格式 + 白名单状态码)
        - 版本兼容(v2 不破坏 v1 契约)
    """

    layer_id: str = "L5"
    layer_name: str = "API 契约与版本兼容审核"
    weight: float = 0.08

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    async def run(self, context: AuditContext) -> LayerResult:
        """执行 L5 全部子检查并归档证据。"""
        started_at = datetime.now(UTC)
        builder = IssueBuilder()
        raw_outputs: dict[str, str] = {}

        checks: list[tuple[str, object]] = [
            ("route_alignment", self._check_route_alignment(builder)),
            ("schema_consistency", self._check_schema_consistency(builder)),
            ("error_codes", self._check_error_codes(builder)),
            ("version_compatibility", self._check_version_compatibility(builder)),
        ]

        all_issues: list[AuditIssue] = []
        for name, coro in checks:
            try:
                issues, raw = await coro  # type: ignore[arg-type]
            except Exception as exc:
                issues = [
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.HIGH,
                        file=str(PROJECT_ROOT),
                        line=1,
                        description=f"子检查 {name} 执行失败: {exc}",
                        suggestion="检查对齐脚本/AST 扫描依赖与路径",
                        rule_id=f"L5-{name.upper()}-EXEC-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                ]
                raw = f"EXECUTION_ERROR: {exc}"
            all_issues.extend(issues)
            raw_outputs[name] = raw

        # 门禁校验: critical/high 阻断
        is_green = self.check_gate(all_issues, threshold=Severity.HIGH)
        status = LayerStatus.PASSED if is_green else LayerStatus.BLOCKED

        evidence_path = await self._archive_evidence(context, raw_outputs, all_issues)

        return LayerResult(
            layer_id=self.layer_id,
            layer_name=self.layer_name,
            status=status,
            issues=all_issues,
            evidence_path=str(evidence_path),
            started_at=started_at,
            finished_at=datetime.now(UTC),
            weight=self.weight,
        )

    # ------------------------------------------------------------------
    # 6.1 路由对齐(前后端 API/路由一致)
    # ------------------------------------------------------------------

    async def _check_route_alignment(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """执行前后端 API/路由对齐脚本并解析输出。

        复用 ``check-api-alignment.mjs`` 与 ``check-route-alignment.mjs``。
        """
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        for script, rule_id, label in (
            (_API_ALIGNMENT_SCRIPT, "L5-API-MISALIGN-001", "API 对齐"),
            (_ROUTE_ALIGNMENT_SCRIPT, "L5-ROUTE-MISALIGN-001", "路由对齐"),
        ):
            if not script.exists():
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.MEDIUM,
                        file=str(script.relative_to(PROJECT_ROOT).as_posix()),
                        line=1,
                        description=f"{label}脚本缺失: {script.name}",
                        suggestion="确认 frontend-vite/scripts/ 下脚本存在",
                        rule_id=rule_id,
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )
                raw_parts.append(f"{script.name}: SCRIPT_MISSING")
                continue

            cmd = ["node", str(script)]
            try:
                proc = await asyncio.to_thread(
                    subprocess.run,
                    cmd,
                    capture_output=True,
                    encoding="utf-8",
                    cwd=str(FRONTEND_DIR),
                    timeout=_TOOL_TIMEOUT,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.MEDIUM,
                        file=str(script.relative_to(PROJECT_ROOT).as_posix()),
                        line=1,
                        description=f"{label}脚本执行超时(>{_TOOL_TIMEOUT}s)",
                        suggestion="检查脚本性能或增大超时阈值",
                        rule_id=rule_id,
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )
                raw_parts.append(f"{script.name}: TIMEOUT")
                continue

            raw = proc.stdout + proc.stderr
            raw_parts.append(f"--- {script.name} ---\n{raw}")
            for line in raw.splitlines():
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                # 对齐脚本输出差异行(含 "diff"/"mismatch"/"missing"/"✗"/"FAIL")
                if re.search(r"(?i)\b(diff|mismatch|missing|fail|✗|error)\b", line_stripped):
                    issues.append(
                        builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.MEDIUM,
                            file=str(script.relative_to(PROJECT_ROOT).as_posix()),
                            line=1,
                            description=f"{label}差异: {line_stripped}",
                            suggestion="同步前后端 API/路由定义",
                            rule_id=rule_id,
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )

        return issues, "\n\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 6.2 Schema 一致性(Pydantic 响应模型 vs 前端 TypeScript 接口)
    # ------------------------------------------------------------------

    async def _check_schema_consistency(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """对比后端 Pydantic 响应模型字段与前端 TypeScript 接口字段。

        策略:
            - AST 提取 ``fastapi_app/schemas/`` 下 Pydantic 模型字段名
            - 正则提取 ``frontend-vite/src/`` 下 TypeScript interface/type 字段名
            - 同名模型字段集合不一致则产出 issue
        """
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        backend_models = self._extract_pydantic_models()
        frontend_interfaces = self._extract_ts_interfaces()

        raw_parts.append(f"backend_models: {json.dumps(sorted(backend_models), ensure_ascii=False)}")
        raw_parts.append(
            f"frontend_interfaces: {json.dumps(sorted(frontend_interfaces), ensure_ascii=False)}"
        )

        # 同名模型对比字段集合
        common_names = set(backend_models) & set(frontend_interfaces)
        for name in sorted(common_names):
            # 跳过同名但用途不同的 Schema(前后端各自独立定义)
            if name in _SCHEMA_NAME_EXEMPTIONS:
                raw_parts.append(f"SKIP {name}: 同名豁免(用途不同)")
                continue
            b_fields = backend_models[name]
            f_fields = frontend_interfaces[name]
            if b_fields != f_fields:
                missing_in_frontend = b_fields - f_fields
                missing_in_backend = f_fields - b_fields
                desc_parts: list[str] = []
                if missing_in_frontend:
                    desc_parts.append(f"前端缺失字段: {sorted(missing_in_frontend)}")
                if missing_in_backend:
                    desc_parts.append(f"后端缺失字段: {sorted(missing_in_backend)}")
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.HIGH,
                        file=f"schemas/{name}.py ↔ src/types/{name}.ts",
                        line=1,
                        description=(
                            f"Schema {name} 字段不一致: " + "; ".join(desc_parts)
                        ),
                        suggestion="同步前后端 Schema 定义并更新契约快照",
                        rule_id="L5-SCHEMA-DIFF-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )

        return issues, "\n".join(raw_parts)

    def _extract_pydantic_models(self) -> dict[str, set[str]]:
        """AST 提取 ``fastapi_app/schemas/`` 下 Pydantic 模型字段名。"""
        models: dict[str, set[str]] = {}
        schemas_dir = FASTAPI_APP_DIR / "schemas"
        if not schemas_dir.exists():
            return models
        for py_file in schemas_dir.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                # 仅处理含 BaseModel 基类的类
                bases = {
                    b.id for b in node.bases if isinstance(b, ast.Name)
                }
                if "BaseModel" not in bases:
                    continue
                fields: set[str] = set()
                for stmt in node.body:
                    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                        fields.add(stmt.target.id)
                if fields:
                    models[node.name] = fields
        return models

    def _extract_ts_interfaces(self) -> dict[str, set[str]]:
        """正则提取 ``frontend-vite/src/`` 下 TypeScript interface/type 字段名。

        使用括号匹配正确处理嵌套对象类型(如 ``products: { ... }``),
        避免 ``[^}]*`` 在首个 ``}`` 处提前终止导致字段提取不完整。
        """
        interfaces: dict[str, set[str]] = {}
        if not FRONTEND_SRC_DIR.exists():
            return interfaces
        # 匹配 interface/type 声明头部
        decl_head_re = re.compile(
            r"(?:interface|type)\s+(\w+)\s*(?:=\s*)?\{",
            re.MULTILINE,
        )
        field_re = re.compile(r"^\s*(?:readonly\s+)?(\w+)\s*[?:]", re.MULTILINE)
        for ts_file in FRONTEND_SRC_DIR.rglob("*.ts"):
            if "node_modules" in ts_file.parts:
                continue
            try:
                source = ts_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for m in decl_head_re.finditer(source):
                name = m.group(1)
                # 从 `{` 之后开始, 用括号匹配找到对应的 `}`
                body_start = m.end()
                body = self._extract_balanced_braces(source, body_start)
                if body is None:
                    continue
                fields = {fm.group(1) for fm in field_re.finditer(body)}
                if fields:
                    # 同名合并(多文件定义取并集)
                    interfaces[name] = interfaces.get(name, set()) | fields
        return interfaces

    @staticmethod
    def _extract_balanced_braces(source: str, start: int) -> str | None:
        """从 ``source[start-1] == '{'`` 之后开始, 返回到匹配 ``}`` 的内容。

        正确处理嵌套 ``{}``/``[]``/``()`` 与字符串字面量。
        """
        if start <= 0 or source[start - 1] != "{":
            return None
        depth = 1
        i = start
        in_string = False
        string_char = ""
        while i < len(source) and depth > 0:
            ch = source[i]
            if in_string:
                if ch == "\\":
                    i += 2
                    continue
                if ch == string_char:
                    in_string = False
            elif ch in ("'", '"', "`"):
                in_string = True
                string_char = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        if depth != 0:
            return None
        return source[start : i - 1]

    # ------------------------------------------------------------------
    # 6.3 错误码统一(统一格式 + 白名单状态码)
    # ------------------------------------------------------------------

    async def _check_error_codes(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """审查错误响应是否遵循统一格式并使用白名单状态码。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []
        scanned = 0

        # 扫描 endpoints/ 与 exception_handler.py 中的裸字符串异常
        scan_dirs: list[Path] = [ENDPOINTS_V1_DIR, ENDPOINTS_V2_DIR]
        scan_dirs.append(FASTAPI_APP_DIR / "core" / "exception_handler.py")
        scan_dirs.append(FASTAPI_APP_DIR / "core" / "exceptions.py")

        for target in scan_dirs:
            if not target.exists():
                continue
            files: list[Path] = [target] if target.is_file() else list(target.rglob("*.py"))
            for py_file in files:
                if "__pycache__" in py_file.parts:
                    continue
                try:
                    source = py_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                scanned += 1
                rel = py_file.relative_to(PROJECT_ROOT).as_posix()
                lines = source.splitlines()
                for idx, line in enumerate(lines, start=1):
                    # 裸字符串异常
                    if _RAW_EXCEPTION_RE.search(line):
                        issues.append(
                            builder.build(
                                layer_id=self.layer_id,
                                severity=Severity.MEDIUM,
                                file=rel,
                                line=idx,
                                description="裸字符串异常,未遵循统一错误响应格式(code/message/detail)",
                                suggestion="使用结构化异常类并返回统一错误响应",
                                rule_id="L5-ERROR-FORMAT-001",
                                owner=DEFAULT_OWNER,
                                due_date=DEFAULT_DUE_DATE,
                            )
                        )
                    # 非白名单状态码: status_code=xxx
                    m = re.search(r"status_code\s*=\s*(\d+)", line)
                    if m:
                        code = int(m.group(1))
                        if code not in _ALLOWED_STATUS_CODES:
                            issues.append(
                                builder.build(
                                    layer_id=self.layer_id,
                                    severity=Severity.MEDIUM,
                                    file=rel,
                                    line=idx,
                                    description=f"非白名单 HTTP 状态码 {code}(允许: {sorted(_ALLOWED_STATUS_CODES)})",
                                    suggestion="使用统一约定的状态码(401/403/404/400/422/500)",
                                    rule_id="L5-ERROR-CODE-001",
                                    owner=DEFAULT_OWNER,
                                    due_date=DEFAULT_DUE_DATE,
                                )
                            )

        raw_parts.append(f"scanned_files: {scanned}")
        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 6.4 版本兼容(v2 不破坏 v1 契约)
    # ------------------------------------------------------------------

    async def _check_version_compatibility(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """审查 v1/v2 API 版本兼容,v2 不得破坏 v1 契约。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        v1_routes = self._extract_routes(ENDPOINTS_V1_DIR)
        v2_routes = self._extract_routes(ENDPOINTS_V2_DIR)

        raw_parts.append(f"v1_routes: {len(v1_routes)}")
        raw_parts.append(f"v2_routes: {len(v2_routes)}")

        if not v1_routes:
            raw_parts.append("v1 endpoints 不存在或无路由,跳过兼容性校验")
            return issues, "\n".join(raw_parts)

        # 版本兼容策略: v1 与 v2 为独立版本, v1 继续可用, v2 为新版本。
        # 仅当 v2 存在与 v1 同 method+path 的接口时, 才检查 v2 是否破坏 v1 契约
        # (例如参数/响应结构不兼容)。v2 不需要复制 v1 的全部接口。
        v1_route_set = {(m, p) for m, p, _ in v1_routes}
        v2_route_set = {(m, p) for m, p, _ in v2_routes}
        v2_routes_by_key: dict[tuple[str, str], tuple[str, int]] = {
            (m, p): (rel, line) for m, p, (rel, line) in v2_routes
        }


        # v2 中与 v1 同 method+path 的接口: 检查是否标注了兼容/迁移说明
        shared_routes = v1_route_set & v2_route_set
        for key in sorted(shared_routes):
            rel, line = v2_routes_by_key[key]
            method, path = key
            py_file = PROJECT_ROOT / rel
            try:
                source = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if not re.search(r"(?i)(v1|migration|迁移|版本|兼容)", source):
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.MEDIUM,
                        file=rel,
                        line=line,
                        description=(
                            f"v2 接口 {method} {path} 与 v1 同路径, "
                            f"未标注版本兼容/迁移说明"
                        ),
                        suggestion="在模块 docstring 中标注 v1 兼容性与迁移说明",
                        rule_id="L5-VERSION-BREAK-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )

        # v2 新接口须标注版本与迁移说明(检查 docstring 含 "v1"/"migration"/"迁移")
        for method, path, (rel, line) in v2_routes:
            if (method, path) not in v1_route_set:
                # v2 新接口: 检查文件 docstring
                py_file = PROJECT_ROOT / rel
                try:
                    source = py_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if not re.search(r"(?i)(v1|migration|迁移|版本)", source):
                    issues.append(
                        builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.MEDIUM,
                            file=rel,
                            line=line,
                            description=(
                                f"v2 新接口 {method} {path} 未标注版本与迁移说明"
                            ),
                            suggestion="在模块 docstring 中标注 v1 兼容性与迁移说明",
                            rule_id="L5-VERSION-MIGRATION-001",
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )

        return issues, "\n".join(raw_parts)

    def _extract_routes(self, endpoints_dir: Path) -> list[tuple[str, str, tuple[str, int]]]:
        """提取 endpoints 目录下所有路由(method, path, (rel_path, line))。"""
        routes: list[tuple[str, str, tuple[str, int]]] = []
        if not endpoints_dir.exists():
            return routes
        for py_file in endpoints_dir.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            rel = py_file.relative_to(PROJECT_ROOT).as_posix()
            for idx, line in enumerate(source.splitlines(), start=1):
                for m in _ROUTE_DECORATOR_RE.finditer(line):
                    method = m.group(1).upper()
                    path = m.group(2)
                    routes.append((method, path, (rel, idx)))
        return routes

    # ------------------------------------------------------------------
    # 证据归档
    # ------------------------------------------------------------------

    async def _archive_evidence(
        self,
        context: AuditContext,
        raw_outputs: dict[str, str],
        issues: Sequence[AuditIssue],
    ) -> Path:
        """归档对齐结果与快照 diff 至 ``evidence/contract_snapshots/`` 与 ``evidence/gate_logs/L5/``。"""
        archiver = context.archiver

        # 1. 契约快照占位(本轮未发起 HTTP 请求,记录核心接口清单)
        snapshot = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "core_endpoints": [
                {"method": m, "path": p} for m, p in _CORE_ENDPOINTS
            ],
            "note": "契约快照录制需在 staging 环境发起 HTTP 请求,本轮仅记录清单",
        }
        path_snapshot = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.CONTRACT_SNAPSHOT,
            content=json.dumps(snapshot, ensure_ascii=False, indent=2),
            filename="L5/core_endpoints.json",
        )

        # 2. 对齐脚本原始输出
        path_raw = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.CONTRACT_SNAPSHOT,
            content="\n\n".join(
                f"=== {k} ===\n{v}" for k, v in raw_outputs.items()
            ),
            filename="L5/alignment_raw.txt",
        )

        # 3. 门禁日志: issues.json + summary.md
        issues_json = json.dumps(
            [issue.model_dump(mode="json") for issue in issues],
            ensure_ascii=False,
            indent=2,
        )
        path_issues = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=issues_json,
            filename="L5/issues.json",
        )
        path_summary = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=(
                "# L5 API 契约与版本兼容审核\n\n"
                "## 路由对齐\n复用 check-api-alignment.mjs / check-route-alignment.mjs。\n\n"
                "## Schema 一致性\n对比 Pydantic 模型与前端 TypeScript 接口字段。\n\n"
                "## 错误码统一\n审查统一错误响应格式与白名单状态码(401/403/404/400/422/500)。\n\n"
                "## 版本兼容\nv2 不得破坏 v1 契约,v2 新接口须标注版本与迁移说明。\n"
            ),
            filename="L5/summary.md",
        )

        return path_summary or path_issues or path_raw or path_snapshot
