"""L8 可观测性审核层执行器。

日志规范与脱敏扫描 / 监控指标覆盖审查 / 链路追踪与告警规则审查。

约束:
    - 复用存量 ``core/logger.py`` / ``core/telemetry.py`` / ``core/metrics.py`` 基线
    - 关键业务操作日志须含上下文(用户 ID/请求 ID/关键业务 ID)
    - 日志不得泄露敏感数据明文

任务来源: ``.codeartsdoer/specs/prod_code_review/tasks.md`` 第 9 节。
"""

from __future__ import annotations

import ast
import json
import re
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

FASTAPI_APP_DIR: Path = PROJECT_ROOT / "fastapi_app"
SERVICES_DIR: Path = FASTAPI_APP_DIR / "services"
ENDPOINTS_V1_DIR: Path = FASTAPI_APP_DIR / "api" / "v1" / "endpoints"
CORE_DIR: Path = FASTAPI_APP_DIR / "core"

DEFAULT_OWNER: str = "observability-reviewer"
DEFAULT_DUE_DATE: str = "2026-09-30"

# 敏感变量名(用于日志泄露扫描)
_SENSITIVE_VAR_NAMES: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "secret_key",
        "token",
        "api_key",
        "apikey",
        "access_key",
        "private_key",
        "credential",
        "authorization",
    }
)

# 日志调用方法名
_LOG_METHODS: frozenset[str] = frozenset(
    {"info", "debug", "warning", "error", "critical", "exception", "log"}
)

# 上下文变量名(请求 ID/用户 ID/关键业务 ID)
_CONTEXT_VAR_NAMES: frozenset[str] = frozenset(
    {
        "request_id",
        "req_id",
        "trace_id",
        "user_id",
        "uid",
        "order_id",
        "stock_id",
        "backup_id",
        "task_id",
        "correlation_id",
    }
)

# 日志上下文豁免标记(函数 def 行含该标记则跳过,用于内部 helper 无请求上下文场景)
_LOG_CONTEXT_EXEMPT_MARKER: str = "log-context"

# 关键业务操作关键词(函数名/路径含这些词须有上下文日志)
_CRITICAL_BUSINESS_KEYWORDS: frozenset[str] = frozenset(
    {"login", "logout", "create_order", "cancel_order", "deduct_stock", "backup", "restore"}
)

# 健康检查端点路径（S7：与 core/health.py 的真实探针契约一致 —— health.py:346/370-373
# 注册的是 **/api/health、/api/health/live、/api/health/ready**；此前漏了 /api 前缀，
# 靠下面的 endswith 宽松匹配才勉强命中，稳定误报「部分端点缺失」，评审 2026-10-11 修）
_HEALTH_ENDPOINT_PATHS: tuple[str, ...] = ("/api/health", "/api/health/live", "/api/health/ready")

# 路由注册路径提取：同时匹配装饰器写法（``@app.get("/x")``）与命令式注册
# （``app.get("/x", tags=...)(handler)``）—— core/health.py 的探针全是命令式，
# 旧正则只认 `@` 装饰器 → 稳定误报（评审 2026-10-11）。要求路径以 `/` 开头，
# 滤掉 ``dict.get("k")`` 这类非路由调用。
_ROUTE_RE = re.compile(r"\.\s*(?:get|post)\s*\(\s*[\"'](/[^\"']*)[\"']")

# 监控指标须覆盖的关键维度
_REQUIRED_METRIC_DIMENSIONS: frozenset[str] = frozenset(
    {
        "request_count",      # 核心接口请求量
        "error_rate",         # 错误率
        "response_time",      # 响应时间
        "cpu",                # CPU
        "memory",             # 内存
        "disk",               # 磁盘
        "connection_pool",    # 连接池
        "order_count",        # 订单量
        "stock_level",        # 库存
        "backup_status",      # 备份状态
    }
)

# 告警规则须覆盖的关键指标
_REQUIRED_ALERT_METRICS: frozenset[str] = frozenset(
    {"error_rate", "response_time", "cpu", "memory", "disk", "connection_pool"}
)


