"""库存结余闸门（2026-10-07）口径一致性集成测试。

出货闸门 `stock_out_service._assert_inventory_balance` 复用
`stock_inventory_service.get_inventory_balance`；本文件锁定它与 /stock 页
`get_inventory_paginated` 的「库存（结余）」列**同口径**（包装部入库 − 已出货），
避免两处口径漂移。

复用根 conftest 的会话级 test_engine，只写测试库并事务回滚。
"""
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.services import stock_inventory_service as svc
from fastapi_app.shared_models import DailyProductionRecord, InventoryLog, Order, Product

pytestmark = pytest.mark.integration

CUSTOMER = '结余闸门口径客户'
PRODUCT_NAME = '结余闸门口径产品'
BARCODE = 'INV-BAL-001'


@pytest_asyncio.fixture
async def db(test_engine):
    """函数级会话：复用会话级引擎 + 事务回滚隔离。"""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()


@pytest_asyncio.fixture
async def seeded(db):
    """包装部入库 100、已出货 30、一条订单（使 /stock 行存在）。"""
    product = Product(name=PRODUCT_NAME, barcode=BARCODE, current_stock=0, initial_stock=0)
    db.add(product)
    await db.flush()
    db.add(DailyProductionRecord(
        department='packaging', product_id=product.id,
        product_name=product.name, barcode=BARCODE,
        quantity=100, production_date=datetime.now(UTC).date(),
    ))
    db.add(InventoryLog(
        product_id=product.id, product_name=product.name, product_barcode=BARCODE,
        change_type='出库', change_quantity=-30,
    ))
    db.add(Order(
        order_no='INV-BAL-ORD-1', customer=CUSTOMER, product_id=product.id,
        quantity=50, order_date=datetime.now(UTC), status='待备货',
    ))
    await db.flush()
    return product


async def test_inventory_balance_is_packaging_minus_shipped(db, seeded):
    """get_inventory_balance = 包装部入库 − 已出货 = 100 − 30 = 70。"""
    assert await svc.get_inventory_balance(db, seeded.id) == 70


async def test_inventory_balance_matches_stock_page_column(db, seeded, monkeypatch):
    """与 /stock 页「库存」列同口径：两处数值必须相等。"""
    monkeypatch.setattr(svc, '_get_all_customers', svc._get_all_customers.__wrapped__)
    result = await svc.get_inventory_paginated.__wrapped__(
        db, search_customer=CUSTOMER, search_product=PRODUCT_NAME, page=1, per_page=50,
    )
    rows = [r for r in result['inventory_data'] if r['customer'] == CUSTOMER]
    assert rows, '库存页应包含该客户行'
    assert rows[0]['inventory_balance'] == await svc.get_inventory_balance(db, seeded.id)


async def test_inventory_balance_zero_when_never_packaged(db, monkeypatch):
    """从未包装入库的产品：结余为 0（闸门据此拒绝出货）。"""
    product = Product(name='未包装产品-结余', barcode='INV-BAL-002', current_stock=0, initial_stock=0)
    db.add(product)
    await db.flush()
    assert await svc.get_inventory_balance(db, product.id) == 0


async def test_packaging_production_only_product_visible_on_stock_page(db, monkeypatch):
    """仅有包装部生产入库、没有备货/订单的商品，也必须出现在 /stock 页。"""
    product = Product(
        name='仅包装生产可见产品', barcode='INV-BAL-005', current_stock=1000, initial_stock=0,
    )
    db.add(product)
    await db.flush()
    db.add(DailyProductionRecord(
        department='packaging', product_id=product.id,
        product_name=product.name, barcode='INV-BAL-005',
        quantity=1000, production_date=datetime.now(UTC).date(),
    ))
    await db.flush()

    monkeypatch.setattr(svc, '_get_all_customers', svc._get_all_customers.__wrapped__)
    result = await svc.get_inventory_paginated.__wrapped__(
        db, search_product=product.name, page=1, per_page=50,
    )
    rows = [r for r in result['inventory_data'] if r['product_name'] == product.name]
    assert rows, '仅包装部生产入库的商品也应在 /stock 页出现'
    assert rows[0]['customer'] == ''
    assert rows[0]['inventory_balance'] == 1000


