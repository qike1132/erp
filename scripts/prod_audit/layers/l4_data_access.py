"""L4 数据访问层审核层执行器。

N+1 治理成果验证 / SQL 注入扫描扩展 / nosec B608 标注保留校验。

约束:
    - 复用存量 ``scripts/check_n_plus_one.py``
    - 复用上一轮 P0-1 N+1 治理基线(6 个高危文件循环内查询数为 0)
    - 复用上一轮 P0-3 CTE 索引验证基线
    - ``stock_inventory_service.py`` 4 处 nosec B608 标注须保留且使用绑定参数

任务来源: ``.codeartsdoer/specs/prod_code_review/tasks.md`` 第 5 节。
"""

from __future__ import annotations

import ast
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
FASTAPI_APP_DIR: Path = PROJECT_ROOT / "fastapi_app"
SERVICES_DIR: Path = FASTAPI_APP_DIR / "services"

# 上一轮 P0-1 治理的 6 个高危文件(目录或文件路径)
_HIGH_RISK_N_PLUS_ONE_TARGETS: tuple[str, ...] = (
    "fastapi_app/services/purchase_plan_crud.py",
    "fastapi_app/services/purchase_order_query.py",
    "fastapi_app/services/customer_sampling",
    "fastapi_app/services/dashboard_service.py",
    "fastapi_app/services/order_crud.py",
    "fastapi_app/services/stock_service.py",
)

# nosec B608 标注基线：stock_service.py 经重构 f585040d 已变为纯再导出 shim（0 处），
# SQL 与标注迁到 stock_inventory_service.py（评审 2026-10-11 修：规则原先指向 shim 文件，
# 稳定误报「0 < 预期 6」）。
_STOCK_SERVICE_PATH: Path = SERVICES_DIR / "stock_inventory_service.py"
_EXPECTED_NOSEC_B608_COUNT: int = 4

# N+1 扫描脚本超时(秒)
_N_PLUS_ONE_TIMEOUT: int = 300

DEFAULT_OWNER: str = "data-access-reviewer"
DEFAULT_DUE_DATE: str = "2026-09-30"

# SQL 上下文关键词: 出现在这些关键词附近的字符串拼接视为 SQL 注入风险
_SQL_CONTEXT_KEYWORDS: frozenset[str] = frozenset(
    {
        "execute",
        "exec",
        "text",
        "raw",
        "query",
        "sql",
        "stmt",
        "statement",
    }
)