class L8Observability(LayerBase):
    """L8 可观测性审核层执行器。

    聚合 6 个子检查:
        - 日志上下文(关键业务操作日志含 request_id/user_id)
        - 日志脱敏(无敏感数据明文)
        - 监控(健康检查端点存在)
        - 链路追踪(trace ID 传播 + DB span)
        - 告警(关键指标阈值告警规则)
        - 指标(Prometheus/metrics 端点)
    """

    layer_id: str = "L8"
    layer_name: str = "可观测性审核"
    weight: float = 0.07

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    async def run(self, context: AuditContext) -> LayerResult:
        """执行 L8 全部子检查并归档证据。"""
        started_at = datetime.now(UTC)
        builder = IssueBuilder()
        raw_outputs: dict[str, str] = {}

        checks: list[tuple[str, object]] = [
            ("logging_context", self._check_logging_context(builder)),
            ("logging_no_secrets", self._check_logging_no_secrets(builder)),
            ("monitoring", self._check_monitoring(builder)),
            ("tracing", self._check_tracing(builder)),
            ("alerting", self._check_alerting(builder)),
            ("metrics", self._check_metrics(builder)),
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
                        suggestion="检查 core/logger.py / telemetry.py / metrics.py 路径",
                        rule_id=f"L8-{name.upper()}-EXEC-001",
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
    # 9.1 日志上下文(关键业务操作日志含 request_id/user_id)
    # ------------------------------------------------------------------

    async def _check_logging_context(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """审查关键业务操作日志是否含上下文(用户 ID/请求 ID/关键业务 ID)。"""
        issues: list[AuditIssue] = []
        scanned = 0
        raw_parts: list[str] = []

        scan_dirs: list[Path] = [SERVICES_DIR, ENDPOINTS_V1_DIR]
        for scan_dir in scan_dirs:
            if not scan_dir.exists():
                continue
            for py_file in scan_dir.rglob("*.py"):
                if "__pycache__" in py_file.parts:
                    continue
                try:
                    source = py_file.read_text(encoding="utf-8")
                    tree = ast.parse(source, filename=str(py_file))
                except (SyntaxError, OSError, UnicodeDecodeError):
                    continue
                scanned += 1
                rel = py_file.relative_to(PROJECT_ROOT).as_posix()
                visitor = _LogContextVisitor(rel, self.layer_id, builder, source.splitlines())
                visitor.visit(tree)
                issues.extend(visitor.issues)

        raw_parts.append(f"scanned_files: {scanned}")
        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 9.1 日志脱敏(无敏感数据明文)
    # ------------------------------------------------------------------

    async def _check_logging_no_secrets(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """AST 扫描日志调用参数是否含敏感变量名。"""
        issues: list[AuditIssue] = []
        scanned = 0
        raw_parts: list[str] = []

        scan_dirs: list[Path] = [SERVICES_DIR, ENDPOINTS_V1_DIR, CORE_DIR]
        for scan_dir in scan_dirs:
            if not scan_dir.exists():
                continue
            for py_file in scan_dir.rglob("*.py"):
                if "__pycache__" in py_file.parts:
                    continue
                try:
                    source = py_file.read_text(encoding="utf-8")
                    tree = ast.parse(source, filename=str(py_file))
                except (SyntaxError, OSError, UnicodeDecodeError):
                    continue
                scanned += 1
                rel = py_file.relative_to(PROJECT_ROOT).as_posix()
                visitor = _LogSecretLeakVisitor(rel, self.layer_id, builder)
                visitor.visit(tree)
                issues.extend(visitor.issues)

        raw_parts.append(f"scanned_files: {scanned}")
        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 9.2 监控(健康检查端点存在)
    # ------------------------------------------------------------------

    async def _check_monitoring(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """验证健康检查端点存在(/health, /health/live, /health/ready)。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        found_paths: set[str] = set()
        scan_dirs: list[Path] = [ENDPOINTS_V1_DIR, FASTAPI_APP_DIR / "api" / "v2" / "endpoints"]
        # 也扫描 main.py / monitoring.py
        extra_files = [
            FASTAPI_APP_DIR / "main.py",
            ENDPOINTS_V1_DIR / "monitoring.py",
            # S7：真实探针注册在 app 层（core/health.py），不在此目录内
            FASTAPI_APP_DIR / "core" / "health.py",
        ]

        all_files: list[Path] = []
        for d in scan_dirs:
            if d.exists():
                all_files.extend(d.rglob("*.py"))
        all_files.extend(f for f in extra_files if f.exists())

        for py_file in all_files:
            if "__pycache__" in py_file.parts:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for m in _ROUTE_RE.finditer(source):
                path = m.group(1)
                # 精确匹配：去掉原先的 endswith 宽松匹配（它会让 /api/v1/backup/health
                # 冒充 app 探针，掩盖真实缺失）
                if path in _HEALTH_ENDPOINT_PATHS:
                    found_paths.add(path)

        raw_parts.append(f"found_health_endpoints: {sorted(found_paths)}")

        missing = set(_HEALTH_ENDPOINT_PATHS) - found_paths
        # 至少须有 /health 与 /ready 之一
        if not found_paths:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file="fastapi_app/",
                    line=1,
                    description=f"未发现健康检查端点(期望: {_HEALTH_ENDPOINT_PATHS})",
                    suggestion="添加 /health、/health/live 与 /health/ready 健康检查端点",
                    rule_id="L8-HEALTH-ENDPOINT-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
        elif missing:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.LOW,
                    file="fastapi_app/",
                    line=1,
                    description=f"部分健康检查端点缺失: {sorted(missing)}",
                    suggestion="补齐 /health、/health/live 与 /health/ready 端点",
                    rule_id="L8-HEALTH-ENDPOINT-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )

        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 9.3 链路追踪(trace ID 传播 + DB span)
    # ------------------------------------------------------------------

    async def _check_tracing(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """审查 core/telemetry.py 跨服务调用 trace ID 传播与数据库查询 span 记录。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        telemetry_file = CORE_DIR / "telemetry.py"
        if not telemetry_file.exists():
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=str(telemetry_file.relative_to(PROJECT_ROOT).as_posix()),
                    line=1,
                    description="core/telemetry.py 不存在,链路追踪未配置",
                    suggestion="创建 core/telemetry.py 配置 OpenTelemetry 追踪",
                    rule_id="L8-TRACE-MISSING-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
            return issues, "telemetry.py 不存在"

        try:
            source = telemetry_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return [
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=str(telemetry_file.relative_to(PROJECT_ROOT).as_posix()),
                    line=1,
                    description=f"读取 telemetry.py 失败: {exc}",
                    suggestion="检查文件权限与编码",
                    rule_id="L8-TRACE-MISSING-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            ], f"READ_ERROR: {exc}"

        # 检查 trace ID 传播: FastAPIInstrumentor / tracing / span / trace
        trace_indicators = re.compile(
            r"(?i)(FastAPIInstrumentor|SQLAlchemyInstrumentor|start_span|trace|tracer|span|propagat)"
        )
        has_trace = bool(trace_indicators.search(source))
        raw_parts.append(f"has_trace_indicators: {has_trace}")

        if not has_trace:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=str(telemetry_file.relative_to(PROJECT_ROOT).as_posix()),
                    line=1,
                    description="telemetry.py 未检测到 trace/span 配置",
                    suggestion="配置 OpenTelemetry FastAPIInstrumentor 与 SQLAlchemyInstrumentor",
                    rule_id="L8-TRACE-MISSING-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )

        # 检查 DB span: SQLAlchemyInstrumentor
        has_db_span = bool(re.search(r"(?i)SQLAlchemyInstrumentor", source))
        raw_parts.append(f"has_db_span: {has_db_span}")
        if not has_db_span:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=str(telemetry_file.relative_to(PROJECT_ROOT).as_posix()),
                    line=1,
                    description="未检测到数据库查询 span 记录(SQLAlchemyInstrumentor)",
                    suggestion="启用 SQLAlchemyInstrumentor 记录 DB 查询 span",
                    rule_id="L8-TRACE-DB-SPAN-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )

        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 9.3 告警(关键指标阈值告警规则)
    # ------------------------------------------------------------------

    async def _check_alerting(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """审查告警规则是否覆盖关键指标阈值且不过度敏感。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        # 告警规则常见位置: monitoring/ / alerts/ / prometheus/ / core/metrics.py
        alert_search_dirs: list[Path] = [
            PROJECT_ROOT / "monitoring",
            PROJECT_ROOT / "alerts",
            PROJECT_ROOT / "prometheus",
            CORE_DIR,
        ]
        alert_file_patterns = ("*.yaml", "*.yml", "*.json", "*.py")
        alert_re = re.compile(
            r"(?i)(alert|alerting|AlertRule|rule\s*:\s*alert)"
        )
        # 告警规则中涉及的指标名
        metric_in_alert_re = re.compile(
            r"(?i)\b(error_rate|response_time|cpu|memory|disk|connection_pool|latency|p95|p99)\b"
        )

        found_alert_files: list[Path] = []
        found_metrics: set[str] = set()
        for search_dir in alert_search_dirs:
            if not search_dir.exists():
                continue
            for pattern in alert_file_patterns:
                for f in search_dir.rglob(pattern):
                    if "node_modules" in f.parts or "__pycache__" in f.parts:
                        continue
                    try:
                        content = f.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        continue
                    if alert_re.search(content):
                        found_alert_files.append(f)
                        found_metrics.update(metric_in_alert_re.findall(content))

        raw_parts.append(f"alert_files: {len(found_alert_files)}")
        raw_parts.append(f"metrics_in_alerts: {sorted(found_metrics)}")

        if not found_alert_files:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file="monitoring/ | alerts/ | core/metrics.py",
                    line=1,
                    description="未发现告警规则文件",
                    suggestion="创建告警规则覆盖 error_rate/response_time/cpu/memory/disk 阈值",
                    rule_id="L8-ALERT-RULE-MISSING-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
        else:
            missing_metrics = _REQUIRED_ALERT_METRICS - found_metrics
            if missing_metrics:
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.MEDIUM,
                        file=str(found_alert_files[0].relative_to(PROJECT_ROOT).as_posix()),
                        line=1,
                        description=f"告警规则未覆盖关键指标: {sorted(missing_metrics)}",
                        suggestion="补充缺失指标的告警规则",
                        rule_id="L8-ALERT-METRIC-MISSING-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )

        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 9.2 指标(Prometheus/metrics 端点)
    # ------------------------------------------------------------------

    async def _check_metrics(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """验证 Prometheus/metrics 端点或等价指标采集配置。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        # 1. 检查 core/metrics.py 存在并覆盖关键指标维度
        metrics_file = CORE_DIR / "metrics.py"
        if not metrics_file.exists():
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=str(metrics_file.relative_to(PROJECT_ROOT).as_posix()),
                    line=1,
                    description="core/metrics.py 不存在,监控指标未配置",
                    suggestion="创建 core/metrics.py 定义 Prometheus 指标",
                    rule_id="L8-METRIC-MISSING-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
            return issues, "metrics.py 不存在"

        try:
            source = metrics_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return [
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=str(metrics_file.relative_to(PROJECT_ROOT).as_posix()),
                    line=1,
                    description=f"读取 metrics.py 失败: {exc}",
                    suggestion="检查文件权限与编码",
                    rule_id="L8-METRIC-MISSING-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            ], f"READ_ERROR: {exc}"

        # 检查指标维度覆盖(Counter/Histogram/Gauge 关键词 + 维度名)
        metric_def_re = re.compile(
            r"(?i)\b(Counter|Histogram|Gauge|Summary)\s*\(\s*[\"']([^\"']+)[\"']"
        )
        defined_metric_names = {m.group(2) for m in metric_def_re.finditer(source)}
        raw_parts.append(f"defined_metrics: {sorted(defined_metric_names)}")

        # 检查关键维度: 将维度名扁平化匹配(如 request_count_total 含 request_count)
        source_lower = source.lower()
        missing_dimensions: set[str] = set()
        for dim in _REQUIRED_METRIC_DIMENSIONS:
            if dim.lower() not in source_lower:
                missing_dimensions.add(dim)

        if missing_dimensions:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=str(metrics_file.relative_to(PROJECT_ROOT).as_posix()),
                    line=1,
                    description=f"监控指标未覆盖关键维度: {sorted(missing_dimensions)}",
                    suggestion="补充缺失的 Prometheus 指标定义",
                    rule_id="L8-METRIC-MISSING-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )

        # 2. 检查 /metrics 端点
        metrics_endpoint_re = re.compile(r"[\"'](/metrics)[\"']")
        found_metrics_endpoint = False
        for py_file in ENDPOINTS_V1_DIR.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if metrics_endpoint_re.search(content):
                found_metrics_endpoint = True
                break
        # 也检查 main.py
        main_file = FASTAPI_APP_DIR / "main.py"
        if not found_metrics_endpoint and main_file.exists():
            try:
                content = main_file.read_text(encoding="utf-8")
                if metrics_endpoint_re.search(content):
                    found_metrics_endpoint = True
            except (OSError, UnicodeDecodeError):
                pass
        # 也检查 core/health.py
        health_file = CORE_DIR / "health.py"
        if not found_metrics_endpoint and health_file.exists():
            try:
                content = health_file.read_text(encoding="utf-8")
                if metrics_endpoint_re.search(content):
                    found_metrics_endpoint = True
            except (OSError, UnicodeDecodeError):
                pass

        raw_parts.append(f"metrics_endpoint_found: {found_metrics_endpoint}")
        if not found_metrics_endpoint:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file="fastapi_app/",
                    line=1,
                    description="未发现 /metrics 端点(Prometheus 指标暴露)",
                    suggestion="添加 /metrics 端点暴露 Prometheus 指标",
                    rule_id="L8-METRICS-ENDPOINT-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )

        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 证据归档
    # ------------------------------------------------------------------

    async def _archive_evidence(
        self,
        context: AuditContext,
        raw_outputs: dict[str, str],
        issues: Sequence[AuditIssue],
    ) -> Path:
        """归档审查记录至 ``evidence/manual_reviews/L8/`` 与 ``evidence/gate_logs/L8/``。"""
        archiver = context.archiver

        # 1. 人工审查记录: 日志上下文
        path_log_ctx = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.MANUAL_REVIEW,
            content=(
                "# L8 日志上下文人工审查\n\n"
                "## 审查范围\n关键业务操作(登录/订单创建/库存扣减/备份)日志。\n\n"
                "## 审查要点\n- 日志是否含 request_id / user_id / 关键业务 ID\n"
                "- 关键业务操作是否有日志记录\n- 日志级别是否合理\n\n"
                f"## 自动扫描结果\n{raw_outputs.get('logging_context', 'N/A')}\n"
            ),
            filename="L8/log_context.md",
        )

        # 2. 人工审查记录: 告警规则
        path_alert = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.MANUAL_REVIEW,
            content=(
                "# L8 告警规则人工审查\n\n"
                "## 审查范围\n告警规则文件(monitoring/ alerts/ core/metrics.py)。\n\n"
                "## 审查要点\n- 关键指标(error_rate/response_time/cpu/memory/disk)是否有阈值\n"
                "- 阈值是否合理(不过度敏感)\n- 告警接收人是否正确\n\n"
                f"## 自动扫描结果\n{raw_outputs.get('alerting', 'N/A')}\n"
            ),
            filename="L8/alert_rules.md",
        )

        # 3. 原始扫描输出
        path_raw = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content="\n\n".join(
                f"=== {k} ===\n{v}" for k, v in raw_outputs.items()
            ),
            filename="L8/scan_raw.txt",
        )

        # 4. 门禁日志: issues.json + summary.md
        issues_json = json.dumps(
            [issue.model_dump(mode="json") for issue in issues],
            ensure_ascii=False,
            indent=2,
        )
        path_issues = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=issues_json,
            filename="L8/issues.json",
        )
        path_summary = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=(
                "# L8 可观测性审核\n\n"
                "## 日志上下文\n关键业务操作日志须含 request_id/user_id/业务 ID。\n\n"
                "## 日志脱敏\n日志参数不得含 password/secret/token/api_key 变量。\n\n"
                "## 监控\n须有 /health 与 /ready 健康检查端点。\n\n"
                "## 链路追踪\ncore/telemetry.py 须配置 trace ID 传播与 DB span。\n\n"
                "## 告警\n告警规则须覆盖 error_rate/response_time/cpu/memory/disk 阈值。\n\n"
                "## 指标\ncore/metrics.py 须覆盖核心接口/系统资源/业务关键指标,并暴露 /metrics 端点。\n"
            ),
            filename="L8/summary.md",
        )

        return path_summary or path_issues or path_raw or path_alert or path_log_ctx


# ---------------------------------------------------------------------------
# AST 访问器: 日志上下文校验
# ---------------------------------------------------------------------------


class _LogContextVisitor(ast.NodeVisitor):
    """检测关键业务操作函数是否含带上下文的日志调用。"""

    def __init__(self, file: str, layer_id: str, builder: IssueBuilder, source_lines: list[str]) -> None:
        self.file = file
        self.layer_id = layer_id
        self.builder = builder
        self.source_lines = source_lines
        self.issues: list[AuditIssue] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # 豁免标记检查(行内含 log-context 则跳过)
        if 1 <= node.lineno <= len(self.source_lines) and _LOG_CONTEXT_EXEMPT_MARKER in self.source_lines[node.lineno - 1]:
            self.generic_visit(node)
            return
        # 判断是否为关键业务操作
        func_name_lower = node.name.lower()
        is_critical = any(kw in func_name_lower for kw in _CRITICAL_BUSINESS_KEYWORDS)
        if not is_critical:
            self.generic_visit(node)
            return

        # 收集函数体内所有日志调用的参数变量名
        log_calls: list[ast.Call] = []
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr in _LOG_METHODS
            ):
                log_calls.append(child)

        if not log_calls:
            self.issues.append(
                self.builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=self.file,
                    line=node.lineno,
                    description=(
                        f"关键业务操作 {node.name} 无日志记录"
                    ),
                    suggestion="添加含 request_id/user_id 上下文的日志",
                    rule_id="L8-LOG-CONTEXT-MISSING-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
            self.generic_visit(node)
            return

        # 检查日志参数是否含上下文变量
        has_context = False
        for call in log_calls:
            for arg in call.args:
                if isinstance(arg, ast.Name) and arg.id in _CONTEXT_VAR_NAMES:
                    has_context = True
                    break
                if isinstance(arg, ast.JoinedStr):
                    for v in arg.values:
                        if isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name) and v.value.id in _CONTEXT_VAR_NAMES:
                            has_context = True
                            break
            for kw in call.keywords:
                if isinstance(kw.value, ast.Name) and kw.value.id in _CONTEXT_VAR_NAMES:
                    has_context = True
            if has_context:
                break

        if not has_context:
            self.issues.append(
                self.builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=self.file,
                    line=node.lineno,
                    description=(
                        f"关键业务操作 {node.name} 日志未含上下文"
                        f"(request_id/user_id/业务 ID)"
                    ),
                    suggestion="在日志中添加 request_id/user_id 上下文字段",
                    rule_id="L8-LOG-CONTEXT-MISSING-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# AST 访问器: 日志敏感数据泄露
# ---------------------------------------------------------------------------


class _LogSecretLeakVisitor(ast.NodeVisitor):
    """检测日志调用参数是否含敏感变量名。"""

    def __init__(self, file: str, layer_id: str, builder: IssueBuilder) -> None:
        self.file = file
        self.layer_id = layer_id
        self.builder = builder
        self.issues: list[AuditIssue] = []

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _LOG_METHODS:
            for arg in node.args:
                self._check_arg(arg, node.lineno)
            for kw in node.keywords:
                self._check_arg(kw.value, node.lineno)
        self.generic_visit(node)

    def _check_arg(self, arg: ast.AST, line: int) -> None:
        # 直接传敏感变量: logger.info(password)
        if isinstance(arg, ast.Name) and arg.id in _SENSITIVE_VAR_NAMES:
            self._add_issue(line, f"日志参数 {arg.id} 为敏感变量,可能泄露明文")
        # f-string 含敏感变量: logger.info(f"... {password}")
        elif isinstance(arg, ast.JoinedStr):
            for v in arg.values:
                if isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name) and v.value.id in _SENSITIVE_VAR_NAMES:
                    self._add_issue(line, f"日志 f-string 含敏感变量 {v.value.id}")
        # .format(password) / format(key=password)
        elif isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "format":
            for fmt_arg in arg.args:
                if isinstance(fmt_arg, ast.Name) and fmt_arg.id in _SENSITIVE_VAR_NAMES:
                    self._add_issue(line, f"日志 .format() 含敏感变量 {fmt_arg.id}")
            for kw in arg.keywords:
                if kw.arg in _SENSITIVE_VAR_NAMES:
                    self._add_issue(line, f"日志 .format() 含敏感关键字参数 {kw.arg}")

    def _add_issue(self, line: int, desc: str) -> None:
        self.issues.append(
            self.builder.build(
                layer_id=self.layer_id,
                severity=Severity.CRITICAL,
                file=self.file,
                line=line,
                description=desc,
                suggestion="移除日志中的敏感变量或使用脱敏函数",
                rule_id="L8-LOG-LEAK-001",
                owner=DEFAULT_OWNER,
                due_date=DEFAULT_DUE_DATE,
            )
        )
