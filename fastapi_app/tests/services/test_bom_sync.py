"""BOM 明细同步服务测试（task-3）。

覆盖：pending 单整单重建、无变化不抖动、跨部位率/价继承、
非 pending 跳过、版本冲突 409、审计删除行快照、用户编辑递增版本、大批量告警。
"""
import json
import logging

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


# ============================================================
# 终审修复：审计删除行快照 / 用户编辑递增 items_version / 大批量告警
# ============================================================

async def _bom_sync_audit_entries(db) -> list[dict]:
    rows = (await db.execute(
        select(ModificationLog).where(ModificationLog.field_name == 'bom_sync')
    )).scalars().all()
    return [json.loads(row.new_value) for row in rows]


async def test_sync_audit_log_contains_removed_row_snapshot(db):
    """spec §同步算法-6：审计 new_value 除计数外还要有被删除行的明细快照。"""
    await _seed(db)
    await sync_purchase_order_items(db, 8101)

    entries = await _bom_sync_audit_entries(db)
    assert len(entries) == 1
    summary = entries[0]
    assert (summary['added'], summary['updated'], summary['removed']) == (8, 0, 2)
    assert 'removed_truncated' not in summary
    by_name = {row['material_name']: row for row in summary['removed_rows']}
    assert set(by_name) == {'绿色超柔', '蓝色超柔'}
    assert by_name['绿色超柔'] == {
        'material_name': '绿色超柔', 'specification': '234', 'unit': '码',
        'part_name': None, 'role_id': None, 'supplier_name': '美利达',
        'quantity': 50.0, 'loss_rate': 30.0, 'unit_price': 2.0,
    }
    assert by_name['蓝色超柔'] == {
        'material_name': '蓝色超柔', 'specification': '223', 'unit': '码',
        'part_name': None, 'role_id': None, 'supplier_name': '美利达',
        # unit_price 列有 Python 侧默认 0（未显式赋值的行 flush 后即为 0）；
        # loss_rate 无默认值，保持 NULL → None。
        'quantity': 890.0, 'loss_rate': None, 'unit_price': 0.0,
    }


async def test_sync_audit_truncates_removed_snapshot_at_200(db):
    """删除行快照上限 200 行：超出部分截断并置 removed_truncated。"""
    await _seed(db)
    for idx in range(201):
        db.add(PurchaseOrderItem(
            id=1000 + idx, order_id=8101, material_name=f'手工行{idx}',
            specification=str(idx), unit='个', supplier_name='美利达',
            quantity=1, material_category='accessory',
        ))
    await db.commit()
    await sync_purchase_order_items(db, 8101)

    summary = (await _bom_sync_audit_entries(db))[0]
    assert summary['removed'] == 203          # 2 条旧行 + 201 条手工行
    assert len(summary['removed_rows']) == 200
    assert summary['removed_truncated'] is True


async def test_factory_save_bumps_items_version_on_quantity_edit(db):
    await _seed(db)
    res = await save_factory_summary_edits(
        db, [{'item_ids': [1], 'quantity': 60}], 'tester', order_ids=[8101],
    )
    assert res['items_versions'] == {8101: 1}
    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 1


async def test_factory_save_bumps_items_version_on_loss_rate_only(db):
    await _seed(db)                       # item 1: loss_rate=30
    res = await save_factory_summary_edits(
        db, [{'item_ids': [1], 'loss_rate': 40}], 'tester', order_ids=[8101],
    )
    assert res['items_versions'] == {8101: 1}
    assert (await db.get(PurchaseOrder, 8101)).items_version == 1


async def test_factory_save_no_bump_when_values_unchanged(db):
    """同值重发不算变更：版本不动（否则每保存一次就顶掉别人的版本）。"""
    await _seed(db)                       # item 1: quantity=50 / loss_rate=30
    res = await save_factory_summary_edits(
        db, [{'item_ids': [1], 'quantity': 50, 'loss_rate': 30}], 'tester',
        order_ids=[8101],
    )
    assert res['items_versions'] == {}
    assert (await db.get(PurchaseOrder, 8101)).items_version == 0


