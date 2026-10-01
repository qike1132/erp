"""
采购中心 - 产品/BOM 管理服务

从 purchase_center_service.py 拆分，包含产品查询、BOM 保存和物料计算。
"""
import logging
from collections.abc import Callable, Sequence
from decimal import Decimal
from functools import partial

from sqlalchemy import func, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.core.cache import cache_result
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.shared_models import (
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    ProductRole,
)
from fastapi_app.utils import calc_total_pages
from fastapi_app.utils.scope_order import order_scopes, scope_label

logger = logging.getLogger(__name__)


# BOM 领域逻辑已聚合到 bom_service.py，此处重新导出以保持向后兼容
# （purchase_bom_copy_service、purchase_center_service 等仍从此处导入）
from fastapi_app.services.bom_service import get_bom as get_product_bom  # noqa: F401
from fastapi_app.services.bom_service import has_bom as product_has_bom
from fastapi_app.services.bom_service import save_bom as save_product_bom  # noqa: F401


async def _batch_check_bom_exists(db: AsyncSession, product_ids: list[int]) -> set[int]:
    if not product_ids:
        return set()

    subq = union_all(
        select(ProductMaterial.product_id).where(
            ProductMaterial.product_id.in_(product_ids),
            ProductMaterial.cotton_usage > 0,
        ),
        select(ProductFabric.product_id).where(
            ProductFabric.product_id.in_(product_ids),
        ),
        select(ProductAccessory.product_id).where(
            ProductAccessory.product_id.in_(product_ids),
        ),
    )
    result = await db.execute(select(subq.c.product_id))
    return {row[0] for row in result}


@cache_result(
    key_prefix="purchase:products",
    ttl=60,
    key_builder=lambda **kwargs: (
        f"p{kwargs.get('page', 1)}:pp{kwargs.get('per_page', 50)}:"
        f"s{(kwargs.get('search', '') or '').strip().lower()}:"
        f"hb{kwargs.get('has_bom', 'all')}:c{kwargs.get('category', '')}:"
        f"sb{kwargs.get('sort_by', 'name')}:so{kwargs.get('sort_order', 'asc')}:"
        f"simp{kwargs.get('simple', False)}"
    ),
)
async def get_products(db: AsyncSession, *, page: int = 1, per_page: int = 50,
                       search: str = '', has_bom: str = 'all', category: str = '',
                       sort_by: str = 'name', sort_order: str = 'asc',
                       simple: bool = False) -> dict:
    query = select(Product)
    count_query = select(func.count(Product.id))

    if not simple:
        query = query.options(
            selectinload(Product.material),
            selectinload(Product.material_rows),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
        )

    if search:
        query = query.where(
            or_(
                Product.name.ilike(f'%{escape_like(search)}%'),
                Product.barcode.ilike(f'%{escape_like(search)}%')
            )
        )
        count_query = count_query.where(
            or_(
                Product.name.ilike(f'%{escape_like(search)}%'),
                Product.barcode.ilike(f'%{escape_like(search)}%')
            )
        )

    if has_bom == 'true':
        query = query.where(Product.material_rows.any())
        count_query = count_query.where(Product.material_rows.any())
    elif has_bom == 'false':
        query = query.where(~Product.material_rows.any())
        count_query = count_query.where(~Product.material_rows.any())

    if category:
        if category == 'filling':
            query = query.where(Product.material_rows.any())
            count_query = count_query.where(Product.material_rows.any())
        elif category == 'fabric':
            query = query.where(Product.fabrics.any())
            count_query = count_query.where(Product.fabrics.any())
        elif category == 'accessory':
            query = query.where(Product.accessories.any())
            count_query = count_query.where(Product.accessories.any())

    sort_map = {
        'name': Product.name,
        'barcode': Product.barcode,
        'create_time': Product.create_time,
    }
    sort_col = sort_map.get(sort_by, Product.name)
    # P2-A2 类型收窄：desc 分支在 order_by 实参上求值，避免把 UnaryExpression 赋回原变量（排序语义不变）
    if sort_order == 'desc':
        query = query.order_by(sort_col.desc())
    else:
        query = query.order_by(sort_col)

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    products = result.scalars().unique().all()

    if simple:
        product_ids = [p.id for p in products]
        bom_product_ids = await _batch_check_bom_exists(db, product_ids)
        output = []
        for p in products:
            output.append({
                'id': p.id,
                'name': p.name,
                'barcode': p.barcode,
                'has_bom': p.id in bom_product_ids,
            })
        return {
            'products': output,
            'total': len(output),
            'pages': 1,
            'current_page': page,
        }

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    output = []
    for p in products:
        has_bom_flag = product_has_bom(p)
        bom_info = {}
        if has_bom_flag:
            bom_info = {
                'filling_count': sum(1 for m in p.material_rows if m.cotton_usage and m.cotton_usage > 0),
                'fabric_count': len(p.fabrics),
                'accessory_count': len(p.accessories),
            }
        output.append({
            'id': p.id,
            'name': p.name,
            'barcode': p.barcode,
            'price': float(p.price) if p.price else 0,
            'has_bom': has_bom_flag,
            'bom_info': bom_info,
            'current_stock': p.current_stock,
        })

    return {
        'products': output,
        'total': total,
        'pages': calc_total_pages(total, per_page),
        'current_page': page,
    }


