"""备品按部位损耗率重算（公式 A：瓶颈部位决定）回归测试。

口径见 docs/purchase/备品数量按部位差异化损耗率计算方案.md。
核心不变量：备品 = Σ_SKU ceil(SKU订单数量 × max(该SKU各部位行损耗率)‰)。
降级不变量：产品/BOM 无法匹配部位行时回退「该单全部明细 max」并告警；
SKU 快照表/快照行不可得时回退既有订单级口径。绝不抛错、绝不静默清零。
"""
import logging

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services.purchase_order_sku import po_sku_available
from fastapi_app.services.purchase_order_spare import (
    _load_bom_item_keys,
    recompute_po_spare_from_item_rates,
)
from fastapi_app.shared_models import (
    Base,
    MaterialRegistration,
    MaterialRegistrationItem,
    ModificationLog,
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderSku,
)

pytestmark = pytest.mark.experimental

_XIAOTU = '兔子公仔'

# 本模块 logger 名（降级告警断言用）
_SPARE_LOGGER = 'fastapi_app.services.purchase_order_spare'

# 全部用例共用的建表清单：Task 4 的完成路径会写 MaterialRegistration /
# MaterialRegistrationItem / ModificationLog，故一并建出（对 Task 1-3 无害）。
_TABLES = [
    Product.__table__, ProductFabric.__table__, ProductMaterial.__table__,
    ProductAccessory.__table__, PurchaseOrder.__table__,
    PurchaseOrderItem.__table__, PurchaseOrderSku.__table__,
    MaterialRegistration.__table__, MaterialRegistrationItem.__table__,
    ModificationLog.__table__,
]


@pytest_asyncio.fixture
async def db():
    """真实模型的 sqlite 内存库会话。

    不建 Role / Supplier 等表亦可 —— sqlite 不校验 FK 目标是否存在，
    且本模块的 BOM 键加载不依赖角色名（按 role_id 全量读取，不区分作用域）。
    """
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed_product_with_bom(db: AsyncSession, pid: int = 9001) -> int:
    """一个产品 + 三类 BOM 各一行（口径见 _MATERIAL_SPECS）。"""
    db.add(Product(id=pid, name=_XIAOTU))
    db.add(ProductMaterial(
        id=pid * 10 + 1, product_id=pid, cotton_usage=10, specification='填充A', unit='克',
    ))
    db.add(ProductFabric(
        id=pid * 10 + 2, product_id=pid, fabric_name='对条头布',
        specification='S1', quantity=0.2, unit='米',
    ))
    db.add(ProductAccessory(
        id=pid * 10 + 3, product_id=pid, accessory_name='眼睛扣',
        specification='', quantity=2, unit='个',
    ))
    await db.commit()
    return pid


async def test_load_bom_item_keys_matches_generation_naming(db):
    """BOM 键必须与采购明细生成口径逐字一致（三类物料各一行）。"""
    session = db
    pid = await _seed_product_with_bom(session)

    keys = await _load_bom_item_keys(session, {pid: _XIAOTU})

    assert keys[pid] == {
        (f'{_XIAOTU}-填充物', '填充A', '克'),
        ('对条头布', 'S1', '米'),
        ('眼睛扣', '', '个'),
    }


async def test_load_bom_item_keys_empty_products_returns_empty(db):
    """无产品 → 空映射（不得发起查询、不得抛错）。"""
    assert await _load_bom_item_keys(db, {}) == {}


async def test_load_bom_item_keys_missing_tables_degrades(db):
    """BOM 表不可用 → 返回空映射并降级，绝不抛错。"""
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as bare:
        assert await _load_bom_item_keys(bare, {1: '不存在'}) == {}
    await engine.dispose()


_H_TIAO = ('对条头布', 'S1', '米')
_H_SU = ('素色身布', 'S2', '米')


