"""CR-1 增量对抗复验（独立于工程师自测 test_beile_orders.py）。

CR-1 变更：
  1. `is_ordered` 作为**事实字段**的严格判定：已确认的历史行不影响其判定结果
     （计数口径曾一并收敛，`unordered_count` 已随顶部横幅一同下线）。
  2. confirm_beile_order / confirm_beile_stockin 明确「**幂等早退在门控之前**」。

本文件用于：
  - 独立复现「未确认+未下单 / 已确认+未下单 / 未确认+已下单」三类互斥下
    `is_ordered` 事实字段的严格判定。
  - 为变异实验提供「必然变红」的守卫用例（变异由外部脚本执行，见报告）：
      * M2：把门控前移到幂等早退之前 → 幂等 200 用例变红。
仅使用 sqlite 内存库 + 真实模型，不接触生产库。
"""
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.core.exceptions import ConflictError
from fastapi_app.services.order.beile import (
    BEILE_NOT_ORDERED_DETAIL,
    confirm_beile_order,
    confirm_beile_stockin,
    get_beile_orders_with_stockins,
)
from fastapi_app.shared_models import (
    Base,
    Notification,
    Order,
    OrderItem,
    Product,
    PurchaseOrder,
    PurchaseOrderStatus,
    StockIn,
    User,
)


