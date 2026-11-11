"""工厂内部订单「产品部位」拆行 / 旧单回退回归测试。

需求：同一物料用于多个部位时，工厂汇总按部位拆行；旧采购明细没有 part_name 时
按物料合并，绝不重复计量或让两行共用同一 item_ids。
"""
import re
from types import SimpleNamespace

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services.purchase_order_generate import _material_row
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

MATERIAL = '面料A'
SPEC = 'S1'
UNIT = '米'


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    tables = [
        PurchaseOrder.__table__, PurchaseOrderItem.__table__, PurchaseOrderSku.__table__,
        Order.__table__, OrderItem.__table__, Product.__table__,
        ProductFabric.__table__, ProductAccessory.__table__, ProductMaterial.__table__,
        # 角色名并入产品查询（LEFT JOIN product_role）——「角色名称」列的数据源
        ProductRole.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed(
    db: AsyncSession,
    *,
    po_id: int = 8001,
    item_parts: tuple[str | None, str | None] = ('身体', '头部'),
    bom_parts: tuple[str | None, str | None] = ('身体', '头部'),
    quantities: tuple[float, float] = (12, 8),
    order_id: int = 9001,
    order_item_id: int = 1,
    sku_id: int = 1,
    with_product: bool = True,
    with_bom: bool = True,
) -> int:
    """一个产品、两条同物料不同部位的 BOM 行 + 一条采购单。

    用量 0.12 / 0.08 × 订单 100 = 12 / 8，与落库明细一致。
    ``with_bom=False``：只建采购单与明细、不建 BOM 行（用于「BOM 不可用回退」与
    「组内旧单无 BOM」场景；同产品第二张单不再重复加 BOM，避免同键 BOM 行翻倍）。
    """
    if with_product:
        db.add(Product(id=101, name='产品A'))
    if with_bom:
        db.add(ProductFabric(
            id=po_id * 10 + 1, product_id=101, fabric_name=MATERIAL, specification=SPEC, unit=UNIT,
            quantity=0.12, supplier_name='供应商甲', part_name=bom_parts[0],
        ))
        db.add(ProductFabric(
            id=po_id * 10 + 2, product_id=101, fabric_name=MATERIAL, specification=SPEC, unit=UNIT,
            quantity=0.08, supplier_name='供应商甲', part_name=bom_parts[1],
        ))
    db.add(Order(id=order_id, order_no=f'SO-{order_id}', customer='客户甲',
                 product_id=101, quantity=100, status='待备货'))
    db.add(OrderItem(id=order_item_id, order_id=order_id, product_id=101,
                     product_name='产品A', quantity=100))
    db.add(PurchaseOrder(
        id=po_id, order_no=f'PO-{po_id}', customer_name='客户甲', product_name='产品A',
        product_quantity=100, supplier_name='供应商甲', source_order_ids=f'[{order_id}]',
    ))
    db.add(PurchaseOrderItem(
        id=po_id * 10 + 1, order_id=po_id, material_name=MATERIAL, specification=SPEC,
        unit=UNIT, quantity=quantities[0], supplier_name='供应商甲', part_name=item_parts[0],
    ))
    db.add(PurchaseOrderItem(
        id=po_id * 10 + 2, order_id=po_id, material_name=MATERIAL, specification=SPEC,
        unit=UNIT, quantity=quantities[1], supplier_name='供应商甲', part_name=item_parts[1],
    ))
    db.add(PurchaseOrderSku(
        id=sku_id, po_id=po_id, product_name='产品A', product_barcode='bA',
        order_qty=100, source_order_id=order_id, source_record_type='order',
    ))
    await db.commit()
    return po_id


def _fabrics(group) -> list[dict]:
    return [f for sup in group['suppliers'] for f in sup['fabrics']]


async def test_new_order_splits_same_material_by_part(db):
    """新单：同物料两个部位 → 两条 fabric 行，item_ids 不重叠，数量各取落库值。"""
    session = db
    po_id = await _seed(session)

    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]
    fabrics = _fabrics(group)

    by_part = {f.get('part_name'): f for f in fabrics}
    assert set(by_part) == {'身体', '头部'}
    assert float(by_part['身体']['quantity']) == 12
    assert float(by_part['头部']['quantity']) == 8
    assert list(by_part['身体']['item_ids']) == [po_id * 10 + 1]
    assert list(by_part['头部']['item_ids']) == [po_id * 10 + 2]
    assert set(by_part['身体']['item_ids']).isdisjoint(by_part['头部']['item_ids'])

    # 按 SKU 展开的物料也按部位两行
    sku_materials = group['skus'][0]['materials']
    by_part_sku = {m.get('part_name'): m for m in sku_materials}
    assert set(by_part_sku) == {'身体', '头部'}
    assert float(by_part_sku['身体']['quantity']) == 12
    assert float(by_part_sku['头部']['quantity']) == 8


