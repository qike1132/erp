"""BOM 明细同步服务测试（task-3）。

覆盖：pending 单整单重建、无变化不抖动、跨部位率/价继承、
非 pending 跳过、版本冲突 409。
"""
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services.purchase.bom_sync import (
    ItemsVersionConflict,
    find_pending_po_ids_for_product,
    product_has_bom,
    sync_pending_items_for_product,
    sync_purchase_order_items,
)
from fastapi_app.services.purchase_order_crud import (
    _items_version_lock_stmt,
    save_factory_summary_edits,
    update_purchase_order,
)
from fastapi_app.services.purchase_order_query import get_factory_order_summary
from fastapi_app.shared_models import (
    Base,
    Order,
    OrderItem,
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    ProductRole,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderSku,
)
from fastapi_app.shared_models.purchase_center import ModificationLog


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    tables = [PurchaseOrder.__table__, PurchaseOrderItem.__table__, PurchaseOrderSku.__table__,
              Order.__table__, OrderItem.__table__, Product.__table__,
              ProductFabric.__table__, ProductAccessory.__table__, ProductRole.__table__,
              ProductMaterial.__table__, ModificationLog.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


_UNSET = object()


async def _seed(session, *, status='pending', po_id=8101, po_sku_name='产品A',
                source_order_ids=_UNSET, product_barcode=_UNSET, extra_sku_name=None):
    """盲盒产品 201：6 角色；绿色超柔跨身体/脚底各 1.0；木棒辅料每角色 1.0。

    共享夹具（产品/BOM/客户订单）只插一次；可多次调用追加多张采购单，
    旧行 id 按 po_id 偏移（8101 → 1/2、8102 → 11/12），避免主键冲突。
    ``product_barcode`` 显式传入时对已存在的产品同样生效（不静默忽略）；
    ``extra_sku_name`` 额外插一行同单 sku（用于「部分行可解」场景）。
    """
    if source_order_ids is _UNSET:
        # sqlite 不支持 partial unique index（uq_po_pending_dedup 的 WHERE 被丢弃），
        # 同 (customer, supplier, source ids) 的第二张单会撞唯一键 → 非 8101 的
        # 单用自身 id 作来源区分；默认调用方只把它当 completed 单，不参与解析。
        source_order_ids = '[9101]' if po_id == 8101 else f'[{po_id}]'
    product = await session.get(Product, 201)
    if product is None:
        session.add(Product(
            id=201, name='产品A', is_blind_box=True, has_hidden_role=False,
            barcode=None if product_barcode is _UNSET else product_barcode,
        ))
        for rid in range(11, 17):
            session.add(ProductRole(id=rid, product_id=201, role_name=f'角色{rid}'))
            session.add(ProductAccessory(
                id=1000 + rid, product_id=201, role_id=rid, accessory_name='木棒按摩锤',
                specification='1条', unit='个', quantity=1.0, supplier_name='木棒'))
        for fid, part in ((1, '身体'), (2, '脚底')):
            session.add(ProductFabric(
                id=fid, product_id=201, role_id=None, fabric_name='绿色超柔',
                specification='234', unit='码', quantity=1.0, part_name=part,
                supplier_name='美利达'))
        session.add(Order(id=9101, order_no='SO-9101', customer='客户甲',
                          product_id=201, quantity=10000, status='已备货'))
        session.add(OrderItem(id=1, order_id=9101, product_id=201,
                              product_name='产品A', quantity=10000))
    elif product_barcode is not _UNSET:
        product.barcode = product_barcode
    session.add(PurchaseOrder(
        id=po_id, order_no=f'PO-{po_id}', customer_name='客户甲', product_name='产品A',
        product_quantity=10000, supplier_name='美利达',
        source_order_ids=source_order_ids, status=status))
    session.add(PurchaseOrderSku(
        id=po_id, po_id=po_id, product_name=po_sku_name, product_barcode='bA',
        order_qty=10000, source_order_id=9101, source_record_type='order'))
    if extra_sku_name:
        session.add(PurchaseOrderSku(
            id=po_id * 10, po_id=po_id, product_name=extra_sku_name,
            product_barcode='bX', order_qty=1, source_order_id=9101,
            source_record_type='order'))
    # 旧快照：绿色超柔一行 50（无部位、有率/价）；手工孤儿行 蓝色超柔 890
    base = (po_id - 8101) * 10
    session.add(PurchaseOrderItem(
        id=base + 1, order_id=po_id, material_name='绿色超柔', specification='234',
        unit='码', part_name=None, supplier_name='美利达', quantity=50,
        loss_rate=30, unit_price=2, material_category='fabric'))
    session.add(PurchaseOrderItem(
        id=base + 2, order_id=po_id, material_name='蓝色超柔', specification='223',
        unit='码', part_name=None, supplier_name='美利达', quantity=890,
        material_category='fabric'))
    await session.commit()


async def test_sync_rebuilds_rows_for_pending_po_blind_box(db):
    await _seed(db)
    res = await sync_purchase_order_items(db, 8101)
    assert res.changed and res.added == 8  # 绿色身体/脚底 2 行 + 6 条辅料行

    rows = (await db.execute(select(PurchaseOrderItem).where(
        PurchaseOrderItem.order_id == 8101))).scalars().all()
    green = sorted((r.part_name, float(r.quantity)) for r in rows if r.material_name == '绿色超柔')
    assert green == [('脚底', 10000.0), ('身体', 10000.0)]
    # 孤儿行（蓝色超柔）被删除
    assert all(r.material_name != '蓝色超柔' for r in rows)
    # 辅料每角色一行、合计恒等于订单量
    wood = [r for r in rows if r.material_name == '木棒按摩锤']
    assert len(wood) == 6
    assert sum(float(r.quantity) for r in wood) == 10000.0

    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 1


async def test_sync_is_noop_when_unchanged(db):
    await _seed(db)
    await sync_purchase_order_items(db, 8101)
    res = await sync_purchase_order_items(db, 8101)
    assert res.changed is False
    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 1  # 无变化不抖动


async def test_sync_preserves_loss_rate_and_price_across_parts(db):
    await _seed(db)
    await sync_purchase_order_items(db, 8101)
    green = (await db.execute(select(PurchaseOrderItem).where(
        PurchaseOrderItem.order_id == 8101,
        PurchaseOrderItem.material_name == '绿色超柔'))).scalars().all()
    assert {float(r.loss_rate) for r in green} == {30.0}
    assert {float(r.unit_price) for r in green} == {2.0}
    assert {float(r.total_price) for r in green} == {20600.0}  # 10000×1.03×2


async def test_sync_skips_completed_po(db):
    await _seed(db, status='completed')
    res = await sync_purchase_order_items(db, 8101)
    assert res.changed is False and res.skipped_reason == 'status:completed'


async def test_stale_version_raises_conflict(db):
    await _seed(db)
    with pytest.raises(ItemsVersionConflict):
        await sync_purchase_order_items(db, 8101, expected_version=99)


async def test_dry_run_reports_counts_without_writing(db):
    # 行锁语义（dry_run 不 FOR UPDATE）在 sqlite 无法验证（sqlite 忽略 FOR UPDATE），
    # 这里锁定 dry-run 的可观测契约：零写入、版本不变、无审计。
    await _seed(db)
    res = await sync_purchase_order_items(db, 8101, dry_run=True)
    assert res.changed and res.added == 8 and res.removed == 2
    assert sorted(res.removed_rows) == [1, 2]
    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 0
    rows = (await db.execute(select(PurchaseOrderItem).where(
        PurchaseOrderItem.order_id == 8101))).scalars().all()
    assert len(rows) == 2  # 未删未插
    assert (await db.execute(
        select(func.count()).select_from(ModificationLog))).scalar() == 0


async def test_sync_resolves_sku_by_barcode_when_product_renamed(db):
    # 产品改名 + 无 source_order_ids：po_sku 快照名对不上，必须靠条码回退解析 pid
    await _seed(db, po_sku_name='产品A-旧名', source_order_ids=None, product_barcode='bA')
    res = await sync_purchase_order_items(db, 8101)
    assert res.changed and res.added == 8
    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 1


async def test_sync_marks_unresolved_when_name_and_barcode_both_miss(db):
    await _seed(db, po_sku_name='不存在', source_order_ids=None)
    res = await sync_purchase_order_items(db, 8101)
    assert res.changed is False and res.skipped_reason == 'unresolved_sku'
    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 0


async def test_sync_pending_items_for_product_batches(db):
    await _seed(db)
    matched, unresolved = await find_pending_po_ids_for_product(db, 201)
    assert matched == [8101] and unresolved == []
    out = await sync_pending_items_for_product(db, 201)
    assert out['synced'] == 1
    assert out['unresolved_po_ids'] == []
    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 1


async def test_find_pending_only_and_skip_completed(db):
    await _seed(db)                       # PO 8101 pending，产品 201
    await _seed(db, po_id=8102, status='completed')
    affected, unresolved = await find_pending_po_ids_for_product(db, 201)
    assert affected == [8101]
    assert unresolved == []


async def test_unresolved_sku_is_reported_not_written(db):
    # 无 source_order_ids 且 sku 名称对不上 → 三层回退全部失败 → unresolved
    await _seed(db, po_sku_name='改名前的产品名', source_order_ids=None)
    affected, unresolved = await find_pending_po_ids_for_product(db, 201)
    assert affected == []
    assert unresolved == [8101]
    report = await sync_pending_items_for_product(db, 201)
    assert report['synced'] == 0
    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 0  # 解析失败不写库


async def test_find_pending_resolves_snapshot_name_without_source_ids(db):
    # 备货「一键生成」单主表无来源，来源只在 po_sku 快照：按快照名反查（产品未改名）
    await _seed(db, source_order_ids=None)
    affected, unresolved = await find_pending_po_ids_for_product(db, 201)
    assert affected == [8101]
    assert unresolved == []  # 能解析却报 unresolved = 该单永远不会被同步（静默漏同步）


async def test_find_pending_resolves_barcode_when_renamed_without_source_ids(db):
    # 快照名已过期（产品改名）但条码仍可解析：与单张同步的条码回退同口径
    await _seed(db, po_sku_name='产品A-旧名', source_order_ids=None, product_barcode='bA')
    affected, unresolved = await find_pending_po_ids_for_product(db, 201)
    assert affected == [8101]
    assert unresolved == []


async def test_sync_pending_items_for_product_syncs_no_source_id_po_by_name(db):
    # 发现与同步必须同口径：快照名可解析的单要真能同步（产品无条码也成立）
    await _seed(db, source_order_ids=None)
    report = await sync_pending_items_for_product(db, 201)
    assert report['synced'] == 1
    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 1


async def test_partial_unresolved_sku_po_reported_as_unresolved_not_silent(db):
    # 两行 sku：一行可解、一行不可解 → 同步必失败；发现层不得只凭部分行命中就判 matched
    await _seed(db, extra_sku_name='幽灵产品')
    matched, unresolved = await find_pending_po_ids_for_product(db, 201)
    assert matched == []
    assert unresolved == [8101]
    report = await sync_pending_items_for_product(db, 201)
    assert report['synced'] == 0
    assert report['unresolved_po_ids'] == [8101]
    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 0  # 部分可解也不写库


async def test_ambiguous_barcode_is_unresolved_and_not_written(db):
    # Product.barcode 非唯一：两产品同码视为歧义，不按条码解析（防判给错误产品写错 BOM）
    await _seed(db, po_sku_name='产品A-旧名', source_order_ids=None, product_barcode='bA')
    db.add(Product(id=202, name='产品B', is_blind_box=False, has_hidden_role=False,
                   barcode='bA'))
    await db.commit()
    matched, unresolved = await find_pending_po_ids_for_product(db, 201)
    assert matched == []
    assert unresolved == [8101]
    report = await sync_pending_items_for_product(db, 201)
    assert report['synced'] == 0 and report['unresolved_po_ids'] == [8101]
    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 0


async def test_product_has_bom_matches_revoke_oracle(db):
    """BOM 存在性守卫与撤销链同口径：任一 BOM 子表有行即视为「未删空」。

    回调层用它决定是否同步：BOM 为空时同步必须跳过，否则条码回退命中的
    pending 单会被按空 BOM 整单删光明细（2026-11-11 评审 Important）。
    """
    await _seed(db)
    assert await product_has_bom(db, 201) is True   # 面料/辅料有行
    assert await product_has_bom(db, 99999) is False  # 不存在的产品视为无 BOM

    await db.execute(delete(ProductAccessory))
    await db.execute(delete(ProductFabric))
    assert await product_has_bom(db, 201) is False  # 删空后必须判 False


# ============================================================
# Task 6：明细写接口 items_version 409 并发保护
# ============================================================

async def test_factory_save_rejects_stale_items_version(db):
    await _seed(db)                       # items_version=0
    with pytest.raises(ItemsVersionConflict):
        await save_factory_summary_edits(
            db, [], 'tester', spare_rate=30, order_ids=[8101],
            items_versions={8101: 99},
        )


async def test_update_order_rejects_stale_items_version(db):
    await _seed(db)
    with pytest.raises(ItemsVersionConflict):
        await update_purchase_order(db, 8101, {'items_version': 99})


async def test_factory_summary_exposes_items_versions(db):
    await _seed(db)
    summary = await get_factory_order_summary(db, [8101])
    assert summary['items_versions'] == {8101: 0}


async def test_factory_save_accepts_matching_items_version(db):
    """版本一致时正常落库（对照组：防「恒抛 409」的假修复）。"""
    await _seed(db)
    res = await save_factory_summary_edits(
        db, [], 'tester', spare_rate=30, order_ids=[8101],
        items_versions={8101: 0},
    )
    assert res['spare_updated_count'] == 1
    po = await db.get(PurchaseOrder, 8101)
    assert float(po.spare_rate) == 30.0


async def test_update_order_accepts_matching_items_version(db):
    await _seed(db)
    await update_purchase_order(
        db, 8101, {'items_version': 0, 'note': '改备注'},
    )
    po = await db.get(PurchaseOrder, 8101)
    assert po.remark == '改备注'


async def test_factory_save_checks_orders_reached_via_edits_union(db):
    """order_ids 为空、采购单只由 edits 命中：并集口径必须仍校验该单版本。"""
    await _seed(db)
    with pytest.raises(ItemsVersionConflict):
        await save_factory_summary_edits(
            db, [{'item_ids': [1], 'quantity': 60}], 'tester',
            order_ids=[], items_versions={8101: 99},
        )


async def test_factory_save_stale_version_writes_nothing(db):
    """校验在任何写入之前：冲突抛出后明细/损耗率均保持原值。"""
    await _seed(db)
    with pytest.raises(ItemsVersionConflict):
        await save_factory_summary_edits(
            db, [{'item_ids': [1], 'quantity': 12345}], 'tester',
            spare_rate=30, order_ids=[8101], items_versions={8101: 99},
        )
    item = await db.get(PurchaseOrderItem, 1)
    assert float(item.quantity) == 50.0
    po = await db.get(PurchaseOrder, 8101)
    assert po.spare_rate is None


def test_items_version_check_compiles_with_for_update_on_postgres():
    """版本校验语句必须在 PostgreSQL 下带 ``FOR UPDATE``（行锁）。

    评审修复（Task 6）：比对后、flush 前若 BOM 同步提交了新版本，无锁 SELECT
    仍会写入旧快照 —— 正是本任务要防的场景。本用例锁定「校验语句含行锁」这一
    编译期契约。局限：sqlite 夹具不支持 FOR UPDATE 语义（方言直接忽略），无法
    在行为上验证并发互斥效果；实际锁语义依赖 PG。
    """
    stmt = _items_version_lock_stmt([8101, 8102])
    sql = str(stmt.compile(dialect=postgresql.dialect())).upper()
    assert 'FOR UPDATE' in sql, sql
    # 多行加锁按 id 排序，降低并发保存互相死锁的可能
    assert 'ORDER BY PURCHASE_ORDER.ID' in sql, sql


async def test_factory_save_partial_items_versions_skips_uncovered_orders(db):
    """Ruling：部分覆盖只校验字典里出现的单；未出现的涉及单不校验（旧客户端兼容）。

    字典里只出现无关单（9999）时，涉及单 8101 没有被校验，保存照常落库；
    若实现误做「全量强制」，此用例会抛 ItemsVersionConflict 变红。
    """
    await _seed(db)
    result = await save_factory_summary_edits(
        db, [{'item_ids': [1], 'quantity': 60}], 'tester',
        order_ids=[8101], items_versions={9999: 0},
    )
    assert result['updated_count'] == 1
    item = await db.get(PurchaseOrderItem, 1)
    assert float(item.quantity) == 60.0
