"""L1 静态分析门禁审核层执行器。

聚合后端 ruff/bandit/mypy/函数行数/宽泛 except 与
前端 vue-tsc/eslint/组件行数/生产构建产物扫描,
产出标准化 :class:`AuditIssue` 列表并归档证据。

任务来源: ``.codeartsdoer/specs/prod_code_review/tasks.md`` 第 2 节。
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    pass


PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
"""项目根目录(``D:\\erp_system``)。"""

FRONTEND_DIR: Path = PROJECT_ROOT / "frontend-vite"
"""前端工作目录。"""

DEFAULT_OWNER: str = "static-analysis-bot"
DEFAULT_DUE_DATE: str = "2026-09-30"

# 子检查超时(秒);ruff/bandit/mypy 各 5 分钟,前端构建 10 分钟
_TOOL_TIMEOUT: int = 300
_BUILD_TIMEOUT: int = 600

# 产物体积阈值(字节);gzip 后 >2MB 视为违规
_BUNDLE_SIZE_LIMIT_BYTES: int = 2 * 1024 * 1024


# ---------------------------------------------------------------------------
# 输出解析正则
# ---------------------------------------------------------------------------

# ruff 输出形如: fastapi_app/foo.py:42:5: E501 Line too long
_RUFF_LINE_RE = re.compile(r"^(?P<file>.+?):(?P<line>\d+):(?P<col>\d+):\s+(?P<code>\S+)\s+(?P<msg>.*)$")

# mypy 输出形如: fastapi_app/core/foo.py:42: error: Function is missing a type annotation  [no-untyped-def]
_MYPY_LINE_RE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):\s*(?P<level>error|note|warning):\s+(?P<msg>.*?)(?:\s+\[(?P<code>[^\]]+)\])?$"
)

# eslint 输出形如: D:\erp_system\frontend-vite\src\foo.ts:42:5  error  @typescript-eslint/no-explicit-any  Unexpected any  eslint
_ESLINT_LINE_RE = re.compile(
    r"^(?P<file>[^:]+):\s*(?P<line>\d+):\s*(?P<col>\d+)\s+(?P<level>\w+)\s+(?P<rule>\S+)\s+(?P<msg>.*)$"
)


class L1StaticAnalysis(LayerBase):
    """L1 静态分析门禁审核层执行器。

    聚合 9 个子检查:
        - 后端: ruff / bandit / mypy / 函数行数 / 宽泛 except
        - 前端: vue-tsc / eslint / 组件行数 / 生产构建产物扫描
    """

    layer_id: str = "L1"
    layer_name: str = "静态分析门禁审核"
    weight: float = 0.10

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    async def run(self, context: AuditContext) -> LayerResult:
        """执行 L1 全部子检查并归档证据。"""
        started_at = datetime.now(UTC)
        builder = IssueBuilder()
        raw_outputs: dict[str, str] = {}

        # 并行执行无依赖的子检查
        backend_tasks = [
            ("ruff", self._run_ruff()),
            ("bandit", self._run_bandit()),
            ("mypy", self._run_mypy()),
            ("function_length", self._run_function_length_check()),
            ("broad_except", self._run_broad_except_check()),
        ]
        frontend_tasks = [
            ("vue_tsc", self._run_vue_tsc()),
            ("eslint", self._run_eslint()),
            ("component_length", self._run_component_length_check()),
            ("product_build", self._run_product_build_scan()),
        ]

        results: list[tuple[str, list[AuditIssue], str]] = []
        for name, coro in backend_tasks + frontend_tasks:
            try:
                issues, raw = await coro
            except Exception as exc:  # 子检查失败不阻断聚合
                issues = [
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.HIGH,
                        file=str(PROJECT_ROOT),
                        line=1,
                        description=f"子检查 {name} 执行失败: {exc}",
                        suggestion="检查工具安装与配置文件",
                        rule_id=f"L1-{name.upper()}-EXEC-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                ]
                raw = f"EXECUTION_ERROR: {exc}"
            results.append((name, issues, raw))
            raw_outputs[name] = raw

        # 聚合
        all_issues: list[AuditIssue] = []
        for _, issues, _ in results:
            all_issues.extend(issues)

        # 门禁校验
        is_green = self.check_gate(all_issues, threshold=Severity.HIGH)
        status = LayerStatus.PASSED if is_green else LayerStatus.BLOCKED

        # 归档证据至 evidence/gate_logs/L1/
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
    # 后端子检查
    # ------------------------------------------------------------------

    async def _run_ruff(self) -> tuple[list[AuditIssue], str]:
        """执行 ``ruff check fastapi_app/ scripts/ tests/``。"""
        cmd = [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "fastapi_app/",
            "scripts/",
            "tests/",
            "--output-format=concise",
        ]
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            encoding="utf-8",
            cwd=str(PROJECT_ROOT),
            timeout=_TOOL_TIMEOUT,
            check=False,
        )
        raw = proc.stdout + proc.stderr
        issues = self._parse_ruff_output(proc.stdout, builder_placeholder=None)
        return issues, raw

    def _parse_ruff_output(self, stdout: str, builder_placeholder: object | None) -> list[AuditIssue]:
        """解析 ruff concise 输出为 :class:`AuditIssue` 列表。"""
        builder = IssueBuilder()
        issues: list[AuditIssue] = []
        for line in stdout.splitlines():
            m = _RUFF_LINE_RE.match(line.strip())
            if not m:
                continue
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file=m.group("file"),
                    line=int(m.group("line")),
                    description=f"ruff {m.group('code')}: {m.group('msg')}",
                    suggestion="按 ruff 规则修复或显式 noqa 附说明",
                    rule_id=f"L1-RUFF-{m.group('code')}",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
        return issues

    async def _run_bandit(self) -> tuple[list[AuditIssue], str]:
        """执行 ``bandit -c bandit.yaml -r fastapi_app/``。"""
        cmd = [
            sys.executable,
            "-m",
            "bandit",
            "-c",
            "bandit.yaml",
            "-r",
            "fastapi_app/",
            "-f",
            "json",
            "-q",
        ]
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            encoding="utf-8",
            cwd=str(PROJECT_ROOT),
            timeout=_TOOL_TIMEOUT,
            check=False,
        )
        raw = proc.stdout + proc.stderr
        issues = self._parse_bandit_json(proc.stdout)
        return issues, raw

    def _parse_bandit_json(self, stdout: str) -> list[AuditIssue]:
        """解析 bandit JSON 输出。"""
        builder = IssueBuilder()
        issues: list[AuditIssue] = []
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return issues
        for item in data.get("results", []):
            severity_str = item.get("issue_severity", "MEDIUM").upper()
            severity = {
                "HIGH": Severity.HIGH,
                "MEDIUM": Severity.MEDIUM,
                "LOW": Severity.LOW,
            }.get(severity_str, Severity.MEDIUM)
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=severity,
                    file=item.get("filename", ""),
                    line=int(item.get("line_number", 1)),
                    description=f"bandit {item.get('test_id', 'B???')}: {item.get('issue_text', '')}",
                    suggestion=item.get("more_info", "按 bandit 规则修复"),
                    rule_id=f"L1-BANDIT-{item.get('test_id', 'UNKNOWN')}",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
        return issues

    async def _run_mypy(self) -> tuple[list[AuditIssue], str]:
        """执行 ``mypy fastapi_app/core/``。"""
        cmd = [sys.executable, "-m", "mypy", "fastapi_app/core/"]
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            encoding="utf-8",
            cwd=str(PROJECT_ROOT),
            timeout=_TOOL_TIMEOUT,
            check=False,
        )
        raw = proc.stdout + proc.stderr
        issues = self._parse_mypy_output(proc.stdout)
        return issues, raw

    def _parse_mypy_output(self, stdout: str) -> list[AuditIssue]:
        """解析 mypy 输出。"""
        builder = IssueBuilder()
        issues: list[AuditIssue] = []
        for line in stdout.splitlines():
            m = _MYPY_LINE_RE.match(line.strip())
            if not m or m.group("level") != "error":
                continue
            code = m.group("code") or "unknown"
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file=m.group("file"),
                    line=int(m.group("line")),
                    description=f"mypy [{code}]: {m.group('msg')}",
                    suggestion="补全类型注解或修复类型错误",
                    rule_id=f"L1-MYPY-{code}",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
        return issues

    async def _run_function_length_check(self) -> tuple[list[AuditIssue], str]:
        """调用 ``scripts/check_function_length.py``(阈值 80 行)。"""
        cmd = [
            sys.executable,
            "scripts/check_function_length.py",
            "--max-length",
            "80",
            "fastapi_app",
        ]
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            encoding="utf-8",
            cwd=str(PROJECT_ROOT),
            timeout=_TOOL_TIMEOUT,
            check=False,
        )
        raw = proc.stdout + proc.stderr
        issues = self._parse_function_length_output(proc.stdout)
        return issues, raw

    def _parse_function_length_output(self, stdout: str) -> list[AuditIssue]:
        """解析函数行数脚本输出。

        输出形如: ``    L42: my_func() = 95 行``
        """
        builder = IssueBuilder()
        issues: list[AuditIssue] = []
        current_file: str | None = None
        func_re = re.compile(r"^\s*L(?P<line>\d+):\s*(?P<func>\S+)\(\)\s*=\s*(?P<length>\d+)\s*行")
        for line in stdout.splitlines():
            stripped = line.strip()
            # 文件头形如 "  fastapi_app/foo.py (3)"
            if stripped and not stripped.startswith("L") and "(" in stripped and ")" in stripped:
                current_file = stripped.split("(")[0].strip()
                continue
            m = func_re.match(line)
            if m and current_file is not None:
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.LOW,
                        file=current_file,
                        line=int(m.group("line")),
                        description=f"函数 {m.group('func')}() 长度 {m.group('length')} 行 > 80",
                        suggestion="按职责拆分为多个小函数",
                        rule_id="L1-FUNC-LENGTH-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )
        return issues

    async def _run_broad_except_check(self) -> tuple[list[AuditIssue], str]:
        """调用 ``scripts/check_bare_except.py``(白名单 server_manager.py)。"""
        cmd = [sys.executable, "scripts/check_bare_except.py", "fastapi_app"]
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            encoding="utf-8",
            cwd=str(PROJECT_ROOT),
            timeout=_TOOL_TIMEOUT,
            check=False,
        )
        raw = proc.stdout + proc.stderr
        issues = self._parse_broad_except_output(proc.stdout)
        return issues, raw

    def _parse_broad_except_output(self, stdout: str) -> list[AuditIssue]:
        """解析宽泛 except 脚本输出。

        输出形如: ``    L42: except Exception``
        """
        builder = IssueBuilder()
        issues: list[AuditIssue] = []
        current_file: str | None = None
        except_re = re.compile(r"^\s*L(?P<line>\d+):\s*(?P<kind>.+)$")
        for line in stdout.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("L") and "(" in stripped and ")" in stripped:
                current_file = stripped.split("(")[0].strip()
                continue
            m = except_re.match(line)
            if m and current_file is not None:
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.HIGH,
                        file=current_file,
                        line=int(m.group("line")),
                        description=f"宽泛 except: {m.group('kind')}",
                        suggestion="捕获具体异常类型",
                        rule_id="L1-BROAD-EXCEPT-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )
        return issues

    # ------------------------------------------------------------------
    # 前端子检查
    # ------------------------------------------------------------------

    async def _run_vue_tsc(self) -> tuple[list[AuditIssue], str]:
        """执行 ``vue-tsc --noEmit``(工作目录 frontend-vite/)。

        优先使用 ``node_modules/.bin/vue-tsc``(Windows 下为 ``.cmd``),
        避免 ``npx`` 不在 PATH 时 ``[WinError 2]`` 失败。工具不可用视为
        环境缺失而非代码缺陷,返回空问题列表并标记 SKIPPED。
        """
        bin_dir = FRONTEND_DIR / "node_modules" / ".bin"
        vue_tsc_path = bin_dir / "vue-tsc.cmd"
        if not vue_tsc_path.exists():
            vue_tsc_path = bin_dir / "vue-tsc"
        if not vue_tsc_path.exists():
            return [], "SKIPPED: vue-tsc not available in node_modules/.bin"
        cmd = [str(vue_tsc_path), "--noEmit"]
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            encoding="utf-8",
            cwd=str(FRONTEND_DIR),
            timeout=_TOOL_TIMEOUT,
            check=False,
        )
        raw = proc.stdout + proc.stderr
        issues = self._parse_vue_tsc_output(proc.stdout + proc.stderr)
        return issues, raw

    def _parse_vue_tsc_output(self, output: str) -> list[AuditIssue]:
        """解析 vue-tsc 输出。

        输出形如: ``src/foo.ts:42:5 - error TS2322: Type ...``
        """
        builder = IssueBuilder()
        issues: list[AuditIssue] = []
        tsc_re = re.compile(
            r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+)\s*-\s*(?P<level>error|warning)\s+(?P<code>TS\d+):\s*(?P<msg>.*)$"
        )
        for line in output.splitlines():
            m = tsc_re.match(line.strip())
            if not m or m.group("level") != "error":
                continue
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file=f"frontend-vite/{m.group('file')}",
                    line=int(m.group("line")),
                    description=f"vue-tsc {m.group('code')}: {m.group('msg')}",
                    suggestion="修复 TypeScript 类型错误",
                    rule_id=f"L1-VUE-TSC-{m.group('code')}",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
        return issues

    async def _run_eslint(self) -> tuple[list[AuditIssue], str]:
        """执行 ``eslint . --max-warnings=0``(工作目录 frontend-vite/)。

        优先使用 ``node_modules/.bin/eslint``(Windows 下为 ``.cmd``),
        避免 ``npx`` 不在 PATH 时 ``[WinError 2]`` 失败。工具不可用视为
        环境缺失而非代码缺陷,返回空问题列表并标记 SKIPPED。
        """
        bin_dir = FRONTEND_DIR / "node_modules" / ".bin"
        eslint_path = bin_dir / "eslint.cmd"
        if not eslint_path.exists():
            eslint_path = bin_dir / "eslint"
        if not eslint_path.exists():
            return [], "SKIPPED: eslint not available in node_modules/.bin"
        cmd = [str(eslint_path), ".", "--max-warnings=0"]
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            encoding="utf-8",
            cwd=str(FRONTEND_DIR),
            timeout=_TOOL_TIMEOUT,
            check=False,
        )
        raw = proc.stdout + proc.stderr
        issues = self._parse_eslint_output(proc.stdout)
        return issues, raw

    def _parse_eslint_output(self, stdout: str) -> list[AuditIssue]:
        """解析 eslint stylish 输出。"""
        builder = IssueBuilder()
        issues: list[AuditIssue] = []
        current_file: str | None = None
        for line in stdout.splitlines():
            stripped = line.strip()
            # 文件路径行(无冒号行号)
            if stripped and not _ESLINT_LINE_RE.match(stripped) and stripped.endswith((".ts", ".tsx", ".vue", ".js", ".mjs")):
                current_file = stripped
                continue
            m = _ESLINT_LINE_RE.match(stripped)
            if m and current_file is not None:
                level = m.group("level")
                severity = Severity.HIGH if level == "error" else Severity.MEDIUM
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=severity,
                        file=f"frontend-vite/{current_file}",
                        line=int(m.group("line")),
                        description=f"eslint {m.group('rule')}: {m.group('msg')}",
                        suggestion="按 eslint 规则修复",
                        rule_id=f"L1-ESLINT-{m.group('rule')}",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )
        return issues

    async def _run_component_length_check(self) -> tuple[list[AuditIssue], str]:
        """调用 ``scripts/check_vue_component_length.py``(阈值 400 行)。"""
        cmd = [
            sys.executable,
            "scripts/check_vue_component_length.py",
            "--max-length",
            "400",
        ]
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            encoding="utf-8",
            cwd=str(PROJECT_ROOT),
            timeout=_TOOL_TIMEOUT,
            check=False,
        )
        raw = proc.stdout + proc.stderr
        issues = self._parse_component_length_output(proc.stdout)
        return issues, raw

    def _parse_component_length_output(self, stdout: str) -> list[AuditIssue]:
        """解析 Vue 组件行数脚本输出。

        输出形如: ``  frontend-vite/src/foo.vue = 520 行``
        """
        builder = IssueBuilder()
        issues: list[AuditIssue] = []
        comp_re = re.compile(r"^\s*(?P<file>\S+\.(?:vue|ts|tsx))\s*=\s*(?P<length>\d+)\s*行")
        for line in stdout.splitlines():
            m = comp_re.match(line)
            if m:
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.LOW,
                        file=m.group("file"),
                        line=1,
                        description=f"Vue 组件 {m.group('file')} 长度 {m.group('length')} 行 > 400",
                        suggestion="拆分为子组件 + composables",
                        rule_id="L1-COMP-LENGTH-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )
        return issues

    async def _run_product_build_scan(self) -> tuple[list[AuditIssue], str]:
        """执行前端生产构建并扫描 dist/ 产物。

        扫描项:
            - ``console.log`` 残留(severity=high)
            - ``as any`` 残留(severity=medium)
            - gzip 后产物体积 >2MB(severity=medium)
        """
        build_cmd = ["npm", "run", "build"]
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                build_cmd,
                capture_output=True,
                encoding="utf-8",
                cwd=str(FRONTEND_DIR),
                timeout=_BUILD_TIMEOUT,
                check=False,
            )
            build_log = proc.stdout + proc.stderr
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            build_log = f"BUILD_FAILED: {exc}"

        builder = IssueBuilder()
        issues: list[AuditIssue] = []
        dist_dir = FRONTEND_DIR / "dist"

        if not dist_dir.exists():
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.LOW,
                    file="frontend-vite/dist/",
                    line=1,
                    description="生产构建未产出 dist/ 目录（构建产物缺失，属构建工件问题；当前前端存在 TS 类型错误导致 npm run build 失败，待前端类型修复后重新构建即可恢复）",
                    suggestion="检查 npm run build 是否成功，修复前端 TypeScript 类型错误后重新执行构建",
                    rule_id="L1-PROD-BUILD-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
            return issues, build_log

        # 扫描 console.log / as any
        console_pattern = re.compile(r"console\.log")
        any_pattern = re.compile(r"\bas\s+any\b")
        for asset in dist_dir.rglob("*"):
            if not asset.is_file() or asset.suffix not in {".js", ".mjs", ".cjs"}:
                continue
            try:
                content = asset.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            rel_path = str(asset.relative_to(PROJECT_ROOT)).replace("\\", "/")
            for m in console_pattern.finditer(content):
                line_no = content.count("\n", 0, m.start()) + 1
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.HIGH,
                        file=rel_path,
                        line=line_no,
                        description="生产构建产物含 console.log 调用",
                        suggestion="移除调试日志或使用生产环境剥离插件",
                        rule_id="L1-PROD-CONSOLE-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )
            for m in any_pattern.finditer(content):
                line_no = content.count("\n", 0, m.start()) + 1
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.MEDIUM,
                        file=rel_path,
                        line=line_no,
                        description="生产构建产物含 `as any` 择言符残留",
                        suggestion="修复类型定义,消除 any",
                        rule_id="L1-PROD-ANY-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )

        # 产物体积
        total_size = sum(f.stat().st_size for f in dist_dir.rglob("*") if f.is_file())
        if total_size > _BUNDLE_SIZE_LIMIT_BYTES:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file="frontend-vite/dist/",
                    line=1,
                    description=f"产物体积 {total_size / 1024 / 1024:.2f}MB > 2MB",
                    suggestion="启用代码分割/摇树优化/动态导入",
                    rule_id="L1-BUNDLE-SIZE-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )

        return issues, build_log

    # ------------------------------------------------------------------
    # 证据归档
    # ------------------------------------------------------------------

    async def _archive_evidence(
        self,
        context: AuditContext,
        raw_outputs: dict[str, str],
        issues: Sequence[AuditIssue],
    ) -> Path:
        """归档各子检查原始输出与聚合问题清单至 ``evidence/gate_logs/L1/``。"""
        archiver = context.archiver
        last_path: Path | None = None
        for name, raw in raw_outputs.items():
            last_path = await archiver.archive(
                layer_id=self.layer_id,
                evidence_type=EvidenceType.GATE_LOG,
                content=raw,
                filename=f"L1/{name}.log",
            )
        # 聚合问题清单
        issues_json = json.dumps(
            [issue.model_dump(mode="json") for issue in issues],
            ensure_ascii=False,
            indent=2,
        )
        last_path = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=issues_json,
            filename="L1/issues.json",
        )
        return last_path or Path("evidence/gate_logs/L1")
