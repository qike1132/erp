"""
日志模块测试 — 纯 FastAPI 版

验证日志系统在无 Flask 依赖下正常工作。
"""


def test_logger_import():
    """测试 logger 模块可正常导入"""
    from utils.logger import logger

    assert logger is not None
    assert hasattr(logger, "info")
    assert hasattr(logger, "error")
    assert hasattr(logger, "warning")
    assert hasattr(logger, "debug")


def test_logger_basic_methods(caplog):
    """测试日志记录方法"""
    from utils.logger import logger, setup_logging

    # 初始化：setup_logging 设置 root logger，然后绑定到 logger 实例
    root_logger, _ = setup_logging()
    logger.logger = root_logger

    with caplog.at_level("INFO"):
        logger.info("Test info message")
        logger.warning("Test warning message")
        logger.error("Test error message")

    log_text = caplog.text
    assert "Test info message" in log_text
    assert "Test warning message" in log_text
    assert "Test error message" in log_text


def test_setup_logging():
    """测试日志初始化函数"""
    from utils.logger import setup_logging

    # 不应抛出异常
    setup_logging()
