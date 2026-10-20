"""P1-26：来料登记列表 keyword 跨字段搜索（采购订单号 / 供应商 / 物料名称）。

移动端搜索框此前是死 UI（keyword 从未进入请求），后端也没有 keyword 参数。
本文件用 compile 级断言锁定「keyword 被转成 SQL 条件」且通配符被转义，
不连接数据库；另验证端点把 keyword 透传给服务层。
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from fastapi_app.api.v1.endpoints import material_registration as ep
from fastapi_app.services.material_registration._queries import (
    _build_registration_keyword_condition,
    get_registrations,
)
from fastapi_app.shared_models import MaterialRegistration


def _compile_condition(keyword: str) -> str:
    stmt = select(MaterialRegistration.id).where(_build_registration_keyword_condition(keyword))
    # named paramstyle：literal_binds 下 pyformat 会把字面量里的 % 转义成 %%，
    # 断言需面对转义噪声；named 保留原样，便于逐字验证转义结果。
    dialect = postgresql.dialect(paramstyle='named')
    return str(stmt.compile(dialect=dialect, compile_kwargs={'literal_binds': True}))


def test_keyword_matches_order_no_supplier_and_material_name() -> None:
    sql = _compile_condition('棉')
    assert "purchase_order_no ILIKE '%棉%'" in sql
    assert "supplier_name ILIKE '%棉%'" in sql
    # 物料明细用 EXISTS 子查询匹配 material_name
    assert 'material_name ILIKE' in sql
    assert 'EXISTS' in sql.upper()


def test_keyword_escapes_like_wildcards() -> None:
    # 用编译参数断言（literal_binds 会再转义 SQL 里的反斜杠，噪声大）：
    # 首尾包裹的 % 保留模糊匹配语义，用户输入的 % / _ 必须被反斜杠转义
    stmt = select(MaterialRegistration.id).where(_build_registration_keyword_condition('100%_x'))
    params = {v for v in stmt.compile(dialect=postgresql.dialect()).params.values() if isinstance(v, str)}
    assert params == {r'%100\%\_x%'}


class _RecordingDB:
    """记录 execute 收到的语句，不连数据库。"""

    def __init__(self) -> None:
        self.statements: list = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        result = MagicMock()
        result.scalar.return_value = 0
        result.scalars.return_value.all.return_value = []
        return result


async def test_get_registrations_applies_keyword_to_count_and_data_queries() -> None:
    db = _RecordingDB()
    # 绕过 @cache_result（functools.wraps 保留 __wrapped__），只验查询条件组装
    await inspect.unwrap(get_registrations)(db, keyword='棉')

    assert len(db.statements) == 2  # count + data
    for stmt in db.statements:
        sql = str(stmt.compile(
            dialect=postgresql.dialect(paramstyle='named'),
            compile_kwargs={'literal_binds': True},
        ))
        assert "purchase_order_no ILIKE '%棉%'" in sql
        assert "supplier_name ILIKE '%棉%'" in sql
        assert 'material_name ILIKE' in sql


async def test_endpoint_forwards_keyword(monkeypatch) -> None:
    svc = AsyncMock(return_value={'registrations': [], 'total': 0, 'pages': 0, 'current_page': 1})
    monkeypatch.setattr(ep.mr_service, 'get_registrations', svc)

    await ep.list_registrations(
        page=2, per_page=50, status='', order_no='', supplier='',
        customer_name='', material_category='', start_date='', end_date='',
        exclude_completed=False, keyword='PP棉', user=SimpleNamespace(), db=AsyncMock(),
    )

    svc.assert_awaited_once()
    args, kwargs = svc.await_args
    assert kwargs.get('keyword') == 'PP棉'
    assert args[1] == 2  # page 仍按位置透传
    assert args[2] == 50  # per_page 仍按位置透传