async def test_legacy_order_without_item_part_names_splits_by_bom(db):
    """旧单（明细无 part_name）也按 BOM 拆行：BOM 是唯一真源，不再静默合并。

    2026-11-11 用户裁决：拆行判定改为 **BOM 感知**（旧口径「任一明细缺部位就整组
    合并」会把同物料跨部位并成一行）。历史未同步单的明细匹配不到带部位的 BOM 行，
    行按 BOM 用量给出推算值、item_ids 为空 —— 由前端「推算 vs 实际」差异横幅暴露，
    交 backfill 校正；绝不静默合并冒充一致。
    """
    session = db
    po_id = await _seed(session, item_parts=(None, None))

    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]
    fabrics = _fabrics(group)

    by_part = {f.get('part_name'): f for f in fabrics}
    assert set(by_part) == {'身体', '头部'}, 'BOM 有部位就必须拆行'
    assert float(by_part['身体']['quantity']) == 12
    assert float(by_part['头部']['quantity']) == 8
    # 明细无部位 → 匹配不到带部位的 BOM 行 → 纯推算行（只读），差异交给前端横幅
    assert by_part['身体']['item_ids'] == []
    assert by_part['头部']['item_ids'] == []

    sku_materials = group['skus'][0]['materials']
    by_part_sku = {m.get('part_name'): m for m in sku_materials}
    assert set(by_part_sku) == {'身体', '头部'}
    assert float(by_part_sku['身体']['quantity']) == 12
    assert float(by_part_sku['头部']['quantity']) == 8


async def test_bom_unavailable_fallback_still_shows_item_parts(db):
    """BOM 完全不可用（回退用采购明细）时，「产品部位」列仍须显示明细自带的部位。

    2026-11-05 生产缺陷（整列空白）的同类保证在新的路径下继续成立：BOM 有部位时
    走拆行（每行 ``part_display`` = 自己的部位）；BOM 不可用时回退
    ``_accumulate_factory_po_items``，必须把明细的 part_name 带进聚合键与展示文本。
    """
    session = db
    session.add_all([
        Product(id=101, name='产品A'),
        Order(id=9001, order_no='SO-9001', customer='客户甲',
              product_id=101, quantity=100, status='待备货'),
        OrderItem(id=1, order_id=9001, product_id=101, product_name='产品A', quantity=100),
        PurchaseOrder(id=8001, order_no='PO-8001', customer_name='客户甲',
                      product_name='产品A', product_quantity=100,
                      supplier_name='供应商甲', source_order_ids='[9001]'),
        PurchaseOrderItem(id=1, order_id=8001, material_name=MATERIAL, specification=SPEC,
                          unit=UNIT, quantity=12, supplier_name='供应商甲', part_name='身体'),
        PurchaseOrderItem(id=2, order_id=8001, material_name=MATERIAL, specification=SPEC,
                          unit=UNIT, quantity=8, supplier_name='供应商甲', part_name='头部'),
        PurchaseOrderSku(id=1, po_id=8001, product_name='产品A', product_barcode='bA',
                         order_qty=100, source_order_id=9001, source_record_type='order'),
    ])
    await session.commit()

    group = (await get_factory_order_summary(session, [8001]))['groups'][0]
    by_part = {f.get('part_name'): f for f in _fabrics(group)}

    assert set(by_part) == {'身体', '头部'}
    assert float(by_part['身体']['quantity']) == 12
    assert float(by_part['头部']['quantity']) == 8
    assert by_part['身体']['part_display'] == '身体'
    assert by_part['头部']['part_display'] == '头部'
    assert list(by_part['身体']['item_ids']) == [1]
    assert list(by_part['头部']['item_ids']) == [2]


