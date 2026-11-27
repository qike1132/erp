"""D-H2 回归：三条订单导入入口必须写 ``OrderItem`` 并生成外发工序（湖北页可见）。

## 缺陷（审计 2026-11-27，独立复核 CONFIRMED）

三个导入实现只写 ``Order`` + ``InventoryLog``：

- ARQ 端点 ``/tasks/import-orders`` → ``batch_tasks.batch_import_orders_task``
- 综合导入的「订单管理」Sheet → ``batch_import_core.import_orders_from_data``
- 单 Sheet 端点 ``/batch/import-orders`` → ``batch_import_service.import_orders_service``

三条都**不写 OrderItem**、也不调 ``auto_generate_for_order``。而湖北订单页/外发进度页
的唯一入选条件是 ``Order.items.any(OrderItem.product.has(Product.factory == factory))``
（``services/order/beile.py:59-68``，无 ``Order.product_id`` 回退）→ 导入的湖北订单在
湖北侧完全不可见（确认流程 404、不带出外发工序）；PC 订单列表按 ``Order.product_id``
照常显示 → 「下单了但湖北看不到」。

## 本文件锁什么

对**每个导入入口**导入一行含湖北工厂 SKU 的数据，断言：

1. 建出的订单有且仅有一条 SKU 级 ``OrderItem``（产品、数量一致）；
2. ``auto_generate_for_order`` 按 SKU 预设生成了外发工序实例（``order_item_id`` 指向
   第 1 条明细）；
3. 用湖北订单页的**权威查询构造器** ``_build_beile_unified_query`` 能选中该订单。

Red（修复前）：三个用例在断言 1 即失败（无明细）。
"""
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

import fastapi_app.tasks.batch_tasks as bt
from fastapi_app.services import batch_import_core as bic
from fastapi_app.services import batch_import_service as bis
from fastapi_app.services.order.beile import _build_beile_unified_query
from fastapi_app.shared_models import (
    Customer,
    Order,
    OrderItem,
    OrderOutsourceProcess,
    OutsourceProcessType,
    Product,
)

_HUBEI = '湖北'
_PROCESS = '电绣'
_QTY = 7


async def _seed(db, suffix: str) -> tuple[str, Product]:
    """一个湖北工厂 SKU + 一条启用预设 + 客户主数据（均为该用例独有，避开幂等键相撞）。"""
    customer_name = f'导入湖北客户{suffix}'
    product = Product(
        name=f'导入湖北SKU{suffix}', barcode=f'HB-DH2-{suffix}',
        factory=_HUBEI, current_stock=0, initial_stock=0,
    )
    db.add(Customer(name=customer_name))
    db.add(product)
    await db.flush()
    db.add(OutsourceProcessType(
        product_id=product.id, process_type=_PROCESS, sort_order=1, is_active=True,
    ))
    await db.flush()
    return customer_name, product


async def _assert_created(db, order_no: str, product: Product) -> None:
    order = (await db.execute(
        select(Order).where(Order.order_no == order_no)
    )).scalar_one()

    items = (await db.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).scalars().all()
    assert len(items) == 1, (
        f'导入订单 {order_no} 必须恰好一条 SKU 明细，实际 {len(items)} 条 —— '
        '缺明细会让它在湖北页/外发页完全不可见（D-H2）'
    )
    assert items[0].product_id == product.id
    assert items[0].quantity == _QTY

    processes = (await db.execute(
        select(OrderOutsourceProcess).where(OrderOutsourceProcess.order_id == order.id)
    )).scalars().all()
    assert [(p.order_item_id, p.product_id, p.process_type) for p in processes] == [
        (items[0].id, product.id, _PROCESS),
    ], f'导入订单 {order_no} 未按 SKU 预设生成外发工序: {processes}'

    # 湖北订单页/外发进度页的真实入选条件：Order.items.any(product.factory == 湖北)
    # （构造器返回的已经是 UNION ALL 子查询）
    hubei_page = _build_beile_unified_query(
        None, None, _HUBEI, include_stockins=False)
    visible_order_nos = (await db.execute(
        select(hubei_page.c.order_no)
    )).scalars().all()
    assert order_no in visible_order_nos, (
        f'导入订单 {order_no} 未被湖北页查询选中：湖北侧将「看不到这笔订单」'
    )


def _noop(*_args, **_kwargs) -> None:
    return None


def _isolate_post_commit_hooks(monkeypatch) -> None:
    """导入骨架只管登记提交后钩子；用例不执行真实缓存失效/采购扫描。"""
    monkeypatch.setattr(bic, 'schedule_post_commit_invalidation', _noop)
    monkeypatch.setattr(
        'fastapi_app.services.purchase._auto_generate.schedule_auto_generate_purchase_orders',
        _noop,
    )


@pytest.mark.asyncio
async def test_comprehensive_import_order_sheet_creates_order_item(async_db_session, monkeypatch):
    """综合导入「订单管理」Sheet（batch_import_core.import_orders_from_data）。"""
    customer, product = await _seed(async_db_session, 'core')
    _isolate_post_commit_hooks(monkeypatch)
    order_no = 'SO-DH2-CORE'

    deps = bic.ImportDeps(generate_order_number=AsyncMock(return_value=order_no))
    count, messages = await bic.import_orders_from_data(
        async_db_session,
        [{'客户名称': customer, '产品名称': product.name, '数量': _QTY}],
        deps=deps,
    )

    assert count == 1, messages
    await _assert_created(async_db_session, order_no, product)


