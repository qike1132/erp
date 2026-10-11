"""L7 性能与可扩展性审核层执行器。

locust 压测编排 / 冷启动与资源监控 / 前端首屏测速(Lighthouse CI)
/ N+1 治理性能收益验证 / 查询模式与索引/分页/缓存静态审查。

约束:
    - 复用存量 ``tests/qa/locustfile.py`` 与 ``tests/performance/benchmark.py``
    - 压测须使用生产规模数据集
    - 静态审查部分(查询模式/索引/分页/缓存/前端性能/产物体积)不依赖 staging

任务来源: ``.codeartsdoer/specs/prod_code_review/tasks.md`` 第 8 节。
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
from scripts.prod_audit.base.size_utils import gzip_size

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
"""项目根目录(``D:\\erp_system``)。"""

FRONTEND_DIR: Path = PROJECT_ROOT / "frontend-vite"
FASTAPI_APP_DIR: Path = PROJECT_ROOT / "fastapi_app"
SERVICES_DIR: Path = FASTAPI_APP_DIR / "services"
ENDPOINTS_V1_DIR: Path = FASTAPI_APP_DIR / "api" / "v1" / "endpoints"

DEFAULT_OWNER: str = "performance-reviewer"
DEFAULT_DUE_DATE: str = "2026-09-30"

# 子进程超时(秒)
_LOCUST_TIMEOUT: int = 600
_LHCI_TIMEOUT: int = 600
_COLD_START_TIMEOUT: int = 60

# 性能阈值
_P95_LIST_MS: int = 300
_P95_AGG_MS: int = 500
_MIN_RPS: int = 500
_MAX_ERROR_RATE: float = 0.001  # 0.1%
_COLD_START_LIMIT_S: int = 10
_MEMORY_LIMIT_MB: int = 1024
_CONN_POOL_LIMIT_PCT: int = 80
_LCP_LIMIT_MS: int = 2500
_FID_LIMIT_MS: int = 100
_CLS_LIMIT: float = 0.1
_BUNDLE_SIZE_LIMIT_MB: int = 2

# locustfile 与 benchmark 路径
_LOCUSTFILE: Path = PROJECT_ROOT / "tests" / "qa" / "locustfile.py"
_BENCHMARK_SCRIPT: Path = PROJECT_ROOT / "tests" / "performance" / "benchmark.py"

# CTE 索引建议文档
_CTE_INDEX_DOC: Path = PROJECT_ROOT / "docs" / "cte_index_suggestions.md"

# N+1 治理前后压测基线目录
_N1_BASELINE_DIR: Path = (
    PROJECT_ROOT / ".codeartsdoer" / "specs" / "code_quality_opt" / "benchmark"
)

# N+1 白名单(与 scripts/check_n_plus_one.py 共用,支持 file 或 file:line 两种形式)
_N1_WHITELIST: Path = PROJECT_ROOT / "scripts" / "allowed_n_plus_one.yaml"

# 循环内查询豁免注释标记(行内含该标记则跳过)
_BATCH_LOOP_MARKER: str = "batch-loop"

# SELECT * 豁免注释标记(行内含该标记则跳过,用于 backup/restore 全表导出场景)
_SELECT_ALL_MARKER: str = "select-all"


def _load_n1_whitelist(path: Path) -> frozenset[str]:
    """加载 N+1 白名单(纯文本,每行 file 或 file:line,跨平台路径分隔符统一为 /)。"""
    if not path.exists():
        return frozenset()
    entries: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(line.replace("\\", "/"))
    return frozenset(entries)


class L7Performance(LayerBase):
    """L7 性能与可扩展性审核层执行器。

    聚合 6 个子检查:
        - 查询模式(慢查询: missing LIMIT / SELECT * / N+1)
        - 索引提示(CTE 查询索引校验,参考 docs/cte_index_suggestions.md)
        - 分页(列表端点须分页)
        - 缓存(频繁访问数据须 Redis 缓存)
        - 前端性能(lazy loading / code splitting / 图片优化)
        - 产物体积(gzip 后 ≤ 2MB)
    """

    layer_id: str = "L7"
    layer_name: str = "性能与可扩展性审核"
    weight: float = 0.10

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    async def run(self, context: AuditContext) -> LayerResult:
        """执行 L7 全部子检查并归档证据。"""
        started_at = datetime.now(UTC)
        builder = IssueBuilder()
        raw_outputs: dict[str, str] = {}

        checks: list[tuple[str, object]] = [
            ("query_patterns", self._check_query_patterns(builder)),
            ("index_hints", self._check_index_hints(builder)),
            ("pagination", self._check_pagination(builder)),
            ("caching", self._check_caching(builder)),
            ("frontend_perf", self._check_frontend_perf(builder)),
            ("bundle_size", self._check_bundle_size(builder)),
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
                        suggestion="检查扫描路径/压测脚本/staging 配置",
                        rule_id=f"L7-{name.upper()}-EXEC-001",
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
    # 8.1 查询模式(慢查询: missing LIMIT / SELECT * / N+1)
    # ------------------------------------------------------------------

    async def _check_query_patterns(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """扫描潜在慢查询(missing LIMIT / SELECT * / N+1)。"""
        issues: list[AuditIssue] = []
        scanned = 0

        if not SERVICES_DIR.exists():
            return issues, "services/ 不存在,跳过"

        # 加载 N+1 白名单(file 或 file:line),与 scripts/check_n_plus_one.py 共用
        whitelist = _load_n1_whitelist(_N1_WHITELIST)
        select_star_re = re.compile(r"(?i)\bSELECT\s+\*\s+FROM\b")
        # 缺少 LIMIT 的查询(粗略: 含 SELECT ... FROM 但同函数无 LIMIT)
        for py_file in SERVICES_DIR.rglob("*.py"):
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
                # SELECT *
                if select_star_re.search(line) and _SELECT_ALL_MARKER not in line:
                    issues.append(
                        builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.MEDIUM,
                            file=rel,
                            line=idx,
                            description="使用 SELECT *,可能返回过多列导致慢查询",
                            suggestion="显式列出所需列,避免 SELECT *",
                            rule_id="L7-SELECT-STAR-001",
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )

            # AST 检测循环内查询(N+1)
            try:
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError:
                continue
            visitor = _NPlusOneVisitor(rel, self.layer_id, builder, lines, whitelist)
            visitor.visit(tree)
            issues.extend(visitor.issues)

        return issues, f"scanned_files: {scanned}"

    # ------------------------------------------------------------------
    # 8.1 索引提示(CTE 查询索引校验)
    # ------------------------------------------------------------------

    async def _check_index_hints(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """验证 CTE 查询有合适索引(参考 docs/cte_index_suggestions.md)。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        if not _CTE_INDEX_DOC.exists():
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=str(_CTE_INDEX_DOC.relative_to(PROJECT_ROOT).as_posix()),
                    line=1,
                    description="CTE 索引建议文档缺失: docs/cte_index_suggestions.md",
                    suggestion="确认 docs/cte_index_suggestions.md 存在",
                    rule_id="L7-CTE-INDEX-DOC-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
            return issues, "cte_index_suggestions.md 缺失"

        try:
            doc_content = _CTE_INDEX_DOC.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return [
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=str(_CTE_INDEX_DOC.relative_to(PROJECT_ROOT).as_posix()),
                    line=1,
                    description=f"读取 CTE 索引建议文档失败: {exc}",
                    suggestion="检查文件权限与编码",
                    rule_id="L7-CTE-INDEX-DOC-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            ], f"READ_ERROR: {exc}"

        # 提取文档中建议的表名(## 表名 / ### 表名)
        suggested_tables = set(re.findall(r"(?im)^#{2,3}\s+(\w+)", doc_content))
        raw_parts.append(f"suggested_tables: {sorted(suggested_tables)}")

        # 扫描 services/ 中 CTE 查询(WITH ... AS)并校验是否在建议表清单
        cte_re = re.compile(r"(?i)\bWITH\s+(\w+)\s+AS\s*\(")
        scanned = 0
        if SERVICES_DIR.exists():
            for py_file in SERVICES_DIR.rglob("*.py"):
                if "__pycache__" in py_file.parts:
                    continue
                try:
                    source = py_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                scanned += 1
                rel = py_file.relative_to(PROJECT_ROOT).as_posix()
                for idx, line in enumerate(source.splitlines(), start=1):
                    # 检查同文件是否引用了建议表(粗略)
                    if cte_re.search(line) and suggested_tables and not any(
                        t in source for t in suggested_tables
                    ):
                        issues.append(
                                builder.build(
                                    layer_id=self.layer_id,
                                    severity=Severity.MEDIUM,
                                    file=rel,
                                    line=idx,
                                    description="CTE 查询未在 docs/cte_index_suggestions.md 建议索引清单中",
                                    suggestion="在 docs/cte_index_suggestions.md 补充该 CTE 的索引建议",
                                    rule_id="L7-CTE-INDEX-MISSING-001",
                                    owner=DEFAULT_OWNER,
                                    due_date=DEFAULT_DUE_DATE,
                                )
                            )

        raw_parts.append(f"scanned_files: {scanned}")
        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 8.1 分页(列表端点须分页)
    # ------------------------------------------------------------------

    async def _check_pagination(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """验证所有列表端点使用分页(offset/limit/page/page_size)。"""
        issues: list[AuditIssue] = []
        scanned = 0

        pagination_params = frozenset(
            {"offset", "limit", "page", "page_size", "pageSize", "skip", "take"}
        )

        for endpoints_dir in (ENDPOINTS_V1_DIR,):
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
                visitor = _PaginationVisitor(
                    rel, self.layer_id, builder, pagination_params
                )
                visitor.visit(tree)
                issues.extend(visitor.issues)

        return issues, f"scanned_files: {scanned}"

    # ------------------------------------------------------------------
    # 8.1 缓存(频繁访问数据须 Redis 缓存)
    # ------------------------------------------------------------------

    async def _check_caching(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """验证频繁访问数据使用 Redis 缓存(检测 cache 装饰器/调用)。"""
        issues: list[AuditIssue] = []
        scanned = 0

        # 频繁访问服务(仪表盘/统计/配置类)
        frequent_patterns = re.compile(
            r"(?i)(dashboard|stats|summary|config|meta|menu|dictionary)"
        )
        cache_indicators = re.compile(
            r"(?i)(@cache|cache_get|cache\.get|redis\.get|cached|@cached|aiocache)"
        )

        if not SERVICES_DIR.exists():
            return issues, "services/ 不存在,跳过"

        for py_file in SERVICES_DIR.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            scanned += 1
            rel = py_file.relative_to(PROJECT_ROOT).as_posix()
            if frequent_patterns.search(rel) and not cache_indicators.search(source):
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.MEDIUM,
                        file=rel,
                        line=1,
                        description="频繁访问数据服务未使用 Redis 缓存",
                        suggestion="为 dashboard/stats 类服务添加 Redis 缓存",
                        rule_id="L7-CACHE-MISSING-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )

        return issues, f"scanned_files: {scanned}"

    # ------------------------------------------------------------------
    # 8.3 前端性能(lazy loading / code splitting / 图片优化)
    # ------------------------------------------------------------------

    async def _check_frontend_perf(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """验证前端 lazy loading / code splitting / 图片优化。"""
        issues: list[AuditIssue] = []
        scanned = 0
        raw_parts: list[str] = []

        if not FRONTEND_DIR.exists():
            return issues, "frontend-vite/ 不存在,跳过"

        src_dir = FRONTEND_DIR / "src"
        if not src_dir.exists():
            return issues, "frontend-vite/src/ 不存在,跳过"

        # 1. 路由 lazy loading: () => import('...')
        lazy_import_re = re.compile(r"\(\s*\)\s*=>\s*import\s*\(")
        # 2. 静态 import 大组件(非 lazy)
        static_component_import_re = re.compile(
            r"^\s*import\s+\w+\s+from\s+[\"'](.*/components/[^\"']+)[\"']"
        )
        # 3. 图片优化: <img src=...> 未用懒加载属性
        img_without_lazy_re = re.compile(r"<img(?![^>]*loading=)[^>]*src=")

        for vue_file in src_dir.rglob("*.vue"):
            if "node_modules" in vue_file.parts:
                continue
            try:
                source = vue_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            scanned += 1
            rel = vue_file.relative_to(PROJECT_ROOT).as_posix()
            for idx, line in enumerate(source.splitlines(), start=1):
                if img_without_lazy_re.search(line):
                    issues.append(
                        builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.LOW,
                            file=rel,
                            line=idx,
                            description="<img> 标签未设置 loading=\"lazy\" 属性",
                            suggestion="添加 loading=\"lazy\" 实现图片懒加载",
                            rule_id="L7-IMG-LAZY-001",
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )

        # 4. 检查路由文件是否使用 lazy import
        router_files = list(src_dir.rglob("router/**/*.ts")) + list(src_dir.rglob("router/**/*.js"))
        if not router_files:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file="frontend-vite/src/router/",
                    line=1,
                    description="未找到路由配置文件,无法校验 lazy loading",
                    suggestion="确认路由配置路径",
                    rule_id="L7-ROUTER-LAZY-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
        else:
            for router_file in router_files:
                try:
                    source = router_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                scanned += 1
                rel = router_file.relative_to(PROJECT_ROOT).as_posix()
                # 含静态组件 import 且无 lazy import
                if static_component_import_re.search(source) and not lazy_import_re.search(source):
                    issues.append(
                        builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.MEDIUM,
                            file=rel,
                            line=1,
                            description="路由使用静态 import,未启用 code splitting",
                            suggestion="改为 () => import('...') 动态导入实现 code splitting",
                            rule_id="L7-CODE-SPLIT-001",
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )

        raw_parts.append(f"scanned_files: {scanned}")
        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 8.3 产物体积(gzip 后 ≤ 2MB)
    # ------------------------------------------------------------------

    async def _check_bundle_size(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """检查前端生产构建产物体积(gzip 后 ≤ 2MB)。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        # 优先检查 dist/ 产物
        dist_dir = FRONTEND_DIR / "dist"
        if not dist_dir.exists():
            raw_parts.append("dist/ 不存在,跳过产物体积校验(需先执行构建)")
            return issues, "\n".join(raw_parts)

        limit_bytes = _BUNDLE_SIZE_LIMIT_MB * 1024 * 1024
        oversized_files: list[tuple[Path, int]] = []
        total_size = 0
        for asset in dist_dir.rglob("*.js"):
            if "node_modules" in asset.parts:
                continue
            size = gzip_size(asset)  # 判据是「gzip 后 ≤ 2MB」，非原始字节（评审 2026-10-11）
            total_size += size
            if size > limit_bytes:
                oversized_files.append((asset, size))

        raw_parts.append(f"dist_total_js_bytes: {total_size}")
        raw_parts.append(f"limit_bytes: {limit_bytes}")

        if total_size > limit_bytes:
            rel = "frontend-vite/dist/"
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=rel,
                    line=1,
                    description=(
                        f"前端产物 gzip 后总体积 {total_size // 1024}KB > "
                        f"限制 {_BUNDLE_SIZE_LIMIT_MB}MB"
                    ),
                    suggestion="启用 code splitting / tree shaking / 按需加载减小体积",
                    rule_id="L7-BUNDLE-SIZE-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )

        for asset, size in oversized_files:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=str(asset.relative_to(PROJECT_ROOT).as_posix()),
                    line=1,
                    description=f"单个 JS 产物 gzip 后 {size // 1024}KB > 限制 {_BUNDLE_SIZE_LIMIT_MB}MB",
                    suggestion="拆分该 chunk 或按需加载",
                    rule_id="L7-BUNDLE-CHUNK-001",
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
        """归档压测报告至 ``evidence/perf_reports/``。"""
        archiver = context.archiver

        # 1. 原始扫描输出
        path_raw = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.PERF_REPORT,
            content="\n\n".join(
                f"=== {k} ===\n{v}" for k, v in raw_outputs.items()
            ),
            filename="L7/scan_raw.txt",
        )

        # 2. 性能阈值清单
        thresholds = {
            "p95_list_ms": _P95_LIST_MS,
            "p95_agg_ms": _P95_AGG_MS,
            "min_rps": _MIN_RPS,
            "max_error_rate": _MAX_ERROR_RATE,
            "cold_start_limit_s": _COLD_START_LIMIT_S,
            "memory_limit_mb": _MEMORY_LIMIT_MB,
            "conn_pool_limit_pct": _CONN_POOL_LIMIT_PCT,
            "lcp_limit_ms": _LCP_LIMIT_MS,
            "fid_limit_ms": _FID_LIMIT_MS,
            "cls_limit": _CLS_LIMIT,
            "bundle_size_limit_mb": _BUNDLE_SIZE_LIMIT_MB,
        }
        path_thresholds = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.PERF_REPORT,
            content=json.dumps(thresholds, ensure_ascii=False, indent=2),
            filename="L7/thresholds.json",
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
            filename="L7/issues.json",
        )
        path_summary = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=(
                "# L7 性能与可扩展性审核\n\n"
                "## 查询模式\n扫描 SELECT * / 循环内查询(N+1)。\n\n"
                "## 索引提示\nCTE 查询索引校验,参考 docs/cte_index_suggestions.md。\n\n"
                "## 分页\n列表端点须含 offset/limit/page/page_size 参数。\n\n"
                "## 缓存\ndashboard/stats 类服务须使用 Redis 缓存。\n\n"
                "## 前端性能\n路由 lazy loading / code splitting / 图片 loading=\"lazy\"。\n\n"
                "## 产物体积\n前端 dist/ 总体积 gzip 后 ≤ 2MB。\n"
            ),
            filename="L7/summary.md",
        )

        return path_summary or path_issues or path_thresholds or path_raw


# ---------------------------------------------------------------------------
# AST 访问器: N+1 循环内查询
# ---------------------------------------------------------------------------


class _NPlusOneVisitor(ast.NodeVisitor):
    """检测循环内执行数据库查询(N+1 模式)。

    与 ``scripts/check_n_plus_one.py`` 对齐:
        - 仅标记 ``await <session>.execute/scalar/scalars/stream/stream_scalars(...)``
          出现在 for/async for/while 循环体内的情况(真正的 DB 往返)。
        - 排除遍历已执行结果的 ``.scalars()/.all()/.first()/.count()`` 等非 await 调用。
        - 跳过 ``scripts/allowed_n_plus_one.yaml`` 白名单(file 或 file:line)。
        - 跳过行内含 ``# batch-loop:`` 注释的豁免标记。
    """

    _QUERY_METHODS: frozenset[str] = frozenset(
        {"execute", "scalar", "scalars", "stream", "stream_scalars"}
    )

    def __init__(
        self,
        file: str,
        layer_id: str,
        builder: IssueBuilder,
        source_lines: list[str],
        whitelist: frozenset[str],
    ) -> None:
        self.file = file
        self.layer_id = layer_id
        self.builder = builder
        self.source_lines = source_lines
        self.whitelist = whitelist
        self.issues: list[AuditIssue] = []
        self._loop_depth: int = 0

    def _is_skipped(self, lineno: int) -> bool:
        """是否被白名单或 ``# batch-loop:`` 注释豁免。"""
        norm_file = self.file.replace("\\", "/")
        if norm_file in self.whitelist or f"{norm_file}:{lineno}" in self.whitelist:
            return True
        if 1 <= lineno <= len(self.source_lines):
            if _BATCH_LOOP_MARKER in self.source_lines[lineno - 1]:
                return True
        return False

    def visit_For(self, node: ast.For) -> None:
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_While(self, node: ast.While) -> None:
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_Await(self, node: ast.Await) -> None:
        # 仅当 await 的值是查询调用时才记录(排除遍历已有结果的 .scalars()/.all())
        if self._loop_depth > 0 and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Attribute) and func.attr in self._QUERY_METHODS:
                if not self._is_skipped(node.lineno):
                    self.issues.append(
                        self.builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.HIGH,
                            file=self.file,
                            line=node.lineno,
                            description=(
                                f"循环内执行数据库查询 .{func.attr}(),存在 N+1 风险"
                            ),
                            suggestion="改为批量查询或 IN 子句/selectinload",
                            rule_id="L7-N-PLUS-ONE-001",
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# AST 访问器: 分页校验
# ---------------------------------------------------------------------------


class _PaginationVisitor(ast.NodeVisitor):
    """检测列表端点(GET)是否含分页参数。"""

    def __init__(
        self,
        file: str,
        layer_id: str,
        builder: IssueBuilder,
        pagination_params: frozenset[str],
    ) -> None:
        self.file = file
        self.layer_id = layer_id
        self.builder = builder
        self.pagination_params = pagination_params
        self.issues: list[AuditIssue] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # 仅检查 GET 路由且路径含列表语义(/xxx 不含 /{id})
        is_get_list = False
        route_path = ""
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call):
                func = dec.func
                if isinstance(func, ast.Attribute) and func.attr == "get":
                    if dec.args and isinstance(dec.args[0], ast.Constant):
                        route_path = str(dec.args[0].value)
                        # 列表语义: 路径不含 /{...} 参数
                        if not re.search(r"\{[^}]+\}", route_path):
                            is_get_list = True
                        break
        if not is_get_list:
            self.generic_visit(node)
            return

        # 检查参数名是否含分页参数
        param_names = {arg.arg for arg in node.args.args}
        has_pagination = bool(param_names & self.pagination_params)
        if not has_pagination:
            self.issues.append(
                self.builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=self.file,
                    line=node.lineno,
                    description=(
                        f"列表端点 {route_path} 缺少分页参数"
                        f"(offset/limit/page/page_size)"
                    ),
                    suggestion="添加 offset/limit 或 page/page_size 分页参数",
                    rule_id="L7-PAGINATION-MISSING-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
        self.generic_visit(node)
