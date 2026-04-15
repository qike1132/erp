
import logging
import sys
from pathlib import Path
from datetime import datetime


def setup_logging():
    """配置日志系统（幂等：重复调用不会累积处理器）"""
    log_format = (
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    date_format = "%Y-%m-%d %H:%M:%S"
    
    # 创建日志目录
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # 幂等处理：移除旧处理器，避免热重载后日志重复输出
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(log_format, date_format)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # 文件处理器
    log_file = log_dir / f"fastapi_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(log_format, date_format)
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)
    
    # 设置特定模块的日志级别
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    
    return root_logger


logger = setup_logging()