async def get_products_batch_bom(db: AsyncSession, product_ids_str: str) -> dict:
    if not product_ids_str:
        return {'products': {}}

    try:
        pid_list = [int(x) for x in product_ids_str.split(',') if x.strip().isdigit()]
    except ValueError:
        return {'products': {}}

    result = await db.execute(
        select(Product).options(
            selectinload(Product.material),
            selectinload(Product.material_rows),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
        ).where(Product.id.in_(pid_list))
    )
    products = result.scalars().unique().all()

    output = {}
    for p in products:
        if p.has_bom():
            all_mats = p.get_all_materials()
            output[str(p.id)] = {
                'name': p.name,
                'barcode': p.barcode,
                'materials': all_mats,
            }
    return {'products': output}


async def get_search_suggestions(db: AsyncSession, keyword: str) -> list:
    if not keyword or len(keyword) < 1:
        return []

    result = await db.execute(
        select(Product).where(
            or_(
                Product.name.ilike(f'%{escape_like(keyword)}%'),
                Product.barcode.ilike(f'%{escape_like(keyword)}%')
            )
        ).limit(10)
    )
    products = result.scalars().all()

    product_ids = [p.id for p in products]
    bom_product_ids = await _batch_check_bom_exists(db, product_ids)

    return [
        {
            'id': p.id, 'name': p.name, 'barcode': p.barcode,
            'price': float(p.price) if p.price else 0,
            'has_bom': p.id in bom_product_ids,
        }
        for p in products
    ]


async def get_products_statistics(db: AsyncSession) -> dict:
    total_result = await db.execute(select(func.count(Product.id)))
    total = total_result.scalar() or 0

    has_bom_result = await db.execute(
        select(func.count(Product.id)).where(Product.material_rows.any())
    )
    has_bom = has_bom_result.scalar() or 0

    return {
        'total': total,
        'has_bom': has_bom,
        'no_bom': total - has_bom,
    }


def _accumulate_bom_rows(
    totals: dict[tuple, dict], rows: list, quantity: Decimal,
) -> None:
    """把一组带 ``category`` 的 BOM 行累加进 ``totals``（聚合内核，纯函数）。

    聚合 key = ``(分类, 物料名, 供应商, 规格)``：必须含供应商与规格，避免同名不同
    供应商/规格的物料被错误合并；使用元组而非字符串拼接，杜绝分隔符 ':' 导致的键冲突。

    Args:
        totals: 累加容器 ``{(cat, name, supplier, spec): bucket}``；**就地修改**。
        rows: BOM 行字典列表（含 category/material_name/supplier_name/specification/
            unit/unit_usage/material_code）。
        quantity: 该组行共用的数量乘子（订单总数量，不分摊）。
    """
    for mat in rows:
        category = mat.get('category', '')
        # 文本字段一律归一：三张物料表的 material_code/unit/specification/supplier_name
        # 在 DB 层均可空，`to_dict()` 原样透出 None。响应模型 MaterialCalcRow 声明为
        # `str`（契约文档 +str），若不归一会抛 ResponseValidationError → 接口 500
        # （2026-09-17 线上事故，见 test_calculate_material_null_code.py）。
        name = mat.get('material_name', '') or ''
        supplier_name = mat.get('supplier_name', '') or ''
        specification = mat.get('specification', '') or ''
        key = (category, name, supplier_name, specification)

        bucket = totals.get(key)
        if bucket is None:
            bucket = {
                'total': Decimal(0),
                'name': name,
                'category': category,
                'unit': mat.get('unit', '') or '',
                'supplier_name': supplier_name,
                'specification': specification,
                'material_code': mat.get('material_code', '') or '',
            }
            totals[key] = bucket

        # 数值字段同样不得裸露：`Decimal(str(None))` 抛 arithmetic.InvalidOperation，
        # 而它是 ArithmeticError 子类，**不在**接口 except 元组
        # (ValueError, OperationalError, DisconnectionError, RuntimeError) 内
        # ⇒ 会退化成无友好文案的 500。`unit_usage` 目前由三张表的 to_dict() 各自兜底
        # （float(x) if x else 0），但那是**生产者自觉**；内核必须自己防住
        # （见 test_kernel_tolerates_null_unit_usage）。
        per_unit = Decimal(str(mat.get('unit_usage') or 0))
        bucket['total'] += per_unit * quantity