@pytest.mark.asyncio
async def test_sheet_import_endpoint_creates_order_item(async_db_session, monkeypatch):
    """单 Sheet 端点 /batch/import-orders（batch_import_service.import_orders_service）。"""
    customer, product = await _seed(async_db_session, 'sheet')
    _isolate_post_commit_hooks(monkeypatch)
    order_no = 'SO-DH2-SHEET'

    async def _read_rows(_file, _keywords, _missing):
        return [{'客户名称': customer, '产品名称': product.name, '订单数量': _QTY}], None

    monkeypatch.setattr(bis, '_validate_xlsx_file', lambda _f: None)
    monkeypatch.setattr(bis, '_read_excel_sheets', _read_rows)
    monkeypatch.setattr(bis, 'generate_order_number', AsyncMock(return_value=order_no))

    result = await bis.import_orders_service(
        async_db_session, SimpleNamespace(filename='orders.xlsx'))

    assert result.imported == 1, result.message
    await _assert_created(async_db_session, order_no, product)


def _arq_rows(customer: str, product: Product) -> list[dict]:
    return [{'客户名称': customer, '产品名称': product.name, '数量': _QTY}]


def _patch_arq_task(monkeypatch, test_engine, rows: list, order_no: str) -> None:
    """worker 用**独立会话**（``_open_import_session``）并自行提交：把会话工厂换成
    **测试库引擎**的同款 sessionmaker（生产走 ``require_async_session_local``，测试里
    全局引擎未初始化），并隔离解析/取号/ARQ 重放幂等（后者依赖 Redis）。
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(bt, '_open_import_session', AsyncMock(side_effect=session_factory))
    monkeypatch.setattr(bt, '_parse_rows_async', AsyncMock(return_value=(True, rows, '')))
    monkeypatch.setattr(
        'fastapi_app.services.numbering.generate_order_number',
        AsyncMock(return_value=order_no),
    )
    monkeypatch.setattr(
        'fastapi_app.core.arq_app.job_idempotency', lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_arq_import_creates_order_item(async_db_session, test_engine, monkeypatch):
    """ARQ 端点 /tasks/import-orders 的 worker 任务（batch_tasks.batch_import_orders_task）。

    种子先提交，任务结束后从 ``async_db_session`` 读回（READ COMMITTED 下新语句
    可见已提交行）。
    """
    customer, product = await _seed(async_db_session, 'arq')
    await async_db_session.commit()
    order_no = 'SO-DH2-ARQ'
    _patch_arq_task(monkeypatch, test_engine, _arq_rows(customer, product), order_no)

    result = await bt.batch_import_orders_task(
        {'job_id': 'd-h2-arq-import'}, os.path.join(tempfile.gettempdir(), 'd_h2_arq.xlsx'),
        'orders.xlsx', 1,
    )

    assert result['imported_count'] == 1, result
    assert result['errors'] == [], result
    await async_db_session.rollback()  # 结束可能存在的旧快照，读任务已提交的行
    await _assert_created(async_db_session, order_no, product)


@pytest.mark.asyncio
async def test_arq_import_rejects_unknown_customer(async_db_session, test_engine, monkeypatch):
    """D-H2 收敛：ARQ 路径补上客户主数据校验（此前不校验，静默建出孤儿订单）。"""
    _customer, product = await _seed(async_db_session, 'arqcust')
    await async_db_session.commit()
    unknown = '不存在的客户arqcust'
    _patch_arq_task(monkeypatch, test_engine, _arq_rows(unknown, product), 'SO-DH2-ARQ-CUST')

    result = await bt.batch_import_orders_task(
        {'job_id': 'd-h2-arq-cust'}, os.path.join(tempfile.gettempdir(), 'd_h2_arq_cust.xlsx'),
        'orders.xlsx', 1,
    )

    assert result['imported_count'] == 0, result
    assert len(result['errors']) == 1, result
    assert '不存在于客户主数据' in result['errors'][0]['error'], result['errors']
    await async_db_session.rollback()
    orphan = (await async_db_session.execute(
        select(Order).where(Order.customer == unknown)
    )).scalars().all()
    assert orphan == [], '未知客户不得建出孤儿订单'


class _ScalarsResult:
    def __init__(self, values) -> None:
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return list(self._values)


class _ProductLookupDb:
    """只回答 ``_resolve_product_locked`` 的 SELECT 的假会话。"""

    def __init__(self, products) -> None:
        self._products = products

    async def execute(self, *_args, **_kwargs):
        return _ScalarsResult(self._products)


@pytest.mark.asyncio
async def test_product_identifier_multi_hit_is_row_level_error() -> None:
    """D-M4：名称/条码分别命中不同产品时，行级 ValueError 而非整批任务崩溃。

    原实现 ``scalar_one_or_none`` 在两条命中时抛 ``MultipleResultsFound``，
    该异常不在 ``_import_rows`` 的行级 except 里 → 整个导入任务失败。
    """
    multi = _ProductLookupDb([SimpleNamespace(id=1), SimpleNamespace(id=2)])
    with pytest.raises(ValueError, match='同时命中多个产品'):
        await bt._resolve_product_locked(multi, '重名标识')

    single = _ProductLookupDb([SimpleNamespace(id=3)])
    assert (await bt._resolve_product_locked(single, '唯一标识')).id == 3
    assert await bt._resolve_product_locked(_ProductLookupDb([]), '不存在') is None


def test_three_paths_must_share_one_creation_service() -> None:
    """结构守卫（O-30）：三段订单导入实现必须调用同一个建单服务函数。

    直接在各行处理器内联写 Order/OrderItem 正是本缺陷的根因——三条实现各自漂移，
    某次修复只改了一条。此守卫让「再内联一份」立即变红。
    """
    import inspect

    creation = 'create_imported_order'
    assert creation in inspect.getsource(bt.batch_import_orders_task)
    assert creation in inspect.getsource(bic.import_orders_from_data)
    assert creation in inspect.getsource(bis.import_orders_service)