async def test_cross_sku_shared_material_lists_every_sku_part(db):
    """2 个 SKU 共用同一物料、各用在**不同部位**：每个 SKU 的部位都各自成行。

    BOM 感知拆行（2026-11-11）后，落库明细由同步保证与 BOM 同形（身体/头部各一行）；
    工厂页据此拆成两行、各挂自己的明细 —— 两个 SKU 的部位都必须出现，谁也不能被
    合并行冒充。`skus[].materials` 是逐 SKU 口径：各 SKU 只含自己的部位。
    """
    session = db
    session.add_all([
        Product(id=101, name='产品A'),
        Product(id=102, name='产品B'),
        # 同一物料、同一规格/单位，两个 SKU 分别用在「身体」「头部」
        ProductFabric(
            id=1, product_id=101, fabric_name=MATERIAL, specification=SPEC, unit=UNIT,
            quantity=0.3, supplier_name='供应商甲', part_name='身体',
        ),
        ProductFabric(
            id=2, product_id=102, fabric_name=MATERIAL, specification=SPEC, unit=UNIT,
            quantity=0.3, supplier_name='供应商甲', part_name='头部',
        ),
        Order(id=9001, order_no='SO-9001', customer='客户甲',
              product_id=101, quantity=200, status='待备货'),
        OrderItem(id=1, order_id=9001, product_id=101, product_name='产品A', quantity=100),
        OrderItem(id=2, order_id=9001, product_id=102, product_name='产品B', quantity=100),
        PurchaseOrder(
            id=8001, order_no='PO-8001', customer_name='客户甲', product_name='产品A、产品B',
            product_quantity=200, supplier_name='供应商甲', source_order_ids='[9001]',
        ),
        # 同步后的明细：同一物料两行，各自带部位（0.3 × 各 100 件 = 30）
        PurchaseOrderItem(
            id=1, order_id=8001, material_name=MATERIAL, specification=SPEC, unit=UNIT,
            quantity=30, supplier_name='供应商甲', part_name='身体',
        ),
        PurchaseOrderItem(
            id=2, order_id=8001, material_name=MATERIAL, specification=SPEC, unit=UNIT,
            quantity=30, supplier_name='供应商甲', part_name='头部',
        ),
        PurchaseOrderSku(
            id=1, po_id=8001, product_name='产品A', product_barcode='bA',
            order_qty=100, source_order_id=9001, source_record_type='order',
        ),
        PurchaseOrderSku(
            id=2, po_id=8001, product_name='产品B', product_barcode='bB',
            order_qty=100, source_order_id=9001, source_record_type='order',
        ),
    ])
    await session.commit()

    group = (await get_factory_order_summary(session, [8001]))['groups'][0]

    fabrics = _fabrics(group)
    by_part = {f.get('part_name'): f for f in fabrics}
    assert set(by_part) == {'身体', '头部'}, '两个 SKU 的部位都必须成行'
    assert float(by_part['身体']['quantity']) == 30
    assert float(by_part['头部']['quantity']) == 30
    assert list(by_part['身体']['item_ids']) == [1]
    assert list(by_part['头部']['item_ids']) == [2]
    assert set(by_part['身体']['item_ids']).isdisjoint(by_part['头部']['item_ids']), \
        '同一份明细只能挂一次，不得因跨 SKU 共享而重复'

    materials_by_sku = {s['product_name']: s['materials'] for s in group['skus']}
    assert [(m['part_display'], float(m['quantity'])) for m in materials_by_sku['产品A']] == [
        ('身体', 30.0),
    ]
    assert [(m['part_display'], float(m['quantity'])) for m in materials_by_sku['产品B']] == [
        ('头部', 30.0),
    ]


