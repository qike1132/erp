"""汇总接口「已存损耗率快照」回归测试（services/purchase_order_query.get_factory_order_summary）。

背景（BUG）：/purchase 汇总下单弹窗录入损耗率 → 已保存 → 关闭重开回显为 0。
根因：汇总接口从不返回 spare_rate，前端无从回显。

本文件锁定「汇总接口必须返回它正在编辑的那个状态」这一契约：
- 全无值（列全 NULL）                → spare_rate=None,  spare_rate_mixed=False
- 全相同（含 0）                     → spare_rate=该值,  spare_rate_mixed=False（0 原样回显）
- 各单不一致                         → spare_rate=None,  spare_rate_mixed=True
- order_ids 为空（early return）     → spare_rate=None,  spare_rate_mixed=False
- 两个返回分支的字段形状必须一致
- 取值不产生额外 DB 往返（只在已加载 ORM 实例上读属性）

⚠️ spare_rate=0 是合法「已记录」值，绝不能被当成缺失。同源先例：
fastapi_app/tests/services/test_beile_orders.py::test_ordered_spare_rate_zero_survives
fastapi_app/tests/services/test_qa_beile_adversarial.py::test_qa_gating_and_list_flag_same_source
"""
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services.purchase_order_query import get_factory_order_summary
from fastapi_app.shared_models import Base, PurchaseOrder, PurchaseOrderItem

# 汇总流水线在两个返回分支都必须携带的字段
_REQUIRED_KEYS = {'groups', 'order_count', 'spare_rate', 'spare_rate_mixed'}