def _finalize_bom_totals(totals: dict[tuple, dict]) -> dict[str, list[dict]]:
    """把累加容器收敛为 ``{category: [CalcRow, ...]}``（聚合内核，纯函数）。

    未知分类被丢弃并告警（与历史行为一致）。返回的四类键恒存在（可能为空列表）。
    """
    result: dict[str, list[dict]] = {
        'filling': [],
        'fabric': [],
        'accessory': [],
        'packaging': [],
    }
    for info in totals.values():
        category = info['category']
        if category in result:
            result[category].append({
                'name': info['name'],
                'material_name': info['name'],
                'material_code': info.get('material_code', '') or '',
                'specification': info.get('specification', '') or '',
                'total_quantity': float(info['total']),
                'unit': info.get('unit', '') or '',
                'supplier_name': info.get('supplier_name', '') or '',
            })
        else:
            logger.warning('未知物料分类被丢弃: %s (物料: %s)', category, info['name'])
    return result


def aggregate_materials(orders_data: list, product_map: dict) -> dict:
    """按 (分类, 物料名, 供应商, 规格) 聚合物料用量（**全作用域合并口径**）。

    纯函数：无 DB 依赖，便于单元测试聚合策略。口径与迁移前**完全一致**——
    所有作用域的物料合并累计，供旧客户端兼容（§7#8/#9）。

    Args:
        orders_data: 订单列表，每项含 product_id 与 quantity。
        product_map: {product_id: Product} 映射，Product 须实现 has_bom() 与 get_all_materials()。

    Returns:
        dict: {category: [CalcRow, ...]}，category ∈ filling/fabric/accessory/packaging。
    """
    totals: dict[tuple, dict] = {}
    for order_item in orders_data:
        product_id = order_item.get('product_id')
        quantity = Decimal(str(order_item.get('quantity', 0)))

        product = product_map.get(product_id)
        if not product or not product.has_bom():
            continue

        _accumulate_bom_rows(totals, product.get_all_materials(), quantity)

    return _finalize_bom_totals(totals)


def _merge_order_quantities(orders_data: list) -> dict[int, Decimal]:
    """把订单行按 product_id 合并数量（同产品多行求和）。"""
    merged: dict[int, Decimal] = {}
    for order_item in orders_data:
        product_id = order_item.get('product_id')
        if not product_id:
            continue
        merged[product_id] = merged.get(product_id, Decimal(0)) + Decimal(
            str(order_item.get('quantity', 0))
        )
    return merged


