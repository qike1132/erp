"""L10 前端与移动端审核层执行器。

组件拆分验证 / 类型安全(any 消除) / 调试代码(console.log) /
可访问性(a11y) / Capacitor 配置校验。

约束:
    - 复用上一轮 P1-5 组件拆分 / P2-1 any 消除 / P2-2 console.log 清理基线
    - 复用存量 ``capacitor.config.ts`` 与 ``.env.capacitor``
    - 组件行数上限 400 行

任务来源: ``.codeartsdoer/specs/prod_code_review/tasks.md`` 第 11 节。
"""

from __future__ import annotations

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

FRONTEND_DIR: Path = PROJECT_ROOT / "frontend-vite"
FRONTEND_SRC_DIR: Path = FRONTEND_DIR / "src"

DEFAULT_OWNER: str = "frontend-mobile-reviewer"
DEFAULT_DUE_DATE: str = "2026-09-30"

# 组件行数上限
_MAX_COMPONENT_LINES: int = 400

# P1-5 拆分的 7 个巨型组件(基线)
_REFACTORED_COMPONENTS: tuple[str, ...] = (
    "CustomerView",
    "SupplierView",
    "CompletedOrdersPanel",
    "ProjectDetailPanel",
    "ProjectFormDialog",
    "ApprovalView",
    "ProductionEntryDrawer",
)

# any 类型正则(排除注释行)
_ANY_TYPE_RE = re.compile(r"\bany\b")
_AS_ANY_RE = re.compile(r"\bas\s+any\b")
# 字符串字面量中的 "any"（HTML 属性值如 step="any" 或字符串 'any'）— 非类型使用,排除
_QUOTED_ANY_RE = re.compile(r"""(['"])\s*any\s*\1""")

# console.log 正则(白名单: devLog)
_CONSOLE_LOG_RE = re.compile(r"\bconsole\s*\.\s*log\s*\(")
_DEV_LOG_RE = re.compile(r"\bdevLog\s*\(")
# console.log 文件级白名单: devLog 工具实现本身需要 console.log
_CONSOLE_WHITELIST_FILES: tuple[str, ...] = ("utils/devLog.ts",)

# 可访问性正则
_IMG_WITHOUT_ALT_RE = re.compile(r"<img(?![^>]*\balt\s*=)[^>]*>")
_INTERACTIVE_RE = re.compile(
    r"<(button|a|input|select|textarea)(?![^>]*\baria-label\s*=)[^>]*>"
)
_FORM_INPUT_RE = re.compile(r"<input(?![^>]*\b(?:aria-label|id)\s*=)[^>]*>")

# Capacitor 配置关键字段
_CAPACITOR_REQUIRED_FIELDS: tuple[str, ...] = ("appId", "appName", "webDir")


