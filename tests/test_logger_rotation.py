"""H3：多 worker 共用日志文件时，进程内午夜轮转会产生竞态；改由外部 copytruncate。"""
import logging
from logging.handlers import TimedRotatingFileHandler


def test_logger_uses_plain_file_handler(tmp_path, monkeypatch):
    from fastapi_app.core import logger

    monkeypatch.setattr(logger, "Path", lambda _p: tmp_path)
    logger.setup_logging()

    root = logging.getLogger()
    try:
        assert any(isinstance(h, logging.FileHandler) for h in root.handlers)
        assert not any(
            isinstance(h, TimedRotatingFileHandler) for h in root.handlers
        ), "多 worker 下不得在进程内做午夜轮转，应交给 utils.log_rotation"
    finally:
        for handler in list(root.handlers):
            if isinstance(handler, logging.FileHandler):
                root.removeHandler(handler)
                handler.close()
