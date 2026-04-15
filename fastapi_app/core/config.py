import os
from dotenv import load_dotenv

# 在类定义之前加载 .env，确保 os.getenv("DB_PASSWORD") 等能读到值
# pydantic_settings 的 env_file 仅为其自身字段服务，不会注入 os.environ
load_dotenv(override=False)

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


def _build_database_uri() -> str:
    """与 Flask 的 get_database_uri() 使用相同逻辑构建数据库 URI"""
    db_type = os.getenv("DB_TYPE", "mysql")
    if db_type == "mysql":
        db_host = os.getenv("DB_HOST", "localhost")
        db_port = os.getenv("DB_PORT", "3306")
        db_user = os.getenv("DB_USER", "root")
        db_password = os.getenv("DB_PASSWORD", "")
        db_name = os.getenv("DB_NAME", "erp_system")
        return f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}?charset=utf8mb4"
    # sqlite fallback
    return "sqlite:///:memory:"


class Settings(BaseSettings):
    """FastAPI应用配置"""

    # 应用基本信息
    APP_NAME: str = "滨发协同系统 API"
    APP_VERSION: str = "2.0.0"
    FASTAPI_DEBUG: bool = os.getenv("FASTAPI_DEBUG", "false").lower() in ("true", "1", "yes")

    # API配置
    API_PREFIX: str = "/api/v1"
    DOCS_URL: str = "/api/docs"
    REDOC_URL: str = "/api/redoc"
    OPENAPI_URL: str = "/api/openapi.json"

    # 数据库配置 - 与 Flask 共享相同的构建逻辑
    # 优先使用 DATABASE_URL 环境变量，否则从 DB_* 变量构建
    DATABASE_URL: str = os.getenv("DATABASE_URL") or _build_database_uri()

    # 异步数据库URL - 用于 FastAPI 主要业务逻辑
    ASYNC_DATABASE_URL: str = os.getenv(
        "ASYNC_DATABASE_URL",
        (os.getenv("DATABASE_URL") or _build_database_uri()).replace(
            "mysql+pymysql", "mysql+aiomysql"
        )
    )

    # Redis配置
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 安全验证已在上方 SECRET_KEY 检查中完成
        if not self.REDIS_PASSWORD and os.getenv("FLASK_ENV") == "production":
            import warnings
            warnings.warn(
                "REDIS_PASSWORD 未设置，生产环境建议启用 Redis 认证",
                UserWarning,
                stacklevel=2,
            )

    # Celery配置
    CELERY_BROKER_URL: str = os.getenv(
        "CELERY_BROKER_URL",
        f"redis://:{os.getenv('REDIS_PASSWORD', '')}@{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', '6379')}/1"
    )
    CELERY_RESULT_BACKEND: str = os.getenv(
        "CELERY_RESULT_BACKEND",
        f"redis://:{os.getenv('REDIS_PASSWORD', '')}@{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', '6379')}/2"
    )

    # CORS配置 - 从环境变量读取允许的源，默认仅允许本地访问
    # 包含 Nginx 统一入口（端口80）以及直接访问模式（端口5002/5003）
    BACKEND_CORS_ORIGINS: List[str] = os.getenv("CORS_ORIGINS", "http://localhost,http://localhost:5003,http://localhost:5002").split(",")

    # 安全配置 - 从环境变量读取，生产环境必须显式设置
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.SECRET_KEY:
            raise RuntimeError(
                "SECRET_KEY 必须通过环境变量 SECRET_KEY 或 .env 文件设置，"
                "不允许使用空值或默认值启动"
            )
        if self.SECRET_KEY in ("CHANGE-ME-IN-PRODUCTION", "dev-key-for-local-only"):
            raise RuntimeError(
                f"SECRET_KEY 不能使用不安全的默认值 '{self.SECRET_KEY}'，"
                "请生成新的密钥: python -c \"import secrets; print(secrets.token_hex(32))\""
            )

    # 分页配置
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")


settings = Settings()
