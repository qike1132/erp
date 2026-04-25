"""base_search_service 单元测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi_app.services.base_search_service import BaseSearchService


class _MockSearchService(BaseSearchService):
    """测试用的搜索服务实现"""
    def get_model_class(self):
        return MagicMock(__name__='MockModel')
    def get_search_fields(self):
        return ['name', 'code']
    def get_result_serializer(self):
        return lambda x: {'id': x.id, 'name': getattr(x, 'name', '')}


class TestBaseSearchService:
    def test_get_model_class(self):
        svc = _MockSearchService()
        assert svc.get_model_class().__name__ == 'MockModel'

    def test_get_search_fields(self):
        svc = _MockSearchService()
        fields = svc.get_search_fields()
        assert fields == ['name', 'code']

    def test_get_result_serializer(self):
        svc = _MockSearchService()
        serializer = svc.get_result_serializer()
        m = MagicMock(id=1, name='Test')
        result = serializer(m)
        assert result['id'] == 1

    def test_get_cache_key(self):
        svc = _MockSearchService(cache_prefix='test')
        key = svc._get_cache_key('abc', 10, None)
        assert 'test:search:' in key
