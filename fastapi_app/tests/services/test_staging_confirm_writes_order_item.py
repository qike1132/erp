"""暂存订单确认必须写 OrderItem 明细（审计批次4：P1-8）。

## 拦哪种出错

订单主表 `order` 的 SKU 字段已进入「兼容保留」阶段，读取方逐步改为遍历
`order.items`（SKU 级明细）。写明细的路径有两条：`create_order`
（order/commands.py:157-167）与批量创建（order_batch_create._create_order_items）。
**暂存订单确认这条漏了**：它只写 `Order` + `InventoryLog`，于是这些订单在按 items
读取的链路上表现为「没有明细」。

后果不在「能不能下单」，而在下游悄悄降级：
- `bom_sync._sku_rows_for_order` 的采购明细三层回退（po_sku 快照 → OrderItem →
  订单级单行）只能落到第三层，SKU 级行数/名称全丢，按整单摊平；
- 订单详情/对账序列化（beile / unified / _unprocessed / order_serializer）读到的
  `deduct_quantity` 全为 0，与同一笔确认写下的库存流水自相矛盾；
- 谁也不会报错 —— 数据「看起来正常」，只是粗了一档。

## 本文件各锁一件事

1. `test_confirm_writes_order_item_with_sku_fields`：确认一行就要落一条与之等价的
   OrderItem（order_id / product_id / 名称 / 条码 / 数量 / 抵扣 / 备注）；
2. `test_confirm_writes_one_order_item_per_row`：N 行 → N 条明细，不合并、不漏行；
3. `test_confirm_without_deduct_writes_zero_deduct`：未勾抵扣的行明细抵扣为 0（别把
   上一行的值带过来）。

## 变异检查

- 删掉 `_write_confirmed_order` 里的 `db.add(_confirmed_order_item(...))` → 用例 1/2/3 全红；
- 把 `_confirmed_order_item` 的 `order_id=order.id` 改成 `None` → 用例 1 红；
- 把 `deduct_quantity` 写死为 0 → 用例 1 红（抵扣字段丢失）。
"""
from types import SimpleNamespace

from fastapi_app.core.state_machine import StagingStatus
from fastapi_app.services.staging import order as staging_order_mod
from fastapi_app.shared_models import Order, OrderItem, StagingOrder


class _Scalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)


class _Result:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class _Cursor:
    rowcount = 0


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class _FakeDB:
    """只实现 confirm 用到的四件事：execute / begin_nested / add / flush。"""

    def __init__(self, rows: list) -> None:
        self._rows = rows
        self._select_done = False
        self.added: list = []
        self._next_id = 5000

    async def execute(self, _stmt):
        if not self._select_done:
            self._select_done = True
            return _Result(self._rows)
        return _Cursor()

    def begin_nested(self) -> _Savepoint:
        return _Savepoint()

    def add(self, obj) -> None:
        # 真实 flush 才分配主键；这里在 add 时给主订单编号，好让明细的 order_id 可校验
        if isinstance(obj, Order) and getattr(obj, 'id', None) is None:
            self._next_id += 1
            obj.id = self._next_id
        self.added.append(obj)

    async def flush(self) -> None:
        return None


def _product():
    return SimpleNamespace(id=1, name='P-1', factory=None, barcode='690001',
                           current_stock=1000, version=1)


def _staging_row(**over: object) -> StagingOrder:
    row = StagingOrder(
        session_id='u7:default', customer='C1', product_name='P-1',
        product_id=1, quantity=5, note='备注A',
        deduct_stock=True, deduct_quantity=2,
    )
    row.is_validated = True
    row.status = StagingStatus.PENDING
    for k, v in over.items():
        setattr(row, k, v)
    return row


async def _noop_async(*_a, **_kw):
    return None


def _patch_world(monkeypatch, product=None):
    """把确认链路的 I/O 全部替掉，只留下「写了什么」这一观察点。"""
    product = product or _product()

    async def _get_product(_db, _pid):
        return product

    monkeypatch.setattr(
        'fastapi_app.shared.stock_concurrency.get_product_for_update', _get_product)
    monkeypatch.setattr(staging_order_mod, 'generate_order_number',
                        lambda *_a, **_kw: _value('ORD-1'))
    monkeypatch.setattr(staging_order_mod, 'process_order_deduction', _noop_async)
    monkeypatch.setattr(
        'fastapi_app.services.outsource_service.auto_generate_for_order', _noop_async)
    monkeypatch.setattr(staging_order_mod.cache_mgr, 'invalidate_stock_and_order', _noop_async)
    monkeypatch.setattr(staging_order_mod, 'schedule_post_commit_invalidation',
                        lambda *_a, **_kw: None)
    return product


def _value(value):
    async def _inner(*_a, **_kw):
        return value
    return _inner()


async def test_confirm_writes_order_item_with_sku_fields(monkeypatch):
    """确认一行 → 必须落一条与之等价的 OrderItem（修复前一条都没有）。"""
    _patch_world(monkeypatch)

    row = _staging_row()
    db = _FakeDB([row])
    confirmed, errors = await staging_order_mod.confirm_staging_orders(db, 'u7:default')

    assert confirmed == 1, f'前置：本用例要求该行被确认，errors={errors}'
    items = [o for o in db.added if isinstance(o, OrderItem)]
    assert len(items) == 1, f'确认后没有订单明细（审计 P1-8）：新增对象={db.added}'

    item = items[0]
    order = next(o for o in db.added if isinstance(o, Order))
    assert item.order_id == order.id, '明细必须挂到本次创建的订单上'
    assert item.product_id == 1
    assert item.product_name == 'P-1'
    assert item.product_barcode == '690001'
    assert item.quantity == 5
    assert item.deduct_stock is True
    assert item.deduct_quantity == 2, '明细抵扣与本次实际扣减口径必须一致'
    assert item.note == '备注A'


async def test_confirm_writes_one_order_item_per_row(monkeypatch):
    """两行各自确认 → 两条明细（不合并、不漏行）。"""
    _patch_world(monkeypatch)

    rows = [_staging_row(), _staging_row(customer='C2', quantity=7)]
    db = _FakeDB(rows)
    confirmed, errors = await staging_order_mod.confirm_staging_orders(db, 'u7:default')

    assert confirmed == 2, f'前置：两行都该确认，errors={errors}'
    items = [o for o in db.added if isinstance(o, OrderItem)]
    assert len(items) == 2, f'明细条数与确认行数不一致：{[type(o).__name__ for o in db.added]}'
    assert sorted(i.quantity for i in items) == [5, 7]


async def test_confirm_without_deduct_writes_zero_deduct(monkeypatch):
    """未勾抵扣的行：明细抵扣为 0，且不调用扣减。"""
    _patch_world(monkeypatch)
    called: list = []

    async def _deduct(*_a, **_kw):
        called.append(_kw)

    monkeypatch.setattr(staging_order_mod, 'process_order_deduction', _deduct)

    db = _FakeDB([_staging_row(deduct_stock=False, deduct_quantity=0)])
    confirmed, errors = await staging_order_mod.confirm_staging_orders(db, 'u7:default')

    assert confirmed == 1, errors
    item = next(o for o in db.added if isinstance(o, OrderItem))
    assert item.deduct_stock is False and item.deduct_quantity == 0
    assert called == [], '未勾抵扣不该调用扣减'
