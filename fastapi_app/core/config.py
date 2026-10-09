import ipaddress
import logging
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from dotenv import load_dotenv

# 在类定义之前加载 .env，确保 os.getenv("DB_PASSWORD") 等能读到值
# pydantic_settings 的 env_file 仅为其自身字段服务，不会注入 os.environ
load_dotenv(override=False)

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# 「单元素错配」告警的进程内一次性闸门。
# _is_production_env() 会被 Settings.is_production 属性按请求调用
# （core/middleware.py 的 CSRF / CSP 中间件），若无该闸门，
# 在错配环境下每个 HTTP 请求都会刷一条 WARNING，造成日志洪泛。
_single_element_env_warned = False


def _build_database_uri() -> str:
    """构建数据库URI（PostgreSQL + asyncpg）"""
    db_host = os.getenv("DB_HOST", "localhost")
    db_user = os.getenv("DB_USER", "erp_app")
    db_password = os.getenv("DB_PASSWORD", "")
    db_name = os.getenv("DB_NAME", "erp_system")
    db_port = os.getenv("DB_PORT", "5432")
    # 使用 asyncpg 作为异步驱动
    return f"postgresql+asyncpg://{quote_plus(db_user)}:{quote_plus(db_password)}@{db_host}:{db_port}/{db_name}"


def _build_sync_database_uri() -> str:
    """构建同步数据库URI（PostgreSQL + psycopg3）- 用于 Alembic 迁移"""
    db_host = os.getenv("DB_HOST", "localhost")
    db_user = os.getenv("DB_USER", "erp_app")
    db_password = os.getenv("DB_PASSWORD", "")
    db_name = os.getenv("DB_NAME", "erp_system")
    db_port = os.getenv("DB_PORT", "5432")
    # 使用 psycopg3 作为同步驱动
    return f"postgresql+psycopg://{quote_plus(db_user)}:{quote_plus(db_password)}@{db_host}:{db_port}/{db_name}"


def _is_production_env() -> bool:
    """判定当前是否生产环境（全库统一入口，动态读取以兼容测试 monkeypatch）。

    容错：取第一个空白分隔的 token 比较。历史安装脚本曾把 NSSM AppEnvironmentExtra
    写成单个字符串（如 APP_ENV="production FASTAPI_DEBUG=false PYTHONPATH=..."），
    若整串比较将永远判不成 production，导致文档端点/安全闸门意外失效。

    注意：该容错只救回 APP_ENV 一个变量，同一串里的其余变量
    （FASTAPI_DEBUG / PYTHONPATH / PYTHONUTF8 / PYTHONUNBUFFERED / UVICORN_WORKERS）
    实际都**没有**生效。因此检测到含空白时打一条显式告警，把「静默错配」变成「可见」。
    待 NSSM AppEnvironmentExtra 改为「一变量一元素」后，可移除该容错改为严格比较。
    """
    global _single_element_env_warned
    raw = os.getenv("APP_ENV", "").strip().lower()
    if raw and len(raw.split()) > 1 and not _single_element_env_warned:
        _single_element_env_warned = True
        logger.warning(
            "APP_ENV 含空白分隔（值=%r）：疑似 NSSM AppEnvironmentExtra 被写成"
            "单个 REG_MULTI_SZ 元素，此时 FASTAPI_DEBUG/PYTHONPATH/PYTHONUTF8/"
            "PYTHONUNBUFFERED/UVICORN_WORKERS 均不会生效。"
            "修复方式见 deliverables/audit-2026-09-17/ 或运行脚本 fix_nssm_appenv.ps1。",
            raw,
        )
    return bool(raw) and raw.split()[0] in ("prod", "production")


def _is_private_or_loopback_ip(host: str) -> bool:
    """host 是否为回环或内网 IP **字面量**（`localhost` 由调用方单独判定）。

    只接受 IP 字面量，不接受域名——`http://erp.lan` 这类内网主机名不放行，
    避免依赖不可控的内网 DNS 解析结果。
    """
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    # is_private 覆盖 10/8、172.16/12、192.168/16、127/8、169.254/16 等私有段
    return ip.is_private or ip.is_loopback