async def test_inventory_balance_excludes_deduction_types(db, monkeypatch):
    """抵扣三型不进结余（Round16 口径修正）。

    Round16 核实：真实抵扣路径写的是「订单抵扣」(−) 而非「出库」，
    且「取消抵扣」(+) 与之对称；删单时写「抵扣回滚」(+)/「抵扣回滚(审批)」(+)
    ——若回滚计入而「订单抵扣」从未计入，结余虚高回滚量。故抵扣三型整体排除：
    抵扣期间结余不变，删单回滚也不再改变结余。
    同时覆盖闸门函数与 /stock 页 CTE 两条口径。
    """
    product = Product(name='抵扣回滚结余产品', barcode='INV-BAL-003', current_stock=0, initial_stock=0)
    db.add(product)
    await db.flush()
    # 真实抵扣生命周期：下单抵扣 −10000 → 审批删单回滚 +10000
    for change_type, quantity in (('订单抵扣', -10000), ('抵扣回滚(审批)', 10000)):
        db.add(InventoryLog(
            product_id=product.id, product_name=product.name, product_barcode='INV-BAL-003',
            change_type=change_type, change_quantity=quantity,
        ))
    # 一条订单让 /stock 页出现该产品行（CTE 只输出 has_stockin/has_order 且 total_qty>0 的行）
    db.add(Order(
        order_no='INV-BAL-ORD-2', customer='抵扣回滚结余客户', product_id=product.id,
        quantity=10000, order_date=datetime.now(UTC), status='待备货',
    ))
    await db.flush()

    # 抵扣与回滚都不影响结余：0（无包装入库、无真实出货）
    assert await svc.get_inventory_balance(db, product.id) == 0

    monkeypatch.setattr(svc, '_get_all_customers', svc._get_all_customers.__wrapped__)
    result = await svc.get_inventory_paginated.__wrapped__(
        db, search_customer='抵扣回滚结余客户', search_product='抵扣回滚结余产品', page=1, per_page=50,
    )
    rows = [r for r in result['inventory_data'] if r['customer'] == '抵扣回滚结余客户']
    assert rows, '库存页应包含该客户行'
    assert rows[0]['inventory_balance'] == 0


async def test_inventory_balance_nets_returns(db, monkeypatch):
    """退货回补（退货）与取消（退货取消）都要计入已出货净额，且两处口径一致。

    回归 2026-10-08：退货 2500 后「库存」列纹丝不动（shipped_net 不含退货类型）。
    递进断言——旧口径在第二步会停在 -5000，从而暴露漏项。
    """
    product = Product(name='退货结余产品', barcode='INV-BAL-004', current_stock=0, initial_stock=0)
    db.add(product)
    await db.flush()
    # 一条订单让 /stock 页出现该产品行（CTE 只输出 has_stockin/has_order 且 total_qty>0 的行）
    db.add(Order(
        order_no='INV-BAL-ORD-3', customer='退货结余客户', product_id=product.id,
        quantity=5000, order_date=datetime.now(UTC), status='待备货',
    ))
    db.add(InventoryLog(
        product_id=product.id, product_name=product.name, product_barcode='INV-BAL-004',
        change_type='出库', change_quantity=-5000,
    ))
    await db.flush()
    assert await svc.get_inventory_balance(db, product.id) == -5000

    # 退货 2500：已出货净额 −5000 → −2500，结余随之 +2500
    db.add(InventoryLog(
        product_id=product.id, product_name=product.name, product_barcode='INV-BAL-004',
        change_type='退货', change_quantity=2500,
    ))
    await db.flush()
    assert await svc.get_inventory_balance(db, product.id) == -2500

    # /stock 页 CTE 同口径
    monkeypatch.setattr(svc, '_get_all_customers', svc._get_all_customers.__wrapped__)
    result = await svc.get_inventory_paginated.__wrapped__(
        db, search_customer='退货结余客户', search_product='退货结余产品', page=1, per_page=50,
    )
    rows = [r for r in result['inventory_data'] if r['customer'] == '退货结余客户']
    assert rows, '库存页应包含该客户行'
    assert rows[0]['inventory_balance'] == -2500

    # 取消该退货：冲回 −2500，回到 −5000
    db.add(InventoryLog(
        product_id=product.id, product_name=product.name, product_barcode='INV-BAL-004',
        change_type='退货取消', change_quantity=-2500,
    ))
    await db.flush()
    assert await svc.get_inventory_balance(db, product.id) == -5000