@pytest_asyncio.fixture
async def db():
    """独立 sqlite 内存库（真实模型），每个测试一个实例。"""
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    tables = [
        User.__table__, Product.__table__, Order.__table__,
        OrderItem.__table__, StockIn.__table__, Notification.__table__,
        PurchaseOrder.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _no_redis(monkeypatch):
    """强制 L2 不可用 + 清空 L1：计数/列表函数始终回源，观察真实语义。"""
    from fastapi_app.core import cache as cache_module
    monkeypatch.setattr(cache_module, '_get_redis_cache', lambda: None)
    cache_module.invalidate_local_cache('*')
    yield


# 与 DB 中持久化的 user(id=1) 对齐的分离实例（服务仅读取 username / id）
QA_USER_OBJ = User(id=1, username='qa_cr1', password='x', factory='湖北')


def _user() -> User:
    return User(id=1, username='qa_cr1', password='x', factory='湖北')


def _order(oid, no, customer, date, product, qty, **kw):
    return Order(
        id=oid, order_no=no, customer=customer, order_date=date,
        product_id=product.id, quantity=qty,
        items=[OrderItem(product_id=product.id, product_name=product.name,
                         product_barcode=product.barcode, quantity=qty)],
        **kw,
    )


# =========================================================================
# 1. is_ordered 事实口径：三类互斥（未确认+未下单 / 已确认+未下单 / 未确认+已下单）
#    —— 事实字段严格判定，不受记录是否已确认影响
# =========================================================================
async def test_cr1_is_ordered_three_mutually_exclusive_cases(db):
    """`is_ordered` 只由「是否存在 completed 采购单」决定，与确认状态无关。

    三类订单 + 三类备货各自独立判定，期望 o_uu/o_cu/s_uu/s_cu 为 False、
    o_uc/s_uc 为 True。
    """
    p = Product(id=1, name='变形金刚', barcode='690001', factory='湖北')

    # ---- 订单三类 ----
    o_uu = _order(1001, 'OO-1', 'C-uu', datetime(2026, 9, 1), p, 10)             # 未确认+未下单
    o_cu = _order(1002, 'OC-1', 'C-cu', datetime(2026, 9, 2), p, 10,
                  confirmed_at=datetime(2026, 9, 2, 12), confirmed_by_id=1)      # 已确认+未下单
    o_uc = _order(1003, 'OU-1', 'C-uc', datetime(2026, 9, 3), p, 10)             # 未确认+已下单

    # ---- 备货三类 ----
    s_uu = StockIn(id=2001, stockin_no='SU-1', customer='S-uu', product_id=1,
                   quantity=5, stockin_date=datetime(2026, 9, 1))                 # 未确认+未下单
    s_cu = StockIn(id=2002, stockin_no='SC-1', customer='S-cu', product_id=1,
                   quantity=5, stockin_date=datetime(2026, 9, 2),
                   confirmed_at=datetime(2026, 9, 2, 12), confirmed_by_id=1)     # 已确认+未下单
    s_uc = StockIn(id=2003, stockin_no='SO-1', customer='S-uc', product_id=1,
                   quantity=5, stockin_date=datetime(2026, 9, 3))                 # 未确认+已下单

    pos = [
        PurchaseOrder(id=3001, order_no='CB-1', status=PurchaseOrderStatus.COMPLETED,
                      supplier_name='供A', source_order_ids='[1003]', customer_name='C-uc',
                      product_name='变形金刚', product_quantity=10),               # 命中 o_uc
        PurchaseOrder(id=3002, order_no='CB-2', status=PurchaseOrderStatus.COMPLETED,
                      supplier_name='供B', source_order_ids='[]', customer_name='S-uc',
                      product_name='变形金刚', product_quantity=10),               # 命中 s_uc（按客户+产品）
    ]
    db.add_all([_user(), p, o_uu, o_cu, o_uc, s_uu, s_cu, s_uc, *pos])
    await db.commit()

    result = await get_beile_orders_with_stockins(db, page=1, per_page=50)
    by_id = {r['id']: r for r in result['items']}
    assert by_id[1001]['is_ordered'] is False
    assert by_id[1002]['is_ordered'] is False, 'is_ordered 是事实字段，已确认不影响其严格判定'
    assert by_id[1003]['is_ordered'] is True
    assert by_id[2001]['is_ordered'] is False
    assert by_id[2002]['is_ordered'] is False
    assert by_id[2003]['is_ordered'] is True


# =========================================================================
# 2. 幂等早退必须在门控之前（变异 M2 的守卫）
# =========================================================================
async def test_cr1_idempotent_early_return_precedes_gate_order(db):
    """已确认 **且** 未下单的订单再次确认 → 幂等 200（不得被门控拦成 409）。

    变异 M2（把门控移到幂等早退之前）后，本用例将抛 ConflictError → 变红。
    """
    p = Product(id=1, name='变形金刚', barcode='690001', factory='湖北')
    o_conf = _order(1001, 'OC-1', 'C1', datetime(2026, 9, 1), p, 10,
                    confirmed_at=datetime(2026, 9, 2, 9), confirmed_by_id=1)
    po_pending = PurchaseOrder(id=3001, order_no='PB-1', status=PurchaseOrderStatus.PENDING,
                               source_order_ids='[1001]', customer_name='C1',
                               product_name='变形金刚', product_quantity=10)
    db.add_all([_user(), p, o_conf, po_pending])
    await db.commit()

    res = await confirm_beile_order(db, 1001, QA_USER_OBJ)
    assert res['success'] is True, '已确认记录必须幂等成功（200），而非 409'
    assert res['already_confirmed'] is True


async def test_cr1_idempotent_early_return_precedes_gate_stockin(db):
    """已确认 **且** 无匹配 completed 采购单的备货再次确认 → 幂等 200（不得 409）。"""
    p = Product(id=1, name='变形金刚', barcode='690001', factory='湖北')
    s_conf = StockIn(id=2001, stockin_no='SC-1', customer='客户Z', product_id=1,
                     quantity=5, stockin_date=datetime(2026, 9, 1),
                     confirmed_at=datetime(2026, 9, 2, 9), confirmed_by_id=1)
    db.add_all([_user(), p, s_conf])
    await db.commit()

    res = await confirm_beile_stockin(db, 2001, QA_USER_OBJ)
    assert res['success'] is True
    assert res['already_confirmed'] is True


async def test_cr1_gate_still_blocks_unconfirmed_unordered_order_and_stockin(db):
    """顺序调整后门控仍生效：**未确认 且 未下单** → 409，confirmed_at 保持 NULL。"""
    p = Product(id=1, name='变形金刚', barcode='690001', factory='湖北')
    o_uu = _order(1001, 'OO-1', 'C-uu', datetime(2026, 9, 1), p, 10)
    s_uu = StockIn(id=2001, stockin_no='SU-1', customer='S-uu', product_id=1,
                   quantity=5, stockin_date=datetime(2026, 9, 1))
    db.add_all([_user(), p, o_uu, s_uu])
    await db.commit()

    with pytest.raises(ConflictError) as exc_o:
        await confirm_beile_order(db, 1001, QA_USER_OBJ)
    assert exc_o.value.status_code == 409
    assert exc_o.value.message == BEILE_NOT_ORDERED_DETAIL
    assert (await db.get(Order, 1001)).confirmed_at is None

    with pytest.raises(ConflictError) as exc_s:
        await confirm_beile_stockin(db, 2001, QA_USER_OBJ)
    assert exc_s.value.status_code == 409
    assert exc_s.value.message == BEILE_NOT_ORDERED_DETAIL
    assert (await db.get(StockIn, 2001)).confirmed_at is None
