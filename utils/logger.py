"""
日志系统配置
提供结构化日志记录功能
"""
import contextvars
import logging
import os
import shutil
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

# 使用 contextvars 存储 trace_id
trace_id_var = contextvars.ContextVar('trace_id', default='system')


class WindowsSafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    """Windows 安全的按时间轮转日志处理器

    解决 Windows 上 os.rename 因文件被其他线程/进程占用而抛出
    PermissionError [WinError 32] 的问题。
    当 rename 失败时，退化为 copy + truncate 方式完成轮转。
    """

    def rotate(self, source, dest):
        try:
            os.rename(source, dest)
        except PermissionError:
            # Windows: 文件被其他线程/进程占用，rename 失败
            # 退化为 copy + truncate：将内容复制到备份文件，再清空原文件
            shutil.copy2(source, dest)
            with open(source, 'w', encoding=self.encoding or 'utf-8'):
                pass  # 截断原文件为空

class RequestFormatter(logging.Formatter):
    """自定义日志格式化器，注入 trace_id"""
    def format(self, record):
        record.trace_id = trace_id_var.get()
        return super().format(record)

def setup_logging(app=None):
    """
    配置日志系统

    Args:
        debug: 是否开启调试模式
    """
    debug = app if isinstance(app, bool) else (getattr(app, 'debug', False) if app else False)

    # 创建日志目录
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)

    # 设置日志级别
    log_level = logging.DEBUG if debug else logging.INFO

    # 配置根日志记录器
    target_logger = logging.getLogger()
    target_logger.setLevel(log_level)

    # 1. 文件日志处理器 - 按大小轮转
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'erp.log'),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=10,
        encoding='utf-8'
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(RequestFormatter(
        '[%(asctime)s] [%(levelname)s] [%(trace_id)s] in %(module)s: %(message)s'
    ))

    # 2. 错误日志处理器 - 单独记录错误
    error_handler = RotatingFileHandler(
        os.path.join(log_dir, 'error.log'),
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(RequestFormatter(
        '[%(asctime)s] [%(levelname)s] [%(trace_id)s] in %(module)s [%(pathname)s:%(lineno)d]:\n%(message)s\n'
    ))

    # 3. 访问日志处理器 - 按天轮转（Windows 安全版本）
    access_handler = WindowsSafeTimedRotatingFileHandler(
        os.path.join(log_dir, 'access.log'),
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    access_handler.setLevel(logging.INFO)
    access_handler.setFormatter(RequestFormatter(
        '[%(asctime)s] [%(trace_id)s] %(message)s'
    ))

    # 添加处理器
    target_logger.addHandler(file_handler)
    target_logger.addHandler(error_handler)

    # 返回访问日志记录器
    access_logger = logging.getLogger('access')
    access_logger.addHandler(access_handler)
    access_logger.setLevel(logging.INFO)

    return target_logger, access_logger


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
            remote_addr = getattr(request, 'client_host', '127.0.0.1')
            method = getattr(request, 'method', 'GET')
            path = getattr(request, 'path', '/')
            status_code = getattr(response, 'status_code', 200)
            content_length = getattr(response, 'content_length', 0) or 0
            self.access_logger.info(
                f'{remote_addr} - "{method} {path}" '
                f'{status_code} - {content_length} bytes'
            )


# 全局日志实例
logger = Logger()


def log_request(response):
    """请求日志装饰器 (FastAPI 兼容版本)"""
    # 在 FastAPI 中，请求日志由中间件处理，此装饰器保留为兼容
    return response
