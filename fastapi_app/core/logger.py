"""
结构化日志配置 - 使用 structlog

提供 JSON 格式日志输出，适配 Loki/Promtail 日志聚合。
支持动态日志级别调整、correlation ID 追踪。
"""

import logging
import sys
from datetime import UTC, datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import structlog
from structlog.processors import JSONRenderer, TimeStamper


def setup_logging():
    """配置结构化日志系统（幂等：重复调用不会累积处理器）"""

    # 创建日志目录
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # 配置 structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,  # 合并 contextvars 中的上下文
            structlog.stdlib.filter_by_level,  # 按日志级别过滤
            structlog.stdlib.add_logger_name,  # 添加 logger 名称
            structlog.stdlib.add_log_level,  # 添加日志级别
            structlog.stdlib.PositionalArgumentsFormatter(),  # 处理位置参数
            TimeStamper(fmt="iso"),  # ISO 8601 时间戳
            structlog.processors.StackInfoRenderer(),  # 堆栈信息
            structlog.processors.format_exc_info,  # 异常信息
            structlog.processors.UnicodeDecoder(),  # Unicode 解码
            # 根据环境选择渲染器
            _get_renderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # 配置标准库 logging
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # 幂等处理：移除旧处理器
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root_logger.addHandler(console_handler)

    # 文件处理器（JSON 格式，按天轮转，保留 14 天）
    # 为什么是 14 天（S2 可观测性）：排障与复盘需要覆盖「上周同一时间」的对照窗口；
    # 原值 3 天使得跨周末的事故（周五发生、周一发现）已经无日志可查。
    log_file = log_dir / f"fastapi_{datetime.now(UTC).strftime('%Y%m%d')}.log"
    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        backupCount=14,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(message)s"))  # structlog 已格式化
    root_logger.addHandler(file_handler)

    # 设置特定模块的日志级别
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

    return root_logger


def _get_renderer():
    """根据环境选择日志渲染器。

    用 config._is_production_env() 这个**全库统一入口**判定，不要自己判等 APP_ENV：
    它接受 prod/production 并容忍大小写与空白，而 `== "production"` 会把 APP_ENV=prod、
    或本仓库已记录过的 NSSM AppEnvironmentExtra 单元素错配（APP_ENV 里混进其它键）判成
    "非生产" → 生产落到带颜色的 ConsoleRenderer（非 JSON），Loki/Promtail 解析与告警受影响。
    """
    from fastapi_app.core.config import _is_production_env
    if _is_production_env():
        return JSONRenderer(ensure_ascii=False)
    return structlog.dev.ConsoleRenderer(colors=True)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """获取结构化 logger"""
    return structlog.get_logger(name)


# TODO(P3): 副作用导入 - setup_logging() 在模块导入时自动执行，属于隐式副作用。
# 理想方案是在 main.py lifespan 中显式调用 setup_logging()，但当前许多模块依赖
# `from fastapi_app.core.logger import logger` 时日志系统已初始化，直接移除会
# 导致日志未配置。保留自动调用以保证兼容性，后续重构应在 main.py 启动入口
# 先调用 setup_logging()，再导入其他业务模块。
setup_logging()

# 默认 logger
logger = get_logger("fastapi_app")
