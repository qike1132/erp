"""L3 业务逻辑与正确性审核层执行器。

扫描 except 块/手动 commit/rollback/循环内查询;
全局异常处理器存在性校验。

约束: 复用上一轮 P1-4 宽泛 except 收敛基线,
桌面壳(根 ``server_manager.py`` 薄壳 + ``server_manager/`` 包内各模块)的宽泛
except 保留附说明,按**包前缀**豁免。

注: 本层的宽泛 except 扫描范围是 ``fastapi_app/**``(见 ``_scan_broad_except``),
桌面壳不在其中 —— 该白名单在**当前**扫描范围下不会命中任何被扫文件。保留它
并按包前缀修正语义,是为了(a)消除 basename 撞名的误豁免陷阱,(b)若将来把桌面壳
纳入扫描范围,豁免仍然正确。(T6 收尾,2026-09-28;premise 更正见 task-6-report。)

任务来源: ``.codeartsdoer/specs/prod_code_review/tasks.md`` 第 4 节。
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
FASTAPI_APP_DIR: Path = PROJECT_ROOT / "fastapi_app"
SERVICES_DIR: Path = FASTAPI_APP_DIR / "services"

# 白名单: 桌面壳入口模块(39 处宽泛 except 已逐一审查)。
# 包化后宽泛 except 的主体已散在 ``server_manager/`` 包内的 app.py / widgets.py /
# action_gate.py(仓库根的 ``server_manager.py`` 只剩薄壳),故按**包前缀**豁免整个
# 桌面壳,而不是按 basename —— basename 匹配既漏掉包内模块,又会与同名文件
# (如将来某个 ``app.py``)撞名而误豁免。
_BROAD_EXCEPT_WHITELIST_FILES: frozenset[str] = frozenset({"server_manager.py"})
_BROAD_EXCEPT_WHITELIST_PACKAGES: frozenset[str] = frozenset({"server_manager"})


def _is_broad_except_whitelisted(py_file: Path) -> bool:
    """桌面壳模块豁免:根薄壳 ``server_manager.py`` 与 ``server_manager/`` 包内各模块。"""
    if py_file.name in _BROAD_EXCEPT_WHITELIST_FILES:
        return True
    try:
        rel = py_file.resolve().relative_to(PROJECT_ROOT)
    except (OSError, ValueError):
        return False
    return bool(rel.parts) and rel.parts[0] in _BROAD_EXCEPT_WHITELIST_PACKAGES


# 全局异常处理器应注册的文件
_GLOBAL_HANDLER_FILES: tuple[Path, ...] = (
    FASTAPI_APP_DIR / "main.py",
    FASTAPI_APP_DIR / "core" / "middleware.py",
    FASTAPI_APP_DIR / "core" / "audit_middleware.py",
)

# 全局处理器识别模式
_EXCEPTION_HANDLER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"add_exception_handler|exception_handler|@app\.exception_handler"),
    re.compile(r"register_exception_handlers|setup_exception_handlers"),
)

DEFAULT_OWNER: str = "business-logic-reviewer"
DEFAULT_DUE_DATE: str = "2026-09-30"


class _LoopQueryVisitor(ast.NodeVisitor):
    """检测 for/async for 循环体内 await 查询调用(execute/scalar/scalars)。"""

    def __init__(self, file: str, layer_id: str, builder: IssueBuilder, lines: list[str] | None = None) -> None:
        self.file = file
        self.layer_id = layer_id
        self.builder = builder
        self.lines = lines or []
        self.issues: list[AuditIssue] = []
        self._loop_depth: int = 0

    def visit_For(self, node: ast.For) -> None:
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    visit_AsyncFor = visit_For

    def visit_Await(self, node: ast.Await) -> None:
        if self._loop_depth > 0 and isinstance(node.value, ast.Call):
            func = node.value.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in {"execute", "scalar", "scalars"}
            ):
                # 行内 # batch-loop: 标注豁免(有意逐行处理)
                line_text = self.lines[node.lineno - 1] if 0 < node.lineno <= len(self.lines) else ""
                if "batch-loop:" not in line_text:
                    self.issues.append(
                        self.builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.HIGH,
                            file=self.file,
                            line=node.lineno,
                            description=f"循环内数据库查询: .{func.attr}()",
                            suggestion="改为批量查询或 IN 子句,避免 N+1",
                            rule_id="L3-LOOP-DB-QUERY-001",
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )
        self.generic_visit(node)


class L3BusinessLogic(LayerBase):
    """L3 业务逻辑与正确性审核层执行器。"""

    layer_id: str = "L3"
    layer_name: str = "业务逻辑与正确性审核"
    weight: float = 0.12

    async def run(self, context: AuditContext) -> LayerResult:
        """执行 L3 全部子检查并归档证据。"""
        started_at = datetime.now(UTC)
        builder = IssueBuilder()

        broad_issues = self._scan_broad_except(builder)
        empty_issues = self._scan_empty_except(builder)
        global_issues = self._scan_global_exception_handler(builder)
        commit_issues = self._scan_manual_commit_rollback(builder)
        loop_issues = self._scan_loop_db_query(builder)

        all_issues: list[AuditIssue] = (
            broad_issues + empty_issues + global_issues + commit_issues + loop_issues
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
    # 异常处理扫描
    # ------------------------------------------------------------------

    def _scan_broad_except(self, builder: IssueBuilder) -> list[AuditIssue]:
        """AST 扫描 ``except Exception`` / 裸 ``except:``,白名单豁免。"""
        issues: list[AuditIssue] = []
        if not FASTAPI_APP_DIR.exists():
            return issues
        for py_file in FASTAPI_APP_DIR.rglob("*.py"):
            if "__pycache__" in py_file.parts or "tests" in py_file.parts:
                continue
            if _is_broad_except_whitelisted(py_file):
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue
            lines = source.splitlines()
            rel = py_file.relative_to(PROJECT_ROOT).as_posix()
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                kind = self._except_kind(node)
                if kind is None:
                    continue
                # 行内 # defensive: / # broad-except: 标注豁免
                line_text = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
                if "defensive:" in line_text or "broad-except:" in line_text:
                    continue
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.HIGH,
                        file=rel,
                        line=node.lineno,
                        description=f"宽泛 except: {kind}",
                        suggestion="捕获具体异常类型,避免吞掉所有异常",
                        rule_id="L3-BROAD-EXCEPT-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )
        return issues

    @staticmethod
    def _except_kind(handler: ast.ExceptHandler) -> str | None:
        """返回 except 风险类型,无风险返回 None。"""
        typ = handler.type
        if typ is None:
            return "bare except"
        if isinstance(typ, ast.Name) and typ.id == "Exception":
            return "except Exception"
        if isinstance(typ, ast.Tuple):
            for elt in typ.elts:
                if isinstance(elt, ast.Name) and elt.id == "Exception":
                    return "except (..., Exception)"
        return None

    def _scan_empty_except(self, builder: IssueBuilder) -> list[AuditIssue]:
        """AST 扫描空 except 块或仅 ``pass`` 的 except 块。"""
        issues: list[AuditIssue] = []
        if not FASTAPI_APP_DIR.exists():
            return issues
        for py_file in FASTAPI_APP_DIR.rglob("*.py"):
            if "__pycache__" in py_file.parts or "tests" in py_file.parts:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue
            lines = source.splitlines()
            rel = py_file.relative_to(PROJECT_ROOT).as_posix()
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                body = node.body
                # 行内 # defensive: / # broad-except: 标注豁免
                if self._except_has_exempt_comment(node, lines):
                    continue
                # 空 body 或仅 pass
                if not body:
                    issues.append(self._build_empty_except_issue(builder, rel, node.lineno, "空 except 块"))
                elif len(body) == 1 and isinstance(body[0], ast.Pass):
                    issues.append(self._build_empty_except_issue(builder, rel, node.lineno, "except 块仅 pass"))
        return issues

    @staticmethod
    def _except_has_exempt_comment(handler: ast.ExceptHandler, lines: list[str]) -> bool:
        """检查 except 行或其 body 语句行是否带有防御性豁免注释。"""
        for stmt in (handler, *handler.body):
            ln = stmt.lineno
            lt = lines[ln - 1] if 0 < ln <= len(lines) else ""
            if "defensive:" in lt or "broad-except:" in lt:
                return True
        return False

    def _build_empty_except_issue(
        self, builder: IssueBuilder, file: str, line: int, desc: str
    ) -> AuditIssue:
        return builder.build(
            layer_id=self.layer_id,
            severity=Severity.HIGH,
            file=file,
            line=line,
            description=desc,
            suggestion="至少记录异常日志或重新抛出",
            rule_id="L3-EMPTY-EXCEPT-001",
            owner=DEFAULT_OWNER,
            due_date=DEFAULT_DUE_DATE,
        )

    def _scan_global_exception_handler(self, builder: IssueBuilder) -> list[AuditIssue]:
        """检查 main.py/middleware.py 是否注册全局异常处理器。"""
        issues: list[AuditIssue] = []
        found_handler = False
        for candidate in _GLOBAL_HANDLER_FILES:
            if not candidate.exists():
                continue
            try:
                source = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for pattern in _EXCEPTION_HANDLER_PATTERNS:
                if pattern.search(source):
                    found_handler = True
                    break
            if found_handler:
                break
        if not found_handler:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file="fastapi_app/main.py",
                    line=1,
                    description="未检测到全局异常处理器注册",
                    suggestion="在 main.py 或 middleware.py 注册全局异常处理器,返回统一错误格式",
                    rule_id="L3-GLOBAL-HANDLER-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
        return issues

    # ------------------------------------------------------------------
    # 事务边界扫描
    # ------------------------------------------------------------------

    def _scan_manual_commit_rollback(self, builder: IssueBuilder) -> list[AuditIssue]:
        """AST 扫描 services/ 中 ``session.commit()`` / ``session.rollback()``。"""
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
            lines = source.splitlines()
            rel = py_file.relative_to(PROJECT_ROOT).as_posix()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute):
                    continue
                if func.attr not in {"commit", "rollback"}:
                    continue
                # 形如 session.commit() / db.commit()
                if not isinstance(func.value, ast.Name):
                    continue
                # 行内 manual-tx: / noqa 标注豁免
                line_text = lines[node.lineno - 1] if 0 < node.lineno <= len(lines) else ""
                if "manual-tx:" in line_text or "noqa" in line_text:
                    continue
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.HIGH,
                        file=rel,
                        line=node.lineno,
                        description=f"手动事务操作: {func.value.id}.{func.attr}()",
                        suggestion="事务应由 db_transaction 统一管理,避免手动 commit/rollback",
                        rule_id="L3-MANUAL-COMMIT-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )
        return issues

    def _scan_loop_db_query(self, builder: IssueBuilder) -> list[AuditIssue]:
        """AST 扫描 for 循环体内 ``await db.execute/scalar/scalars``。"""
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
            lines = source.splitlines()
            rel = py_file.relative_to(PROJECT_ROOT).as_posix()
            visitor = _LoopQueryVisitor(rel, self.layer_id, builder, lines)
            visitor.visit(tree)
            issues.extend(visitor.issues)
        return issues

    # ------------------------------------------------------------------
    # 证据归档
    # ------------------------------------------------------------------

    async def _archive_evidence(
        self,
        context: AuditContext,
        issues: Sequence[AuditIssue],
    ) -> Path:
        """归档问题清单与人工审查占位至 ``evidence/gate_logs/L3/``。"""
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
            filename="L3/issues.json",
        )
        # 人工审查记录占位
        path2 = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.MANUAL_REVIEW,
            content=(
                "# L3 业务逻辑人工审查记录\n\n"
                "## 边界条件审查\n待补充: boundary_conditions.md\n\n"
                "## 并发安全审查\n待补充: concurrency_safety.md\n"
            ),
            filename="L3/manual_review.md",
        )
        return path2 or path1