def aggregate_materials_by_scope(
    orders_data: list,
    product_map: dict,
    *,
    name_of: Callable[[int, int], str | None],
) -> list[dict]:
    """按「产品 × 作用域(角色)」分块聚合物料（计算器 ``groups`` 的唯一来源）。

    与 :func:`aggregate_materials` 共用同一份累加/收敛内核，保证扁平口径与分块口径
    **天然自洽**：``Σ(groups 各块[category]) ≡ aggregate_materials[category]``
    （由单测恒等式固化）。

    数量语义（§7#9）：一个产品只有一个订单总数量，**每个作用域都用该总数量展开，
    不分摊**。空作用域（该角色下无任何物料）不产出块。

    Args:
        orders_data: 订单列表，每项含 ``product_id`` 与 ``quantity``。
        product_map: ``{product_id: Product}``，Product 须实现 ``has_bom()`` /
            ``get_all_materials()`` 且有 ``name``。
        name_of: 角色名解析函数 ``(product_id, role_id) -> str | None``。

    Returns:
        list[dict]: 每块 ``{product_id, product_name, role_id, role_name, quantity,
        filling[], fabric[], accessory[], packaging[]}``。顺序：产品按订单首现顺序；
        产品内作用域为默认 BOM 首位 + 其余按显示名升序（``order_scopes``）。
    """
    groups: list[dict] = []
    for product_id, quantity in _merge_order_quantities(orders_data).items():
        product = product_map.get(product_id)
        if not product or not product.has_bom():
            continue

        rows = product.get_all_materials()
        scopes = order_scopes(
            {row.get('role_id') for row in rows} | {None},
            # P2-A2 类型收窄：partial 等价于原绑定默认值的 lambda（order_scopes.name_of 只接收 1 个参数）
            name_of=partial(name_of, product_id),
        )
        for role_id in scopes:
            scope_totals: dict[tuple, dict] = {}
            _accumulate_bom_rows(
                scope_totals,
                [row for row in rows if row.get('role_id') == role_id],
                quantity,
            )
            block = _finalize_bom_totals(scope_totals)
            if not any(block.values()):
                continue  # 空作用域不产出块（§7 完成判据 2）
            groups.append({
                'product_id': product_id,
                'product_name': getattr(product, 'name', '') or '',
                'role_id': role_id,
                'role_name': scope_label(
                    role_id, name_of(product_id, role_id) if role_id is not None else None,
                ),
                'quantity': float(quantity),
                **block,
            })
    return groups


def _collect_role_names(products: Sequence[Product]) -> dict[tuple[int, int], str]:
    """汇总 ``{(product_id, product_role.id): 显示名}``。

    展示名优先取全局角色名（§7#10），缺失回退镜像列 ``role_name``。调用方须已
    ``selectinload(Product.roles).selectinload(ProductRole.global_role)``，否则
    ``ProductRole.global_role``（``lazy='raise'``）会抛 ``InvalidRequestError``——
    这是**刻意 fail-loud**：对未加载关系不做静默探测（§7#6）。
    """
    names: dict[tuple[int, int], str] = {}
    for product in products:
        for pr in product.roles:
            global_role = pr.global_role
            name = getattr(global_role, 'name', None) if global_role is not None else None
            names[(product.id, pr.id)] = name or pr.role_name or ''
    return names


async def calculate_material(db: AsyncSession, orders_data: list) -> dict:
    """计算物料需求：返回扁平合并口径 + 按「产品 × 作用域」分块的 ``groups``。

    - 扁平字段（filling/fabric/accessory/packaging）：全作用域合并口径，数值与迁移前
      完全一致（旧客户端兼容，§7#8）；
    - ``groups``：每块对应「产品 × 作用域(角色)」，默认 BOM 恒首块（§7#2）。

    Args:
        db: 异步数据库会话。
        orders_data: 订单列表，每项含 product_id 与 quantity。

    Returns:
        dict: 含 filling/fabric/accessory/packaging/groups 的物料计算结果。
    """
    empty: dict[str, list] = {'filling': [], 'fabric': [], 'accessory': [], 'packaging': [], 'groups': []}
    product_ids = [item.get('product_id') for item in orders_data if item.get('product_id')]
    if not product_ids:
        return empty

    products_result = await db.execute(
        select(Product).options(
            selectinload(Product.material),
            selectinload(Product.material_rows),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
            # 计算器需按角色展示，故须加载 Product.roles 及其全局角色名（§7#10）。
            selectinload(Product.roles).selectinload(ProductRole.global_role),
        ).where(Product.id.in_(product_ids))
    )
    products = products_result.scalars().unique().all()
    product_map = {p.id: p for p in products}
    role_names = _collect_role_names(products)

    result = aggregate_materials(orders_data, product_map)
    result['groups'] = aggregate_materials_by_scope(
        orders_data,
        product_map,
        name_of=lambda pid, rid: role_names.get((pid, rid)),
    )
    return result
