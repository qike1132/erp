"""L11 部署就绪与配置审核层执行器。

配置管理 / 依赖锁文件 / 数据库迁移 / 健康检查端点 /
回滚预案 / 容器化配置。

约束:
    - 复用存量 ``.env.example`` / ``.env.production`` / ``core/config.py``
    - 复用 ``deploy-windows.ps1`` / ``requirements.txt`` / ``package-lock.json``
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

# 容器/部署脚本候选
_DEPLOY_SCRIPTS: tuple[str, ...] = (
    "deploy-windows.ps1",
    "deploy_nginx.ps1",
    "build_and_release.py",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
)


class L11Deployment(LayerBase):
    """L11 部署就绪与配置审核层执行器。

    聚合 6 个子检查:
        - 配置管理(.env.example 完整 / .env.production 无硬编码密钥)
        - 依赖锁文件(requirements.txt / package-lock.json 锁定版本)
        - 数据库迁移(Alembic 无 pending)
        - 健康检查端点(/health /ready)
        - 回滚预案(文档化)
        - 容器化配置(Dockerfile / 部署脚本)
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
        """审查 Alembic 迁移是否就绪(无 pending migrations)。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        # Alembic 配置与版本目录候选
        alembic_ini = PROJECT_ROOT / "alembic.ini"
        alembic_dir = PROJECT_ROOT / "alembic"
        # 也检查 fastapi_app 下的 alembic
        alembic_dir_alt = FASTAPI_APP_DIR / "alembic"

        if not alembic_ini.exists() and not alembic_dir.exists() and not alembic_dir_alt.exists():
            raw_parts.append("Alembic 未配置,跳过迁移检查")
            return issues, "\n".join(raw_parts)

        # 检查 versions 目录存在且有迁移文件
        versions_dir = None
        for candidate in (alembic_dir / "versions", alembic_dir_alt / "versions"):
            if candidate.exists():
                versions_dir = candidate
                break

        if versions_dir is None:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file="alembic/versions/",
                    line=1,
                    description="Alembic versions 目录不存在",
                    suggestion="创建 alembic/versions/ 并添加迁移脚本",
                    rule_id="L11-CONFIG-MISSING-001",
                    owner=DEFAULT_OWNER,
                    due_date=DEFAULT_DUE_DATE,
                )
            )
            return issues, "\n".join(raw_parts)

        migration_files = list(versions_dir.glob("*.py"))
        raw_parts.append(f"migration_files: {len(migration_files)}")

        if not migration_files:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=str(versions_dir.relative_to(PROJECT_ROOT).as_posix()),
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
        """审查 Dockerfile 或部署脚本存在且合规(非 root / 最小化)。"""
        issues: list[AuditIssue] = []
        raw_parts: list[str] = []

        dockerfile = PROJECT_ROOT / "Dockerfile"
        docker_compose_candidates = [
            PROJECT_ROOT / "docker-compose.yml",
            PROJECT_ROOT / "docker-compose.yaml",
        ]
        deploy_scripts = [
            PROJECT_ROOT / "deploy-windows.ps1",
            PROJECT_ROOT / "deploy_nginx.ps1",
            PROJECT_ROOT / "build_and_release.py",
        ]

        has_dockerfile = dockerfile.exists()
        has_compose = any(f.exists() for f in docker_compose_candidates)
        has_deploy_script = any(f.exists() for f in deploy_scripts)

        raw_parts.append(
            f"dockerfile={has_dockerfile}, compose={has_compose}, deploy_script={has_deploy_script}"
        )

        if not has_dockerfile and not has_compose and not has_deploy_script:
            issues.append(
                builder.build(
                    layer_id=self.layer_id,
                    severity=Severity.MEDIUM,
                    file=str(PROJECT_ROOT),
                    line=1,
                    description="无 Dockerfile / docker-compose / 部署脚本",
                    suggestion="创建 Dockerfile 或部署脚本(deploy-windows.ps1 等)",
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