def _is_production_allowed_origin(origin: str) -> bool:
    """生产环境是否放行该 CORS origin。

    规则（2026-09-17 放开局域网）：
    - ``https://`` 一律放行（链路已加密，无中间人窃听面）；
    - 明文 ``http://`` **仅**放行 localhost / 回环 / 内网 IP 字面量
      （10/8、172.16/12、192.168/16 等），供内网 Nginx 入口使用，
      例如 ``http://192.168.0.95:3000``；
    - 公网明文 HTTP（公网域名或公网 IP）一律拒收；
    - 内网**域名**（如 ``http://erp.lan``）不放行，只认 IP 字面量。

    必须按 URL 解析取 host 判定，**不可**用 ``startswith("http://192.168")``——
    否则 ``http://192.168.0.95.evil.com`` 会被前缀仿冒绕过。
    """
    if origin.startswith("https://"):
        return True
    if not origin.startswith("http://"):
        return False
    host = urlparse(origin).hostname or ""
    if host == "localhost":
        return True
    return _is_private_or_loopback_ip(host)


def filter_cors_origins(raw: str, *, is_production: bool) -> list[str]:
    """把 CORS_ORIGINS 原始串切成可用 origin 列表。

    生产环境会按 ``_is_production_allowed_origin`` 过滤掉明文 HTTP 源。
    抽成模块级函数（原为类体内联推导式）以便单测直接覆盖该规则——
    否则该规则只在 import 时求值一次，只能靠改环境变量才能验证。
    """
    return [
        origin.strip()
        for origin in raw.split(",")
        if origin.strip()
        and (not is_production or _is_production_allowed_origin(origin.strip()))
    ]


# ---------------------------------------------------------------------------
# 生产环境备份/监控配置校验（S3，2026-09-30）
#
# 背景：本应用**只加载项目根 .env**（见本文件顶部 load_dotenv 与 model_config 的 env_file）。
# 生产机上 .env 与 .env.production / config/.env.production 长期漂移（缺 90+ 键，含全部
# BACKUP_*），而备份服务读取这些键的方式又各不相同：
#   · BACKUP_ENCRYPTION_ENABLED 默认 false  （services/backup/_constants.py:51，2026-10-09 起）
#   · BACKUP_ENCRYPTION_PASSWORD 默认 ''    （同文件 :44）
#   ⇒ 两者组合会产出「看着成功、但无人能解开」的备份文件（P0-1 同类事故）。
# 因此这里对「已启用备份加密却拿不到密钥」直接拒绝启动（fail fast）；
# 其余缺失项只告警——它们大多有合理默认值
# （services/backup/orchestration/policy_service.py:43/46/63）。
# 可用 STRICT_CONFIG_CHECK=false 临时关闭本校验。
# ---------------------------------------------------------------------------

# 模板占位值前缀（.env.example 里的 <...> / changeme / your-xxx 等）
_PLACEHOLDER_PREFIXES = ("<", "changeme", "change-me", "your-", "your_", "xxx", "todo", "placeholder")

# 最近一次 Settings() 构造收集到的生产配置告警（供启动后统一打印）
_production_config_warnings: list[str] = []


def _is_strict_config_check_enabled() -> bool:
    """STRICT_CONFIG_CHECK 开关（默认开启；false/0/no/off 关闭生产配置强校验）。"""
    raw = os.getenv("STRICT_CONFIG_CHECK", "").strip().lower()
    return raw not in ("false", "0", "no", "off")


def _is_test_process() -> bool:
    """测试进程判定：用于豁免生产配置强校验。

    本仓库多处测试为了让**其它**生产闸门生效而伪造 APP_ENV=production
    （tests/test_config.py:36、fastapi_app/tests/test_security_and_batch.py:130/188 等），
    它们验证的是 SECRET_KEY / ALLOWED_HOSTS 等规则，不应被备份校验拦截；
    且没有 .env 的 CI 环境本来就拿不到 BACKUP_* 的值。
    生产进程（prod_runner / uvicorn / ARQ worker）从不导入 pytest，
    也不会设置 PYTEST_CURRENT_TEST，因此本豁免不会削弱生产保护。
    """
    return "pytest" in sys.modules or bool(os.getenv("PYTEST_CURRENT_TEST"))


