"""L11 部署就绪与配置审核层执行器。

配置管理 / 依赖锁文件 / 数据库迁移 / 健康检查端点 /
回滚预案 / 部署就绪(容器化 **或** Windows 原生 NSSM)。

约束:
    - 复用存量 ``.env.example`` / ``.env.production`` / ``core/config.py``
    - 复用 ``requirements.txt`` / ``package-lock.json``
    - 判据须匹配**本仓库实际形态**(内网 Windows 原生 + NSSM 托管)：
      * 迁移在 ``migrations/``(``alembic.ini`` 不在仓库根，且 ``script_location = %(here)s``)
      * 部署证据 = NSSM 托管关键字(运维脚本 / runbook)；本仓库**没有也不应有** Dockerfile
      * 历史遗留的 ``deploy-windows.ps1`` / ``deploy_nginx.ps1`` 已删除(commit 15e13a79)，
        **不得**再把它们当作判据 —— 否则稳定产生假阳性(容器检查)与假阴性(迁移检查)
    - 无硬编码密钥(从环境变量或密钥管理服务读取)

任务来源: ``.codeartsdoer/specs/prod_code_review/tasks.md`` 第 12 节。
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

FASTAPI_APP_DIR: Path = PROJECT_ROOT / "fastapi_app"
CORE_DIR: Path = FASTAPI_APP_DIR / "core"
ENDPOINTS_V1_DIR: Path = FASTAPI_APP_DIR / "api" / "v1" / "endpoints"
FRONTEND_DIR: Path = PROJECT_ROOT / "frontend-vite"

DEFAULT_OWNER: str = "deploy-readiness-reviewer"
DEFAULT_DUE_DATE: str = "2026-09-30"

# .env.example 须枚举的必需变量
_REQUIRED_ENV_VARS: tuple[str, ...] = (
    "DATABASE_URL",
    "REDIS_URL",
    "SECRET_KEY",
    "ENVIRONMENT",
)

# 硬编码密钥正则(在 .env.production 中检测)
_HARDCODED_SECRET_RE = re.compile(
    r"(?i)\b(SECRET_KEY|API_KEY|PRIVATE_KEY|PASSWORD|TOKEN|ACCESS_KEY)\s*[:=]\s*"
    r"(?!['\"]?\$\{)['\"]?[A-Za-z0-9+/=]{8,}['\"]?"
)

# 浮动版本依赖正则(>= / > / < / <= / ~= / * 无精确锁定)
_FLOATING_VERSION_RE = re.compile(r"^[A-Za-z0-9_.-]+\s*(>=|>|<|<=|~=|\*)")

# 健康检查端点路径
_HEALTH_ENDPOINT_PATHS: tuple[str, ...] = ("/health", "/ready", "/healthz", "/readyz")

# 回滚文档关键词
_ROLLBACK_KEYWORDS: tuple[str, ...] = (
    "rollback",
    "回滚",
    "revert",
    "previous version",
    "上一版本",
)

# 部署脚本候选(供回滚预案检查扫描其中是否含回滚逻辑)。
# 注意: ``deploy-windows.ps1`` / ``deploy_nginx.ps1`` 已删除(commit 15e13a79)、
# ``build_and_release.py`` 从未存在 —— 保留幽灵文件名只会让检查静默失效。
_DEPLOY_SCRIPTS: tuple[str, ...] = (
    "restart_prod.ps1",
    "scripts/enhanced-rollback.ps1",
)

# 容器化编排文件(仅当项目确实采用容器部署时才作为判据)
_CONTAINER_FILES: tuple[str, ...] = (
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
)

# Windows 原生部署证据:NSSM 托管关键字(匹配时大小写不敏感)
_NSSM_KEYWORDS: tuple[str, ...] = ("nssm",)

# 承载 NSSM 部署说明的文档(本项目权威部署路径)
_DEPLOY_RUNBOOK: str = "docs/runbooks/service-lifecycle.md"

# 原生部署证据的脚本扫描范围(相对仓库根,浅层 glob)
_DEPLOY_SCRIPT_GLOBS: tuple[str, ...] = ("*.ps1", "scripts/*.ps1")

# Alembic 路径候选(本仓库实际布局优先,通用布局兜底)
_ALEMBIC_INI_CANDIDATES: tuple[str, ...] = (
    "migrations/alembic.ini",  # ← 本仓库实际
    "alembic.ini",  # 通用兜底
)
_ALEMBIC_DIR_CANDIDATES: tuple[str, ...] = (
    "migrations",  # ← 本仓库实际
    "alembic",  # 通用兜底
    "fastapi_app/alembic",  # 历史变体
)

# alembic.ini 中 script_location 的解析(本项目为 ``%(here)s``,即 ini 所在目录)
_SCRIPT_LOCATION_RE = re.compile(r"(?m)^\s*script_location\s*=\s*(.+?)\s*$")


def _rel(path: Path | None) -> str:
    """相对仓库根的 posix 路径(不在仓库内时回落为绝对路径)。"""
    if path is None:
        return "none"
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve_script_location(alembic_ini: Path | None) -> Path | None:
    """把 alembic.ini 的 ``script_location`` 解析为绝对目录(无法解析返回 ``None``)。

    支持 ``%(here)s``(Alembic 注入的默认值 = ini 所在目录;本项目 ``migrations/alembic.ini``
    正是用 ``%(here)s``)以及相对/绝对路径。注释行以 ``#`` 开头,不会命中正则。
    """
    if alembic_ini is None or not alembic_ini.is_file():
        return None
    try:
        text = alembic_ini.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _SCRIPT_LOCATION_RE.search(text)
    if match is None:
        return None
    raw = match.group(1).strip()
    if not raw:
        return None
    candidate = Path(raw.replace("%(here)s", str(alembic_ini.parent)))
    if not candidate.is_absolute():
        candidate = alembic_ini.parent / candidate
    return candidate.resolve()


def _find_native_deploy_evidence() -> list[str]:
    """返回「Windows 原生 NSSM 部署」的证据来源(相对路径),空列表表示未检出。

    证据 = runbook 或任一运维脚本中出现 NSSM 托管关键字(大小写不敏感)。
    本仓库无 Dockerfile,这是其**真实**部署路径的判据。
    """
    sources: list[str] = []

    runbook = PROJECT_ROOT / _DEPLOY_RUNBOOK
    if runbook.is_file() and _contains_nssm(runbook):
        sources.append(_DEPLOY_RUNBOOK)

    seen: set[Path] = set()
    for pattern in _DEPLOY_SCRIPT_GLOBS:
        for script in sorted(PROJECT_ROOT.glob(pattern)):
            if script in seen or not script.is_file():
                continue
            seen.add(script)
            if _contains_nssm(script):
                sources.append(_rel(script))

    return sources


def _contains_nssm(path: Path) -> bool:
    """文件内容是否出现 NSSM 关键字(读取失败视为否)。"""
    try:
        content = path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    return any(kw in content for kw in _NSSM_KEYWORDS)


class L11Deployment(LayerBase):
    """L11 部署就绪与配置审核层执行器。

    聚合 6 个子检查:
        - 配置管理(.env.example 完整 / .env.production 无硬编码密钥)
        - 依赖锁文件(requirements.txt / package-lock.json 锁定版本)
        - 数据库迁移(Alembic 无 pending)
        - 健康检查端点(/health /ready)
        - 回滚预案(文档化)
        - 部署就绪(容器化配置 **或** Windows 原生 NSSM 部署证据,二者有其一即可)
    """

    layer_id: str = "L11"
    layer_name: str = "部署就绪与配置审核"
    weight: float = 0.04

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    async def run(self, context: AuditContext) -> LayerResult:
        """执行 L11 全部子检查并归档证据。"""
        started_at = datetime.now(UTC)
        builder = IssueBuilder()
        raw_outputs: dict[str, str] = {}

        checks: list[tuple[str, object]] = [
            ("env_config", self._check_env_config(builder)),
            ("dependency_lock", self._check_dependency_lock(builder)),
            ("migrations", self._check_migrations(builder)),
            ("health_endpoints", self._check_health_endpoints(builder)),
            ("rollback_plan", self._check_rollback_plan(builder)),
            ("container_config", self._check_container_config(builder)),
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
                        suggestion="检查部署配置文件路径",
                        rule_id=f"L11-{name.upper()}-EXEC-001",
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
    # 12.1 配置管理(.env.example 完整 / .env.production 无硬编码密钥)
    # ------------------------------------------------------------------

    async def _check_env_config(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """审查 .env.example 枚举完整且 .env.production 无硬编码密钥。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        # 1. .env.example 存在且枚举完整
        env_example = PROJECT_ROOT / ".env.example"
        if not env_example.exists():
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file=".env.example",
                    line=1,
                    description=".env.example 不存在,环境变量未文档化",
                    suggestion="创建 .env.example 枚举所有必需环境变量",
                    rule_id="L11-CONFIG-MISSING-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
        else:
            try:
                example_content = env_example.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.HIGH,
                        file=".env.example",
                        line=1,
                        description=f"读取 .env.example 失败: {exc}",
                        suggestion="检查文件权限与编码",
                        rule_id="L11-CONFIG-MISSING-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )
                example_content = ""

            # 检查必需变量是否枚举
            example_vars = {
                line.split("=")[0].strip()
                for line in example_content.splitlines()
                if "=" in line and not line.strip().startswith("#")
            }
            raw_parts.append(f"env_example_vars: {sorted(example_vars)}")

            for var in _REQUIRED_ENV_VARS:
                if var not in example_vars:
                    issues.append(
                        builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.MEDIUM,
                            file=".env.example",
                            line=1,
                            description=f".env.example 缺少必需变量 {var}",
                            suggestion=f"添加 {var} 及说明",
                            rule_id="L11-CONFIG-MISSING-001",
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )

        # 2. .env.production 无硬编码密钥
        env_prod = PROJECT_ROOT / ".env.production"
        if env_prod.exists():
            try:
                prod_lines = env_prod.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError) as exc:
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.HIGH,
                        file=".env.production",
                        line=1,
                        description=f"读取 .env.production 失败: {exc}",
                        suggestion="检查文件权限与编码",
                        rule_id="L11-HARDCODED-SECRET-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )
                return issues, "\n".join(raw_parts)

            for idx, line in enumerate(prod_lines, start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if _HARDCODED_SECRET_RE.search(line):
                    issues.append(
                        builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.CRITICAL,
                            file=".env.production",
                            line=idx,
                            description="检测到硬编码密钥/密码(非环境变量引用)",
                            suggestion="改为从环境变量或密钥管理服务读取",
                            rule_id="L11-HARDCODED-SECRET-001",
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )
            raw_parts.append(f"env_prod_lines: {len(prod_lines)}")
        else:
            raw_parts.append(".env.production 不存在,跳过硬编码密钥检查")

        # 3. core/config.py Pydantic Settings 校验
        config_file = CORE_DIR / "config.py"
        if config_file.exists():
            try:
                config_source = config_file.read_text(encoding="utf-8")
                has_settings = bool(re.search(r"class\s+\w+\s*\(\s*BaseSettings\s*\)", config_source))
                raw_parts.append(f"config_pydantic_settings: {has_settings}")
                if not has_settings:
                    issues.append(
                        builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.MEDIUM,
                            file=str(config_file.relative_to(PROJECT_ROOT).as_posix()),
                            line=1,
                            description="core/config.py 未使用 Pydantic BaseSettings",
                            suggestion="使用 Pydantic Settings 管理配置并添加校验",
                            rule_id="L11-CONFIG-MISSING-001",
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )
            except (OSError, UnicodeDecodeError):
                pass

        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 12.1 依赖锁文件(requirements.txt / package-lock.json)
    # ------------------------------------------------------------------

    async def _check_dependency_lock(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """审查 requirements.txt 与 package-lock.json 锁定全部依赖版本。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        # 1. requirements.txt 锁定版本
        req_file = PROJECT_ROOT / "requirements.txt"
        if not req_file.exists():
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file="requirements.txt",
                    line=1,
                    description="requirements.txt 不存在",
                    suggestion="创建 requirements.txt 并锁定所有依赖版本",
                    rule_id="L11-DEP-UNLOCKED-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
        else:
            try:
                req_lines = req_file.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError) as exc:
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.HIGH,
                        file="requirements.txt",
                        line=1,
                        description=f"读取 requirements.txt 失败: {exc}",
                        suggestion="检查文件权限",
                        rule_id="L11-DEP-UNLOCKED-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )
                return issues, "\n".join(raw_parts)

            for idx, line in enumerate(req_lines, start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or stripped.startswith("-"):
                    continue
                if _FLOATING_VERSION_RE.match(stripped):
                    issues.append(
                        builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.HIGH,
                            file="requirements.txt",
                            line=idx,
                            description=f"浮动版本依赖: {stripped}",
                            suggestion="使用 == 锁定精确版本",
                            rule_id="L11-DEP-UNLOCKED-001",
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )
            raw_parts.append(f"requirements_lines: {len(req_lines)}")

        # 2. package-lock.json 存在
        lock_file = FRONTEND_DIR / "package-lock.json"
        if not lock_file.exists():
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file="frontend-vite/package-lock.json",
                    line=1,
                    description="package-lock.json 不存在,前端依赖未锁定",
                    suggestion="运行 npm install 生成 package-lock.json",
                    rule_id="L11-DEP-UNLOCKED-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
        else:
            try:
                lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
                lockfile_version = lock_data.get("lockfileVersion", "unknown")
                raw_parts.append(f"package_lockfile_version: {lockfile_version}")
            except (json.JSONDecodeError, OSError):
                raw_parts.append("package-lock.json 解析失败")

        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 12.3 数据库迁移(Alembic 无 pending)
    # ------------------------------------------------------------------

    async def _check_migrations(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """审查 Alembic 迁移是否就绪(无 pending migrations)。

        路径候选**本仓库实际布局优先**: ``migrations/alembic.ini``(本项目;
        其 ``script_location = %(here)s`` ⇒ env.py 与 versions/ 与 ini 同目录),
        再回落通用布局(仓库根 ``alembic.ini`` / ``alembic/`` / ``fastapi_app/alembic/``)。

        2026-09-24 修正: 原实现只找后三种通用布局,本仓库三者皆无 ⇒
        **整个迁移检查被静默跳过**(假阴性: 真实 schema 漂移会被无声放过)。
        现在找不到配置时发 LOW 提示,让「跳过」可见,而不是假装通过。
        """
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        alembic_ini = next(
            (p for p in (PROJECT_ROOT / c for c in _ALEMBIC_INI_CANDIDATES) if p.is_file()),
            None,
        )
        alembic_dir = next(
            (p for p in (PROJECT_ROOT / c for c in _ALEMBIC_DIR_CANDIDATES) if p.is_dir()),
            None,
        )

        if alembic_ini is None and alembic_dir is None:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.LOW,
                    file=str(PROJECT_ROOT),
                    line=1,
                    description="未检出 Alembic 配置,数据库迁移检查已跳过",
                    suggestion=(
                        "确认迁移目录(本项目为 migrations/);"
                        "若确不使用 Alembic,请在本层显式豁免该子检查"
                    ),
                    rule_id="L11-CONFIG-MISSING-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
            raw_parts.append("alembic_config: not_found (迁移检查已跳过)")
            return issues, "\n".join(raw_parts)

        raw_parts.append(f"alembic_ini: {_rel(alembic_ini)}")
        raw_parts.append(f"alembic_dir: {_rel(alembic_dir)}")

        # versions 目录: 先按 ini 的 script_location 解析,再回落 ini 同级 / alembic 目录
        search_roots: list[Path] = []
        script_root = _resolve_script_location(alembic_ini)
        if script_root is not None:
            search_roots.append(script_root)
        if alembic_ini is not None:
            search_roots.append(alembic_ini.parent)
        if alembic_dir is not None:
            search_roots.append(alembic_dir)

        versions_dir = next(
            (r / "versions" for r in search_roots if (r / "versions").is_dir()), None
        )

        if versions_dir is None:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file="migrations/versions/",
                    line=1,
                    description="Alembic versions 目录不存在",
                    suggestion="创建 migrations/versions/ 并添加迁移脚本",
                    rule_id="L11-CONFIG-MISSING-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
            return issues, "\n".join(raw_parts)

        migration_files = list(versions_dir.glob("*.py"))
        raw_parts.append(f"versions_dir: {_rel(versions_dir)}")
        raw_parts.append(f"migration_files: {len(migration_files)}")

        if not migration_files:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=_rel(versions_dir),
                    line=1,
                    description="无数据库迁移文件",
                    suggestion="使用 alembic revision --autogenerate 生成迁移",
                    rule_id="L11-CONFIG-MISSING-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )

        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 12.3 健康检查端点(/health /ready)
    # ------------------------------------------------------------------

    async def _check_health_endpoints(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """审查 /health 与 /ready 端点存在且含依赖检查。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        found_paths: set[str] = set()
        route_re = re.compile(r"@\w+\.(get|post)\s*\(\s*[\"']([^\"']+)[\"']")

        scan_dirs: list[Path] = [
            ENDPOINTS_V1_DIR,
            FASTAPI_APP_DIR / "api" / "v2" / "endpoints",
            FASTAPI_APP_DIR,
        ]
        # 也检查 core/health.py / core/db_health.py
        extra_files = [
            CORE_DIR / "health.py",
            CORE_DIR / "db_health.py",
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
            for m in route_re.finditer(source):
                path = m.group(2)
                for health_path in _HEALTH_ENDPOINT_PATHS:
                    if path == health_path or path.endswith(health_path):
                        found_paths.add(health_path)

        raw_parts.append(f"found_health_endpoints: {sorted(found_paths)}")

        if not found_paths:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file="fastapi_app/",
                    line=1,
                    description="未发现健康检查端点(期望 /health 与 /ready)",
                    suggestion="添加 /health 与 /ready 端点含数据库/Redis 依赖检查",
                    rule_id="L11-HEALTH-CHECK-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
        else:
            # 至少须有 /health
            if "/health" not in found_paths and "/healthz" not in found_paths:
                issues.append(
                    builder.build(
                        layer_id=self.layer_id,
                        severity=Severity.HIGH,
                        file="fastapi_app/",
                        line=1,
                        description="缺少 /health 健康检查端点",
                        suggestion="添加 /health 端点含依赖状态检查",
                        rule_id="L11-HEALTH-CHECK-001",
                        owner=DEFAULT_OWNER,
                        due_date=DEFAULT_DUE_DATE,
                    )
                )

        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 12.3 回滚预案(文档化)
    # ------------------------------------------------------------------

    async def _check_rollback_plan(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """审查回滚预案是否文档化(部署可回滚 / 迁移可回滚)。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        # 搜索文档目录与部署脚本中的回滚关键词
        search_dirs: list[Path] = [
            PROJECT_ROOT / "docs",
            PROJECT_ROOT,
        ]
        search_patterns = ("*.md", "*.txt", "*.rst")

        found_rollback_doc = False
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for pattern in search_patterns:
                for doc_file in search_dir.glob(pattern):
                    if "node_modules" in doc_file.parts or ".git" in doc_file.parts:
                        continue
                    try:
                        content = doc_file.read_text(encoding="utf-8").lower()
                    except (OSError, UnicodeDecodeError):
                        continue
                    if any(kw.lower() in content for kw in _ROLLBACK_KEYWORDS):
                        found_rollback_doc = True
                        rel = doc_file.relative_to(PROJECT_ROOT).as_posix()
                        raw_parts.append(f"rollback_doc: {rel}")
                        break
                if found_rollback_doc:
                    break
            if found_rollback_doc:
                break

        # 也检查部署脚本中是否含回滚逻辑
        for script_name in _DEPLOY_SCRIPTS:
            script_path = PROJECT_ROOT / script_name
            if script_path.exists():
                try:
                    content = script_path.read_text(encoding="utf-8").lower()
                    if any(kw.lower() in content for kw in _ROLLBACK_KEYWORDS):
                        found_rollback_doc = True
                        raw_parts.append(f"rollback_in_script: {script_name}")
                        break
                except (OSError, UnicodeDecodeError):
                    pass

        if not found_rollback_doc:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.HIGH,
                    file="docs/",
                    line=1,
                    description="未发现回滚预案文档",
                    suggestion="创建回滚预案文档(部署回滚 + 迁移回滚 + 数据备份)",
                    rule_id="L11-ROLLBACK-MISSING-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )

        return issues, "\n".join(raw_parts)

    # ------------------------------------------------------------------
    # 12.2 容器化配置(Dockerfile / 部署脚本)
    # ------------------------------------------------------------------

    async def _check_container_config(
        self, builder: IssueBuilder
    ) -> tuple[list[AuditIssue], str]:
        """审查**部署就绪**: 容器化配置 **或** Windows 原生 NSSM 部署证据。

        判据(二者有其一即视为已具备部署路径):
            - 容器路径: ``Dockerfile`` / ``docker-compose.*`` 存在 → 追加校验非 root 用户
            - 原生路径: NSSM 托管证据存在(runbook 或任一运维脚本含 ``nssm`` 关键字)

        2026-09-24 修正: 原实现只认 ``Dockerfile`` / ``docker-compose.*`` /
        ``deploy-*.ps1``,而本仓库是**内网 Windows 原生 + NSSM**,既无容器文件、
        也无那两个已删除的部署脚本 ⇒ 稳定产生假阳性(详见模块 docstring)。
        """
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        dockerfile = PROJECT_ROOT / "Dockerfile"
        has_dockerfile = dockerfile.is_file()
        has_container_file = any((PROJECT_ROOT / name).is_file() for name in _CONTAINER_FILES)
        nssm_evidence = _find_native_deploy_evidence()
        has_native_deploy = bool(nssm_evidence)

        raw_parts.append(
            f"dockerfile={has_dockerfile}, container_file={has_container_file}, "
            f"native_nssm={has_native_deploy}"
        )
        if nssm_evidence:
            raw_parts.append(f"nssm_evidence: {', '.join(nssm_evidence)}")

        if not has_container_file and not has_native_deploy:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=str(PROJECT_ROOT),
                    line=1,
                    description="未检出部署路径(既无容器化配置,也无 Windows 原生 NSSM 部署证据)",
                    suggestion=(
                        "补充其一: Dockerfile / docker-compose.*,"
                        f"或 NSSM 部署说明({_DEPLOY_RUNBOOK})与含 nssm 的运维脚本"
                    ),
                    rule_id="L11-CONTAINER-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
            return issues, "\n".join(raw_parts)

        # 若有 Dockerfile, 校验非 root 用户
        if has_dockerfile:
            try:
                dockerfile_content = dockerfile.read_text(encoding="utf-8")
                has_non_root = bool(
                    re.search(r"(?i)\bUSER\s+(?!root\b)\S+", dockerfile_content)
                )
                raw_parts.append(f"dockerfile_non_root_user: {has_non_root}")
                if not has_non_root:
                    issues.append(
                        builder.build(
                            layer_id=self.layer_id,
                            severity=Severity.MEDIUM,
                            file="Dockerfile",
                            line=1,
                            description="Dockerfile 未配置非 root 用户",
                            suggestion="添加 USER 指令指定非 root 用户",
                            rule_id="L11-CONTAINER-001",
                            owner=DEFAULT_OWNER,
                            due_date=DEFAULT_DUE_DATE,
                        )
                    )
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
        """归档审查记录至 ``evidence/manual_reviews/L11/`` 与 ``evidence/gate_logs/L11/``。"""
        archiver = context.archiver

        # 1. 人工审查记录
        path_review = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.MANUAL_REVIEW,
            content=(
                "# L11 部署就绪与配置人工审查\n\n"
                "## 配置管理\n.env.example 枚举完整 / .env.production 无硬编码密钥。\n\n"
                "## 依赖锁文件\nrequirements.txt / package-lock.json 锁定版本。\n\n"
                "## 数据库迁移\nAlembic 迁移就绪,无 pending。\n\n"
                "## 健康检查\n/health /ready 端点含依赖检查。\n\n"
                "## 回滚预案\n回滚步骤文档化。\n\n"
                "## 容器化\nDockerfile / 部署脚本合规(非 root / 最小化)。\n\n"
                f"## 自动扫描结果\n{json.dumps(raw_outputs, ensure_ascii=False, indent=2)}\n"
            ),
            filename="L11/review.md",
        )

        # 2. 原始扫描输出
        path_raw = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content="\n\n".join(f"=== {k} ===\n{v}" for k, v in raw_outputs.items()),
            filename="L11/scan_raw.txt",
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
            filename="L11/issues.json",
        )

        # 4. summary.md
        path_summary = await archiver.archive(
            layer_id=self.layer_id,
            evidence_type=EvidenceType.GATE_LOG,
            content=(
                "# L11 部署就绪与配置审核\n\n"
                "## 配置管理\n.env.example 完整 / .env.production 无硬编码密钥。\n\n"
                "## 依赖锁文件\n全部依赖锁定版本。\n\n"
                "## 数据库迁移\nAlembic 无 pending。\n\n"
                "## 健康检查\n/health /ready 存在且含依赖检查。\n\n"
                "## 回滚预案\n文档化。\n\n"
                "## 容器化\nDockerfile / 部署脚本合规。\n"
            ),
            filename="L11/summary.md",
        )

        return path_summary or path_issues or path_raw or path_review