async def test_factory_save_spare_rate_bumps_all_involved_orders_once(db):
    """spare_rate 覆盖写：涉及的每张单各 +1（order_ids 重复也只加一次）。"""
    await _seed(db)
    await _seed(db, po_id=8102)
    res = await save_factory_summary_edits(
        db, [], 'tester', spare_rate=25, order_ids=[8101, 8102, 8102],
    )
    assert res['items_versions'] == {8101: 1, 8102: 1}
    assert (await db.get(PurchaseOrder, 8101)).items_version == 1
    assert (await db.get(PurchaseOrder, 8102)).items_version == 1


async def test_factory_save_bumps_each_edited_order_once(db):
    """两张单各自被编辑（含同单多次编辑）：每单只 +1。"""
    await _seed(db)
    await _seed(db, po_id=8102)
    res = await save_factory_summary_edits(
        db, [
            {'item_ids': [1], 'quantity': 60},
            {'item_ids': [11], 'quantity': 70},
            {'item_ids': [1], 'loss_rate': 40},   # 8101 的第二次编辑
        ], 'tester', order_ids=[8101, 8102],
    )
    assert res['items_versions'] == {8101: 1, 8102: 1}


async def test_update_order_item_prices_bumps_items_version_only_on_change(db):
    await _seed(db)
    same = await update_purchase_order(
        db, 8101, {'item_prices': [{'id': 1, 'unit_price': 2}], 'items_version': 0},
    )
    assert same['items_version'] == 0     # 同值重发不递增
    changed = await update_purchase_order(
        db, 8101, {'item_prices': [{'id': 1, 'unit_price': 3}], 'items_version': 0},
    )
    assert changed['items_version'] == 1  # 真实改价 +1，响应携带新版本
    assert (await db.get(PurchaseOrder, 8101)).items_version == 1


async def test_update_order_items_upsert_bumps_items_version(db):
    await _seed(db)
    result = await update_purchase_order(db, 8101, {
        'items_version': 0,
        'items': [{
            'id': 1, 'material_name': '绿色超柔', 'specification': '234',
            'unit': '码', 'unit_price': 2, 'quantity': 60,
            'material_category': 'fabric',
        }],
    })
    assert result['items_version'] == 1
    assert (await db.get(PurchaseOrder, 8101)).items_version == 1


async def test_bulk_sync_warns_when_more_than_20_orders(db, monkeypatch, caplog):
    """一次 BOM 保存影响 >20 张 pending 单时打印 warning（日志可被发现）。"""
    from fastapi_app.services.purchase import bom_sync as bom_sync_mod

    async def fake_find(_db, _product_id):
        return list(range(9001, 9022)), []    # 21 张

    async def fake_sync(_db, po_id, *, dry_run=False):
        return bom_sync_mod.SyncResult(po_id=po_id, changed=False)

    monkeypatch.setattr(bom_sync_mod, 'find_pending_po_ids_for_product', fake_find)
    monkeypatch.setattr(bom_sync_mod, 'sync_purchase_order_items', fake_sync)
    with caplog.at_level(logging.WARNING,
                         logger='fastapi_app.services.purchase.bom_sync'):
        await sync_pending_items_for_product(db, 201)
    assert any('BOM 同步影响采购单较多' in msg for msg in caplog.messages)


# ---------------------------------------------------------------------------
# 角色/部位独立口径（2026-11-11）：损耗率与数量按 (role_id, part_name) 独立
# ---------------------------------------------------------------------------

