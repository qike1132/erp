"""L2 架构与分层审核层执行器。

基于 AST 生成后端模块依赖图,检测反向依赖/循环依赖/
职责单一(服务文件长度)/端点瘦身(业务逻辑下沉)。

依赖方向约束: ``endpoints → services → core → models``,禁止反向。
例外: ``core → services`` 允许 —— core 是组合根(AGENTS.md §2)。

任务来源: ``.codeartsdoer/specs/prod_code_review/tasks.md`` 第 3 节。
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

# 模块根目录
ENDPOINTS_DIR: Path = PROJECT_ROOT / "fastapi_app" / "api" / "v1" / "endpoints"
SERVICES_DIR: Path = PROJECT_ROOT / "fastapi_app" / "services"
CORE_DIR: Path = PROJECT_ROOT / "fastapi_app" / "core"
MODELS_DIR: Path = PROJECT_ROOT / "fastapi_app" / "models"

# 分层等级(数字越小越靠上);依赖只能从高等级流向低等级
_LAYER_RANK: dict[str, int] = {
    "endpoints": 0,
    "services": 1,
    "core": 2,
    "models": 3,
}

# 服务文件行数阈值
_SERVICE_FILE_LENGTH_LIMIT: int = 800

DEFAULT_OWNER: str = "architecture-reviewer"
DEFAULT_DUE_DATE: str = "2026-09-30"

# 端点中禁止出现的业务逻辑模式
_ENDPOINT_BUSINESS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsession\.commit\s*\("),
    re.compile(r"\bsession\.rollback\s*\("),
    re.compile(r"\bsession\.flush\s*\("),
    re.compile(r"\bawait\s+\w+\.execute\s*\("),
    re.compile(r"\bawait\s+\w+\.scalar\s*\("),
    re.compile(r"\bawait\s+\w+\.scalars\s*\("),
)


class L2Architecture(LayerBase):
    """L2 架构与分层审核层执行器。"""

    layer_id: str = "L2"
    layer_name: str = "架构与分层审核"
    weight: float = 0.08

    async def run(self, context: AuditContext) -> LayerResult:
        """执行 L2 全部子检查并归档证据。"""
        started_at = datetime.now(UTC)
        builder = IssueBuilder()

        # 1. 构建依赖图
        graph = self._build_dependency_graph()

        # 2. 反向依赖检测
        reverse_issues = self._detect_reverse_dependencies(graph, builder)

        # 3. 循环依赖检测
        circular_issues = self._detect_circular_dependencies(graph, builder)

        # 4. 服务文件长度
        service_len_issues = self._check_service_file_length(builder)

        # 5. 端点瘦身
        endpoint_issues = self._check_endpoint_thin(builder)

        all_issues: list[AuditIssue] = (
            reverse_issues + circular_issues + service_len_issues + endpoint_issues
        )

        is_green = self.check_gate(all_issues, threshold=Severity.HIGH)
        status = LayerStatus.PASSED if is_green else LayerStatus.BLOCKED

        evidence_path = await self._archive_evidence(
            context, graph, all_issues
        )

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
    # 依赖图构建
    # ------------------------------------------------------------------

    def _build_dependency_graph(self) -> dict[str, set[str]]:
        """AST 解析各层模块 import 语句,构建模块依赖图。

        返回:
            ``{模块路径: {依赖模块路径集合}}``
        """
        graph: dict[str, set[str]] = {}
        for layer_name, layer_dir in (
            ("endpoints", ENDPOINTS_DIR),
            ("services", SERVICES_DIR),
            ("core", CORE_DIR),
            ("models", MODELS_DIR),
        ):
            if not layer_dir.exists():
                continue
            for py_file in layer_dir.rglob("*.py"):
                if "__pycache__" in py_file.parts:
                    continue
                module_key = self._module_key(py_file, layer_name)
                deps = self._extract_imports(py_file)
                graph.setdefault(module_key, set()).update(deps)
        return graph

    @staticmethod
    def _module_key(py_file: Path, layer_name: str) -> str:
        """生成模块键,形如 ``endpoints:api/v1/endpoints/auth.py``。"""
        try:
            rel = py_file.relative_to(PROJECT_ROOT)
        except ValueError:
            rel = py_file
        return f"{layer_name}:{rel.as_posix()}"

    def _extract_imports(self, py_file: Path) -> set[str]:
        """AST 提取文件顶层 import 语句,映射到层键。

        只检查模块顶层导入(``tree.body``),不递归遍历函数/类体内的
        延迟导入,避免将 core 模块函数内部的延迟导入误报为反向依赖。
        """
        deps: set[str] = set()
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except (SyntaxError, OSError, UnicodeDecodeError):
            return deps

        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = self._resolve_import_to_layer(alias.name)
                    if target is not None:
                        deps.add(target)
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                target = self._resolve_import_to_layer(node.module)
                if target is not None:
                    deps.add(target)
        return deps

    @staticmethod
    def _resolve_import_to_layer(module_name: str) -> str | None:
        """将 import 模块名映射到层键。

        例如 ``fastapi_app.services.order_service`` → ``services``
        """
        parts = module_name.split(".")
        if len(parts) < 2 or parts[0] != "fastapi_app":
            return None
        sub = parts[1]
        if sub in _LAYER_RANK:
            return sub
        # api/v1/endpoints 路径
        if sub == "api" and len(parts) >= 4 and parts[2] == "v1" and parts[3] == "endpoints":
            return "endpoints"
        return None

    # ------------------------------------------------------------------
    # 反向依赖检测
    # ------------------------------------------------------------------

    def _detect_reverse_dependencies(
        self,
        graph: dict[str, set[str]],
        builder: IssueBuilder,
    ) -> list[AuditIssue]:
        """检测反向依赖: endpoints→models / services→endpoints / core→endpoints。

        ⚠️ **core → services 不在禁止清单**: AGENTS.md §2 明文「core 是组合根,
        允许 import services(契约未禁止,勿当越层修)」——core/arq_app.py 顶层
        import services 正是该契约允许的组合根模式,判成违规是**误报型检查器
        缺陷**(审计 #18a),长期报下去会训练团队忽略 L2 的真实发现。
        """
        issues: list[AuditIssue] = []
        forbidden: dict[str, set[str]] = {
            "endpoints": {"models"},
            "services": {"endpoints"},
            "core": {"endpoints"},
        }
        for module_key, deps in graph.items():
            source_layer = module_key.split(":", 1)[0]
            forbidden_targets = forbidden.get(source_layer, set())
            if not forbidden_targets:
                continue
            file_path = module_key.split(":", 1)[1]
            for dep in deps:
                if dep in forbidden_targets:
                    issues.append(
                        builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.HIGH,
                            file=file_path,
                            line=1,
                            description=f"反向依赖: {source_layer} → {dep}(违反分层约束)",
                            suggestion=f"{source_layer} 层禁止直接依赖 {dep} 层,应通过中间层",
                            rule_id="L2-REVERSE-DEP-001",
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )
        return issues

    # ------------------------------------------------------------------
    # 循环依赖检测
    # ------------------------------------------------------------------

    def _detect_circular_dependencies(
        self,
        graph: dict[str, set[str]],
        builder: IssueBuilder,
    ) -> list[AuditIssue]:
        """DFS 染色环检测。"""
        issues: list[AuditIssue] = []
        # 颜色: 0=未访问, 1=访问中(灰), 2=已完成(黑)
        color: dict[str, int] = dict.fromkeys(graph, 0)
        stack: list[str] = []

        def dfs(node: str) -> None:
            color[node] = 1
            stack.append(node)
            for neighbor in graph.get(node, set()):
                if neighbor not in color:
                    continue
                if color[neighbor] == 1:
                    # 发现环
                    cycle_start = stack.index(neighbor)
                    cycle = [*stack[cycle_start:], neighbor]
                    issues.append(
                        builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.HIGH,
                            file=neighbor.split(":", 1)[-1] if ":" in neighbor else neighbor,
                            line=1,
                            description=f"循环依赖: {' → '.join(cycle)}",
                            suggestion="提取共享子模块或接口打破环",
                            rule_id="L2-CIRCULAR-DEP-001",
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )
                elif color[neighbor] == 0:
                    dfs(neighbor)
            color[node] = 2
            stack.pop()

        for node in list(graph.keys()):
            if color[node] == 0:
                dfs(node)
        return issues

    # ------------------------------------------------------------------
    # 服务文件长度
    # ------------------------------------------------------------------

    def _check_service_file_length(self, builder: IssueBuilder) -> list[AuditIssue]:
        """扫描 services/ 单文件 >800 行。"""
        issues: list[AuditIssue] = []
        if not SERVICES_DIR.exists():
            return issues
        for py_file in SERVICES_DIR.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            try:
                line_count = sum(
                    1
                    for _ in py_file.read_text(encoding="utf-8").splitlines()
                )
            except (OSError, UnicodeDecodeError):
                continue
            if line_count > _SERVICE_FILE_LENGTH_LIMIT:
                rel = py_file.relative_to(PROJECT_ROOT).as_posix()
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.LOW,
                        file=rel,
                        line=1,
                        description=f"服务文件 {rel} 长度 {line_count} 行 > 800",
                        suggestion="按职责拆分为多个服务模块",
                        rule_id="L2-SERVICE-LEN-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )
        return issues

    # ------------------------------------------------------------------
    # 端点瘦身
    # ------------------------------------------------------------------

    def _check_endpoint_thin(self, builder: IssueBuilder) -> list[AuditIssue]:
        """扫描 endpoints/ 检测业务逻辑/事务操作下沉。"""
        issues: list[AuditIssue] = []
        if not ENDPOINTS_DIR.exists():
            return issues
        for py_file in ENDPOINTS_DIR.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            lines = source.splitlines()
            rel = py_file.relative_to(PROJECT_ROOT).as_posix()
            for idx, line in enumerate(lines, start=1):
                for pattern in _ENDPOINT_BUSINESS_PATTERNS:
                    if pattern.search(line):
                        issues.append(
                            builder.build(
                                layer_id=self.layer_id,
                                severity=Severity.MEDIUM,
                                file=rel,
                                line=idx,
                                description=f"端点含业务逻辑/事务操作: {line.strip()}",
                                suggestion="将业务逻辑下沉至 service 层,端点仅做参数校验与转发",
                                rule_id="L2-ENDPOINT-BUSINESS-001",
                                owner=DEFAULT_OWNER,
                                due_date=DEFAULT_DUE_DATE,
                            )
                        )
                        break
        return issues

    # ------------------------------------------------------------------
    # 证据归档
    # ------------------------------------------------------------------

    async def _archive_evidence(
        self,
        context: AuditContext,
        graph: dict[str, set[str]],
        issues: Sequence[AuditIssue],
    ) -> Path:
        """归档依赖图(JSON)与问题清单至 ``evidence/gate_logs/L2/``。"""
        archiver = context.archiver
        graph_json = json.dumps(
            {k: sorted(v) for k, v in graph.items()},
            ensure_ascii=False,
            indent=2,
        )
        path1 = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=graph_json,
            filename="L2/dependency_graph.json",
        )
        issues_json = json.dumps(
            [issue.model_dump(mode="json") for issue in issues],
            ensure_ascii=False,
            indent=2,
        )
        path2 = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=issues_json,
            filename="L2/issues.json",
        )
        # 人工审查记录占位
        path3 = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.MANUAL_REVIEW,
            content="# L2 架构人工审查记录\n\n依赖图与分层审查结果见 gate_logs/L2/。\n",
            filename="L2/architecture_review.md",
        )
        return path3 or path2 or path1
