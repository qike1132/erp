"""皮套查询域（SKU 搜索/列表 / 出入库流水 / 库存分组汇总）"""
import logging

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, joinedload

from fastapi_app.core.exceptions import NotFoundError
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.services.case._common import (
    DEFAULT_SEARCH_LIMIT,
    MAX_LIST_PAGE_SIZE,
    MAX_SUMMARY_PAGE_SIZE,
    _apply_date_filter,
    _apply_quantity_filter,
    _normalize_pagination,
)
from fastapi_app.services.case._serializers import _serialize_item, _serialize_movement
from fastapi_app.shared_models import DIRECTION_IN, DIRECTION_OUT, Case, CaseMovement, Product
from fastapi_app.utils import calc_total_pages

logger = logging.getLogger(__name__)


def _item_search_conditions(search: str) -> list:
    """SKU 名称/条码模糊匹配条件（空搜索返回空列表）。"""
    if not search:
        return []
    pattern = f'%{escape_like(search)}%'
    return [or_(Case.name.like(pattern), Case.barcode.like(pattern))]  # sql-safe: escape_like/绑定参数


def _attach_totals(item: dict, case_id: int, totals: dict) -> None:
    """把某 SKU 的累计入库/出库写入序列化字典。"""
    item['total_in'] = totals.get((case_id, DIRECTION_IN), 0)
    item['total_out'] = totals.get((case_id, DIRECTION_OUT), 0)


async def _totals_by_case(db: AsyncSession, case_ids: list[int]) -> dict:
    """返回 {(case_id, direction): 累计数量}；无 id 时直接返回空（不发查询）。"""
    if not case_ids:
        return {}
    rows = await db.execute(
        select(CaseMovement.case_id, CaseMovement.direction, func.sum(CaseMovement.quantity))
        .where(CaseMovement.case_id.in_(case_ids))
        .group_by(CaseMovement.case_id, CaseMovement.direction)
    )
    return {(int(cid), direction): int(total or 0) for cid, direction, total in rows.all()}


async def search_cases(db: AsyncSession, query: str = '') -> list[dict]:
    """皮套 SKU 搜索（录入联想，附库存）。无关键词时返回前 20 条。"""
    q = select(Case)
    conditions = _item_search_conditions(query)
    if conditions:
        q = q.where(*conditions)
    else:
        q = q.limit(DEFAULT_SEARCH_LIMIT)
    q = q.order_by(Case.id)
    result = await db.execute(q)
    cases = list(result.scalars().all())
    # 只读本表字段：**不要**用 c.sync_name/c.sync_barcode —— 它们在 product_id 非空时
    # 会访问 self.product 关系，async 会话在该处触发 IO 报 MissingGreenlet（→ 500）。
    # 与 _serializers.py 的修复同口径（f7b6549d 只修了那边，这里漏网；生产 case 表
    # 已有 product_id 非空的行，无关键词时默认返回前 20 条必含它 → 必然 500）。
    return [{
        'id': c.id, 'name': c.name or '', 'barcode': c.barcode or '',
        'current_stock': c.current_stock or 0, 'parent_id': c.parent_id,
    } for c in cases]


async def get_case_items(db: AsyncSession, page: int = 1, per_page: int = 50, search: str = '',
                         parent_id: int | None = None, roots_only: bool = False) -> dict:
    """皮套 SKU 列表（分页）。`roots_only` 只看主件；`parent_id` 只看某主件的配件。"""
    page, per_page = _normalize_pagination(page, per_page, MAX_SUMMARY_PAGE_SIZE)
    conditions = _item_search_conditions(search)
    if roots_only:
        conditions.append(Case.parent_id.is_(None))
    elif parent_id is not None:
        conditions.append(Case.parent_id == parent_id)

    count_q = select(func.count()).select_from(Case)
    query = select(Case)
    if conditions:
        count_q = count_q.where(*conditions)  # sql-safe: 绑定参数
        query = query.where(*conditions)
    total = (await db.execute(count_q)).scalar() or 0

    offset = (page - 1) * per_page
    result = await db.execute(query.order_by(Case.id).offset(offset).limit(per_page))
    items = [_serialize_item(c) for c in result.scalars().all()]
    return {
        'items': items, 'total': total, 'page': page, 'per_page': per_page,
        'pages': calc_total_pages(total, per_page),
    }