def test_finalize_sku_materials_is_idempotent():
    """QA Low-2：`_finalize_factory_sku_materials` 连续调用两次，展示文本不得被抹成空串。"""
    from fastapi_app.services.purchase._factory import _finalize_factory_sku_materials

    group_map = {
        ('客户甲', '产品A'): {
            '_sku_materials': {
                '产品A': {
                    ('供应商甲', MATERIAL, SPEC, UNIT, ''): {
                        'supplier_name': '供应商甲', 'material_name': MATERIAL,
                        'part_name': None, 'specification': SPEC, 'unit': UNIT,
                        'quantity': 12, '_part_names': ['身体', '头部'], '_part_unknown': False,
                    },
                },
            },
        },
    }

    _finalize_factory_sku_materials(group_map)
    first = group_map[('客户甲', '产品A')]['_sku_materials']['产品A']
    assert first[0]['part_display'] == '身体/头部'
    assert '_part_names' not in first[0], '内部记账字段不得泄漏进接口'

    # 二次调用（同一份 group_map，此时 _sku_materials 已定稿为 list）
    _finalize_factory_sku_materials(group_map)
    second = group_map[('客户甲', '产品A')]['_sku_materials']['产品A']

    assert second[0]['part_display'] == '身体/头部', '二次定稿不得把展示文本清成空串'
    assert second == first, '二次定稿必须逐字段等价（幂等）'


def test_finalize_sku_materials_keeps_accumulator_state():
    """定稿必须**复制**行、不能就地 pop —— 就地会毁掉累加态，部位再也算不出来。

    这条锁的是 `dict(row)` 的理由（与 `_serialize_factory_groups` 同写法）：定稿是
    「把累加态投影成接口形状」，不该反过来破坏累加态；同一份 group_map 若还要再定稿、
    或将来有第二个消费方要读部位，就地 pop 会让它们只能拿到空串。
    """
    from fastapi_app.services.purchase._factory import _finalize_factory_sku_materials

    bucket_key = ('供应商甲', MATERIAL, SPEC, UNIT, '')
    bucket_row = {
        'supplier_name': '供应商甲', 'material_name': MATERIAL,
        'part_name': None, 'specification': SPEC, 'unit': UNIT,
        'quantity': 12, '_part_names': ['身体'], '_part_unknown': False,
    }
    group_map = {('客户甲', '产品A'): {'_sku_materials': {'产品A': {bucket_key: bucket_row}}}}

    _finalize_factory_sku_materials(group_map)

    # 定稿产出了 part_display，但**源桶的记账字段必须还在**
    assert group_map[('客户甲', '产品A')]['_sku_materials']['产品A'][0]['part_display'] == '身体'
    assert bucket_row['_part_names'] == ['身体'], '就地 pop 会破掉累加态（必须复制后定稿）'
    assert bucket_row['_part_unknown'] is False