async def _seed_product_two_fabrics(db: AsyncSession, pid: int = 9100) -> int:
    """两部位产品：对条头布 + 素色身布（同一默认 BOM 作用域）。"""
    db.add(Product(id=pid, name=_XIAOTU))
    db.add(ProductFabric(
        id=pid * 10 + 1, product_id=pid, fabric_name='对条头布',
        specification='S1', quantity=0.2, unit='米',
    ))
    db.add(ProductFabric(
        id=pid * 10 + 2, product_id=pid, fabric_name='素色身布',
        specification='S2', quantity=0.8, unit='米',
    ))
    await db.commit()
    return pid


async def _seed_po(
    db: AsyncSession, po_id: int, *, product_quantity: float,
    spare_rate: float | None = None, item_rates: dict | None = None,
    skus: list[dict] | None = None, items: list[dict] | None = None,
) -> int:
    """构造一张采购单 + 明细 +（可选）逐 SKU 快照。

    item_rates 形如 ``{('对条头布', 'S1', '米'): 30}``；值 None 表示该行未配率。
    使用 int/float 写入（filterwarnings=error 下 Decimal 会失败）。
    """
    db.add(PurchaseOrder(
        id=po_id, order_no=f'SP-{po_id}', customer_name='客户A',
        product_name=_XIAOTU, product_quantity=product_quantity,
        supplier_name='供应商甲', spare_rate=spare_rate,
    ))
    rows = items if items is not None else [
        {'material_name': k[0], 'specification': k[1], 'unit': k[2], 'rate': v}
        for k, v in (item_rates or {}).items()
    ]
    for i, row in enumerate(rows, start=1):
        db.add(PurchaseOrderItem(
            id=po_id * 10 + i, order_id=po_id,
            material_name=row['material_name'], specification=row['specification'],
            unit=row['unit'], quantity=100, loss_rate=row.get('rate'),
        ))
    for i, sku in enumerate(skus or [], start=1):
        db.add(PurchaseOrderSku(
            id=po_id * 100 + i, po_id=po_id,
            product_name=sku['product_name'], product_barcode=sku.get('barcode'),
            order_qty=sku['order_qty'], source_order_id=sku.get('source_order_id', i),
            source_record_type='order',
        ))
    await db.commit()
    return po_id


async def _po_spare(db: AsyncSession, po_id: int) -> tuple[float | None, list]:
    """读回 (主表备品, [(sku备品, sku率), ...])。"""
    order = await db.get(PurchaseOrder, po_id)
    rows = (await db.execute(
        select(PurchaseOrderSku).where(PurchaseOrderSku.po_id == po_id)
        .order_by(PurchaseOrderSku.id)
    )).scalars().all()
    return order.spare_quantity, [(r.spare_qty, r.spare_rate) for r in rows]


async def test_spare_uses_max_part_rate(db):
    """单 SKU 两部位 30/10‰、N=1000 → 备品 30（瓶颈部位决定，不是 10、不是 40）。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7001, product_quantity=1000,
        item_rates={_H_TIAO: 30, _H_SU: 10},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    assert await recompute_po_spare_from_item_rates(session, [7001]) == 1

    spare, sku_rows = await _po_spare(session, 7001)
    assert float(spare) == 30
    assert sku_rows == [(30, 30)]


async def test_uniform_rate_matches_legacy_behavior(db):
    """【兼容锚】单 SKU 两部位同率 5‰、N=1000 → 备品 5，与改动前逐字一致。

    这是「上线无跳变」的证明：全行同率时 max = R，结果等于旧口径
    ceil(N × R/1000)。
    """
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7020, product_quantity=1000,
        item_rates={_H_TIAO: 5, _H_SU: 5},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7020])

    spare, _ = await _po_spare(session, 7020)
    assert float(spare) == 5  # ceil(1000 × 5/1000)


async def test_spare_is_per_sku_then_summed(db):
    """多 SKU：各自按自身部位 max，逐 SKU ceil 后求和（不是先求和再 ceil）。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7002, product_quantity=100,
        item_rates={_H_TIAO: 30, _H_SU: 10},
        skus=[
            {'product_name': _XIAOTU, 'order_qty': 50},
            {'product_name': _XIAOTU, 'order_qty': 50},
        ],
    )

    await recompute_po_spare_from_item_rates(session, [7002])

    spare, sku_rows = await _po_spare(session, 7002)
    # 每个 SKU: ceil(50 × 30/1000) = ceil(1.5) = 2 → 合计 4（若先求和再 ceil 则为 3）
    assert [int(r[0]) for r in sku_rows] == [2, 2]
    assert float(spare) == 4


