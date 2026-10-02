"""case_service 单元测试

2026-10-02 第二轮审计：本文件原先按**重写前**的 API 写（mock 的是 `Product`
并走 `mr.unique()`），而重写后 `search_cases` 直接查 `Case` 表与会话的 `scalars()`
—— 于是 `list(MagicMock())` 得到空表、断言恒假，**长期红灯反而掩盖了真实回归**。
现按现行契约重写，并加一条**禁止碰懒加载关系**的守卫（本轮 `/cases/search` 500 的根因）。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services.case_service import search_cases


def _db_returning(rows):
    """假 AsyncSession：search_cases 的取数路径是 execute → scalars() → all()。"""
    mr = MagicMock()
    mr.scalars.return_value.all.return_value = rows
    db = AsyncMock()
    db.execute = AsyncMock(return_value=mr)
    return db


class _NoLazyRelation:
    """Case 行替身：**一旦访问 product 关系或 sync_* 属性就断言失败**。

    async 会话里访问未加载的 relationship 会抛 MissingGreenlet（→ 500）。
    把这条隐含约束变成显式断言，任何回归立刻变红。
    """

    def __init__(self, **kw):
        self.__dict__.update(kw)

    @property
    def product(self):
        raise AssertionError('不得访问 case.product（async 下懒加载会 MissingGreenlet → 500）')

    @property
    def sync_name(self):
        raise AssertionError('不得使用 sync_name（内部会懒加载 product）')

    @property
    def sync_barcode(self):
        raise AssertionError('不得使用 sync_barcode（内部会懒加载 product）')


class TestCaseService:
    @pytest.mark.asyncio
    async def test_search_cases_empty_query(self):
        """无关键词：返回 SKU 基本字段（不碰懒加载关系）。"""
        row = _NoLazyRelation(id=20006, name='鲨鱼', barcode='', current_stock=100, parent_id=None)
        result = await search_cases(_db_returning([row]), query='')
        assert len(result) == 1
        assert result[0] == {
            'id': 20006, 'name': '鲨鱼', 'barcode': '',
            'current_stock': 100, 'parent_id': None,
        }

    @pytest.mark.asyncio
    async def test_search_cases_with_query(self):
        row = _NoLazyRelation(id=20007, name='鲨鱼帽子', barcode='X1', current_stock=5, parent_id=20006)
        result = await search_cases(_db_returning([row]), query='鲨鱼')
        assert len(result) == 1
        assert result[0]['name'] == '鲨鱼帽子'
        assert result[0]['parent_id'] == 20006

    @pytest.mark.asyncio
    async def test_search_cases_null_fields_default_to_empty(self):
        """name/barcode 为空时返回空串、库存为 0 —— 不是 None。"""
        row = _NoLazyRelation(id=1, name=None, barcode=None, current_stock=None, parent_id=None)
        result = await search_cases(_db_returning([row]), query='')
        assert result[0]['name'] == ''
        assert result[0]['barcode'] == ''
        assert result[0]['current_stock'] == 0