async def test_mixed_part_bom_splits_and_keeps_partless_row(db):
    """BOM 自身混有部位/无部位行时仍按部位拆行：无部位行单独成行。

    旧口径在合并行里用「身体/未标注」提示混合；BOM 感知拆行后每一行只覆盖一个
    部位键（``part_key=''`` 表示无部位行），行内不会再混入「已知 + 未标注」，
    故该标记不再出现 —— 无部位行以空 ``part_display`` 单独展示。
    """
    session = db
    po_id = await _seed(session, item_parts=(None, None), bom_parts=('身体', None))

    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]
    fabrics = _fabrics(group)

    by_part = {f.get('part_name') or '': f for f in fabrics}
    assert set(by_part) == {'身体', ''}, '无部位 BOM 行必须单独成行，不得并进带部位行'
    assert float(by_part['身体']['quantity']) == 12
    assert by_part['身体']['part_display'] == '身体'
    # 无部位 BOM 行精确匹配两条无部位旧明细（12+8=20）；带部位行匹配不到 → 按 BOM 推算 12。
    # 推算 32 ≠ 落库 20，会以差异横幅暴露 —— 这正是「不静默合并」的目的（backfill 校正）。
    assert float(by_part['']['quantity']) == 20
    assert list(by_part['']['item_ids']) == [80011, 80012]
    assert by_part['']['part_display'] == ''

    sku_materials = group['skus'][0]['materials']
    by_part_sku = {m.get('part_name') or '': m for m in sku_materials}
    assert set(by_part_sku) == {'身体', ''}
    assert float(by_part_sku['身体']['quantity']) == 12
    assert float(by_part_sku['']['quantity']) == 8, '按 SKU 推算只看 BOM 用量（无部位行 0.08×100）'


async def test_no_part_anywhere_stays_blank_instead_of_noise(db):
    """BOM 与明细都没部位 → 展示仍为空（数据缺失），不给每一行添「未标注」噪声。"""
    session = db
    po_id = await _seed(session, item_parts=(None, None), bom_parts=(None, None))

    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]

    assert _fabrics(group)[0]['part_display'] == ''
    assert group['skus'][0]['materials'][0]['part_display'] == ''


async def test_split_mode_part_display_equals_part_name(db):
    """拆行模式（明细带部位）：展示文本逐字等于聚合键部位，零变化。"""
    session = db
    po_id = await _seed(session)

    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]

    for fabric in _fabrics(group):
        assert fabric['part_display'] == fabric['part_name']
    for material in group['skus'][0]['materials']:
        assert material['part_display'] == material['part_name']
    # 内部记账字段不得泄漏进接口
    for fabric in _fabrics(group):
        assert '_part_names' not in fabric
        assert '_part_unknown' not in fabric



async def test_mixed_group_splits_when_any_po_bom_has_parts(db):
    """混合组：组内任一 PO 的 BOM 有部位 → 整组拆行（组级取 OR）。

    旧口径「任一旧单无部位明细就整组合并」会把另一张新单的部位拆行一起压掉。
    新口径：组键 (客户, 产品名) 共用同一套聚合键，拆行判定按组 OR —— 新单的
    部位照常拆行；旧单（明细无部位）按 BOM 推算，差异由前端横幅暴露。
    """
    session = db
    await _seed(session, po_id=8001)
    await _seed(
        session, po_id=8002, item_parts=(None, None), quantities=(5, 5),
        order_id=9002, order_item_id=2, sku_id=2, with_product=False, with_bom=False,
    )

    group = (await get_factory_order_summary(session, [8001, 8002]))['groups'][0]
    by_part = {f.get('part_name'): f for f in _fabrics(group)}

    assert set(by_part) == {'身体', '头部'}, '组内任一单 BOM 有部位 → 整组拆行'
    # 8001 明细精确命中 12 / 8；8002 无部位明细匹配不到 → 按同一份 BOM 推算 12 / 8
    assert float(by_part['身体']['quantity']) == 24
    assert float(by_part['头部']['quantity']) == 16
    assert list(by_part['身体']['item_ids']) == [80011]
    assert list(by_part['头部']['item_ids']) == [80012]


def test_material_row_carries_part_name():
    """生成采购明细的 dict 必须携带 BOM 行的 part_name。"""
    spec = SimpleNamespace(
        usage_attr='quantity', name_attr='fabric_name', default_name='面料',
        default_unit='米', category='fabric',
    )
    row = SimpleNamespace(
        fabric_name=MATERIAL,
        quantity=0.12, material_code='M1', specification=SPEC, unit=UNIT,
        supplier_name='供应商甲', supplier_id=1, part_name='身体',
    )

    result = _material_row(spec, row, 100, '产品A', '客户甲', '默认BOM')

    assert result['part_name'] == '身体'
    assert result['quantity'] == 12