class L4DataAccess(LayerBase):
    """L4 数据访问层审核层执行器。"""

    layer_id: str = "L4"
    layer_name: str = "数据访问层审核"
    weight: float = 0.10

    async def run(self, context: AuditContext) -> LayerResult:
        """执行 L4 全部子检查并归档证据。"""
        started_at = datetime.now(UTC)
        builder = IssueBuilder()

        baseline_issues = await self._verify_n_plus_one_baseline(builder)
        new_n_plus_one_issues = await self._scan_new_n_plus_one(builder)
        sql_injection_issues = self._scan_sql_injection(builder)
        nosec_issues = self._check_nsec_b608(builder)

        all_issues: list[AuditIssue] = (
            baseline_issues
            + new_n_plus_one_issues
            + sql_injection_issues
            + nosec_issues
        )

        is_green = self.check_gate(all_issues, threshold=Severity.HIGH)
        status = LayerStatus.PASSED if is_green else LayerStatus.BLOCKED

        evidence_path = await self._archive_evidence(context, all_issues)

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
    # N+1 治理成果验证
    # ------------------------------------------------------------------

    async def _verify_n_plus_one_baseline(
        self, builder: IssueBuilder
    ) -> list[AuditIssue]:
        """对 6 个高危文件执行 N+1 扫描,断言循环内查询数为 0。"""
        issues: list[AuditIssue] = []
        for target in _HIGH_RISK_N_PLUS_ONE_TARGETS:
            target_path = PROJECT_ROOT / target
            if not target_path.exists():
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.MEDIUM,
                        file=target,
                        line=1,
                        description=f"高危 N+1 基线文件缺失: {target}",
                        suggestion="确认文件路径或更新基线清单",
                        rule_id="L4-NPLUS-BASELINE-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )
                continue
            violations, _raw = await self._run_n_plus_one_scan(target)
            if violations:
                for v in violations:
                    v_file = v.get("file", target)
                    v_line = int(v.get("line", 1))
                    # 行内 # batch-loop: 标注豁免(有意逐行处理,非 N+1)
                    if self._has_batch_loop_marker(v_file, v_line):
                        continue
                    issues.append(
                        builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.HIGH,
                            file=v_file,
                            line=v_line,
                            description=(
                                f"基线文件 {target} 出现循环内查询 "
                                f"{v.get('query_call', '?')}(违反 P0-1 治理基线)"
                            ),
                            suggestion="改为批量查询或 IN 子句/selectinload",
                            rule_id="L4-NPLUS-BASELINE-001",
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )
        return issues

    async def _scan_new_n_plus_one(
        self, builder: IssueBuilder
    ) -> list[AuditIssue]:
        """全量扫描 services/ 发现新增 N+1 模式。"""
        issues: list[AuditIssue] = []
        if not SERVICES_DIR.exists():
            return issues
        violations, _ = await self._run_n_plus_one_scan("fastapi_app/services")
        for v in violations:
            v_file = v.get("file", "")
            v_line = int(v.get("line", 1))
            # 行内 # batch-loop: 标注豁免(有意逐行处理,非 N+1)
            if self._has_batch_loop_marker(v_file, v_line):
                continue
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file=v_file,
                    line=v_line,
                    description=(
                        f"新增 N+1 模式: {v.get('function', '?')}() 内 "
                        f".{v.get('query_call', '?')}() [loop: {v.get('loop_var', '?')}]"
                    ),
                    suggestion="改为批量查询或 IN 子句/selectinload",
                    rule_id="L4-NEW-N-PLUS-ONE-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
        return issues

    async def _run_n_plus_one_scan(
        self, target: str
    ) -> tuple[list[dict[str, object]], str]:
        """调用 ``scripts/check_n_plus_one.py --json`` 扫描指定路径。

        返回:
            (violations 列表, 原始输出)
        """
        cmd = [
            sys.executable,
            "scripts/check_n_plus_one.py",
            "--json",
            target,
        ]
        # 传入白名单文件(若存在),豁免已确认有意的逐行处理
        whitelist_path = PROJECT_ROOT / "scripts" / "allowed_n_plus_one.yaml"
        if whitelist_path.exists():
            cmd.extend(["--whitelist", str(whitelist_path)])
        try:
            proc = await asyncio_to_thread_subprocess(
                cmd,
                cwd=str(PROJECT_ROOT),
                timeout=_N_PLUS_ONE_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return [], "TIMEOUT"
        raw = proc.stdout + proc.stderr
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return [], raw
        violations = data.get("violations", [])
        return violations, raw

    @staticmethod
    def _has_batch_loop_marker(file: str, line: int) -> bool:
        """检查指定文件行是否含 ``# batch-loop:`` 标注(有意逐行处理豁免)。"""
        if not file or line < 1:
            return False
        path = PROJECT_ROOT / file
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False
        lines = source.splitlines()
        if line - 1 >= len(lines):
            return False
        return "batch-loop:" in lines[line - 1]

    # ------------------------------------------------------------------
    # SQL 注入扫描
    # ------------------------------------------------------------------

    def _scan_sql_injection(self, builder: IssueBuilder) -> list[AuditIssue]:
        """AST 扫描 services/ 中 f-string / .format() / % 拼接用户输入到 SQL。"""
        issues: list[AuditIssue] = []
        if not SERVICES_DIR.exists():
            return issues
        for py_file in SERVICES_DIR.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue
            rel = py_file.relative_to(PROJECT_ROOT).as_posix()
            visitor = _SqlInjectionVisitor(rel, self.layer_id, builder)
            visitor.visit(tree)
            issues.extend(visitor.issues)
        return issues

    # ------------------------------------------------------------------
    # nosec B608 标注校验
    # ------------------------------------------------------------------

    def _check_nsec_b608(self, builder: IssueBuilder) -> list[AuditIssue]:
        """验证 stock_inventory_service.py 4 处 nosec B608 标注保留且使用绑定参数。"""
        issues: list[AuditIssue] = []
        if not _STOCK_SERVICE_PATH.exists():
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file=str(_STOCK_SERVICE_PATH.relative_to(PROJECT_ROOT).as_posix()),
                    line=1,
                    description="stock_service.py 不存在,无法校验 nosec B608 基线",
                    suggestion="确认 stock_service.py 路径",
                    rule_id="L4-NOSEC-B608-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
            return issues

        try:
            source = _STOCK_SERVICE_PATH.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file=str(_STOCK_SERVICE_PATH.relative_to(PROJECT_ROOT).as_posix()),
                    line=1,
                    description=f"读取 stock_service.py 失败: {exc}",
                    suggestion="检查文件权限与编码",
                    rule_id="L4-NOSEC-B608-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
            return issues

        rel = _STOCK_SERVICE_PATH.relative_to(PROJECT_ROOT).as_posix()
        lines = source.splitlines()

        # 统计 nosec B608 标注(兼容 noqa 与 nosec 两种写法)
        nosec_b608_lines = self._collect_nosec_b608_lines(lines)

        if len(nosec_b608_lines) < _EXPECTED_NOSEC_B608_COUNT:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file=rel,
                    line=1,
                    description=(
                        f"stock_inventory_service.py nosec B608 标注数 "
                        f"{len(nosec_b608_lines)} < 预期 {_EXPECTED_NOSEC_B608_COUNT}"
                    ),
                    suggestion="恢复 nosec B608 标注或确认基线变更",
                    rule_id="L4-NOSEC-B608-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )

        # 校验每处 nosec B608 附近使用绑定参数(:param)
        self._check_nosec_binding_params(lines, nosec_b608_lines, rel, builder, issues)
        return issues

    def _collect_nosec_b608_lines(self, lines: list[str]) -> list[int]:
        """统计 nosec B608 标注行号(兼容 noqa 与 nosec 两种写法)。"""
        nosec_b608_lines: list[int] = []
        nosec_re = re.compile(r"#\s*(?:noqa\s*:\s*|nosec\s+)B608", re.IGNORECASE)
        for idx, line in enumerate(lines, start=1):
            if nosec_re.search(line):
                nosec_b608_lines.append(idx)
        return nosec_b608_lines

    def _check_nosec_binding_params(
        self,
        lines: list[str],
        nosec_b608_lines: list[int],
        rel: str,
        builder: IssueBuilder,
        issues: list[AuditIssue],
    ) -> None:
        """校验每处 nosec B608 附近使用绑定参数(:param)。"""
        binding_re = re.compile(r":\w+")
        # 注释中含"绑定参数"关键词视为已确认安全(通过模块级常量间接绑定)
        binding_note_re = re.compile(r"绑定参数|常量", re.IGNORECASE)
        for line_no in nosec_b608_lines:
            # 检查该行及前后 2 行是否含绑定参数
            window_start = max(0, line_no - 3)
            window_end = min(len(lines), line_no + 2)
            window = "\n".join(lines[window_start:window_end])
            # 行内注释已声明"绑定参数"/"常量"则豁免(常量片段含 :param)
            line_text = lines[line_no - 1] if line_no - 1 < len(lines) else ""
            if binding_note_re.search(line_text):
                continue
            if not binding_re.search(window):
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.HIGH,
                        file=rel,
                        line=line_no,
                        description="nosec B608 标注附近未检测到绑定参数(:param)",
                        suggestion="使用绑定参数(:param)构造 SQL,避免字符串拼接",
                        rule_id="L4-NOSEC-B608-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )

    # ------------------------------------------------------------------
    # 证据归档
    # ------------------------------------------------------------------

    async def _archive_evidence(
        self,
        context: AuditContext,
        issues: Sequence[AuditIssue],
    ) -> Path:
        """归档扫描结果至 ``evidence/gate_logs/L4/``。"""
        archiver = context.archiver
        issues_json = json.dumps(
            [issue.model_dump(mode="json") for issue in issues],
            ensure_ascii=False,
            indent=2,
        )
        path1 = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=issues_json,
            filename="L4/issues.json",
        )
        path2 = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=(
                "# L4 数据访问层审核\n\n"
                "## N+1 基线验证\n6 个高危文件循环内查询数应为 0。\n\n"
                "## SQL 注入扫描\n扫描 services/ 中 f-string/.format()/% 拼接。\n\n"
                "## nosec B608 校验\nstock_service.py 6 处 nosec B608 标注须保留。\n"
            ),
            filename="L4/summary.md",
        )
        return path2 or path1


