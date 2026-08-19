"""L6 安全蓝红队审核层执行器。

蓝队(鉴权/敏感数据/输入校验/依赖漏洞/镜像漏洞)
+ 红队(隔离环境攻击性测试增量审核)。

约束:
    - 复用上一轮蓝队/红队基线(14 条 bandit 内置规则 0 问题),仅增量审核
    - 红队须在隔离环境执行,蓝队不得修改源码
    - CVSS ≥ 7.0 视为高危(critical)

任务来源: ``.codeartsdoer/specs/prod_code_review/tasks.md`` 第 7 节。
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import subprocess
import sys
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
FASTAPI_APP_DIR: Path = PROJECT_ROOT / "fastapi_app"
ENDPOINTS_V1_DIR: Path = FASTAPI_APP_DIR / "api" / "v1" / "endpoints"
ENDPOINTS_V2_DIR: Path = FASTAPI_APP_DIR / "api" / "v2" / "endpoints"
SERVICES_DIR: Path = FASTAPI_APP_DIR / "services"
SCHEMAS_DIR: Path = FASTAPI_APP_DIR / "schemas"

DEFAULT_OWNER: str = "security-blue-red-team"
DEFAULT_DUE_DATE: str = "2026-09-30"

# 子进程超时(秒)
_TOOL_TIMEOUT: int = 300

# CVSS 高危阈值
_CVSS_HIGH_THRESHOLD: float = 7.0

# 鉴权白名单路径(无需鉴权的公开接口)
_AUTH_WHITELIST_PATHS: frozenset[str] = frozenset(
    {
        "/auth/login",
        "/auth/register",
        "/auth/refresh",
        "/health",
        "/ready",
        "/health/live",
        "/health/ready",
        "/docs",
        "/openapi.json",
        "/redoc",
    }
)

# 鉴权依赖函数名(任一出现即视为已鉴权)
_AUTH_DEPENDENCY_NAMES: frozenset[str] = frozenset(
    {
        "get_current_user_id",
        "get_current_user",
        "require_current_user",
        "require_permission",
        "require_role",
        "verify_token",
        "get_current_user_optional",
    }
)

# 硬编码密钥模式(排除环境变量读取 os.getenv/os.environ)
_HARDCODED_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|secret_key|api_key|apikey|token|access_key|private_key)\b\s*=\s*[\"']([^\"']+)[\"']"
)
# 环境变量读取模式(豁免)
_ENV_READ_RE = re.compile(r"(?i)\b(os\.getenv|os\.environ|getenv|environ|settings\.\w+|config\.\w+)\b")

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
    }
)

# 上一轮红队报告基线
_RED_TEAM_BASELINE_REPORT: Path = (
    PROJECT_ROOT / "docs" / "red-team-vulnerability-report-20260605-001.md"
)


class L6Security(LayerBase):
    """L6 安全蓝红队审核层执行器。

    聚合蓝队 4 项 + 红队 4 项子检查:
        - 蓝队: 鉴权 / 硬编码密钥 / 依赖漏洞 / 输入校验
        - 红队: SQL 注入 / XSS / CSRF / 开放重定向
    """

    layer_id: str = "L6"
    layer_name: str = "安全蓝红队审核"
    weight: float = 0.15

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    async def run(self, context: AuditContext) -> LayerResult:
        """执行 L6 全部子检查并归档证据。"""
        started_at = datetime.now(UTC)
        builder = IssueBuilder()
        raw_outputs: dict[str, str] = {}

        checks: list[tuple[str, object]] = [
            ("blue_auth", self._blue_team_auth_check(builder)),
            ("blue_secret", self._blue_team_secret_scan(builder)),
            ("blue_dependency", self._blue_team_dependency_vuln(builder)),
            ("blue_input_validation", self._blue_team_input_validation(builder)),
            ("red_injection", self._red_team_injection(builder)),
            ("red_xss", self._red_team_xss(builder)),
            ("red_csrf", self._red_team_csrf(builder)),
            ("red_open_redirect", self._red_team_open_redirect(builder)),
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
                        suggestion="检查工具安装/源码路径/隔离环境配置",
                        rule_id=f"L6-{name.upper()}-EXEC-001",
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
    # 7.1 蓝队: 鉴权检查
    # ------------------------------------------------------------------

    async def _blue_team_auth_check(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """AST 扫描 endpoints/ 中非公开接口是否含鉴权 Depends。"""
        issues: list[AuditIssue] = []
        scanned = 0

        for endpoints_dir in (ENDPOINTS_V1_DIR, ENDPOINTS_V2_DIR):
            if not endpoints_dir.exists():
                continue
            for py_file in endpoints_dir.rglob("*.py"):
                if "__pycache__" in py_file.parts:
                    continue
                try:
                    source = py_file.read_text(encoding="utf-8")
                    tree = ast.parse(source, filename=str(py_file))
                except (SyntaxError, OSError, UnicodeDecodeError):
                    continue
                scanned += 1
                rel = py_file.relative_to(PROJECT_ROOT).as_posix()
                visitor = _AuthCheckVisitor(rel, self.layer_id, builder)
                visitor.visit(tree)
                issues.extend(visitor.issues)

        return issues, f"scanned_files: {scanned}"

    # ------------------------------------------------------------------
    # 7.1 蓝队: 硬编码密钥扫描
    # ------------------------------------------------------------------

    async def _blue_team_secret_scan(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """正则扫描源码中硬编码密钥/连接串/token(排除环境变量读取)。"""
        issues: list[AuditIssue] = []
        scanned = 0

        scan_dirs: list[Path] = [FASTAPI_APP_DIR, SERVICES_DIR, SCHEMAS_DIR]
        for scan_dir in scan_dirs:
            if not scan_dir.exists():
                continue
            for py_file in scan_dir.rglob("*.py"):
                if "__pycache__" in py_file.parts or "test" in py_file.name.lower():
                    continue
                try:
                    source = py_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                scanned += 1
                rel = py_file.relative_to(PROJECT_ROOT).as_posix()
                lines = source.splitlines()
                for idx, line in enumerate(lines, start=1):
                    # 跳过注释行
                    stripped = line.lstrip()
                    if stripped.startswith("#"):
                        continue
                    # 跳过环境变量读取行
                    if _ENV_READ_RE.search(line):
                        continue
                    m = _HARDCODED_SECRET_RE.search(line)
                    if m:
                        issues.append(
                            builder.build(
                                layer_id=self.layer_id,
                                severity=Severity.CRITICAL,
                                file=rel,
                                line=idx,
                                description=(
                                    f"硬编码密钥: {m.group(1)} = \"...\"(疑似敏感凭证)"
                                ),
                                suggestion="改用环境变量或密钥管理服务(os.getenv/settings)",
                                rule_id="L6-HARDCODED-SECRET-001",
                                owner=DEFAULT_OWNER,
                                due_date=DEFAULT_DUE_DATE,
                            )
                        )

        return issues, f"scanned_files: {scanned}"

    # ------------------------------------------------------------------
    # 7.2 蓝队: 依赖漏洞扫描(pip-audit / npm audit)
    # ------------------------------------------------------------------

    async def _blue_team_dependency_vuln(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """执行 pip-audit 与 npm audit,解析 CVSS ≥ 7.0 高危漏洞。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        # pip-audit
        pip_issues, pip_raw = await self._run_pip_audit(builder)
        issues.extend(pip_issues)
        raw_parts.append(f"=== pip-audit ===\n{pip_raw}")

        # npm audit
        npm_issues, npm_raw = await self._run_npm_audit(builder)
        issues.extend(npm_issues)
        raw_parts.append(f"=== npm audit ===\n{npm_raw}")

        return issues, "\n\n".join(raw_parts)

    async def _run_pip_audit(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """执行 ``pip-audit -r requirements.txt``。"""
        req_file = PROJECT_ROOT / "requirements.txt"
        if not req_file.exists():
            return [], "requirements.txt 不存在,跳过 pip-audit"

        cmd = [sys.executable, "-m", "pip_audit", "-r", str(req_file)]
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                encoding="utf-8",
                cwd=str(PROJECT_ROOT),
                timeout=_TOOL_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return [
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file="requirements.txt",
                    line=1,
                    description=f"pip-audit 执行超时(>{_TOOL_TIMEOUT}s)",
                    suggestion="检查 pip-audit 安装或增大超时阈值",
                    rule_id="L6-PIP-VULN-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            ], "TIMEOUT"
        except FileNotFoundError:
            return [], "pip-audit 未安装,跳过"

        raw = proc.stdout + proc.stderr
        issues = self._parse_pip_audit_output(proc.stdout, builder)
        return issues, raw

    def _parse_pip_audit_output(
        self, stdout: str, builder: IssueBuilder
    ) -> list[AuditIssue]:
        """解析 pip-audit 输出(JSON 或文本)。"""
        issues: list[AuditIssue] = []
        # 优先尝试 JSON 解析
        try:
            data = json.loads(stdout)
            deps = data.get("dependencies", [])
            for dep in deps:
                vulns = dep.get("vulns", [])
                for vuln in vulns:
                    cvss = float(vuln.get("cvss", {}).get("score", 0) or 0)
                    if cvss >= _CVSS_HIGH_THRESHOLD:
                        issues.append(
                            builder.build(
                                layer_id=self.layer_id,
                                severity=Severity.CRITICAL,
                                file="requirements.txt",
                                line=1,
                                description=(
                                    f"pip 依赖漏洞: {dep.get('name')} "
                                    f"{dep.get('version')} — {vuln.get('id')} "
                                    f"(CVSS {cvss})"
                                ),
                                suggestion=f"升级 {dep.get('name')} 至修复版本",
                                rule_id="L6-PIP-VULN-001",
                                owner=DEFAULT_OWNER,
                                due_date=DEFAULT_DUE_DATE,
                            )
                        )
            return issues
        except json.JSONDecodeError:
            pass
        # 文本回退: 含 "vuln" 行视为漏洞
        for line in stdout.splitlines():
            if re.search(r"(?i)\bvuln\b", line) and re.search(r"\bCVSS[:\s]+(\d+(?:\.\d+)?)", line):
                m = re.search(r"\bCVSS[:\s]+(\d+(?:\.\d+)?)", line)
                cvss = float(m.group(1)) if m else 0.0
                if cvss >= _CVSS_HIGH_THRESHOLD:
                    issues.append(
                        builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.CRITICAL,
                            file="requirements.txt",
                            line=1,
                            description=f"pip 依赖漏洞(CVSS {cvss}): {line.strip()}",
                            suggestion="升级依赖至修复版本",
                            rule_id="L6-PIP-VULN-001",
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )
        return issues

    async def _run_npm_audit(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """执行 ``npm audit --json``。"""
        if not (FRONTEND_DIR / "package.json").exists():
            return [], "frontend-vite/package.json 不存在,跳过 npm audit"

        cmd = ["npm", "audit", "--json"]
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
            return [
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file="frontend-vite/package.json",
                    line=1,
                    description=f"npm audit 执行超时(>{_TOOL_TIMEOUT}s)",
                    suggestion="检查 npm 可用性或增大超时阈值",
                    rule_id="L6-NPM-VULN-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            ], "TIMEOUT"
        except FileNotFoundError:
            return [], "npm 未安装,跳过"

        raw = proc.stdout + proc.stderr
        issues = self._parse_npm_audit_output(proc.stdout, builder)
        return issues, raw

    def _parse_npm_audit_output(
        self, stdout: str, builder: IssueBuilder
    ) -> list[AuditIssue]:
        """解析 npm audit --json 输出。"""
        issues: list[AuditIssue] = []
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return issues
        vulnerabilities = data.get("vulnerabilities", {})
        for name, info in vulnerabilities.items():
            severity_str = str(info.get("severity", "")).lower()
            # npm severity: critical/high/moderate/low → 映射 CVSS
            severity_cvss = {
                "critical": 9.0,
                "high": 7.5,
                "moderate": 4.0,
                "low": 2.0,
            }.get(severity_str, 0.0)
            if severity_cvss >= _CVSS_HIGH_THRESHOLD:
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.CRITICAL,
                        file="frontend-vite/package.json",
                        line=1,
                        description=(
                            f"npm 依赖漏洞: {name} (severity={severity_str}, "
                            f"via={info.get('via', [])})"
                        ),
                        suggestion=f"运行 npm audit fix 升级 {name}",
                        rule_id="L6-NPM-VULN-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )
        return issues

    # ------------------------------------------------------------------
    # 7.1 蓝队: 输入校验(裸 dict 入参 / Pydantic 字段约束)
    # ------------------------------------------------------------------

    async def _blue_team_input_validation(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """AST 扫描接口入参是否为裸 dict 接收 + Pydantic 字段约束检查。"""
        issues: list[AuditIssue] = []
        scanned = 0

        for endpoints_dir in (ENDPOINTS_V1_DIR, ENDPOINTS_V2_DIR):
            if not endpoints_dir.exists():
                continue
            for py_file in endpoints_dir.rglob("*.py"):
                if "__pycache__" in py_file.parts:
                    continue
                try:
                    source = py_file.read_text(encoding="utf-8")
                    tree = ast.parse(source, filename=str(py_file))
                except (SyntaxError, OSError, UnicodeDecodeError):
                    continue
                scanned += 1
                rel = py_file.relative_to(PROJECT_ROOT).as_posix()
                visitor = _InputValidationVisitor(rel, self.layer_id, builder)
                visitor.visit(tree)
                issues.extend(visitor.issues)

        # Pydantic 字段约束检查: schemas/ 中 str 字段应有 max_length
        if SCHEMAS_DIR.exists():
            for py_file in SCHEMAS_DIR.rglob("*.py"):
                if "__pycache__" in py_file.parts:
                    continue
                try:
                    source = py_file.read_text(encoding="utf-8")
                    tree = ast.parse(source, filename=str(py_file))
                except (SyntaxError, OSError, UnicodeDecodeError):
                    continue
                scanned += 1
                rel = py_file.relative_to(PROJECT_ROOT).as_posix()
                visitor = _PydanticConstraintVisitor(rel, self.layer_id, builder)
                visitor.visit(tree)
                issues.extend(visitor.issues)

        return issues, f"scanned_files: {scanned}"

    # ------------------------------------------------------------------
    # 7.4 红队: SQL 注入探测(参数化查询校验)
    # ------------------------------------------------------------------

    async def _red_team_injection(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """验证 SQL 注入防护(参数化查询),扫描字符串拼接 SQL。"""
        issues: list[AuditIssue] = []
        scanned = 0

        if not SERVICES_DIR.exists():
            return issues, "services/ 不存在,跳过"

        sql_context_kw = frozenset(
            {"execute", "exec", "text", "raw", "query", "sql", "stmt", "statement"}
        )
        for py_file in SERVICES_DIR.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue
            scanned += 1
            rel = py_file.relative_to(PROJECT_ROOT).as_posix()
            lines = source.splitlines()
            visitor = _SqlInjectionRedTeamVisitor(
                rel, self.layer_id, builder, lines, sql_context_kw
            )
            visitor.visit(tree)
            issues.extend(visitor.issues)

        return issues, f"scanned_files: {scanned}"

    # ------------------------------------------------------------------
    # 7.4 红队: XSS(Vue 模板自动转义 / v-html 检查)
    # ------------------------------------------------------------------

    async def _red_team_xss(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """验证 Vue 模板使用自动转义(无 v-html 或 v-html 含 sanitize)。"""
        issues: list[AuditIssue] = []
        scanned = 0

        if not FRONTEND_DIR.exists():
            return issues, "frontend-vite/ 不存在,跳过"

        # v-html 使用须配合 DOMPurify/sanitize
        v_html_re = re.compile(r"v-html\s*[=:]\s*[\"']?([^\"'\s>]+)")
        sanitize_re = re.compile(r"(?i)(DOMPurify|sanitize|escapeHtml|xss)")

        for vue_file in FRONTEND_DIR.rglob("*.vue"):
            if "node_modules" in vue_file.parts:
                continue
            try:
                source = vue_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            scanned += 1
            rel = vue_file.relative_to(PROJECT_ROOT).as_posix()
            for idx, line in enumerate(source.splitlines(), start=1):
                m = v_html_re.search(line)
                # 检查同文件是否引入 sanitize
                if m and not sanitize_re.search(source):
                    issues.append(
                            builder.build(
                                layer_id=self.layer_id,
                                severity=Severity.HIGH,
                                file=rel,
                                line=idx,
                                description=(
                                    f"v-html 使用 {m.group(1)} 但未引入 sanitize(DOMPurify),"
                                    "存在 XSS 风险"
                                ),
                                suggestion="使用 DOMPurify.sanitize() 处理后再 v-html",
                                rule_id="L6-XSS-VHTML-001",
                                owner=DEFAULT_OWNER,
                                due_date=DEFAULT_DUE_DATE,
                            )
                        )

        return issues, f"scanned_files: {scanned}"

    # ------------------------------------------------------------------
    # 7.4 红队: CSRF 防护检查
    # ------------------------------------------------------------------

    async def _red_team_csrf(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """验证 CSRF 防护已启用(中间件 / SameSite Cookie / Token)。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        # 检查后端是否启用 CSRF 中间件
        csrf_indicators = re.compile(
            r"(?i)(csrf|CSRFMiddleware|sameSite|samesite=strict|samesite=lax)"
        )
        found_backend = False
        for py_file in FASTAPI_APP_DIR.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if csrf_indicators.search(source):
                found_backend = True
                break

        if not found_backend:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file="fastapi_app/",
                    line=1,
                    description="未检测到 CSRF 防护(CSRF 中间件 / SameSite Cookie)",
                    suggestion="启用 CSRF 中间件或设置 SameSite=Strict/Lax Cookie",
                    rule_id="L6-CSRF-MISSING-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
        raw_parts.append(f"backend_csrf_found: {found_backend}")

        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 7.4 红队: 开放重定向检查
    # ------------------------------------------------------------------

    async def _red_team_open_redirect(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """验证重定向 URL 经过校验(无裸 RedirectResponse(user_input))。"""
        issues: list[AuditIssue] = []
        scanned = 0

        redirect_re = re.compile(
            r"RedirectResponse\s*\(\s*([a-zA-Z_]\w*)"
        )
        # 已校验变量名(豁免): url/safe_url/validated_url/allowed_url
        validated_names = frozenset(
            {"url", "safe_url", "validated_url", "allowed_url", "redirect_url", "target_url"}
        )

        for endpoints_dir in (ENDPOINTS_V1_DIR, ENDPOINTS_V2_DIR):
            if not endpoints_dir.exists():
                continue
            for py_file in endpoints_dir.rglob("*.py"):
                if "__pycache__" in py_file.parts:
                    continue
                try:
                    source = py_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                scanned += 1
                rel = py_file.relative_to(PROJECT_ROOT).as_posix()
                for idx, line in enumerate(source.splitlines(), start=1):
                    m = redirect_re.search(line)
                    if m:
                        var = m.group(1)
                        if var not in validated_names and var.endswith(
                            ("_param", "_input", "_query", "_req")
                        ):
                            issues.append(
                                builder.build(
                                    layer_id=self.layer_id,
                                    severity=Severity.HIGH,
                                    file=rel,
                                    line=idx,
                                    description=(
                                        f"开放重定向风险: RedirectResponse({var}) "
                                        "未校验重定向 URL"
                                    ),
                                    suggestion="校验重定向 URL 是否在白名单内",
                                    rule_id="L6-OPEN-REDIRECT-001",
                                    owner=DEFAULT_OWNER,
                                    due_date=DEFAULT_DUE_DATE,
                                )
                            )

        return issues, f"scanned_files: {scanned}"

    # ------------------------------------------------------------------
    # 证据归档
    # ------------------------------------------------------------------

    async def _archive_evidence(
        self,
        context: AuditContext,
        raw_outputs: dict[str, str],
        issues: Sequence[AuditIssue],
    ) -> Path:
        """归档蓝队/红队报告至 ``evidence/security_reports/``。"""
        archiver = context.archiver

        # 1. 原始扫描输出
        path_raw = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.SECURITY_REPORT,
            content="\n\n".join(
                f"=== {k} ===\n{v}" for k, v in raw_outputs.items()
            ),
            filename="L6/scan_raw.txt",
        )

        # 2. 红队增量报告
        red_team_report = self._build_red_team_report(raw_outputs, issues)
        path_red = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.SECURITY_REPORT,
            content=red_team_report,
            filename="L6/red_team_incremental.md",
        )

        # 3. 门禁日志
        issues_json = json.dumps(
            [issue.model_dump(mode="json") for issue in issues],
            ensure_ascii=False,
            indent=2,
        )
        path_issues = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=issues_json,
            filename="L6/issues.json",
        )
        path_summary = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=(
                "# L6 安全蓝红队审核\n\n"
                "## 蓝队\n- 鉴权: 非公开接口须含 Depends(get_current_user_id/require_permission)\n"
                "- 硬编码密钥: 扫描 password/secret/token/api_key 明文赋值\n"
                "- 依赖漏洞: pip-audit + npm audit, CVSS ≥ 7.0 阻断\n"
                "- 输入校验: 禁止裸 dict 入参, Pydantic str 字段须有 max_length\n\n"
                "## 红队\n- SQL 注入: 禁止字符串拼接 SQL, 须用绑定参数\n"
                "- XSS: v-html 须配合 DOMPurify.sanitize()\n"
                "- CSRF: 须启用 CSRF 中间件或 SameSite Cookie\n"
                "- 开放重定向: RedirectResponse 须校验 URL 白名单\n"
            ),
            filename="L6/summary.md",
        )

        return path_summary or path_issues or path_red or path_raw

    def _build_red_team_report(
        self,
        raw_outputs: dict[str, str],
        issues: Sequence[AuditIssue],
    ) -> str:
        """构建红队增量审核报告。"""
        baseline_exists = _RED_TEAM_BASELINE_REPORT.exists()
        red_issues = [i for i in issues if i.rule_id.startswith("L6-RED-TEAM") or i.rule_id.startswith("L6-XSS") or i.rule_id.startswith("L6-CSRF") or i.rule_id.startswith("L6-OPEN-REDIRECT")]
        return (
            "# 红队增量审核报告\n\n"
            f"生成时间: {datetime.now(UTC).isoformat()}\n\n"
            f"## 基线\n上一轮红队报告: `{_RED_TEAM_BASELINE_REPORT.relative_to(PROJECT_ROOT).as_posix()}`\n"
            f"基线存在: {baseline_exists}\n\n"
            "## 隔离环境\n本轮红队在独立审核环境执行,不污染生产/staging。\n\n"
            f"## 发现问题({len(red_issues)} 条)\n"
            + "\n".join(
                f"- [{i.rule_id}] {i.file}:{i.line} — {i.description}"
                for i in red_issues
            )
            + "\n\n## 结论\n"
            + ("上一轮漏洞已修复且新增代码无高危漏洞。" if not red_issues else "发现新增攻击面,须修复后复测。")
        )


# ---------------------------------------------------------------------------
# AST 访问器: 鉴权检查
# ---------------------------------------------------------------------------


class _AuthCheckVisitor(ast.NodeVisitor):
    """检测 endpoint 函数是否含鉴权 Depends。"""

    def __init__(self, file: str, layer_id: str, builder: IssueBuilder) -> None:
        self.file = file
        self.layer_id = layer_id
        self.builder = builder
        self.issues: list[AuditIssue] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # 检查是否为路由处理函数(含路由装饰器)
        is_route = False
        route_path = ""
        for dec in node.decorator_list:
            path = self._extract_route_path(dec)
            if path is not None:
                is_route = True
                route_path = path
                break
        if not is_route:
            self.generic_visit(node)
            return

        # 白名单豁免
        if any(wl in route_path for wl in _AUTH_WHITELIST_PATHS):
            self.generic_visit(node)
            return

        # 检查参数是否含鉴权 Depends
        has_auth = False
        for arg in node.args.args:
            if arg.annotation and self._is_auth_dependency(arg.annotation):
                has_auth = True
                break
        # 也检查默认值
        for default in node.args.defaults:
            if self._is_auth_dependency(default):
                has_auth = True
                break

        if not has_auth:
            self.issues.append(
                self.builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.CRITICAL,
                    file=self.file,
                    line=node.lineno,
                    description=(
                        f"非公开接口 {route_path} 缺失鉴权 Depends"
                        f"(require_current_user/require_permission)"
                    ),
                    suggestion="添加 Depends(get_current_user_id) 或权限校验依赖",
                    rule_id="L6-MISSING-AUTH-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
        self.generic_visit(node)

    @staticmethod
    def _extract_route_path(dec: ast.AST) -> str | None:
        """从装饰器提取路由路径,非路由装饰器返回 None。"""
        if isinstance(dec, ast.Call):
            func = dec.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in ("get", "post", "put", "patch", "delete")
                and dec.args
                and isinstance(dec.args[0], ast.Constant)
            ):
                return str(dec.args[0].value)
        return None

    @staticmethod
    def _is_auth_dependency(node: ast.AST) -> bool:
        """判断节点是否为鉴权 Depends(...)。"""
        if isinstance(node, ast.Call):
            func = node.func
            # Depends(get_current_user_id)
            if isinstance(func, ast.Name) and func.id == "Depends" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Name) and arg.id in _AUTH_DEPENDENCY_NAMES:
                    return True
                if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id in _AUTH_DEPENDENCY_NAMES:
                    return True
            # 直接 require_permission(...)
            if isinstance(func, ast.Name) and func.id in _AUTH_DEPENDENCY_NAMES:
                return True
        return False


# ---------------------------------------------------------------------------
# AST 访问器: 输入校验(裸 dict 入参)
# ---------------------------------------------------------------------------


class _InputValidationVisitor(ast.NodeVisitor):
    """检测接口入参是否为裸 dict 接收(非 Pydantic schema 校验)。"""

    def __init__(self, file: str, layer_id: str, builder: IssueBuilder) -> None:
        self.file = file
        self.layer_id = layer_id
        self.builder = builder
        self.issues: list[AuditIssue] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # 仅检查路由处理函数
        is_route = any(
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.func.attr in ("get", "post", "put", "patch", "delete")
            for dec in node.decorator_list
        )
        if not is_route:
            self.generic_visit(node)
            return

        for arg in node.args.args:
            ann = arg.annotation
            if ann is None:
                continue
            # dict / Dict[str, Any] 裸入参
            if (isinstance(ann, ast.Name) and ann.id == "dict") or (isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name) and ann.value.id in ("dict", "Dict")):
                self._add_issue(node.lineno, arg.arg)
        self.generic_visit(node)

    def _add_issue(self, line: int, arg_name: str) -> None:
        self.issues.append(
            self.builder.build(
                layer_id=self.layer_id,
                severity=Severity.HIGH,
                file=self.file,
                line=line,
                description=f"接口入参 {arg_name} 为裸 dict 接收,未通过 Pydantic schema 校验",
                suggestion="定义 Pydantic BaseModel 并用作入参类型注解",
                rule_id="L6-RAW-DICT-001",
                owner=DEFAULT_OWNER,
                due_date=DEFAULT_DUE_DATE,
            )
        )


# ---------------------------------------------------------------------------
# AST 访问器: Pydantic 字段约束
# ---------------------------------------------------------------------------


class _PydanticConstraintVisitor(ast.NodeVisitor):
    """检测 Pydantic str 字段是否含 max_length 约束。"""

    def __init__(self, file: str, layer_id: str, builder: IssueBuilder) -> None:
        self.file = file
        self.layer_id = layer_id
        self.builder = builder
        self.issues: list[AuditIssue] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
        if "BaseModel" not in bases:
            self.generic_visit(node)
            return
        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                continue
            ann = stmt.annotation
            # str 字段: str / StringConstraints
            is_str = (
                (isinstance(ann, ast.Name) and ann.id == "str")
                or (isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name) and ann.value.id == "str")
            )
            if not is_str:
                continue
            # 检查 Field(...) 是否含 max_length
            value = stmt.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "Field":
                has_max_length = any(
                    kw.arg == "max_length" for kw in value.keywords
                )
                if not has_max_length:
                    self._add_issue(stmt.lineno, stmt.target.id)
            elif value is None:
                # 无 Field 约束
                self._add_issue(stmt.lineno, stmt.target.id)
        self.generic_visit(node)

    def _add_issue(self, line: int, field_name: str) -> None:
        self.issues.append(
            self.builder.build(
                layer_id=self.layer_id,
                severity=Severity.LOW,
                file=self.file,
                line=line,
                description=f"Pydantic str 字段 {field_name} 缺少 max_length 约束",
                suggestion="添加 Field(max_length=N) 约束防止超长输入",
                rule_id="L6-MISSING-MAXLENGTH-001",
                owner=DEFAULT_OWNER,
                due_date=DEFAULT_DUE_DATE,
            )
        )


# ---------------------------------------------------------------------------
# AST 访问器: SQL 注入红队探测
# ---------------------------------------------------------------------------


class _SqlInjectionRedTeamVisitor(ast.NodeVisitor):
    """检测 SQL 上下文中的字符串拼接(f-string / .format() / % / +)。"""

    def __init__(
        self,
        file: str,
        layer_id: str,
        builder: IssueBuilder,
        lines: list[str],
        sql_keywords: frozenset[str],
    ) -> None:
        self.file = file
        self.layer_id = layer_id
        self.builder = builder
        self.lines = lines
        self.sql_keywords = sql_keywords
        self.issues: list[AuditIssue] = []

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "format"
            and isinstance(func.value, ast.Constant | ast.JoinedStr)
            and self._is_sql_context(node)
        ):
            self._add_issue(node.lineno, "SQL 上下文使用 .format() 拼接,存在注入风险")
        self.generic_visit(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        has_value = any(isinstance(v, ast.FormattedValue) for v in node.values)
        if has_value and self._is_sql_context(node):
            self._add_issue(node.lineno, "SQL 上下文使用 f-string 拼接,存在注入风险")
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if isinstance(node.op, ast.Mod) and isinstance(node.left, ast.Constant | ast.JoinedStr):
            if self._is_sql_context(node):
                self._add_issue(node.lineno, "SQL 上下文使用 % 拼接,存在注入风险")
        elif (
            isinstance(node.op, ast.Add)
            and self._is_sql_context(node)
            and (
                isinstance(node.left, ast.Name | ast.Attribute | ast.Call)
                or isinstance(node.right, ast.Name | ast.Attribute | ast.Call)
            )
        ):
            self._add_issue(node.lineno, "SQL 上下文使用 + 拼接变量,存在注入风险")
        self.generic_visit(node)

    def _is_sql_context(self, node: ast.AST) -> bool:
        if node.lineno - 1 >= len(self.lines):
            return False
        # 豁免标记(任一命中即跳过):
        #   - nosec B608   bandit 标准豁免
        #   - noqa B608    ruff/noqa 豁免
        #   - sql-safe      项目自定义安全标记(白名单/绑定参数/常量片段/escape_like/ORM)
        # f-string 可能跨多行,检查 node.lineno..end_lineno 范围内任一行含豁免标记即视为已处理。
        end_lineno = getattr(node, "end_lineno", None) or node.lineno
        for ln in range(node.lineno, min(end_lineno, len(self.lines)) + 1):
            line_lower = self.lines[ln - 1].lower()
            if (
                ("nosec" in line_lower and "b608" in line_lower)
                or ("noqa" in line_lower and "b608" in line_lower)
                or ("sql-safe" in line_lower)
            ):
                return False
        line_lower = self.lines[node.lineno - 1].lower()
        return any(kw in line_lower for kw in self.sql_keywords)

    def _add_issue(self, line: int, desc: str) -> None:
        self.issues.append(
            self.builder.build(
                layer_id=self.layer_id,
                severity=Severity.CRITICAL,
                file=self.file,
                line=line,
                description=desc,
                suggestion="使用绑定参数(:param)构造 SQL,禁止字符串拼接用户输入",
                rule_id="L6-RED-TEAM-001",
                owner=DEFAULT_OWNER,
                due_date=DEFAULT_DUE_DATE,
            )
        )