def test_backend_factory_print_has_part_column():
    """后端工厂汇总打印同步 8 列：表头与行都带产品部位，且部位列在供应商列之前。"""
    from fastapi_app.api.v1.endpoints.purchase_center.export_utils import (
        generate_factory_summary_print,
    )

    order = SimpleNamespace(
        id=1, order_no='PO-1', source_order_id=None, product_name='产品A',
        product_quantity=100, customer_name='客户甲', supplier_name='供应商甲',
    )
    item = SimpleNamespace(
        material_name=MATERIAL, specification=SPEC, unit=UNIT, quantity=12,
        supplier_name='供应商甲', part_name='身体',
    )

    html = generate_factory_summary_print([order], {1: [item]})

    assert '<th>产品部位</th>' in html
    assert '<td style="text-align:left">身体</td>' in html
    # 列序（2026-11-05 用户要求）：产品部位在供应商之前
    assert html.index('<th>产品部位</th>') < html.index('<th>供应商</th>')
    # 行内同序：部位单元格必须排在供应商单元格之前（防「表头换了、值串列」）
    assert html.index('<td style="text-align:left">身体</td>') < html.index('>供应商甲</td>')


def _row_widths(page: str) -> list[int]:
    """把打印页每行（含表头/数据/表尾）的**有效列数**算出来。

    规则与浏览器一致：`colspan` 按数展开、`rowspan` 在后续行占位（占位列也算宽度）。
    用于锁住列位置对调后「表头 8 列 == 每个数据行 8 列 == 表尾合计 8 列」——
    colspan 少改/多改一处、或把某个 rowspan 挂错格，这里都会变红。
    """
    occupied: list[int] = []   # occupied[j] = 该列后续还要被上方 rowspan 覆盖的行数
    widths: list[int] = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', page, re.S):
        col = 0
        consumed: list[int] = []   # 本行被上方 rowspan 占掉的列（消费一次要减一）
        for _tag, attrs in re.findall(r'<(td|th)([^>]*)>', tr):
            while col < len(occupied) and occupied[col] > 0:
                consumed.append(col)
                col += 1
            colspan_m = re.search(r'colspan="(\d+)"', attrs)
            rowspan_m = re.search(r'rowspan="(\d+)"', attrs)
            colspan = int(colspan_m.group(1)) if colspan_m else 1
            rowspan = int(rowspan_m.group(1)) if rowspan_m else 1
            for k in range(colspan):
                idx = col + k
                while idx >= len(occupied):
                    occupied.append(0)
                occupied[idx] = max(occupied[idx], rowspan - 1)
            col += colspan
        while col < len(occupied) and occupied[col] > 0:
            consumed.append(col)
            col += 1
        widths.append(col)
        for j in consumed:
            occupied[j] = max(0, occupied[j] - 1)
    return widths


def test_backend_factory_print_all_rows_width_equals_header():
    """单角色/无角色订单：隐藏「角色名称」列，表头 8 列（客户/产品名称/订单数量/产品部位/
    供应商/布料名称/规格型号/数量+单位）；列宽必须与表头一致（2026-11-08 用户要求）。"""
    from fastapi_app.api.v1.endpoints.purchase_center.export_utils import (
        generate_factory_summary_print,
    )

    order = SimpleNamespace(
        id=1, order_no='PO-1', source_order_id=None, product_name='产品A',
        product_quantity=100, customer_name='客户甲', supplier_name='供应商甲',
    )
    items = [
        SimpleNamespace(
            material_name='面料A', specification='S1', unit='米', quantity=12,
            supplier_name='供应商甲', part_name='身体',
        ),
        SimpleNamespace(
            material_name='面料B', specification='S2', unit='米', quantity=8,
            supplier_name='供应商乙', part_name='头部',
        ),
    ]

    html = generate_factory_summary_print([order], {1: items})

    header_width = html.count('<th>')
    assert header_width == 8, '单角色订单必须隐藏角色名称列（8 列）'
    assert '<th>角色名称</th>' not in html
    widths = _row_widths(html)
    assert widths, '打印页必须至少有一行数据'
    assert set(widths) == {header_width}, f'列数不齐：{widths} != {header_width}'


