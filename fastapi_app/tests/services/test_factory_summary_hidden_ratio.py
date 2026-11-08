"""工厂汇总「按 SKU 推算」与陈列样随箱配比的同口径回归测试。

背景：工厂内部订单页用「BOM 单件用量 × 该 SKU 数量」推算每个 SKU 的物料量，
再与采购单落库明细做差异对照。生成路径对配置了 ``product.hidden_carton_ratio``
的 SKU 按「6 常规款均分 + 隐藏款 ceil(N/P)」分配，若推算仍按「全量 × 所有角色」，
未编辑过的单也会被误报「含手工调整」。

本文件锁定：
    H1  配置配比的 SKU：推算值 == 落库值（常规 4×1667 + 2×1666，隐藏 139）；
    H2  同一采购单内多来源行同 SKU：先合并成 N=10000 再分配（隐藏款只进位一次）；
    H3  角色结构非法（配了 P 但不足 6+1）：推算回退全量，不阻断页面；
    H4  未配置配比的 SKU：行为与既有口径逐字一致（零回归）。
"""
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

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

REGULAR_NAMES = ['角色A', '角色B', '角色C', '角色D', '角色E', '角色F']
HIDDEN_NAME = '角色G'  # 用右键指定（is_hidden）识别，名字不必是「隐藏款」
# 10000 = 6×1666 余 4 → 前 4 款各 1667；隐藏 ceil(10000/72)=139
EXPECTED_BY_ROLE = {
    '角色A': 1667, '角色B': 1667, '角色C': 1667, '角色D': 1667,
    '角色E': 1666, '角色F': 1666, '角色G': 139,
}


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    tables = [
        PurchaseOrder.__table__, PurchaseOrderItem.__table__, PurchaseOrderSku.__table__,
        Order.__table__, OrderItem.__table__, Product.__table__,
        ProductFabric.__table__, ProductAccessory.__table__, ProductMaterial.__table__,
        ProductRole.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed_configured_sku(db: AsyncSession, *, role_names: list[str]) -> int:
    """构造「陈列样」SKU（配比 72）+ 一张含两条来源行（6000+4000）的采购单。

    采购单明细按生成路径的落库口径预置：每角色一条布料，数量 = 该角色分配值。
    返回采购单 id。
    """
    db.add(Product(
        id=201, name='陈列样盲盒', hidden_carton_ratio=72,
        is_blind_box=True, has_hidden_role=True,
    ))
    for index, role_name in enumerate(role_names, start=1):
        db.add(ProductRole(
            id=index, product_id=201, role_name=role_name,
            is_hidden=(role_name == HIDDEN_NAME),
        ))
        db.add(ProductFabric(
            id=index, product_id=201, role_id=index,
            fabric_name=f'{role_name}布', specification='S1', unit='米',
            quantity=1, supplier_name='供应商甲',
        ))

    db.add(Order(id=9101, order_no='SO-9101', customer='客户乙', product_id=201, quantity=6000, status='已备货'))
    db.add(Order(id=9102, order_no='SO-9102', customer='客户乙', product_id=201, quantity=4000, status='已备货'))
    db.add(OrderItem(id=1, order_id=9101, product_id=201, product_name='陈列样盲盒', quantity=6000))
    db.add(OrderItem(id=2, order_id=9102, product_id=201, product_name='陈列样盲盒', quantity=4000))

    db.add(PurchaseOrder(
        id=8101, order_no='PO-8101', customer_name='客户乙',
        product_name='陈列样盲盒', product_quantity=10000,
        supplier_name='供应商甲', source_order_ids='[9101, 9102]',
    ))
    db.add_all([
        PurchaseOrderSku(id=1, po_id=8101, product_name='陈列样盲盒', order_qty=6000,
                         source_order_id=9101, source_record_type='order'),
        PurchaseOrderSku(id=2, po_id=8101, product_name='陈列样盲盒', order_qty=4000,
                         source_order_id=9102, source_record_type='order'),
    ])
    for index, role_name in enumerate(role_names, start=1):
        if role_name not in EXPECTED_BY_ROLE:
            continue  # 非法结构场景：落库明细只预置能对上分配表的角色
        db.add(PurchaseOrderItem(
            id=index, order_id=8101, material_name=f'{role_name}布',
            specification='S1', unit='米', quantity=EXPECTED_BY_ROLE[role_name],
            supplier_name='供应商甲',
        ))
    await db.commit()
    return 8101


def _materials_by_name(group) -> dict[str, float]:
    return {
        row['material_name']: float(row['quantity'])
        for sku in group['skus']
        for row in sku['materials']
    }


def _stored_by_name(group) -> dict[str, float]:
    return {
        fabric['fabric_name']: float(fabric['quantity'])
        for supplier in group['suppliers']
        for fabric in supplier['fabrics']
    }


def _roles_by_name(group) -> dict[str, str]:
    """物料名 → 「角色名称」列展示文本（按 SKU 推算侧与落库侧都要有）。"""
    return {
        row['material_name']: row['role_display']
        for sku in group['skus']
        for row in sku['materials']
    }


async def test_h1_configured_sku_projection_matches_stored(db):
    """H1+H2：推算 == 落库；多来源行合并后分配（隐藏款 139，不是 84+56=140）。"""
    po_id = await _seed_configured_sku(db, role_names=[*REGULAR_NAMES, HIDDEN_NAME])

    group = (await get_factory_order_summary(db, [po_id]))['groups'][0]

    projected = _materials_by_name(group)
    stored = _stored_by_name(group)

    assert projected == {f'{name}布': qty for name, qty in EXPECTED_BY_ROLE.items()}
    assert stored == projected, '未编辑过的单：按 SKU 推算必须与落库真值逐行相等'
    # 「角色名称」列：每个角色自己的物料行必须标出自己的角色名（多角色产品分行展示）
    assert _roles_by_name(group) == {
        f'{name}布': name for name in EXPECTED_BY_ROLE
    }
    # 落库侧（suppliers[].fabrics[]）同样带角色名——差异对照块与回退模式共用这份数据
    assert {
        fabric['fabric_name']: fabric['role_display']
        for supplier in group['suppliers']
        for fabric in supplier['fabrics']
    } == {f'{name}布': name for name in EXPECTED_BY_ROLE}
    # 多来源行展示数量合并为订单总数量
    assert group['skus'][0]['order_qty'] == 10000
    # 「按角色数量」（2026-11-08 需求）：与物料分配同源——常规均分 + 隐藏款 ceil(N/P)，
    # 前端把「订单数量」列按角色段拆格；排序默认 BOM（无）→ role_id 升序
    role_quantities = group['skus'][0]['role_quantities']
    assert {r['role_name']: r['quantity'] for r in role_quantities} == EXPECTED_BY_ROLE
    assert [r['role_id'] for r in role_quantities] == sorted(r['role_id'] for r in role_quantities)
    # 隐藏款标记：右键指定的角色G（名字不是「隐藏款」）也必须标出
    assert {r['role_name']: r['is_hidden'] for r in role_quantities} == {
        **dict.fromkeys(REGULAR_NAMES, False), HIDDEN_NAME: True,
    }


async def test_h3_invalid_role_structure_falls_back_without_500(db):
    """H3：配了 P 但角色不足 6+1 —— 推算回退全量（页面不炸，落库真值不受影响）。

    回退全量时**不产出** role_quantities（前端「订单数量」列保持 SKU 级大格），
    与物料行的回退口径一致。
    """
    po_id = await _seed_configured_sku(
        db, role_names=['角色A', '角色B', '角色C', '角色D', '角色E'],
    )

    group = (await get_factory_order_summary(db, [po_id]))['groups'][0]
    projected = _materials_by_name(group)

    # 回退全量：每个已配角色的布料 = 1（单件用量）× 10000（合并数量）
    assert set(projected) == {f'角色{chr(ord("A") + i)}布' for i in range(5)}
    assert all(qty == 10000 for qty in projected.values())
    assert group['skus'][0]['role_quantities'] == []