def _looks_like_placeholder(value: str) -> bool:
    """模板占位值判定（<...> / changeme / your-xxx / 空串等）。"""
    normalized = value.strip().strip('"').strip("'").lower()
    if not normalized:
        return True
    return normalized.startswith(_PLACEHOLDER_PREFIXES)


def _probe_dir_writable(directory: Path) -> bool:
    """真实写入探测。

    不用 os.access(dir, os.W_OK)：Windows 上它依据目录的只读属性判断，
    对 ACL 拒绝写入的目录会误报可写（反之也可能误报不可写而拦住启动）。
    """
    try:
        with tempfile.NamedTemporaryFile(
            dir=directory, prefix=".write_probe_", suffix=".tmp", delete=True
        ):
            return True
    except OSError:
        return False


def _validate_production_backup_config(*, force: bool = False) -> list[str]:
    """生产环境备份/监控配置校验。

    返回**非致命**告警文案列表；致命项直接抛 RuntimeError（拒绝启动）。
    只在生产环境由 Settings.__init__ 调用；force=True 供测试绕过测试进程豁免。

    判定分级（刻意为「能安全启动」留余地）：
      1. 备份加密：生效且拿不到可用密钥 ⇒ **拒绝启动**（会产出不可还原的备份）
      2. BACKUP_DIR：显式声明且目录已存在但不可写 ⇒ **拒绝启动**（备份必然全败）；
         目录不存在只告警（records.py 的 ensure_backup_dir 会在首次使用时创建）
      3. 调度/存储/监控/告警通道缺失 ⇒ 只告警（均有合理默认值或仅影响可观测性）
    """
    warnings: list[str] = []
    if not force and _is_test_process():
        return warnings
    if not _is_strict_config_check_enabled():
        logger.warning("STRICT_CONFIG_CHECK 已关闭，跳过生产备份/监控配置校验")
        return warnings

    # 1) 备份加密
    encryption_declared = os.getenv("BACKUP_ENCRYPTION_ENABLED")
    encryption_enabled = (encryption_declared or "false").strip().lower() == "true"
    if encryption_declared is None:
        warnings.append(
            "未显式声明 BACKUP_ENCRYPTION_ENABLED（代码默认 false，即备份不加密）；"
            "请显式声明，避免默认值变更时静默改变备份行为"
        )
    if encryption_enabled:
        password = os.getenv("BACKUP_ENCRYPTION_PASSWORD", "")
        master_key = os.getenv("BACKUP_ENCRYPTION_KEY", "")
        effective = password if password.strip() else master_key
        if not effective.strip() or _looks_like_placeholder(effective):
            raise RuntimeError(
                "生产环境已启用备份加密（BACKUP_ENCRYPTION_ENABLED 生效为 true）"
                "但未提供可用的 BACKUP_ENCRYPTION_PASSWORD / BACKUP_ENCRYPTION_KEY："
                "备份将产出无法解密的文件，拒绝启动。"
                "确需临时跳过校验请设置 STRICT_CONFIG_CHECK=false。"
            )

    # 2) 备份目录
    backup_dir = os.getenv("BACKUP_DIR", "").strip()
    if backup_dir:
        _dir = Path(backup_dir)
        if _dir.is_dir():
            if not _probe_dir_writable(_dir):
                raise RuntimeError(
                    f"生产环境 BACKUP_DIR={backup_dir!r} 存在但不可写：备份会全部失败，拒绝启动。"
                    "请修正目录权限或改用可写路径。"
                )
        else:
            warnings.append(
                f"BACKUP_DIR={backup_dir!r} 当前不是已存在的目录；"
                "备份服务首次使用时会自动创建（ensure_backup_dir），请确认路径与磁盘挂载正确"
            )
    else:
        warnings.append(
            "未设置 BACKUP_DIR，将使用默认值 backups/server（与数据库同盘，无异地副本）"
        )

    # 3) 备份调度与存储（有合理默认值，缺失只告警）
    for _key, _default, _label in (
        ("BACKUP_STORAGE_LOCATION", "BACKUP_DIR", "备份存储位置"),
        ("BACKUP_FULL_CRON", "0 2 * * *", "全量备份计划"),
        ("BACKUP_INCREMENTAL_CRON", "0 */1 * * *", "增量备份计划"),
    ):
        if not os.getenv(_key, "").strip():
            warnings.append(f"未显式声明 {_key}（{_label}），将使用默认值 {_default}")

    # 4) 监控与告警通道（缺失只告警）
    if not os.getenv("METRICS_BEARER_TOKEN", "").strip():
        warnings.append(
            "未设置 METRICS_BEARER_TOKEN：/metrics 会返回 503（fail-closed），Prometheus 抓取不可用"
        )
    if (
        os.getenv("BACKUP_ALERT_WEBHOOK_ENABLED", "false").strip().lower() == "true"
        and not os.getenv("BACKUP_ALERT_WEBHOOK_URL", "").strip()
    ):
        warnings.append(
            "BACKUP_ALERT_WEBHOOK_ENABLED=true 但 BACKUP_ALERT_WEBHOOK_URL 为空：Webhook 告警不会送出"
        )
    if (
        os.getenv("BACKUP_ALERT_EMAIL_ENABLED", "false").strip().lower() == "true"
        and not os.getenv("BACKUP_ALERT_SMTP_HOST", "").strip()
    ):
        warnings.append(
            "BACKUP_ALERT_EMAIL_ENABLED=true 但 BACKUP_ALERT_SMTP_HOST 为空：邮件告警不会送出"
        )
    return warnings


