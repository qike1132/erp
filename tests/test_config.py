"""
config.py 单元测试

覆盖：Settings 默认值、ALLOWED_HOSTS 生产环境检查、分页配置
"""
import os
from unittest.mock import patch

import pytest

from fastapi_app.core.config import Settings


class TestSettingsDefaults:
    def test_app_name(self):
        s = Settings()
        assert s.APP_NAME is not None
        assert len(s.APP_NAME) > 0

    def test_default_page_size(self):
        s = Settings()
        assert s.DEFAULT_PAGE_SIZE == 20
        assert s.MAX_PAGE_SIZE == 100

    def test_allowed_hosts_default(self):
        s = Settings()
        assert isinstance(s.ALLOWED_HOSTS, list)


class TestAllowedHostsProduction:
    def test_wildcard_raises_in_production(self):
        """生产环境 ALLOWED_HOSTS='*' 必须报错"""
        with patch.dict(os.environ, {"APP_ENV": "production"}), pytest.raises(RuntimeError, match="禁止"):
            Settings(ALLOWED_HOSTS=["*"])

    def test_specific_hosts_ok_in_production(self):
        """生产环境指定具体域名不报错"""
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            s = Settings(ALLOWED_HOSTS=["erp.example.com"])
            assert s.ALLOWED_HOSTS == ["erp.example.com"]

    def test_wildcard_ok_in_dev(self):
        """开发环境 ALLOWED_HOSTS='*' 不报错"""
        with patch.dict(os.environ, {"APP_ENV": "development"}, clear=False):
            s = Settings(ALLOWED_HOSTS=["*"])
            assert s.ALLOWED_HOSTS == ["*"]


class TestDatabaseUrl:
    def test_database_url_set(self):
        s = Settings()
        assert s.DATABASE_URL is not None or s.ASYNC_DATABASE_URL is not None