async def test_null_item_rate_falls_back_to_order_rate(db):
    """订单级率 20、头布行显式 NULL → 该行按 20 参与 max，结果 20。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7003, product_quantity=1000, spare_rate=20,
        item_rates={_H_TIAO: None, ('素色身布', 'S2', '米'): 10},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7003])

    spare, _ = await _po_spare(session, 7003)
    assert float(spare) == 20


async def test_order_rate_null_keeps_item_rates(db):
    """订单级率为 NULL、部分行有率 → 有率的行照常生效，备品不得归 0。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7004, product_quantity=1000, spare_rate=None,
        item_rates={_H_TIAO: 30, ('素色身布', 'S2', '米'): None},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7004])

    spare, _ = await _po_spare(session, 7004)
    assert float(spare) == 30


async def test_all_rates_absent_gives_zero(db):
    """行全 NULL + 订单级 NULL → 备品 0（等价今天「从未设率」的单）。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7005, product_quantity=1000, spare_rate=None,
        item_rates={_H_TIAO: None}, skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7005])

    spare, sku_rows = await _po_spare(session, 7005)
    assert float(spare) == 0
    assert sku_rows == [(0, 0.0)]


async def test_zero_rate_is_recorded_not_missing(db):
    """率恰为 0 是合法「已记录」值：0 原样写回，不得变 NULL。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7006, product_quantity=1000, spare_rate=0,
        item_rates={_H_TIAO: 0}, skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7006])

    spare, sku_rows = await _po_spare(session, 7006)
    assert float(spare) == 0
    assert sku_rows[0][1] == 0


async def test_rate_above_thousand_is_clamped(db):
    """率 > 1000 截断为 1000 → 备品 = N。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7007, product_quantity=100,
        item_rates={_H_TIAO: 5000}, skus=[{'product_name': _XIAOTU, 'order_qty': 100}],
    )

    await recompute_po_spare_from_item_rates(session, [7007])

    spare, _ = await _po_spare(session, 7007)
    assert float(spare) == 100


async def test_illegal_negative_rate_does_not_poison_max(db):
    """非法负率按 0 处理，不得把合规部位的率拉低或令整单备品归 0。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7021, product_quantity=1000,
        item_rates={_H_TIAO: 30, _H_SU: -5},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7021])

    spare, _ = await _po_spare(session, 7021)
    assert float(spare) == 30