def get_production_config_warnings() -> list[str]:
    """返回最近一次 Settings() 构造收集到的生产配置告警（非生产/未构造时为空）。"""
    return list(_production_config_warnings)


class Settings(BaseSettings):
    """FastAPI应用配置"""

    # 应用基本信息
    APP_NAME: str = "滨发协同系统 API"
    APP_VERSION: str = "2.0.0"
    FASTAPI_DEBUG: bool = os.getenv("FASTAPI_DEBUG", "false").lower() in ("true", "1", "yes")

    # API配置
    API_PREFIX: str = "/api/v1"
    # 生产环境（APP_ENV=production）自动关闭文档端点，防止暴露 API 结构
    DOCS_URL: str | None = None if _is_production_env() else "/api/docs"
    REDOC_URL: str | None = None if _is_production_env() else "/api/redoc"
    OPENAPI_URL: str | None = None if _is_production_env() else "/api/openapi.json"

    # 数据库配置
    # 异步数据库URL - 使用 asyncpg 驱动（性能最优）
    ASYNC_DATABASE_URL: str = os.getenv("ASYNC_DATABASE_URL") or _build_database_uri()

    # 同步数据库URL - 使用 psycopg3 驱动（用于 Alembic 迁移等场景）
    DATABASE_URL: str = os.getenv("DATABASE_URL") or _build_sync_database_uri()

    # 只读副本 URL（可选，用于报表/列表查询的读写分离）
    # 设置 DATABASE_REPLICA_URL 后，get_async_read_db() 将使用此连接
    # 未设置时回退到主库，无读写分离效果
    ASYNC_DATABASE_REPLICA_URL: str = os.getenv("ASYNC_DATABASE_REPLICA_URL", "")

    # Redis 配置（向后兼容：未配置独立实例时使用 REDIS_HOST/PORT/DB）
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT") or "6379")
    REDIS_DB: int = int(os.getenv("REDIS_DB") or "0")
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")
    # Redis Sentinel 高可用配置（可选，生产环境使用）
    # 格式: "host1:port1,host2:port2,host3:port3"
    # 为空时使用单机模式（REDIS_HOST/REDIS_PORT）；非空时通过 Sentinel 发现 master
    REDIS_SENTINEL_HOSTS: str = os.getenv("REDIS_SENTINEL_HOSTS", "")

    # Redis 独立实例拆分（缓存 / ARQ Broker）
    # 推荐生产环境使用独立实例或独立 Redis 数据库，避免单实例混用导致相互影响
    REDIS_CACHE_URL: str = os.getenv("REDIS_CACHE_URL", "")
    REDIS_BROKER_URL: str = os.getenv("REDIS_BROKER_URL", "")
    # ARQ 结果存储沿用 broker 实例（REDIS_BROKER_URL），未配置时使用通用 Redis
    REDIS_RESULT_URL: str = os.getenv("REDIS_RESULT_URL", "")

    # CORS配置 - 从环境变量读取允许的源，默认仅允许本地访问
    # 包含 Nginx 统一入口（端口80）、Python HTTP 服务（端口8000/8080）、
    # 直接访问模式（端口5002）以及 Vue/Vite 前端（端口3000）
    # 生产环境按 filter_cors_origins / _is_production_allowed_origin 过滤明文 HTTP 源
    _raw_cors: str = os.getenv("CORS_ORIGINS", "http://localhost,http://localhost:5002,http://localhost:3000,http://localhost:5173,http://localhost:5174,http://localhost:8000,http://localhost:8080,null")
    BACKEND_CORS_ORIGINS: list[str] = filter_cors_origins(
        _raw_cors, is_production=_is_production_env()
    )

    # 安全配置 - 从环境变量读取，生产环境必须显式设置
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")

    # RSA 密钥路径（RS256 模式必填，HS256 模式忽略）
    JWT_PRIVATE_KEY_PATH: str = os.getenv("JWT_PRIVATE_KEY_PATH", "")
    JWT_PUBLIC_KEY_PATH: str = os.getenv("JWT_PUBLIC_KEY_PATH", "")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    # 刷新令牌有效期（天），默认7天
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))
    # httpOnly JWT Cookie 最大有效期（秒），默认1天，配合 refresh token 续期
    COOKIE_MAX_AGE: int = int(os.getenv("COOKIE_MAX_AGE", 86400))

    # 允许的主机名 - 用于 TrustedHostMiddleware 和 CSRF Origin/Referer 校验
    # 生产环境必须通过 ALLOWED_HOSTS 环境变量显式设置（如 "erp.example.com,erp.example.cn"）
    # 开发环境默认允许所有主机（"*"），生产环境必须限制为具体域名
    ALLOWED_HOSTS: list[str] = [h for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)        # 内网宽松：SECRET_KEY 非空即可（不检查长度/弱密码等）
        if not self.SECRET_KEY:
            raise RuntimeError(
                "SECRET_KEY 必须通过环境变量 SECRET_KEY 或 .env 文件设置"
            )
        _ALLOWED_JWT_ALGORITHMS = {"HS256", "RS256", "ES256"}
        if self.ALGORITHM not in _ALLOWED_JWT_ALGORITHMS:
            raise RuntimeError(
                f"JWT_ALGORITHM 必须为 {_ALLOWED_JWT_ALGORITHMS} 之一，"
                f"当前值 '{self.ALGORITHM}' 不在允许范围内"
            )
        # 结构性参数边界（OPT-12，2026-10-01）：这些值写错只会在运行期以诡异方式
        # 爆炸（REDIS_DB 越界会静默连到别的库；API_PREFIX 少斜杠让全站路由 404），
        # 启动期直接拦截。与上方手写闸门同风格，不用 pydantic validator 双轨。
        if not self.API_PREFIX.startswith('/') or self.API_PREFIX.endswith('/'):
            raise RuntimeError(
                f"API_PREFIX 必须以 '/' 开头且不以 '/' 结尾（如 /api/v1），"
                f"当前值 '{self.API_PREFIX}'"
            )
        if not (1 <= self.REDIS_PORT <= 65535):
            raise RuntimeError(f"REDIS_PORT 越界（1-65535）：{self.REDIS_PORT}")
        if not (0 <= self.REDIS_DB <= 15):
            raise RuntimeError(
                f"REDIS_DB 越界（0-15）：{self.REDIS_DB}。写错库号会静默连到别的库"
                "（测试套件已固定使用 15 号库，生产应为 0）"
            )
        if self.ACCESS_TOKEN_EXPIRE_MINUTES <= 0 or self.REFRESH_TOKEN_EXPIRE_DAYS <= 0:
            raise RuntimeError(
                "令牌时效必须为正数（ACCESS_TOKEN_EXPIRE_MINUTES / REFRESH_TOKEN_EXPIRE_DAYS）"
            )
        # 负库存开关与 DB 兜底约束互斥（P1-2 × P1-6）：该开关只解除【应用层】两道闸门，
        # ck_product_current_stock_nonneg 仍会拒绝扣成负数，结果是从清晰的「库存不足」
        # 退化成 500 IntegrityError。要真正启用必须先手工 DROP 该约束（见 .env.example），
        # 所以在启动期直接拦截，避免带着一个不可能生效的开关上生产。
        if os.getenv("ALLOW_NEGATIVE_STOCK", "").strip().lower() in {"1", "true", "yes", "on"}:
            raise RuntimeError(
                "ALLOW_NEGATIVE_STOCK=true 与数据库约束 ck_product_current_stock_nonneg 互斥："
                "该开关只解除应用层校验，扣成负数仍会被 DB 拒绝（表现为 500 IntegrityError）。"
                "要真正启用负库存，须先手工执行 "
                "ALTER TABLE product DROP CONSTRAINT ck_product_current_stock_nonneg"
                "（不可逆，先评估存量负库存数据）；否则请保持该开关为 false。"
            )
        # 生产环境安全配置强校验：防止运维漏配导致安全控制失效
        _is_production = _is_production_env()
        if not _is_production and not self.ALLOWED_HOSTS:
            # 开发环境未配置 ALLOWED_HOSTS 时默认允许所有主机，便于本地调试
            self.ALLOWED_HOSTS = ["*"]
        if _is_production:
            # FASTAPI_DEBUG 必须为假：为真时 sanitize_error 直接返回 str(error)，
            # 而它被数十处端点用于拼 HTTPException(detail=...)（purchase_plan /
            # production_summary / ocr_import / daily_production 等）→ 内部异常、
            # 路径、SQL 细节会原样返回给客户端。原先生产强校验没有这一条。
            if self.FASTAPI_DEBUG:
                raise RuntimeError(
                    "生产环境禁止 FASTAPI_DEBUG=true：它会让 sanitize_error 原样返回异常文本，"
                    "数十处端点会把内部细节拼进响应体返回给客户端。请置为 false。"
                )
            # SECRET_KEY 必须为高强度密钥（长度 >= 32 字符），防止弱密钥被暴力破解后伪造 JWT
            if len(self.SECRET_KEY) < 32:
                raise RuntimeError(
                    "生产环境 SECRET_KEY 长度不足 32 字符，"
                    "请使用高强度随机密钥（如 openssl rand -hex 32 生成后注入）"
                )
            # ALLOWED_HOSTS 必须显式配置具体域名，禁止为空或使用通配 "*"，
            # 防止 TrustedHost 校验完全失效或被绕过。
            if not self.ALLOWED_HOSTS or "*" in self.ALLOWED_HOSTS:
                raise RuntimeError(
                    "生产环境（APP_ENV=production）必须通过 ALLOWED_HOSTS 设置具体域名，"
                    "如 \"erp.example.com,erp.example.cn\"，禁止为空或使用 \"*\"。"
                )
            # 非对称模式（RS256/ES256）下私钥/公钥路径必须显式配置且文件存在（密钥移出仓库，由部署环境注入）
            if self.ALGORITHM in ("RS256", "ES256"):
                if not self.JWT_PRIVATE_KEY_PATH or not os.path.isfile(self.JWT_PRIVATE_KEY_PATH):
                    raise RuntimeError(
                        f"生产环境 {self.ALGORITHM} 模式要求 JWT_PRIVATE_KEY_PATH 指向真实私钥文件，"
                        f"当前值 '{self.JWT_PRIVATE_KEY_PATH}' 不存在。"
                        f"私钥不得提交到代码仓库，须由部署环境（K8s Secret/环境变量挂载）注入。"
                    )
                if not self.JWT_PUBLIC_KEY_PATH or not os.path.isfile(self.JWT_PUBLIC_KEY_PATH):
                    raise RuntimeError(
                        f"生产环境 {self.ALGORITHM} 模式要求 JWT_PUBLIC_KEY_PATH 指向真实公钥文件，"
                        f"当前值 '{self.JWT_PUBLIC_KEY_PATH}' 不存在。"
                    )
            # 生产环境 CORS 不得包含 null 源（沙箱 iframe 逃逸风险）
            if "null" in self.BACKEND_CORS_ORIGINS:
                raise RuntimeError(
                    "生产环境 CORS_ORIGINS 不得包含 'null' 源（沙箱 iframe 逃逸风险），"
                    "请移除 null 并设置为具体 HTTPS 域名。"
                )
            # 备份/监控配置校验（S3）：致命项直接抛错，其余收集为告警
            # ⚠️ 必须放在上面所有既有闸门之后：tests/test_config.py:31 与
            #    fastapi_app/tests/test_security_and_batch.py:124/180 依赖
            #    「长度不足」「禁止」两条报错先触发。
            _warnings = _validate_production_backup_config()
            _production_config_warnings.clear()
            _production_config_warnings.extend(_warnings)
            for _message in _warnings:
                logger.warning("生产配置告警：%s", _message)

    @property
    def is_production(self) -> bool:
        """生产环境判定（全库统一入口；动态读取以兼容测试 monkeypatch APP_ENV）"""
        return _is_production_env()

    # 对象存储配置（P2-1：static/uploads 迁移至 MinIO/S3）
    # STORAGE_TYPE=local 时保持现有本地文件系统行为；=s3 时上传到对象存储
    STORAGE_TYPE: str = os.getenv("STORAGE_TYPE", "local")
    S3_ENDPOINT: str = os.getenv("S3_ENDPOINT", "")
    S3_BUCKET: str = os.getenv("S3_BUCKET", "erp-uploads")
    S3_ACCESS_KEY: str = os.getenv("S3_ACCESS_KEY", "")
    S3_SECRET_KEY: str = os.getenv("S3_SECRET_KEY", "")
    S3_REGION: str = os.getenv("S3_REGION", "us-east-1")
    # 公开访问地址前缀；为空时返回服务内部代理 URL 或 S3 预签名 URL
    S3_PUBLIC_URL: str = os.getenv("S3_PUBLIC_URL", "")

    # 分页配置
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    def sanitize_error(self, error: Exception) -> str:
        """生产环境下脱敏错误消息，防止泄露数据库/内部信息。

        ⚠️ 这里的判定**刻意不用** _is_production_env()：那个入口判的是"是不是生产"，
        而本函数要判的是"是不是**显式**开发环境"。方向必须是 fail-safe ——
        APP_ENV 未设置、写错（prod/production/dev 之外的任意值）时一律**脱敏**。
        （曾试图统一成 `not _is_production_env()`，那会让未设置 APP_ENV 的环境
        返回异常原文，被 tests/test_error_sanitization.py 当场拦下。）
        """
        env = os.getenv("APP_ENV", "").strip().lower()
        if self.FASTAPI_DEBUG or env in ("development", "dev"):
            return str(error)
        return "服务器内部错误，请联系管理员"

    def sanitize_business_error(self, error: Exception) -> str:
        """业务校验错误（如 ValueError）可返回具体信息"""
        if isinstance(error, ValueError):
            return str(error)
        return self.sanitize_error(error)

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")


settings = Settings()
