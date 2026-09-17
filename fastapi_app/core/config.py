import logging
import os
from urllib.parse import quote_plus

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
    # 生产环境自动过滤非 HTTPS 源（localhost/127.0.0.1/null 除外，用于本地开发和独立预览）
    _raw_cors: str = os.getenv("CORS_ORIGINS", "http://localhost,http://localhost:5002,http://localhost:3000,http://localhost:5173,http://localhost:5174,http://localhost:8000,http://localhost:8080,null")
    BACKEND_CORS_ORIGINS: list[str] = [
        origin.strip() for origin in _raw_cors.split(",")
        if origin.strip()
        and (
            not _is_production_env()
            or origin.strip().startswith("https://")
            or origin.strip().startswith("http://localhost")
        )
    ]

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
        # 生产环境安全配置强校验：防止运维漏配导致安全控制失效
        _is_production = _is_production_env()
        if not _is_production and not self.ALLOWED_HOSTS:
            # 开发环境未配置 ALLOWED_HOSTS 时默认允许所有主机，便于本地调试
            self.ALLOWED_HOSTS = ["*"]
        if _is_production:
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
        """生产环境下脱敏错误消息，防止泄露数据库/内部信息"""
        if self.FASTAPI_DEBUG or os.getenv("APP_ENV", "") == "development":
            return str(error)
        return "服务器内部错误，请联系管理员"

    def sanitize_business_error(self, error: Exception) -> str:
        """业务校验错误（如 ValueError）可返回具体信息"""
        if isinstance(error, ValueError):
            return str(error)
        return self.sanitize_error(error)

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")


settings = Settings()
