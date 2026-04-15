import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from utils.logger import logger, setup_logging

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