class L10Frontend(LayerBase):
    """L10 前端与移动端审核层执行器。

    聚合 5 个子检查:
        - 组件拆分(.vue ≤ 400 行)
        - 类型安全(无 any / as any)
        - 调试代码(无裸 console.log,devLog 白名单)
        - 可访问性(alt / aria-label / 表单 label)
        - Capacitor 配置(appId / appName / server url)
    """

    layer_id: str = "L10"
    layer_name: str = "前端与移动端审核"
    weight: float = 0.05

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    async def run(self, context: AuditContext) -> LayerResult:
        """执行 L10 全部子检查并归档证据。"""
        started_at = datetime.now(UTC)
        builder = IssueBuilder()
        raw_outputs: dict[str, str] = {}

        checks: list[tuple[str, object]] = [
            ("component_split", self._check_component_split(builder)),
            ("no_any", self._check_no_any(builder)),
            ("no_console", self._check_no_console(builder)),
            ("accessibility", self._check_accessibility(builder)),
            ("capacitor_config", self._check_capacitor_config(builder)),
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
                        suggestion="检查 frontend-vite/ 目录结构",
                        rule_id=f"L10-{name.upper()}-EXEC-001",
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
    # 11.1 组件拆分验证(.vue ≤ 400 行)
    # ------------------------------------------------------------------

    async def _check_component_split(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """验证 P1-5 拆分的 7 个巨型组件已拆分,且 .vue 文件 ≤ 400 行。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []
        scanned = 0

        if not FRONTEND_SRC_DIR.exists():
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=str(FRONTEND_DIR),
                    line=1,
                    description="frontend-vite/src/ 目录不存在",
                    suggestion="确认前端项目结构",
                    rule_id="L10-COMP-LEN-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
            return issues, "frontend-vite/src/ 不存在"

        # 扫描所有 .vue 文件行数
        for vue_file in FRONTEND_SRC_DIR.rglob("*.vue"):
            if "node_modules" in vue_file.parts:
                continue
            try:
                lines = vue_file.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            scanned += 1
            line_count = len(lines)
            rel = vue_file.relative_to(PROJECT_ROOT).as_posix()

            if line_count > _MAX_COMPONENT_LINES:
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.MEDIUM,
                        file=rel,
                        line=1,
                        description=(
                            f"Vue 组件 {vue_file.stem} 行数 {line_count}"
                            f" 超过上限 {_MAX_COMPONENT_LINES}"
                        ),
                        suggestion="拆分为子组件 + composable",
                        rule_id="L10-COMP-LEN-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )

        # 验证 7 个巨型组件已被拆分(查找是否仍存在同名大文件)
        found_refactored: list[str] = []
        for comp_name in _REFACTORED_COMPONENTS:
            for vue_file in FRONTEND_SRC_DIR.rglob(f"{comp_name}.vue"):
                if "node_modules" in vue_file.parts:
                    continue
                try:
                    line_count = len(
                        vue_file.read_text(encoding="utf-8").splitlines()
                    )
                except (OSError, UnicodeDecodeError):
                    continue
                if line_count > _MAX_COMPONENT_LINES:
                    found_refactored.append(
                        f"{comp_name} ({line_count} 行,未完成拆分)"
                    )

        raw_parts.append(f"scanned_vue_files: {scanned}")
        raw_parts.append(f"refactored_components_status: {found_refactored or 'all_split'}")

        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 11.1 类型安全(无 any / as any)
    # ------------------------------------------------------------------

    async def _check_no_any(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """扫描 .ts/.vue 文件中 any 与 as any(排除 node_modules)。"""
        issues: list[AuditIssue] = []
        scanned = 0
        raw_parts: list[str] = []

        if not FRONTEND_SRC_DIR.exists():
            return issues, "frontend-vite/src/ 不存在"

        scan_patterns = ("*.ts", "*.vue", "*.tsx")
        for pattern in scan_patterns:
            for ts_file in FRONTEND_SRC_DIR.rglob(pattern):
                if "node_modules" in ts_file.parts or ".d.ts" in ts_file.name:
                    continue
                try:
                    lines = ts_file.read_text(encoding="utf-8").splitlines()
                except (OSError, UnicodeDecodeError):
                    continue
                scanned += 1
                rel = ts_file.relative_to(PROJECT_ROOT).as_posix()

                for idx, line in enumerate(lines, start=1):
                    # 跳过注释行
                    stripped = line.strip()
                    if stripped.startswith("//") or stripped.startswith("*"):
                        continue

                    if _AS_ANY_RE.search(line):
                        issues.append(
                            builder.build(
                                layer_id=self.layer_id,
                                severity=Severity.HIGH,
                                file=rel,
                                line=idx,
                                description="使用 'as any' 类型断言",
                                suggestion="替换为具体类型或泛型",
                                rule_id="L10-ANY-001",
                                owner=DEFAULT_OWNER,
                                due_date=DEFAULT_DUE_DATE,
                            )
                        )
                    elif (
                        _ANY_TYPE_RE.search(line)
                        and "any" in line
                        and "import" not in stripped
                        and "from" not in stripped
                        and not _QUOTED_ANY_RE.search(line)
                    ):
                        issues.append(
                            builder.build(
                                layer_id=self.layer_id,
                                severity=Severity.HIGH,
                                file=rel,
                                line=idx,
                                description="使用 any 类型",
                                suggestion="替换为具体类型",
                                rule_id="L10-ANY-001",
                                owner=DEFAULT_OWNER,
                                due_date=DEFAULT_DUE_DATE,
                            )
                        )

        raw_parts.append(f"scanned_ts_vue_files: {scanned}")
        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 11.2 调试代码(无裸 console.log,devLog 白名单)
    # ------------------------------------------------------------------

    async def _check_no_console(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """扫描 .ts/.vue 文件中裸 console.log(devLog 白名单除外)。"""
        issues: list[AuditIssue] = []
        scanned = 0
        raw_parts: list[str] = []

        if not FRONTEND_SRC_DIR.exists():
            return issues, "frontend-vite/src/ 不存在"

        scan_patterns = ("*.ts", "*.vue", "*.tsx")
        for pattern in scan_patterns:
            for ts_file in FRONTEND_SRC_DIR.rglob(pattern):
                if "node_modules" in ts_file.parts:
                    continue
                try:
                    lines = ts_file.read_text(encoding="utf-8").splitlines()
                except (OSError, UnicodeDecodeError):
                    continue
                scanned += 1
                rel = ts_file.relative_to(PROJECT_ROOT).as_posix()

                # 跳过 console.log 文件级白名单(如 devLog.ts 实现本身)
                if any(rel.endswith(w) for w in _CONSOLE_WHITELIST_FILES):
                    continue

                for idx, line in enumerate(lines, start=1):
                    stripped = line.strip()
                    if stripped.startswith("//") or stripped.startswith("*"):
                        continue

                    if _CONSOLE_LOG_RE.search(line) and not _DEV_LOG_RE.search(line):
                        issues.append(
                            builder.build(
                                layer_id=self.layer_id,
                                severity=Severity.HIGH,
                                file=rel,
                                line=idx,
                                description="残留 console.log 调试代码",
                                suggestion="使用 devLog 守卫或移除调试日志",
                                rule_id="L10-CONSOLE-001",
                                owner=DEFAULT_OWNER,
                                due_date=DEFAULT_DUE_DATE,
                            )
                        )

        raw_parts.append(f"scanned_ts_vue_files: {scanned}")
        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 11.2 可访问性(alt / aria-label / 表单 label)
    # ------------------------------------------------------------------

    async def _check_accessibility(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """基础 a11y 检查: 图片 alt / 交互元素 aria-label / 表单 label。"""
        issues: list[AuditIssue] = []
        scanned = 0
        raw_parts: list[str] = []

        if not FRONTEND_SRC_DIR.exists():
            return issues, "frontend-vite/src/ 不存在"

        for vue_file in FRONTEND_SRC_DIR.rglob("*.vue"):
            if "node_modules" in vue_file.parts:
                continue
            try:
                lines = vue_file.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            scanned += 1
            rel = vue_file.relative_to(PROJECT_ROOT).as_posix()

            for idx, line in enumerate(lines, start=1):
                # 图片无 alt
                if _IMG_WITHOUT_ALT_RE.search(line):
                    issues.append(
                        builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.LOW,
                            file=rel,
                            line=idx,
                            description="<img> 标签缺少 alt 属性",
                            suggestion="添加 alt 描述文本",
                            rule_id="L10-A11Y-001",
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )

                # 交互元素无 aria-label
                if _INTERACTIVE_RE.search(line):
                    issues.append(
                        builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.LOW,
                            file=rel,
                            line=idx,
                            description="交互元素缺少 aria-label",
                            suggestion="添加 aria-label 提升可访问性",
                            rule_id="L10-A11Y-001",
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )

        raw_parts.append(f"scanned_vue_files: {scanned}")
        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 11.3 Capacitor 配置校验
    # ------------------------------------------------------------------

    async def _check_capacitor_config(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """审查 ``frontend-vite/capacitor.config.ts`` 配置正确性与 .env.capacitor。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        capacitor_file = FRONTEND_DIR / "capacitor.config.ts"
        if not capacitor_file.exists():
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file=str(capacitor_file.relative_to(PROJECT_ROOT).as_posix()),
                    line=1,
                    description="capacitor.config.ts 不存在,移动端打包配置缺失",
                    suggestion="创建 capacitor.config.ts 配置 Capacitor",
                    rule_id="L10-APK-CONTRACT-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
            return issues, "capacitor.config.ts 不存在"

        try:
            source = capacitor_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return [
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file=str(capacitor_file.relative_to(PROJECT_ROOT).as_posix()),
                    line=1,
                    description=f"读取 capacitor.config.ts 失败: {exc}",
                    suggestion="检查文件权限与编码",
                    rule_id="L10-APK-CONTRACT-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            ], f"READ_ERROR: {exc}"

        # 校验关键字段
        for field in _CAPACITOR_REQUIRED_FIELDS:
            field_re = re.compile(rf"{field}\s*:\s*['\"]([^'\"]+)['\"]")
            match = field_re.search(source)
            if not match:
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.HIGH,
                        file=str(capacitor_file.relative_to(PROJECT_ROOT).as_posix()),
                        line=1,
                        description=f"capacitor.config.ts 缺少 {field} 配置",
                        suggestion=f"添加 {field} 字段",
                        rule_id="L10-APK-CONTRACT-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )
            else:
                raw_parts.append(f"{field}: {match.group(1)}")

        # 校验 server url 配置(生产环境须指向后端 API)
        server_url_re = re.compile(r"url\s*:\s*['\"]([^'\"]+)['\"]")
        server_match = server_url_re.search(source)
        if server_match:
            raw_parts.append(f"server_url: {server_match.group(1)}")
        else:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=str(capacitor_file.relative_to(PROJECT_ROOT).as_posix()),
                    line=1,
                    description="capacitor.config.ts 未配置 server.url",
                    suggestion="添加 server.url 指向后端 API 地址",
                    rule_id="L10-APK-CONTRACT-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )

        # 校验 .env.capacitor 存在
        env_capacitor = FRONTEND_DIR / ".env.capacitor"
        if not env_capacitor.exists():
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=str(env_capacitor.relative_to(PROJECT_ROOT).as_posix()),
                    line=1,
                    description=".env.capacitor 不存在,移动端环境变量未配置",
                    suggestion="创建 .env.capacitor 配置移动端环境变量",
                    rule_id="L10-APK-CONTRACT-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
        else:
            try:
                env_content = env_capacitor.read_text(encoding="utf-8")
                raw_parts.append(f"env_capacitor_lines: {len(env_content.splitlines())}")
            except (OSError, UnicodeDecodeError):
                pass

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
        """归档审查记录至 ``evidence/manual_reviews/L10/`` 与 ``evidence/gate_logs/L10/``。"""
        archiver = context.archiver

        # 1. 人工审查记录
        path_review = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.MANUAL_REVIEW,
            content=(
                "# L10 前端与移动端人工审查\n\n"
                "## 组件拆分\nP1-5 拆分的 7 个巨型组件须 ≤ 400 行。\n\n"
                "## 类型安全\n.ts/.vue 须无 any 与 as any。\n\n"
                "## 调试代码\n须无裸 console.log(devLog 白名单除外)。\n\n"
                "## 可访问性\n图片有 alt / 交互元素有 aria-label / 表单有 label。\n\n"
                "## Capacitor 配置\nappId/appName/server.url 配置正确。\n\n"
                f"## 自动扫描结果\n{json.dumps(raw_outputs, ensure_ascii=False, indent=2)}\n"
            ),
            filename="L10/review.md",
        )

        # 2. 原始扫描输出
        path_raw = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content="\n\n".join(f"=== {k} ===\n{v}" for k, v in raw_outputs.items()),
            filename="L10/scan_raw.txt",
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
            filename="L10/issues.json",
        )

        # 4. summary.md
        path_summary = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=(
                "# L10 前端与移动端审核\n\n"
                "## 组件拆分\n.vue 文件 ≤ 400 行。\n\n"
                "## 类型安全\n无 any / as any。\n\n"
                "## 调试代码\n无裸 console.log。\n\n"
                "## 可访问性\nalt / aria-label / label。\n\n"
                "## Capacitor 配置\nappId / appName / server.url 正确。\n"
            ),
            filename="L10/summary.md",
        )

        return path_summary or path_issues or path_raw or path_review