async def test_po_with_mixed_part_and_null_items_splits(db):
    """一张 PO 内混有带部位与无部位明细 → 按 BOM 拆行，无部位明细单独成行。

    这是 2026-11-11 用户裁决 #5 的核心场景（绿色超柔 身体/脚底 + 木棒无部位）：
    旧口径「任一明细缺部位整组合并」会让身体/脚底并成一行；新口径下无部位明细
    用 ``part_key=''`` 精确命中无部位 BOM 行，不阻塞拆行、也不丢数量。
    """
    session = db
    po_id = await _seed(session, item_parts=('身体', None), bom_parts=('身体', None))

    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]
    fabrics = _fabrics(group)

    by_part = {f.get('part_name') or '': f for f in fabrics}
    assert set(by_part) == {'身体', ''}
    assert float(by_part['身体']['quantity']) == 12
    assert float(by_part['']['quantity']) == 8
    assert list(by_part['身体']['item_ids']) == [80011]
    assert list(by_part['']['item_ids']) == [80012]


def test_backend_factory_print_mixed_parts_merges():
    """后端打印与屏幕同口径：PO 内混有无部位明细时按物料合并，不拆两行。"""
    from fastapi_app.api.v1.endpoints.purchase_center.export_utils import (
        generate_factory_summary_print,
    )

    order = SimpleNamespace(
        id=1, order_no='PO-1', source_order_id=None, product_name='产品A',
        product_quantity=100, customer_name='客户甲', supplier_name='供应商甲',
    )
    items = [
        SimpleNamespace(
            material_name=MATERIAL, specification=SPEC, unit=UNIT, quantity=12,
            supplier_name='供应商甲', part_name='身体',
        ),
        SimpleNamespace(
            material_name=MATERIAL, specification=SPEC, unit=UNIT, quantity=8,
            supplier_name='供应商甲', part_name=None,
        ),
    ]

    html = generate_factory_summary_print([order], {1: items})

    assert '<th>产品部位</th>' in html
    # 合并行覆盖「身体」+ 一条无部位明细 → 展示「身体/未标注」：既列出已知部位，
    # 又用固定标记说明这一行还有未标注明细，不用「身体」冒充全量。
    assert '<td style="text-align:left">身体/未标注</td>' in html
    assert '>20.0 米<' in html


async def test_stockin_po_without_source_order_ids_loads_live_bom(db):
    """备货来源采购单没有 PO.source_order_ids 时，仍应从 purchase_order_sku 解析产品并加载当前 BOM。"""
    session = db
    session.add(Product(id=101, name='产品A'))
    session.add_all([
        ProductFabric(
            id=1, product_id=101, fabric_name='面料A', specification='S1', unit='米',
            quantity=0.12, supplier_name='供应商甲', part_name='身体',
        ),
        ProductFabric(
            id=2, product_id=101, fabric_name='面料B', specification='S2', unit='米',
            quantity=0.08, supplier_name='供应商甲', part_name='头部',
        ),
    ])
    session.add(PurchaseOrder(
        id=8001, order_no='PO-8001', customer_name='客户甲', product_name='产品A',
        product_quantity=1000, supplier_name='供应商甲', source_order_ids=None,
    ))
    session.add(PurchaseOrderItem(
        id=1, order_id=8001, material_name='面料A', specification='S1', unit='米',
        quantity=120, supplier_name='供应商甲', part_name=None,
    ))
    session.add(PurchaseOrderSku(
        id=1, po_id=8001, product_name='产品A', product_barcode='bA',
        order_qty=1000, source_order_id=87300, source_record_type='stockin',
    ))
    await session.commit()

    group = (await get_factory_order_summary(session, [8001]))['groups'][0]

    assert group['product_name'] == '产品A'
    fabrics = _fabrics(group)
    assert len(fabrics) == 2, '当前 BOM 的两行都应出现（不应退化成只有采购明细的一行）'
    by_name = {f['fabric_name']: f for f in fabrics}
    assert float(by_name['面料A']['quantity']) == 120
    assert float(by_name['面料B']['quantity']) == 80
    # 只在 BOM 侧的新行没有采购明细 → 只读
    assert by_name['面料B']['item_ids'] == []
    sku_materials = group['skus'][0]['materials']
    assert {m['material_name'] for m in sku_materials} == {'面料A', '面料B'}