@pytest_asyncio.fixture
async def db():
    """真实模型的 sqlite 内存库会话 + SQL 语句记录器。

    仅建本测试涉及的表：PurchaseOrder / PurchaseOrderItem。
    不建 Order/Product/Bom 等表亦可：本用例的采购单不带 source_order_ids，
    故汇总流水线不会触达这些表的查询（仍会走完整的 groups 构建逻辑）。
    """
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, 'before_cursor_execute')
    def _record_sql(_conn, _cursor, statement, _params, _context, _many):  # pragma: no cover
        statements.append(statement)

    tables = [PurchaseOrder.__table__, PurchaseOrderItem.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session, statements
    await engine.dispose()


async def _seed(db: AsyncSession, rates: list[float | None], id_base: int = 20000) -> list[int]:
    """按给定率构造采购单（每单一条明细），返回其 id 列表。

    使用 int/float 而非 Decimal 写入：sqlite 方言不支持 Decimal 原生存储，
    传 Decimal 会触发 SAWarning，在 filterwarnings=error 下会失败。
    id_base 用于同一测试内多次构造时避免主键冲突。
    """
    ids: list[int] = []
    for i, rate in enumerate(rates, start=1):
        oid = id_base + i
        db.add(PurchaseOrder(
            id=oid,
            order_no=f'FS-{oid}',
            customer_name=f'客户{i}',
            product_name=f'产品{i}',
            product_quantity=1000,
            supplier_name='供应商甲',
            spare_rate=rate,
        ))
        db.add(PurchaseOrderItem(
            id=id_base + 20000 + i,
            order_id=oid,
            material_name=f'布料{i}',
            specification='S1',
            unit='米',
            quantity=10,
        ))
        ids.append(oid)
    await db.commit()
    return ids


async def test_all_none_returns_none_not_mixed(db):
    """所有单都无值（全 NULL）→ spare_rate=None、spare_rate_mixed=False。"""
    session, _ = db
    ids = await _seed(session, [None, None, None])

    result = await get_factory_order_summary(session, ids)

    assert result['spare_rate'] is None
    assert result['spare_rate_mixed'] is False


async def test_all_same_returns_value_not_mixed(db):
    """所有单值相同（非 0）→ 返回该值、spare_rate_mixed=False。"""
    session, _ = db
    ids = await _seed(session, [5, 5, 5])

    result = await get_factory_order_summary(session, ids)

    assert result['spare_rate'] == 5
    assert result['spare_rate_mixed'] is False


async def test_all_zero_returns_zero_not_none(db):
    """所有单值为 0 → 必须原样回显 0（0 是合法「已记录」值，不得判为缺失）。"""
    session, _ = db
    ids = await _seed(session, [0, 0, 0])

    result = await get_factory_order_summary(session, ids)

    assert result['spare_rate'] is not None, '0 不得被当成缺失（None）'
    assert result['spare_rate'] == 0
    assert result['spare_rate_mixed'] is False


async def test_mixed_returns_none_and_flag(db):
    """各单值不一致 → spare_rate=None、spare_rate_mixed=True。"""
    session, _ = db
    ids = await _seed(session, [5, 7])

    result = await get_factory_order_summary(session, ids)

    assert result['spare_rate'] is None
    assert result['spare_rate_mixed'] is True


async def test_mixed_including_zero_is_mixed(db):
    """有值但其中一个为 0、另一个非 0 → 仍属不一致（0 参与比较）。"""
    session, _ = db
    ids = await _seed(session, [0, 5])

    result = await get_factory_order_summary(session, ids)

    assert result['spare_rate'] is None
    assert result['spare_rate_mixed'] is True


async def test_single_none_is_none_not_mixed(db):
    """单张、从未记录损耗率（[None]）→ (None, False)。

    全新勾选且无任何已设率时不得报 mixed（否则会误显「各订单损耗率不一致」）。
    """
    session, _ = db
    ids = await _seed(session, [None])

    result = await get_factory_order_summary(session, ids)

    assert result['spare_rate'] is None
    assert result['spare_rate_mixed'] is False


async def test_single_zero_is_zero_not_none(db):
    """单张、已记录率恰为 0（[0]）→ (0.0, False)：0 必须原样保留。"""
    session, _ = db
    ids = await _seed(session, [0])

    result = await get_factory_order_summary(session, ids)

    assert result['spare_rate'] is not None
    assert result['spare_rate'] == 0
    assert result['spare_rate_mixed'] is False


async def test_all_five_returns_five_not_mixed(db):
    """[5, 5] → (5.0, False)。"""
    session, _ = db
    ids = await _seed(session, [5, 5])

    result = await get_factory_order_summary(session, ids)

    assert result['spare_rate'] == 5
    assert result['spare_rate_mixed'] is False


async def test_zero_and_null_is_mixed(db):
    """[0, None] → (None, True)：NULL 与已记录的 0 也不相同。"""
    session, _ = db
    ids = await _seed(session, [0, None])

    result = await get_factory_order_summary(session, ids)

    assert result['spare_rate'] is None
    assert result['spare_rate_mixed'] is True


async def test_partial_null_is_mixed(db):
    """部分单有值、部分单从未记录（NULL）→ 属不一致：(None, True)。【本次修复点】

    语义：NULL = 「从未记录过损耗率」，与任何已记录值（含 0）都不相同。
    若返回该已记录值，等于向用户声称「本批所有单都是这个率」：
    会抑制「各订单损耗率不一致」提示，并把该率带进备品计算与打印/导出。
    旧实现先滤 None 再比较 → 会把 [None, 5, None, 5] 误判为 (5, False)。
    """
    session, _ = db
    ids = await _seed(session, [None, 5, None, 5])

    result = await get_factory_order_summary(session, ids)

    assert result['spare_rate'] is None
    assert result['spare_rate_mixed'] is True


async def test_value_and_null_is_mixed(db):
    """[5, None] → (None, True)：含 1 张已设率 + 若干未设率的真实勾选须走 mixed。"""
    session, _ = db
    ids = await _seed(session, [5, None])

    result = await get_factory_order_summary(session, ids)

    assert result['spare_rate'] is None
    assert result['spare_rate_mixed'] is True


async def test_null_value_null_is_mixed(db):
    """[None, 5, None] → (None, True)（首元素为 NULL 也不得短路为 «全无值»）。"""
    session, _ = db
    ids = await _seed(session, [None, 5, None])

    result = await get_factory_order_summary(session, ids)

    assert result['spare_rate'] is None
    assert result['spare_rate_mixed'] is True


async def test_empty_order_ids_same_shape(db):
    """order_ids 为空（early return）与正常分支字段形状必须一致。"""
    session, _ = db
    ids = await _seed(session, [5])

    normal = await get_factory_order_summary(session, ids)
    empty = await get_factory_order_summary(session, [])

    assert set(normal.keys()) == set(empty.keys()) == _REQUIRED_KEYS
    assert empty['spare_rate'] is None
    assert empty['spare_rate_mixed'] is False
    assert empty['groups'] == []
    assert empty['order_count'] == 0


async def test_spare_rate_reading_adds_no_db_roundtrip(db):
    """护栏：读取损耗率不得新增 DB 往返。

    以「全 NULL」与「全有值」两次调用对比 SQL 语句数：若实现为取率额外发起
    查询，则两次调用语句数会不同（或其中一次出现独立 SELECT spare_rate）。
    两次合计子句也应一致（率不进入 WHERE）。

    ⚠️ 预热说明（2026-09-18）：`get_factory_order_summary` 现在还会装配逐 SKU
    明细，其取数入口 `po_sku_available` 会对 `purchase_order_sku` 做一次**表能力
    探测**（SAVEPOINT + SELECT + ROLLBACK，表缺失时）。该探测只在**首次调用**发生，
    结果缓存在 `db.info`，与损耗率数据无关。若不预热，本用例的「两次语句数相等」
    代理判据会被这次冷启动打破，从而误报「取率引入了额外查询」。
    预热只消除缓存冷启动差异，**不放松任何判据**（下方三条断言原样保留）。
    """
    session, statements = db
    null_ids = await _seed(session, [None, None])
    set_ids = await _seed(session, [5, 5], id_base=21000)

    # 预热一次性能力探测（表缺失时探测会失败并写入 SAVEPOINT 回滚语句）
    from fastapi_app.services.purchase_order_sku import po_sku_available
    await po_sku_available(session)

    statements.clear()
    await get_factory_order_summary(session, null_ids)
    count_null = len(statements)

    statements.clear()
    await get_factory_order_summary(session, set_ids)
    count_set = len(statements)

    assert count_null == count_set, (
        f'取率引入了数据相关的额外查询（NULL={count_null} vs SET={count_set}）'
    )
    # 主表实体加载本身会 SELECT spare_rate（列属于实体），故排除它后若仍出现
    # spare_rate 投影，则说明实现额外发起了独立查询读取率 —— 属违规。
    projected = [
        s for s in statements
        if 'spare_rate' in s.lower() and 'from purchase_order' not in s.lower()
    ]
    assert projected == [], f'出现疑似单独读取 spare_rate 的查询: {projected}'

    # 主表加载仍是单次 SELECT purchase_order（未因取率而拆分）——
    # 注意 'from purchase_order' 是 'from purchase_order_item' 的子串，故加空格界定表名。
    po_loads = [s for s in statements if 'from purchase_order ' in s.lower().replace('\n', ' ')]
    assert len(po_loads) == 1


async def test_order_count_and_groups_unchanged(db):
    """回归护栏：新增字段不得影响既有 groups / order_count 的产出。"""
    session, _ = db
    ids = await _seed(session, [5, 5])

    result = await get_factory_order_summary(session, ids)

    assert result['order_count'] == 2
    # 每单都被聚为一个 (客户, 产品) 分组
    assert len(result['groups']) == 2
    # 分组内含回退的 PO 明细（无 BOM → 用明细作为布料）
    first_group = result['groups'][0]
    assert first_group['suppliers'][0]['fabrics'][0]['fabric_name'].startswith('布料')


async def test_real_query_still_selects_spare_rate_via_orm_entity(db):
    """正向确认：主表 SELECT 是实体查询（含 spare_rate 列），故属性读取零额外查询。"""
    session, statements = db
    ids = await _seed(session, [5])

    statements.clear()
    await get_factory_order_summary(session, ids)

    po_load = next(
        s for s in statements
        if 'from purchase_order ' in s.lower().replace('\n', ' ')
    )
    assert 'purchase_order.spare_rate' in po_load.lower()


async def test_null_columns_loaded_correctly(db):
    """确认 sqlite 下 Numeric 列往返：写入 int 后可正确读回（None 保持 None）。"""
    session, _ = db
    await _seed(session, [None, 0, 5])

    rows = (await session.execute(select(PurchaseOrder.id, PurchaseOrder.spare_rate))).all()
    by_id = {r.id: r.spare_rate for r in rows}
    assert by_id[20001] is None
    assert by_id[20002] == 0
    assert by_id[20003] == 5