async def _seed_role_fabric(db, po_id=8101):
    """产品 205：2 角色（11/12），同一物料「香珠」各角色一行 + 同角色跨部位 2 行。

    结构（覆盖 a~d 用例）：
    - 角色A(11) / 角色B(12) 各有 香珠(5g) 一行 → 落库应 2 行、role_id 各自正确；
    - 角色A 另有 绿色超柔 跨 身体/脚底 2 行 → 同角色跨部位共享率/价（fallback 保留）；
    - 默认 BOM（role_id=None）一行 木棒 → 落库 role_id 为 None。
    """
    session = db
    session.add(Product(id=205, name='产品B', is_blind_box=False))
    for rid in (11, 12):
        session.add(ProductRole(id=rid, product_id=205, role_name=f'角色{rid}'))
    # 同一物料 香珠 在两个角色各一行（问题 2 的复现场景）
    session.add(ProductAccessory(
        id=2101, product_id=205, role_id=11, accessory_name='香珠',
        specification='5g', unit='个', quantity=1.0, supplier_name='香味'))
    session.add(ProductAccessory(
        id=2102, product_id=205, role_id=12, accessory_name='香珠',
        specification='5g', unit='个', quantity=1.0, supplier_name='香味'))
    # 同角色(11)跨部位 2 行
    for fid, part in ((1, '身体'), (2, '脚底')):
        session.add(ProductFabric(
            id=fid, product_id=205, role_id=11, fabric_name='绿色超柔',
            specification='234', unit='码', quantity=1.0, part_name=part,
            supplier_name='美利达'))
    # 默认 BOM
    session.add(ProductAccessory(
        id=2110, product_id=205, role_id=None, accessory_name='木棒',
        specification='1条', unit='个', quantity=1.0, supplier_name='木棒'))
    session.add(Order(id=9205, order_no='SO-9205', customer='客户乙',
                      product_id=205, quantity=1000, status='已备货'))
    session.add(OrderItem(id=21, order_id=9205, product_id=205,
                          product_name='产品B', quantity=1000))
    session.add(PurchaseOrder(
        id=po_id, order_no=f'PO-{po_id}', customer_name='客户乙', product_name='产品B',
        product_quantity=1000, supplier_name='香味', source_order_ids='[9205]',
        status='pending'))
    session.add(PurchaseOrderSku(
        id=po_id, po_id=po_id, product_name='产品B', product_barcode='bB',
        order_qty=1000, source_order_id=9205, source_record_type='order'))
    await session.commit()


async def test_role_scoped_items_get_distinct_rows_with_role_id(db):
    """a) 同一物料在角色 A、B 下各一行，role_id 正确；默认 BOM 行 role_id 为 None。"""
    await _seed_role_fabric(db)
    res = await sync_purchase_order_items(db, 8101)
    assert res.changed
    rows = (await db.execute(select(PurchaseOrderItem).where(
        PurchaseOrderItem.order_id == 8101))).scalars().all()
    pearl = [r for r in rows if r.material_name == '香珠']
    assert len(pearl) == 2
    assert sorted(r.role_id for r in pearl) == [11, 12]
    # 非盲盒：每个作用域都用完整数量 → 各角色 1000
    assert {float(r.quantity) for r in pearl} == {1000.0}
    # 默认 BOM 行 role_id 为 NULL
    wood = [r for r in rows if r.material_name == '木棒']
    assert len(wood) == 1 and wood[0].role_id is None


async def test_role_loss_rate_not_cross_overwritten(db):
    """b) 把 A 行的 loss_rate 改为 10，B 行仍为原值。"""
    await _seed_role_fabric(db)
    await sync_purchase_order_items(db, 8101)   # 重建出 2 行香珠
    rows = (await db.execute(select(PurchaseOrderItem).where(
        PurchaseOrderItem.order_id == 8101,
        PurchaseOrderItem.material_name == '香珠'))).scalars().all()
    a = next(r for r in rows if r.role_id == 11)
    a.loss_rate = 10
    await db.commit()
    # 再次同步：旧行（键含 role_id）按精确键逐行继承，B 行不得被 A 行的 10 覆盖
    await sync_purchase_order_items(db, 8101)
    rows = (await db.execute(select(PurchaseOrderItem).where(
        PurchaseOrderItem.order_id == 8101,
        PurchaseOrderItem.material_name == '香珠'))).scalars().all()
    a2 = next(r for r in rows if r.role_id == 11)
    b2 = next(r for r in rows if r.role_id == 12)
    assert float(a2.loss_rate) == 10.0
    assert b2.loss_rate is None or float(b2.loss_rate) != 10.0