async def test_zero_or_null_sku_qty_contributes_zero(db):
    """sku.order_qty 为 0 / NULL → 该 SKU 备品 0，且不污染合计。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7008, product_quantity=1000,
        item_rates={_H_TIAO: 30},
        skus=[
            {'product_name': _XIAOTU, 'order_qty': 0},
            {'product_name': _XIAOTU, 'order_qty': None},
            {'product_name': _XIAOTU, 'order_qty': 1000},
        ],
    )

    await recompute_po_spare_from_item_rates(session, [7008])

    spare, sku_rows = await _po_spare(session, 7008)
    # 严格数值比较：None 不被 `or 0` 掩成 0（float(None) 会抛错 → 立即可见）
    assert [float(r[0]) for r in sku_rows] == [0.0, 0.0, 30.0]
    assert float(spare) == 30


async def test_unresolvable_sku_degrades_to_items_max(db):
    """SKU 产品名/条码都对不上产品 → 降级为**该单全部明细的 max**，不抛错。

    口径变更（spec §2.2/§4）：曾一度实现为「回退订单级率」（旧实现跟了 plan 附录，
    违反 spec）。现按 spec 降级为「该单全部明细 max」——本例明细头布率 30、
    订单级率 15，故降级结果为 **30（不是 15，更不是 0）**。
    """
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7009, product_quantity=1000, spare_rate=15,
        item_rates={_H_TIAO: 30},
        skus=[{'product_name': '查无此产品', 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7009])

    spare, _ = await _po_spare(session, 7009)
    assert float(spare) == 30


async def test_unresolvable_sku_null_order_rate_degrades_to_items_max(db, caplog):
    """【I1 回归】产品无法解析 + 顶层率为 NULL → 降级为该单明细 max，**不得静默写 0**。

    旧实现的报警守卫是 ``if part_keys and not _match_part_items(...)``：产品无法解析时
    ``part_keys`` 为 None ⇒ 守卫短路 ⇒ **不告警**；且 ``_effective_rate`` 回退
    ``normalize_spare_rate(None) or 0.0`` ⇒ **静默把 ``sku.spare_qty`` 写成 0**。
    这正是「用户改用逐部位率、顶层率合法为 NULL」时的目标工作流，故必须按 spec 修。
    """
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7130, product_quantity=1000, spare_rate=None,
        item_rates={_H_TIAO: 30},
        skus=[{'product_name': '查无此产品', 'order_qty': 1000}],
    )

    with caplog.at_level(logging.WARNING, logger=_SPARE_LOGGER):
        await recompute_po_spare_from_item_rates(session, [7130])

    spare, sku_rows = await _po_spare(session, 7130)
    assert float(spare) == 30, '产品无法解析且顶层率为 NULL 时必须降级为明细 max，不得写 0'
    assert sku_rows == [(30, 30)]
    warns = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and r.name == _SPARE_LOGGER
    ]
    assert len(warns) == 1, '降级告警应每次调用汇总一次'
    assert '查无此产品' in warns[0].getMessage(), '告警须点名降级的 SKU'


async def test_bom_changed_no_match_degrades_to_items_max(db):
    """产品 BOM 已改名致匹配为空 → 降级为**该单全部明细的 max**，不抛错。

    同 ``test_unresolvable_sku_degrades_to_items_max``：按 spec 降级为明细 max
    （本列明细率 30，故为 **30**，不是订单级率 15）。
    """
    session = db
    await _seed_product_two_fabrics(session)  # BOM 里没有「已停产布料」
    await _seed_po(
        session, 7010, product_quantity=1000, spare_rate=15,
        item_rates={('已停产布料', 'X', '米'): 30},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7010])

    spare, _ = await _po_spare(session, 7010)
    assert float(spare) == 30


async def test_bom_match_empty_logs_warning_naming_sku(db, caplog):
    """L3b 降级必须留痕：产品可解析但 BOM 匹配为空 → 汇总告警一次并点名该 SKU。"""
    session = db
    await _seed_product_two_fabrics(session)  # BOM 里没有「已停产布料」
    await _seed_po(
        session, 7120, product_quantity=1000, spare_rate=15,
        item_rates={('已停产布料', 'X', '米'): 30},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    with caplog.at_level(logging.WARNING, logger=_SPARE_LOGGER):
        await recompute_po_spare_from_item_rates(session, [7120])

    warns = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and r.name == _SPARE_LOGGER
    ]
    assert len(warns) == 1, '降级告警应每次调用汇总一次，不得逐 SKU 重复'
    message = warns[0].getMessage()
    assert _XIAOTU in message, '告警须点名降级的 SKU'
    assert 'BOM' in message, '告警须说明降级原因'


async def test_no_sku_rows_logs_no_degradation_warning(db, caplog):
    """L2（该单无逐 SKU 快照）是合法旧单，不属降级噪声源 → 不得打降级告警。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7121, product_quantity=1000, spare_rate=5,
        item_rates={_H_TIAO: 30}, skus=[],
    )

    with caplog.at_level(logging.WARNING, logger=_SPARE_LOGGER):
        await recompute_po_spare_from_item_rates(session, [7121])

    assert [
        r for r in caplog.records
        if r.levelno == logging.WARNING and r.name == _SPARE_LOGGER
    ] == []