# ===== 后端打印件：合并模式下部位必须来自 BOM（2026-11-07 评审 Low-1） =====


def _print_order(product_name: str = '产品A'):
    return SimpleNamespace(
        id=1, order_no='PO-1', source_order_id=None, product_name=product_name,
        product_quantity=100, customer_name='客户甲', supplier_name='供应商甲',
    )


def _print_item(part_name):
    return SimpleNamespace(
        material_name=MATERIAL, specification=SPEC, unit=UNIT, quantity=12,
        supplier_name='供应商甲', part_name=part_name,
    )


def test_backend_factory_print_uses_bom_parts_when_item_part_is_none():
    """缺陷本体：明细 part_name 为空（合并模式）时，靠 bom_part_map 印出 BOM 部位。

    修复前该列只能印空白，出现「屏幕有部位、打印空白」。
    """
    from fastapi_app.api.v1.endpoints.purchase_center.export_utils import (
        generate_factory_summary_print,
    )

    bom_part_map = {('产品A', MATERIAL, SPEC, UNIT): ['身体', '头部']}
    html = generate_factory_summary_print(
        [_print_order()], {1: [_print_item(None)]}, None, bom_part_map,
    )

    assert '<td style="text-align:left">身体/头部</td>' in html


def test_backend_factory_print_without_bom_map_keeps_legacy_blank():
    """零回归：旧调用方不传 bom_part_map 时，行为与改动前逐字一致（部位仍空）。

    锁住「参数缺省 = 纯明细口径」这条契约，防止后来者把 map 做成必填。
    """
    from fastapi_app.api.v1.endpoints.purchase_center.export_utils import (
        generate_factory_summary_print,
    )

    html = generate_factory_summary_print([_print_order()], {1: [_print_item(None)]})

    assert '<td style="text-align:left"></td>' in html
    assert '未标注' not in html, '不知道部位时不得凭空编造标记'


def test_backend_factory_print_item_part_wins_over_bom_map():
    """拆行模式：明细自带部位时优先用明细，不被 BOM 映射覆盖。"""
    from fastapi_app.api.v1.endpoints.purchase_center.export_utils import (
        generate_factory_summary_print,
    )

    bom_part_map = {('产品A', MATERIAL, SPEC, UNIT): ['别的部位']}
    html = generate_factory_summary_print(
        [_print_order()], {1: [_print_item('身体')]}, None, bom_part_map,
    )

    assert '<td style="text-align:left">身体</td>' in html
    assert '别的部位' not in html


async def test_build_bom_part_display_map_reads_bom_not_items(db):
    """印刷件的数据源：映射必须取自 BOM（明细无部位时也能拿到），并按产品名分键。"""
    from sqlalchemy import select

    from fastapi_app.services.purchase_order_query import build_bom_part_display_map
    from fastapi_app.shared_models import PurchaseOrder

    session = db
    po_id = await _seed(session, item_parts=(None, None))   # 明细无部位，BOM 有 身体/头部
    po = (await session.execute(
        select(PurchaseOrder).where(PurchaseOrder.id == po_id)
    )).scalars().first()

    part_map = await build_bom_part_display_map(session, [po])

    assert part_map[('产品A', MATERIAL, SPEC, UNIT)] == ['身体', '头部']


async def test_build_bom_part_display_map_empty_without_orders(db):
    """无单 → 空映射，且不发查询（防 N+1 / 无谓往返）。"""
    from fastapi_app.services.purchase_order_query import build_bom_part_display_map

    assert await build_bom_part_display_map(db, []) == {}