async def test_same_role_cross_part_shares_rate_via_fallback(db):
    """c) 同角色跨部位仍共享率/价（fallback 收窄为「同 role 内跨部位」）。

    旧快照：同角色（NULL→视为默认 BOM 语义外的 11 不适用；这里用 role=11 的
    历史行）绿色超柔一条带率/价（无部位）。同步后该角色的身体/脚底两行
    经回退键（去部位、留 role）继承同一份率/价。
    """
    await _seed_role_fabric(db)
    db.add(PurchaseOrderItem(
        id=302, order_id=8101, role_id=11, material_name='绿色超柔',
        specification='234', unit='码', part_name=None, supplier_name='美利达',
        quantity=1500, loss_rate=12, unit_price=2, material_category='fabric'))
    await db.commit()
    await sync_purchase_order_items(db, 8101)
    rows = (await db.execute(select(PurchaseOrderItem).where(
        PurchaseOrderItem.order_id == 8101,
        PurchaseOrderItem.material_name == '绿色超柔'))).scalars().all()
    assert len(rows) == 2    # 身体 / 脚底 各一行，同 role=11
    assert {r.role_id for r in rows} == {11}
    # 同角色跨部位共享率/价：回退键去掉部位但保留 role，两行都继承 12‰ / 2
    assert {float(r.loss_rate) for r in rows} == {12.0}
    assert {float(r.unit_price) for r in rows} == {2.0}


async def test_pending_resync_no_role_cross_overwrite(db):
    """d) pending 单经 BOM 保存重建后，角色间不互相覆盖。

    数量按既有契约**恒重建**（BOM 真值，见 test_sync_backfill_script 的
    50→10000 断言）；受保护的是损耗率/单价/备注的按行继承。
    """
    await _seed_role_fabric(db)
    await sync_purchase_order_items(db, 8101)
    rows = (await db.execute(select(PurchaseOrderItem).where(
        PurchaseOrderItem.order_id == 8101,
        PurchaseOrderItem.material_name == '香珠'))).scalars().all()
    a = next(r for r in rows if r.role_id == 11)
    a.loss_rate = 10
    await db.commit()
    await sync_purchase_order_items(db, 8101)
    rows = (await db.execute(select(PurchaseOrderItem).where(
        PurchaseOrderItem.order_id == 8101,
        PurchaseOrderItem.material_name == '香珠'))).scalars().all()
    a2 = next(r for r in rows if r.role_id == 11)
    b2 = next(r for r in rows if r.role_id == 12)
    # A 行编辑过的率按精确键（含 role）继承；B 行不受 A 行影响
    assert float(a2.loss_rate) == 10.0
    assert b2.loss_rate is None
    # 数量按 BOM 重建（既有契约）
    assert {float(r.quantity) for r in rows} == {1000.0}


async def test_role_null_history_row_not_leaked_to_role_rows(db):
    """d2) 历史 NULL-role 行的率/价只允许被 NULL-role 目标行继承，不跨 role 泄漏。"""
    await _seed_role_fabric(db)
    db.add(PurchaseOrderItem(
        id=301, order_id=8101, material_name='香珠', specification='5g',
        unit='个', part_name=None, supplier_name='香味', quantity=1500,
        loss_rate=8, unit_price=1, material_category='accessory'))
    await db.commit()
    await sync_purchase_order_items(db, 8101)
    rows = (await db.execute(select(PurchaseOrderItem).where(
        PurchaseOrderItem.order_id == 8101,
        PurchaseOrderItem.material_name == '香珠'))).scalars().all()
    assert len(rows) == 2
    # 两个角色行都不得从 NULL 历史行继承 8‰（跨 role / 跨 NULL 边界不复用率/价）
    assert all(r.loss_rate is None for r in rows), [
        (r.role_id, r.loss_rate) for r in rows]


async def test_completed_po_snapshot_untouched_by_role_split(db):
    """e) completed 单内容不被改动（快照语义）。"""
    await _seed_role_fabric(db)
    po = await db.get(PurchaseOrder, 8101)
    po.status = 'completed'
    await db.commit()
    res = await sync_purchase_order_items(db, 8101)
    assert res.changed is False and res.skipped_reason == 'status:completed'
    rows = (await db.execute(select(PurchaseOrderItem).where(
        PurchaseOrderItem.order_id == 8101))).scalars().all()
    assert len(rows) == 0   # 未写入任何行
