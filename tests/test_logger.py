import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from flask import Flask
    from app import create_app
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
    create_app = None

try:
    from utils.logger import logger, setup_logging
except ImportError:
    logger = None
    setup_logging = None


@pytest.mark.skipif(not HAS_FLASK, reason="Flask dependencies not available")
def test_logger_initialization():
    app = create_app('testing')
    app.config['WTF_CSRF_ENABLED'] = False
    
    with app.app_context():
        # verify loggers are set
        assert logger.logger is not None
        assert logger.access_logger is not None
        
        # Test logging methods
        logger.info("Test info")
        logger.error("Test error")
        logger.warning("Test warning")
        logger.debug("Test debug")
