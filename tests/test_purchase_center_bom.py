"""采购中心「是否有 BOM」判定口径回归（审计 M-13）

历史缺陷：判定 A（cotton_usage>0，产品页/计算器/搜索建议的 has_bom）与判定 B
（BOM 行存在，未处理列表/生成/撤销/同步）各算各的 —— 提交 cotton_usage=0 的填充行后
UI 显示「未配置 BOM」，待生成列表却照常放行、自动生成产出 quantity=0 的
「<产品>-填充物」明细（0 行进入采购单/汇总/导出）。

口径裁定（审计 M-13）：**0 用量填充行 = 无 BOM**。B 侧统一加
``cotton_usage IS NOT NULL AND cotton_usage > 0`` 过滤后，以下共用路径自动同口径：
- 未处理列表 has_bom 标记 / 自动生成候选（_unprocessed._fetch_bom_product_ids）
- 撤销守卫（purchase_order_revoke.revoke_pending_purchase_orders_for_product）
- 同步守卫（bom_sync.product_has_bom）
- 生成与同步的目标行（purchase_order_generate._load_bom_context → build_expected_items）
"""
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def db(test_engine):
    """函数级会话 + 事务回滚隔离（复用会话级 test_engine）。"""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()


async def _make_product(db, name: str):
    from fastapi_app.shared_models import Product

    product = Product(name=name, barcode=name, current_stock=0, initial_stock=0)
    db.add(product)
    await db.flush()
    return product


def _record(product_id: int, qty: int = 10) -> SimpleNamespace:
    """模拟单 SKU 源记录（StockIn 形态：无 items、用兼容字段）。"""
    return SimpleNamespace(
        items=[], product_id=product_id, quantity=qty, customer='客户A',
    )


async def test_zero_usage_filling_row_not_counted_as_bom(db):
    """cotton_usage=0 的填充行不算「有 BOM」——未处理列表 has_bom / 撤销 / 同步守卫共用。"""
    from fastapi_app.services.purchase._unprocessed import _fetch_bom_product_ids
    from fastapi_app.shared_models import ProductMaterial

    product = await _make_product(db, 'M13-零用量填充')
    db.add(ProductMaterial(product_id=product.id, cotton_usage=0, role_id=None))
    await db.flush()

    assert await _fetch_bom_product_ids(db, [product.id]) == set()


async def test_zero_usage_filling_row_missing_bom_and_no_purchase_row(db):
    """仅 0 用量填充行的产品：BOM 门控判缺 BOM，生成管道不产出任何采购明细。

    旧实现会产出 quantity=0 的「<产品>-填充物」行进入采购单。
    """
    from fastapi_app.services.purchase_order_generate import (
        _build_material_items,
        _load_bom_context,
        _missing_bom_products,
    )
    from fastapi_app.shared_models import ProductMaterial

    product = await _make_product(db, 'M13-零用量生成')
    db.add(ProductMaterial(product_id=product.id, cotton_usage=0, role_id=None))
    await db.flush()

    ctx = await _load_bom_context(db, [product.id])
    record = _record(product.id)
    # BOM 门控：该产品必须被判「未配置 BOM」
    assert _missing_bom_products([record], ctx, {product.id: product.name}) == [
        {'product_id': product.id, 'product_name': product.name},
    ]
    # 生成管道：零明细
    assert _build_material_items([record], ctx, {product.id: product.name}) == []


async def test_zero_usage_filling_with_real_fabric_still_has_bom_but_no_filling_row(db):
    """0 用量填充行 + 真实面料行：产品仍算有 BOM（面料），但不产出 0 用量填充明细。"""
    from fastapi_app.services.purchase._unprocessed import _fetch_bom_product_ids
    from fastapi_app.services.purchase_order_generate import (
        _build_material_items,
        _load_bom_context,
        _missing_bom_products,
    )
    from fastapi_app.shared_models import ProductFabric, ProductMaterial

    product = await _make_product(db, 'M13-零用量加面料')
    db.add(ProductMaterial(product_id=product.id, cotton_usage=0, role_id=None))
    db.add(ProductFabric(
        product_id=product.id, fabric_name='裙身面料', quantity=2.0, unit='米',
    ))
    await db.flush()

    # 面料行存在 → 有 BOM（与判定 A「面料任一存在即有 BOM」同口径）
    assert await _fetch_bom_product_ids(db, [product.id]) == {product.id}

    ctx = await _load_bom_context(db, [product.id])
    record = _record(product.id)
    assert _missing_bom_products([record], ctx, {product.id: product.name}) == []
    items = _build_material_items([record], ctx, {product.id: product.name})
    assert [it['material_name'] for it in items] == ['裙身面料']


async def test_positive_usage_filling_row_still_generates(db):
    """正例守卫：cotton_usage>0 的填充行零回归——门控放行且照常产出明细。"""
    from decimal import Decimal

    from fastapi_app.services.purchase._unprocessed import _fetch_bom_product_ids
    from fastapi_app.services.purchase_order_generate import (
        _build_material_items,
        _load_bom_context,
        _missing_bom_products,
    )
    from fastapi_app.shared_models import ProductMaterial

    product = await _make_product(db, 'M13-正例填充')
    db.add(ProductMaterial(
        product_id=product.id, cotton_usage=Decimal('100'), role_id=None,
    ))
    await db.flush()

    assert await _fetch_bom_product_ids(db, [product.id]) == {product.id}

    ctx = await _load_bom_context(db, [product.id])
    record = _record(product.id, qty=10)
    assert _missing_bom_products([record], ctx, {product.id: product.name}) == []
    items = _build_material_items([record], ctx, {product.id: product.name})
    assert [(it['material_name'], it['quantity']) for it in items] == [
        (f'{product.name}-填充物', 1000.0),
    ]