async def test_no_sku_rows_falls_back_to_order_level(db):
    """明细有率但无 SKU 快照 → 保持既有订单级口径（零回归）。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7011, product_quantity=1000, spare_rate=5,
        item_rates={_H_TIAO: 30}, skus=[],
    )

    await recompute_po_spare_from_item_rates(session, [7011])

    spare, sku_rows = await _po_spare(session, 7011)
    assert float(spare) == 5  # ceil(1000 × 5/1000)，与旧行为一致
    assert sku_rows == []


async def test_empty_items_with_sku_rows_gives_zero(db):
    """SKU 快照存在但该单明细为空 → 无匹配 → 回退订单级率（NULL 则 0），不抛错。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7012, product_quantity=1000, spare_rate=None,
        items=[], skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7012])

    spare, _ = await _po_spare(session, 7012)
    assert float(spare) == 0


async def test_recompute_is_idempotent(db):
    """同一输入连续重算两次，结果逐字不变。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7013, product_quantity=1000,
        item_rates={_H_TIAO: 30, ('素色身布', 'S2', '米'): 10},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7013])
    first = await _po_spare(session, 7013)
    await recompute_po_spare_from_item_rates(session, [7013])
    second = await _po_spare(session, 7013)

    assert first == second


async def test_empty_po_ids_is_noop(db):
    """空入参 → 返回 0，不抛错。"""
    assert await recompute_po_spare_from_item_rates(db, []) == 0
    assert await recompute_po_spare_from_item_rates(db, None) == 0


async def test_sku_table_unavailable_keeps_order_level(db, monkeypatch):
    """SKU 快照表不可用 → 回退订单级口径，不抛错、不清零。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7100, product_quantity=1000, spare_rate=5,
        item_rates={_H_TIAO: 30}, skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    async def _unavailable(_db):
        return False

    monkeypatch.setattr(
        'fastapi_app.services.purchase_order_spare.po_sku_available', _unavailable,
    )

    assert await recompute_po_spare_from_item_rates(session, [7100]) == 1
    assert float((await session.get(PurchaseOrder, 7100)).spare_quantity) == 5


@pytest_asyncio.fixture
async def db_recording():
    """带 SQL 语句记录器的会话（性能护栏专用，仿 test_factory_order_summary_spare_rate）。"""
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, 'before_cursor_execute')
    def _record(_conn, _cursor, statement, _params, _context, _many):  # pragma: no cover
        statements.append(statement)

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session, statements
    await engine.dispose()


async def test_query_count_is_bounded(db_recording):
    """性能护栏：**读查询**数与 SKU 行数无关，不得随行数线性增长（防 N+1）。

    只比对 SELECT 语句数：写回语句（UPDATE）本就随行数增长，属正常，不参与判据。
    实现为固定几条批量读（主表 + 明细 + SKU + 产品 + 三类 BOM），与单量无关。
    """
    session, statements = db_recording
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7110, product_quantity=1000,
        item_rates={_H_TIAO: 30, _H_SU: 10},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    # 预热 po_sku_available 的一次性表能力探测（结果缓存于 db.info）：冷启动探测若
    # 计入首个采样，会把「1 行 8 vs 3 行 7」误判为 N+1（先例与理由见
    # test_factory_order_summary_spare_rate.test_spare_rate_reading_adds_no_db_roundtrip）。
    await po_sku_available(session)

    statements.clear()
    await recompute_po_spare_from_item_rates(session, [7110])
    reads_one_sku = [s for s in statements if s.lstrip().lower().startswith('select')]

    await _seed_po(
        session, 7111, product_quantity=3000,
        item_rates={_H_TIAO: 30, _H_SU: 10},
        skus=[
            {'product_name': _XIAOTU, 'order_qty': 1000},
            {'product_name': _XIAOTU, 'order_qty': 1000},
            {'product_name': _XIAOTU, 'order_qty': 1000},
        ],
    )
    statements.clear()
    await recompute_po_spare_from_item_rates(session, [7111])
    reads_three_skus = [s for s in statements if s.lstrip().lower().startswith('select')]

    assert len(reads_one_sku) == len(reads_three_skus), (
        f'读查询数随 SKU 行数增长（1 行 {len(reads_one_sku)} vs 3 行 '
        f'{len(reads_three_skus)}），疑似 N+1'
    )
    assert len(reads_one_sku) <= 10, f'重算读查询数异常偏多（{len(reads_one_sku)} 条）'
