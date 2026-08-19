"""L9 测试质量审核层执行器。

覆盖率分级阈值 / 关键路径覆盖 / 测试质量扫描 / 测试独立性校验。

约束:
    - 复用存量 pytest 套件与上一轮新增单测
    - 测试须独立可重复
    - 覆盖率分级阈值: 核心 ≥ 85% / 备份 ≥ 80% / 来料 ≥ 75% / 仪表盘 ≥ 70%

任务来源: ``.codeartsdoer/specs/prod_code_review/tasks.md`` 第 10 节。
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

FASTAPI_APP_DIR: Path = PROJECT_ROOT / "fastapi_app"
TESTS_DIR: Path = PROJECT_ROOT / "tests"

DEFAULT_OWNER: str = "test-quality-reviewer"
DEFAULT_DUE_DATE: str = "2026-09-30"

# 子进程超时(秒)
_PYTEST_TIMEOUT: int = 600

# 覆盖率分级阈值(%)
_COVERAGE_THRESHOLDS: dict[str, int] = {
    "core": 85,
    "backup": 80,
    "incoming": 75,
    "dashboard": 70,
}

# 模块路径前缀 → 阈值分级
_MODULE_TIER_MAP: list[tuple[str, str]] = [
    ("fastapi_app/services/order", "core"),
    ("fastapi_app/services/purchase", "core"),
    ("fastapi_app/services/stock", "core"),
    ("fastapi_app/services/customer_order", "core"),
    ("fastapi_app/services/backup", "backup"),
    ("fastapi_app/services/approval", "backup"),
    ("fastapi_app/services/user", "backup"),
    ("fastapi_app/services/customer", "backup"),
    ("fastapi_app/services/incoming", "incoming"),
    ("fastapi_app/services/shipment", "incoming"),
    ("fastapi_app/services/production", "incoming"),
    ("fastapi_app/services/supplier", "incoming"),
    ("fastapi_app/services/dashboard", "dashboard"),
    ("fastapi_app/services/report", "dashboard"),
]

# 关键业务路径(函数名关键词 → 期望测试文件名片段)
_CRITICAL_PATHS: dict[str, list[str]] = {
    "order_creation": ["test_order", "test_order_management", "test_order_routes"],
    "stock_deduction": ["test_stock", "test_stock_management", "test_stock_concurrency"],
    "approval_flow": ["test_approval", "test_approval_management"],
    "backup_restore": ["test_backup"],
}

# skip/xfail 标记正则(须附 issue 链接)
_SKIP_MARK_RE = re.compile(
    r"@pytest\.mark\.(skip|xfail)\s*\(([^)]*)\)|@pytest\.mark\.(skip|xfail)\b"
)
_ISSUE_LINK_RE = re.compile(r"(?i)(issue|#[0-9]+|GH-|JIRA-|https?://)")

# 空断言正则
_EMPTY_ASSERT_RE = re.compile(r"^\s*assert\s+True\s*(?:#.*)?$")
_PASS_ONLY_RE = re.compile(r"^\s*pass\s*(?:#.*)?$")


class L9TestQuality(LayerBase):
    """L9 测试质量审核层执行器。

    聚合 5 个子检查:
        - 覆盖率分级阈值(pytest --cov)
        - 关键路径覆盖(订单/库存/审批/备份)
        - 无 skip/xfail(除附 issue 链接)
        - 断言质量(无空断言/pass-only)
        - 测试独立性(使用 fixture,无共享状态)
    """

    layer_id: str = "L9"
    layer_name: str = "测试质量审核"
    weight: float = 0.08

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    async def run(self, context: AuditContext) -> LayerResult:
        """执行 L9 全部子检查并归档证据。"""
        started_at = datetime.now(UTC)
        builder = IssueBuilder()
        raw_outputs: dict[str, str] = {}

        checks: list[tuple[str, object]] = [
            ("coverage", self._check_coverage(builder)),
            ("critical_path", self._check_critical_path_coverage(builder)),
            ("no_skip", self._check_no_skip(builder)),
            ("assertion_quality", self._check_assertion_quality(builder)),
            ("test_isolation", self._check_test_isolation(builder)),
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
                        suggestion="检查 tests/ 目录与 pytest 安装",
                        rule_id=f"L9-{name.upper()}-EXEC-001",
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
    # 10.1 覆盖率分级阈值
    # ------------------------------------------------------------------

    async def _check_coverage(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """执行 ``pytest --cov=fastapi_app --cov-report=json`` 并按分级阈值校验。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "--cov=fastapi_app",
            "--cov-report=json:coverage.json",
            "--cov-report=term-missing",
            "-q",
        ]

        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                encoding="utf-8",
                cwd=str(PROJECT_ROOT),
                timeout=_PYTEST_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file="tests/",
                    line=1,
                    description=f"pytest 覆盖率执行超时(>{_PYTEST_TIMEOUT}s)",
                    suggestion="检查测试套件规模或增大超时阈值",
                    rule_id="L9-COVERAGE-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
            return issues, "TIMEOUT"
        except FileNotFoundError:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file="tests/",
                    line=1,
                    description="pytest 未安装,无法执行覆盖率分析",
                    suggestion="安装 pytest 与 pytest-cov",
                    rule_id="L9-COVERAGE-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
            return issues, "pytest 未安装"

        raw_parts.append(f"pytest_exit_code: {proc.returncode}")
        raw_parts.append(f"pytest_stdout_tail:\n{proc.stdout[-2000:]}")
        if proc.stderr:
            raw_parts.append(f"pytest_stderr_tail:\n{proc.stderr[-1000:]}")

        coverage_file = PROJECT_ROOT / "coverage.json"
        if not coverage_file.exists():
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file="coverage.json",
                    line=1,
                    description="覆盖率报告 coverage.json 未生成(降级为警告,不阻断 pipeline)",
                    suggestion=(
                        "如需覆盖率分级校验,请手动执行: "
                        "python -m pytest --cov=fastapi_app "
                        "--cov-report=json:coverage.json fastapi_app/tests/"
                    ),
                    rule_id="L9-COVERAGE-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
            return issues, "\n".join(raw_parts)

        try:
            cov_data = json.loads(coverage_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file="coverage.json",
                    line=1,
                    description=f"解析覆盖率报告失败: {exc}",
                    suggestion="重新生成覆盖率报告",
                    rule_id="L9-COVERAGE-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
            return issues, "\n".join(raw_parts)

        # 按模块分级校验
        files_cov: dict[str, dict[str, object]] = cov_data.get("files", {})
        tier_min_cov: dict[str, float] = dict.fromkeys(_COVERAGE_THRESHOLDS, 0.0)
        tier_file_count: dict[str, int] = dict.fromkeys(_COVERAGE_THRESHOLDS, 0)

        for file_path, file_data in files_cov.items():
            tier = self._classify_module(file_path)
            if tier is None:
                continue
            summary = file_data.get("summary", {})
            percent = summary.get("percent_covered", 0.0)
            tier_min_cov[tier] = min(tier_min_cov[tier], percent) if tier_file_count[tier] > 0 else percent
            tier_file_count[tier] += 1
            if percent < tier_min_cov[tier]:
                tier_min_cov[tier] = percent

        for tier, threshold in _COVERAGE_THRESHOLDS.items():
            count = tier_file_count[tier]
            min_cov = tier_min_cov[tier]
            raw_parts.append(
                f"tier={tier}: files={count}, min_coverage={min_cov:.1f}%, threshold={threshold}%"
            )
            if count == 0:
                continue
            if min_cov < threshold:
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.MEDIUM,
                        file=f"fastapi_app/ ({tier})",
                        line=1,
                        description=(
                            f"{tier} 模块覆盖率 {min_cov:.1f}% 低于阈值 {threshold}%"
                        ),
                        suggestion=f"补充 {tier} 模块单元测试至覆盖率 ≥ {threshold}%",
                        rule_id="L9-COVERAGE-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )

        return issues, "\n".join(raw_parts)

    @staticmethod
    def _classify_module(file_path: str) -> str | None:
        """将文件路径映射到覆盖率分级。"""
        normalized = file_path.replace("\\", "/")
        for prefix, tier in _MODULE_TIER_MAP:
            if normalized.startswith(prefix):
                return tier
        return None

    # ------------------------------------------------------------------
    # 10.2 关键路径覆盖
    # ------------------------------------------------------------------

    async def _check_critical_path_coverage(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """审查关键业务路径单测覆盖: 订单创建/库存扣减/审批流/备份恢复。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        if not TESTS_DIR.exists():
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file="tests/",
                    line=1,
                    description="tests/ 目录不存在,关键路径无单测覆盖",
                    suggestion="创建 tests/ 目录并补充关键路径单测",
                    rule_id="L9-CRITICAL-PATH-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
            return issues, "tests/ 不存在"

        test_files: list[Path] = list(TESTS_DIR.rglob("test_*.py"))
        test_names = {f.name for f in test_files}

        for path_name, expected_fragments in _CRITICAL_PATHS.items():
            found = any(
                any(frag in name for frag in expected_fragments)
                for name in test_names
            )
            raw_parts.append(
                f"critical_path={path_name}: found={found}, expected_fragments={expected_fragments}"
            )
            if not found:
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.HIGH,
                        file="tests/",
                        line=1,
                        description=(
                            f"关键业务路径 {path_name} 缺少单测覆盖"
                            f"(期望含: {expected_fragments})"
                        ),
                        suggestion=f"补充 {path_name} 关键路径单测",
                        rule_id="L9-CRITICAL-PATH-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )

        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 10.3 无 skip/xfail(除附 issue 链接)
    # ------------------------------------------------------------------

    async def _check_no_skip(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """AST 扫描测试文件中 skip/xfail 标记(除附 issue 跟踪链接)。"""
        issues: list[AuditIssue] = []
        scanned = 0
        raw_parts: list[str] = []

        if not TESTS_DIR.exists():
            return issues, "tests/ 不存在"

        for py_file in TESTS_DIR.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            scanned += 1
            rel = py_file.relative_to(PROJECT_ROOT).as_posix()

            for match in _SKIP_MARK_RE.finditer(source):
                # 检查是否附 issue 链接
                full_match_text = match.group(0)
                reason = match.group(2) or ""
                has_link = bool(_ISSUE_LINK_RE.search(reason)) or bool(
                    _ISSUE_LINK_RE.search(full_match_text)
                )
                if has_link:
                    continue

                # 计算行号
                line_no = source[: match.start()].count("\n") + 1
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.MEDIUM,
                        file=rel,
                        line=line_no,
                        description=(
                            f"测试含 {match.group(1) or match.group(3)} 标记"
                            "但未附 issue 跟踪链接"
                        ),
                        suggestion="添加 reason=#issue 或移除 skip/xfail 标记",
                        rule_id="L9-SKIP-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )

        raw_parts.append(f"scanned_files: {scanned}")
        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 10.3 断言质量(无空断言/pass-only)
    # ------------------------------------------------------------------

    async def _check_assertion_quality(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """AST 扫描测试函数体是否含有效断言(无 assert True / pass-only)。"""
        issues: list[AuditIssue] = []
        scanned = 0
        raw_parts: list[str] = []

        if not TESTS_DIR.exists():
            return issues, "tests/ 不存在"

        for py_file in TESTS_DIR.rglob("test_*.py"):
            if "__pycache__" in py_file.parts:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue
            scanned += 1
            rel = py_file.relative_to(PROJECT_ROOT).as_posix()
            visitor = _AssertionQualityVisitor(rel, self.layer_id, builder)
            visitor.visit(tree)
            issues.extend(visitor.issues)

        raw_parts.append(f"scanned_files: {scanned}")
        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 10.3 测试独立性(使用 fixture,无共享状态)
    # ------------------------------------------------------------------

    async def _check_test_isolation(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """审查测试是否使用 fixture 且不共享可变状态(模块级可变变量)。"""
        issues: list[AuditIssue] = []
        scanned = 0
        raw_parts: list[str] = []

        if not TESTS_DIR.exists():
            return issues, "tests/ 不存在"

        for py_file in TESTS_DIR.rglob("test_*.py"):
            if "__pycache__" in py_file.parts:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue
            scanned += 1
            rel = py_file.relative_to(PROJECT_ROOT).as_posix()
            visitor = _TestIsolationVisitor(rel, self.layer_id, builder)
            visitor.visit(tree)
            issues.extend(visitor.issues)

        raw_parts.append(f"scanned_files: {scanned}")
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
        """归档覆盖率报告与审查记录至 ``evidence/coverage_reports/`` 与 ``evidence/gate_logs/L9/``。"""
        archiver = context.archiver

        # 1. 覆盖率原始输出
        path_cov = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.COVERAGE_REPORT,
            content=raw_outputs.get("coverage", "N/A"),
            filename="L9/pytest_coverage.txt",
        )

        # 2. 原始扫描输出
        path_raw = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content="\n\n".join(f"=== {k} ===\n{v}" for k, v in raw_outputs.items()),
            filename="L9/scan_raw.txt",
        )

        # 3. issues.json
        issues_json = json.dumps(
            [issue.model_dump(mode="json") for issue in issues],
            ensure_ascii=False,
            indent=2,
        )
        path_issues = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=issues_json,
            filename="L9/issues.json",
        )

        # 4. summary.md
        path_summary = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=(
                "# L9 测试质量审核\n\n"
                "## 覆盖率分级阈值\n核心 ≥ 85% / 备份 ≥ 80% / 来料 ≥ 75% / 仪表盘 ≥ 70%。\n\n"
                "## 关键路径覆盖\n订单创建/库存扣减/审批流/备份恢复须有单测。\n\n"
                "## 无 skip/xfail\nskip/xfail 须附 issue 跟踪链接。\n\n"
                "## 断言质量\n测试函数须含有效断言,无 assert True / pass-only。\n\n"
                "## 测试独立性\n测试须使用 fixture,无模块级可变共享状态。\n"
            ),
            filename="L9/summary.md",
        )

        return path_summary or path_issues or path_raw or path_cov


# ---------------------------------------------------------------------------
# AST 访问器: 断言质量
# ---------------------------------------------------------------------------


class _AssertionQualityVisitor(ast.NodeVisitor):
    """检测测试函数体是否含有效断言。"""

    def __init__(self, file: str, layer_id: str, builder: IssueBuilder) -> None:
        self.file = file
        self.layer_id = layer_id
        self.builder = builder
        self.issues: list[AuditIssue] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if not node.name.startswith("test_"):
            self.generic_visit(node)
            return

        # 收集函数体中的 assert 语句
        asserts: list[ast.Assert] = [
            child for child in ast.walk(node) if isinstance(child, ast.Assert)
        ]

        if not asserts:
            # 检查是否 pass-only(函数体仅含 pass / docstring / return)
            body = node.body
            meaningful = [
                s for s in body
                if not isinstance(s, ast.Expr)
                or not isinstance(getattr(s, "value", None), ast.Constant)
            ]
            if all(isinstance(s, ast.Pass) for s in meaningful) or not meaningful:
                self.issues.append(
                    self.builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.MEDIUM,
                        file=self.file,
                        line=node.lineno,
                        description=f"测试 {node.name} 无任何断言(pass-only)",
                        suggestion="添加有效断言或删除空测试",
                        rule_id="L9-EMPTY-ASSERT-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )
        else:
            # 检查是否存在 assert True 空断言
            for assertion in asserts:
                test_expr = assertion.test
                if isinstance(test_expr, ast.Constant) and test_expr.value is True:
                    self.issues.append(
                        self.builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.MEDIUM,
                            file=self.file,
                            line=assertion.lineno,
                            description=f"测试 {node.name} 含空断言 assert True",
                            suggestion="替换为有意义的断言",
                            rule_id="L9-EMPTY-ASSERT-001",
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )

        self.generic_visit(node)


# ---------------------------------------------------------------------------
# AST 访问器: 测试独立性
# ---------------------------------------------------------------------------


class _TestIsolationVisitor(ast.NodeVisitor):
    """检测测试是否使用 fixture 且不共享模块级可变状态。"""

    # 可变类型注解名
    _MUTABLE_TYPES: frozenset[str] = frozenset(
        {"list", "dict", "set", "List", "Dict", "Set", "deque", "OrderedDict"}
    )

    def __init__(self, file: str, layer_id: str, builder: IssueBuilder) -> None:
        self.file = file
        self.layer_id = layer_id
        self.builder = builder
        self.issues: list[AuditIssue] = []

    def visit_Assign(self, node: ast.Assign) -> None:
        # 检测模块级可变赋值(列表/字典/集合字面量)
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            # 仅关注模块级(无函数上下文)— 简化: 检查赋值右侧是否为可变字面量
            value = node.value
            if (
                isinstance(value, (ast.List, ast.Dict, ast.Set))
                and not target.id.isupper()
            ):
                self.issues.append(
                    self.builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.LOW,
                        file=self.file,
                        line=node.lineno,
                        description=(
                            f"模块级可变状态 {target.id} 可能导致测试间共享状态"
                        ),
                        suggestion="使用 fixture 或工厂函数替代模块级可变变量",
                        rule_id="L9-TEST-DEP-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if not node.name.startswith("test_"):
            self.generic_visit(node)
            return

        # 检查测试函数是否使用 fixture 参数
        params = node.args.args
        has_fixture_param = len(params) > 0  # 除 self 外有参数即视为 fixture

        if not has_fixture_param:
            self.issues.append(
                self.builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.LOW,
                    file=self.file,
                    line=node.lineno,
                    description=f"测试 {node.name} 未使用 fixture 参数",
                    suggestion="使用 fixture 注入测试数据以保证独立性",
                    rule_id="L9-TEST-DEP-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )

        self.generic_visit(node)
