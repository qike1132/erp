"""采购计划列表与 FIFO 分配的接线回归（2026-11-16 上线前审计 #2 / #3）

两个缺陷都在「服务层算出来了、端点和查询没接住」的位置：

#2 `/plans/list` 的 `selectinload(...).load_only(...)` 漏掉 `product_id` / `plan_date`，
   而 fifo_allocation 的 `_fifo_query_with_timeout` 要读这两列 → 异步会话懒加载 →
   MissingGreenlet → 被宽 except 转成 FIFO_ALLOCATION_UNAVAILABLE → 降级空映射
   → 所有计划 total_shipped 恒为 0。
#3 端点构造 `PlanListResponse` 时没把 `fifo_degraded` 传进去，字段存在却永远是 False，
   前端因此无法区分「真的一件没出」和「FIFO 查询挂了」。
"""
import asyncio
from unittest.mock import AsyncMock, patch

from fastapi_app.services import purchase_plan_queries as plan_queries

#: FIFO 读路径（fifo_allocation._fifo_query_with_timeout）实际读到的明细列。
#: 这里是**手写字面量**而不是从生产代码推导，否则被测代码少加载一列时断言跟着变绿。
FIFO_REQUIRED_DETAIL_COLUMNS = {
    'id',
    'plan_id',
    'quantity',
    'product_name',
    'product_id',
    'plan_date',
}


class _EmptyScalars:
    """select() 结果的最小替身：scalars().all() → []。"""

    def scalars(self):
        return self

    def all(self):
        return []


class _CapturingDB:
    """只记录被执行的语句，不连任何数据库。"""

    def __init__(self):
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _EmptyScalars()


async def _noop_fifo_map_safe(db, details, customer_name_map=None, plan_month=''):
    """替身：FIFO 查询本身不在本用例范围内（它要 Redis/出货表）。"""
    return {}, False


def _load_only_column_names(statement) -> set[str]:
    """从 selectinload(...).load_only(...) 选项里取出被显式加载的列名。

    只读 SQLAlchemy 的 options 结构，不执行 SQL：本用例的目的是「列清单里有没有
    这两列」，而真正的 MissingGreenlet 要异步会话才复现（见文件头 #2 说明）。
    """
    names: set[str] = set()
    for option in statement._with_options:
        for element in option.context:
            # 通配项（column:*）是 load_only 自动加的「其余全 defer」，不是具体列
            if getattr(element, 'is_token_strategy', False):
                continue
            key = getattr(element.path[-1], 'key', None)
            if key:
                names.add(key)
    return names


async def _capture_plan_list_statement():
    db = _CapturingDB()
    with patch.object(plan_queries, '_get_shipped_fifo_map_safe', _noop_fifo_map_safe):
        await plan_queries.get_plan_list(db, 2026, 9)
    return db.statements[0]


class TestPlanListLoadOnlyCoversFifoColumns:
    async def test_load_only_includes_every_column_fifo_reads(self):
        # 拦的错：漏掉 product_id / plan_date → 下游 MissingGreenlet → 列表全 0
        statement = await _capture_plan_list_statement()

        loaded = _load_only_column_names(statement)

        missing = FIFO_REQUIRED_DETAIL_COLUMNS - loaded
        assert missing == set(), f'load_only 漏了 FIFO 要读的列: {sorted(missing)}'

    async def test_load_only_does_not_shrink_to_the_list_view_only_columns(self):
        # 拦的错：「列表看起来只用得到 4 列」式裁剪回归（本次缺陷的原始写法）
        statement = await _capture_plan_list_statement()

        loaded = _load_only_column_names(statement)

        assert {'id', 'quantity', 'plan_id', 'product_name'} <= loaded
        assert 'product_id' in loaded
        assert 'plan_date' in loaded


class TestPlanListFifoDegradedPropagated:
    async def test_endpoint_returns_fifo_degraded_true_when_service_degrades(self, client, mock_db):
        # 拦的错：端点丢掉 fifo_degraded，降级时响应仍是 fifo_degraded=False，
        # 前端把「一件都没出」当真值渲染
        service_result = {'plans': [], 'total': 0, 'fifo_degraded': True}
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.get_plan_list = AsyncMock(return_value=service_result)
            response = await client.get('/api/v1/plans/list', params={'year': 2026, 'month': 9})

        assert response.status_code == 200
        assert response.json()['fifo_degraded'] is True

    async def test_endpoint_returns_fifo_degraded_false_when_service_is_healthy(self, client, mock_db):
        # 反向断言：别把标记写成恒 True，否则警示条会变成常态噪音被忽略
        service_result = {'plans': [], 'total': 0, 'fifo_degraded': False}
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.get_plan_list = AsyncMock(return_value=service_result)
            response = await client.get('/api/v1/plans/list', params={'year': 2026, 'month': 9})

        assert response.status_code == 200
        assert response.json()['fifo_degraded'] is False


def test_statement_capture_is_awaitable_from_sync_context():
    """守住 _capture_plan_list_statement 的调用方式（防止有人把它改成协程却忘了 await）。"""
    statement = asyncio.run(_capture_plan_list_statement())
    assert _load_only_column_names(statement)