async def get_case_inventory(db: AsyncSession, page: int = 1, per_page: int = 50, search: str = '') -> dict:
    """皮套库存汇总（按主件分组，含配件明细）+ 整体统计。

    主件 = `parent_id IS NULL` 的 SKU；其配件为 `parent_id = 主件.id` 的 SKU。
    库存一律读 `Case.current_stock`（单一真值来源）。
    """
    page, per_page = _normalize_pagination(page, per_page, MAX_SUMMARY_PAGE_SIZE)
    conditions = _item_search_conditions(search)

    roots_q = select(Case).where(Case.parent_id.is_(None))
    count_q = select(func.count()).select_from(Case).where(Case.parent_id.is_(None))
    if conditions:
        roots_q = roots_q.where(*conditions)  # sql-safe: 绑定参数
        count_q = count_q.where(*conditions)
    total = (await db.execute(count_q)).scalar() or 0

    offset = (page - 1) * per_page
    roots = list((await db.execute(roots_q.order_by(Case.id).offset(offset).limit(per_page))).scalars().all())

    parent_ids = [c.id for c in roots]
    children_by_parent: dict[int | None, list[Case]] = {}
    if parent_ids:
        child_rows = await db.execute(
            select(Case).where(Case.parent_id.in_(parent_ids)).order_by(Case.id)
        )
        for child in child_rows.scalars().all():
            children_by_parent.setdefault(child.parent_id, []).append(child)

    all_ids = parent_ids + [ch.id for chs in children_by_parent.values() for ch in chs]
    totals = await _totals_by_case(db, all_ids)

    inventory = []
    for root in roots:
        node = _serialize_item(root)
        _attach_totals(node, root.id, totals)
        node['children'] = []
        for child in children_by_parent.get(root.id, []):
            child_item = _serialize_item(child)
            _attach_totals(child_item, child.id, totals)
            node['children'].append(child_item)
        inventory.append(node)

    stats = await _compute_inventory_stats(db, conditions)
    return {
        'inventory': inventory, 'total': total, 'page': page, 'per_page': per_page,
        'pages': calc_total_pages(total, per_page), 'stats': stats,
    }


async def _compute_inventory_stats(db: AsyncSession, conditions: list) -> dict:
    """整体统计：SKU 数、总库存、总入库、总出库（受 search 约束）。"""
    stats_stmt = select(func.count(Case.id), func.coalesce(func.sum(Case.current_stock), 0))
    if conditions:
        stats_stmt = stats_stmt.where(*conditions)  # sql-safe: 绑定参数
    total_items, total_stock = (await db.execute(stats_stmt)).one()

    async def _sum_direction(direction: str) -> int:
        q = select(func.coalesce(func.sum(CaseMovement.quantity), 0)).where(CaseMovement.direction == direction)
        if conditions:
            q = q.join(Case, CaseMovement.case_id == Case.id).where(*conditions)
        return int((await db.execute(q)).scalar() or 0)

    return {
        'total_items': int(total_items or 0),
        'total_stock': int(total_stock or 0),
        'total_in': await _sum_direction(DIRECTION_IN),
        'total_out': await _sum_direction(DIRECTION_OUT),
    }


async def list_products_with_parts(db: AsyncSession, page: int = 1, per_page: int = 200,
                                   search: str = '', has_parts: str = 'all') -> dict:
    """产品列表（皮套设置选择用）：每个产品附「配件数」，用于区分有配件/无配件。

    「配件」= `case` 表中 `parent_id IS NOT NULL` 且 `product_id` 指向该产品的行；
    只有主件、0 配件算「无配件」。`has_parts` 取 all/yes/no。
    以 `product` 表为根（LEFT JOIN 配件计数子查询），故**覆盖全部产品**，包括从未建过皮套的。
    """
    page, per_page = _normalize_pagination(page, per_page, MAX_SUMMARY_PAGE_SIZE)

    # 配件 = 主件（parent_id IS NULL）的子件；按**主件的 product_id** 归组。
    # 不能按子件自身的 product_id 分组 —— 配件行（createItem 只给 name+parent_id）
    # 的 product_id 是 NULL，那样数出来恒为 0，有配件也会显示"无配件"。
    part_case = aliased(Case)
    main_case = aliased(Case)
    part_count = (
        select(main_case.product_id.label('product_id'), func.count(part_case.id).label('part_count'))
        .join(part_case, part_case.parent_id == main_case.id)
        .where(main_case.parent_id.is_(None), main_case.product_id.is_not(None))
        .group_by(main_case.product_id)
        .subquery()
    )
    count_expr = func.coalesce(part_count.c.part_count, 0)

    conditions = []
    if search:
        pattern = f'%{escape_like(search)}%'
        conditions.append(or_(Product.name.like(pattern), Product.barcode.like(pattern)))  # sql-safe: escape_like/绑定参数
    if has_parts == 'yes':
        conditions.append(count_expr > 0)
    elif has_parts == 'no':
        conditions.append(count_expr == 0)

    base = (
        select(Product.id, Product.name, Product.barcode, count_expr.label('part_count'))
        .outerjoin(part_count, part_count.c.product_id == Product.id)
    )
    if conditions:
        base = base.where(*conditions)  # sql-safe: 绑定参数
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0

    offset = (page - 1) * per_page
    rows = await db.execute(base.order_by(Product.id).offset(offset).limit(per_page))
    products = [
        {'id': pid, 'name': name or '', 'barcode': barcode or '',
         'part_count': int(pc or 0), 'has_parts': int(pc or 0) > 0}
        for pid, name, barcode, pc in rows.all()
    ]
    return {
        'products': products, 'total': total, 'page': page, 'per_page': per_page,
        'pages': calc_total_pages(total, per_page),
    }


