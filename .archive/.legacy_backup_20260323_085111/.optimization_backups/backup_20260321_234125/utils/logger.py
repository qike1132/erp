"""
日志系统配置
提供结构化日志记录功能
"""
import logging
import os
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler


def setup_logging(app):
    """
    配置日志系统

    Args:
        app: Flask应用实例
    """
    # 创建日志目录
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)

    # 设置日志级别
    log_level = logging.DEBUG if app.debug else logging.INFO

    # 配置根日志记录器
    app.logger.setLevel(log_level)

    # 1. 文件日志处理器 - 按大小轮转
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'erp.log'),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=10,
        encoding='utf-8'
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    ))

    # 2. 错误日志处理器 - 单独记录错误
    error_handler = RotatingFileHandler(
        os.path.join(log_dir, 'error.log'),
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s [%(pathname)s:%(lineno)d]:\n%(message)s\n'
    ))

    # 3. 访问日志处理器 - 按天轮转
    access_handler = TimedRotatingFileHandler(
        os.path.join(log_dir, 'access.log'),
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    access_handler.setLevel(logging.INFO)
    access_handler.setFormatter(logging.Formatter(
        '[%(asctime)s] %(message)s'
    ))

    # 添加处理器
    app.logger.addHandler(file_handler)
    app.logger.addHandler(error_handler)

    # 返回访问日志记录器
    access_logger = logging.getLogger('access')
    access_logger.addHandler(access_handler)
    access_logger.setLevel(logging.INFO)

    return app.logger, access_logger


class Logger:
    """日志工具类"""

    def __init__(self, app=None):
        self.app = app
        self.logger = None
        self.access_logger = None

        if app:
            self.init_app(app)

    def init_app(self, app):
        """初始化日志"""
        self.logger, self.access_logger = setup_logging(app)

    def info(self, message, *args, **kwargs):
        """记录信息日志"""
        if self.logger:
            self.logger.info(message, *args, **kwargs)

    def error(self, message, *args, **kwargs):
        """记录错误日志"""
        if self.logger:
            self.logger.error(message, *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        """记录警告日志"""
        if self.logger:
            self.logger.warning(message, *args, **kwargs)

    def debug(self, message, *args, **kwargs):
        """记录调试日志"""
        if self.logger:
            self.logger.debug(message, *args, **kwargs)

    def access(self, request, response):
        """记录访问日志"""
        if self.access_logger:
            self.access_logger.info(
                f'{request.remote_addr} - "{request.method} {request.path}" '
                f'{response.status_code} - {response.content_length or 0} bytes'
            )


# 全局日志实例
logger = Logger()


def log_request(response):
    """请求日志装饰器"""
    from flask import request
    logger.access(request, response)
    return response