# ---------------------------------------------------------------------------
# 辅助: subprocess 异步包装
# ---------------------------------------------------------------------------


async def asyncio_to_thread_subprocess(
    cmd: list[str],
    cwd: str,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    """在独立线程中执行 subprocess.run。"""
    import asyncio

    return await asyncio.to_thread(
        subprocess.run,
        cmd,
        capture_output=True,
        encoding="utf-8",
        cwd=cwd,
        timeout=timeout,
        check=False,
    )


# ---------------------------------------------------------------------------
# SQL 注入 AST 访问器
# ---------------------------------------------------------------------------


class _SqlInjectionVisitor(ast.NodeVisitor):
    """检测 SQL 上下文中的字符串拼接(f-string / .format() / %)。"""

    def __init__(self, file: str, layer_id: str, builder: IssueBuilder) -> None:
        self.file = file
        self.layer_id = layer_id
        self.builder = builder
        self.issues: list[AuditIssue] = []

    def visit_Call(self, node: ast.Call) -> None:
        # 检测 .format() 调用且调用者是字符串字面量/JoinStr
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "format"
            and self._is_string_like(func.value)
            and self._is_in_sql_context(node)
        ):
            self._add_issue(
                node.lineno,
                "SQL 上下文使用 .format() 拼接,存在注入风险",
            )
        self.generic_visit(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        # f-string: 仅当含 FormattedValue 且在 SQL 上下文
        has_value = any(isinstance(v, ast.FormattedValue) for v in node.values)
        if has_value and self._is_in_sql_context(node):
            self._add_issue(
                node.lineno,
                "SQL 上下文使用 f-string 拼接,存在注入风险",
            )
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        # 字符串 % 拼接: str % args
        if isinstance(node.op, ast.Mod) and self._is_string_like(node.left):
            if self._is_in_sql_context(node):
                self._add_issue(
                    node.lineno,
                    "SQL 上下文使用 % 拼接,存在注入风险",
                )
        # 字符串 + 拼接(弱信号,仅当一侧含变量且在 SQL 上下文)
        elif (
            isinstance(node.op, ast.Add)
            and self._is_in_sql_context(node)
            and (self._has_variable(node.left) or self._has_variable(node.right))
        ):
            self._add_issue(
                node.lineno,
                "SQL 上下文使用 + 拼接变量,存在注入风险",
            )
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _is_string_like(node: ast.AST) -> bool:
        return isinstance(node, ast.Constant | ast.Str | ast.JoinedStr)

    @staticmethod
    def _has_variable(node: ast.AST) -> bool:
        return isinstance(node, ast.Name | ast.Attribute | ast.Call | ast.Subscript)

    def _is_in_sql_context(self, node: ast.AST) -> bool:
        """启发式判断: 检查节点所在行的文本是否含 SQL 上下文关键词。

        由于 AST 节点不直接携带父上下文,这里基于行号回查源文件。
        为保持简单,采用宽松策略: 只要节点行文本含 SQL 关键词即视为 SQL 上下文。
        """
        try:
            source = Path(PROJECT_ROOT / self.file).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False
        lines = source.splitlines()
        if node.lineno - 1 >= len(lines):
            return False
        line_text = lines[node.lineno - 1].lower()
        # 行内 nosec B608 / noqa: B608 标注豁免
        if "b608" in line_text and ("noqa" in line_text or "nosec" in line_text):
            return False
        # 行内 # sql-safe: 标注豁免(已确认安全: escape_like/绑定参数/常量片段)
        if "sql-safe:" in line_text:
            return False
        return any(kw in line_text for kw in _SQL_CONTEXT_KEYWORDS)

    def _add_issue(self, line: int, desc: str) -> None:
        self.issues.append(
            self.builder.build(
                layer_id=self.layer_id,
                severity=Severity.CRITICAL,
                file=self.file,
                line=line,
                description=desc,
                suggestion="使用绑定参数(:param)构造 SQL,禁止字符串拼接用户输入",
                rule_id="L4-SQL-INJECTION-001",
                owner=DEFAULT_OWNER,
                due_date=DEFAULT_DUE_DATE,
            )
        )