async def get_case_movements(db: AsyncSession, page: int = 1, per_page: int = 20, case_id: int | None = None,
                             direction: str = '', customer: str = '', start_date: str = '', end_date: str = '',
                             quantity_min: int | None = None, quantity_max: int | None = None) -> dict:
    """出入库流水列表（分页，可按 SKU/方向/客户/日期/数量过滤）。"""
    page, per_page = _normalize_pagination(page, per_page, MAX_LIST_PAGE_SIZE)
    query = select(CaseMovement).options(joinedload(CaseMovement.case))

    if case_id is not None:
        query = query.where(CaseMovement.case_id == case_id)
    if direction:
        query = query.where(CaseMovement.direction == direction)
    if customer:
        query = query.where(CaseMovement.customer.like(f'%{escape_like(customer)}%'))  # sql-safe: escape_like/绑定参数
    query = _apply_date_filter(query, CaseMovement.movement_date, start_date, end_date, '开始日期')
    query = _apply_quantity_filter(query, CaseMovement.quantity, quantity_min, quantity_max)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    offset = (page - 1) * per_page
    result = await db.execute(
        query.order_by(CaseMovement.movement_date.desc(), CaseMovement.id.desc()).offset(offset).limit(per_page)
    )
    movements = list(result.unique().scalars().all())
    return {
        'movements': [_serialize_movement(m) for m in movements],
        'total': total, 'pages': calc_total_pages(total, per_page), 'current_page': page,
    }


async def get_case_movement_detail(db: AsyncSession, movement_id: int) -> dict:
    """获取单条出入库流水。不存在时抛 404。"""
    result = await db.execute(
        select(CaseMovement).options(joinedload(CaseMovement.case)).where(CaseMovement.id == movement_id)
    )
    movement = result.unique().scalar_one_or_none()
    if not movement:
        raise NotFoundError('流水记录不存在')
    return _serialize_movement(movement)


async def fetch_movements_for_export(db: AsyncSession, case_id: int | None = None, direction: str = '',
                                     customer: str = '', start_date: str = '', end_date: str = '',
                                     limit: int = 20000) -> list[dict]:
    """导出用：按筛选条件取流水（不分页，上限 limit）。"""
    query = select(CaseMovement).options(joinedload(CaseMovement.case))
    if case_id is not None:
        query = query.where(CaseMovement.case_id == case_id)
    if direction:
        query = query.where(CaseMovement.direction == direction)
    if customer:
        query = query.where(CaseMovement.customer.like(f'%{escape_like(customer)}%'))  # sql-safe: escape_like/绑定参数
    query = _apply_date_filter(query, CaseMovement.movement_date, start_date, end_date, '开始日期')
    result = await db.execute(
        query.order_by(CaseMovement.movement_date.desc(), CaseMovement.id.desc()).limit(limit)
    )
    return [_serialize_movement(m) for m in result.unique().scalars().all()]


async def fetch_inventory_for_export(db: AsyncSession, search: str = '', limit: int = 20000) -> list[dict]:
    """导出用：主件 + 配件分组（不分页，上限 limit 个主件）。"""
    conditions = _item_search_conditions(search)
    roots_q = select(Case).where(Case.parent_id.is_(None))
    if conditions:
        roots_q = roots_q.where(*conditions)  # sql-safe: 绑定参数
    roots = list((await db.execute(roots_q.order_by(Case.id).limit(limit))).scalars().all())
    parent_ids = [c.id for c in roots]
    children_by_parent: dict[int | None, list[Case]] = {}
    if parent_ids:
        child_rows = await db.execute(select(Case).where(Case.parent_id.in_(parent_ids)).order_by(Case.id))
        for child in child_rows.scalars().all():
            children_by_parent.setdefault(child.parent_id, []).append(child)
    all_ids = parent_ids + [ch.id for chs in children_by_parent.values() for ch in chs]
    totals = await _totals_by_case(db, all_ids)
    out = []
    for root in roots:
        node = _serialize_item(root)
        _attach_totals(node, root.id, totals)
        node['children'] = []
        for child in children_by_parent.get(root.id, []):
            child_item = _serialize_item(child)
            _attach_totals(child_item, child.id, totals)
            node['children'].append(child_item)
        out.append(node)
    return out
