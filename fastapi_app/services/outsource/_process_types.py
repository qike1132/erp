"""外发工艺类型 CRUD

从 outsource_service.py 按职责拆出,行为与原实现完全一致。
"""
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from fastapi_app.services import escape_like
from fastapi_app.services.outsource._common import _serialize_process_type
from fastapi_app.shared_models import OutsourceProcessType, Product

logger = logging.getLogger(__name__)


async def list_process_types(
    db: AsyncSession, *, product_id: int | None = None,
    product_name: str | None = None, keyword: str | None = None,
    is_active: bool | None = None,
    page: int = 1, per_page: int = 200,
) -> dict:
    """查询 SKU 工序预设（可按产品/关键字筛选，带产品信息）。"""
    query = (
        select(OutsourceProcessType)
        .join(Product, Product.id == OutsourceProcessType.product_id)
        .options(joinedload(OutsourceProcessType.product))
    )
    count_query = (
        select(func.count(OutsourceProcessType.id))
        .join(Product, Product.id == OutsourceProcessType.product_id)
    )

    conditions = []
    if product_id:
        conditions.append(OutsourceProcessType.product_id == product_id)
    if product_name:
        pn = f'%{escape_like(product_name.strip())}%'
        conditions.append(Product.name.like(pn))
    if keyword:
        kw = f'%{keyword.strip()}%'
        conditions.append(OutsourceProcessType.process_type.like(kw))
    if is_active is not None:
        conditions.append(OutsourceProcessType.is_active == is_active)

    for cond in conditions:
        query = query.where(cond)
        count_query = count_query.where(cond)

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(
        query.order_by(OutsourceProcessType.product_id, OutsourceProcessType.sort_order, OutsourceProcessType.id)
        .offset((page - 1) * per_page).limit(per_page)
    )
    items = result.unique().scalars().all()
    return {
        'items': [_serialize_process_type(pt) for pt in items],
        'total': total,
        'page': page,
        'per_page': per_page,
    }

async def create_process_type(
    db: AsyncSession, data: dict, username: str | None = None,
) -> dict:
    """创建 SKU 工序预设；同一产品下工序类型不可重复。"""
    product = await db.get(Product, data['product_id'])
    if not product:
        raise ValueError('产品不存在')

    process_type = data['process_type'].strip()
    if not process_type:
        raise ValueError('工序类型不能为空')

    existing = await db.execute(
        select(OutsourceProcessType.id).where(
            OutsourceProcessType.product_id == data['product_id'],
            OutsourceProcessType.process_type == process_type,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError(f'该产品已配置工序「{process_type}」，请勿重复添加')

    pt = OutsourceProcessType(
        product_id=data['product_id'],
        process_type=process_type,
        sort_order=data.get('sort_order', 0),
        is_active=data.get('is_active', True),
        remark=(data.get('remark') or '').strip() or None,
        created_by=username,
    )
    db.add(pt)
    await db.flush()
    await db.refresh(pt)
    return _serialize_process_type(pt, product)

async def batch_create_process_types(
    db: AsyncSession, *, product_id: int, process_types: list[str], username: str | None = None,
) -> dict:
    """为一个 SKU 批量创建多个工序预设（自由输入工序名称）。

    幂等：同一产品下已存在的工序名称跳过，返回 (created, skipped)。
    sort_order 取该产品现有最大顺序 +1 递增。
    """
    product = await db.get(Product, product_id)
    if not product:
        raise ValueError('产品不存在')

    names = [n.strip() for n in (process_types or []) if n and n.strip()]
    if not names:
        raise ValueError('请至少填写一个工序名称')
    if len(names) > 50:
        raise ValueError('单次最多添加 50 道工序')

    # 现有工序名称集合（去重）+ 当前最大顺序
    existing_result = await db.execute(
        select(OutsourceProcessType.process_type, OutsourceProcessType.sort_order)
        .where(OutsourceProcessType.product_id == product_id)
    )
    existing_names = set()
    max_sort = 0
    for row in existing_result.all():
        existing_names.add(row[0])
        max_sort = max(max_sort, row[1] or 0)

    created = 0
    skipped = 0
    next_sort = max_sort + 1
    seen: set[str] = set()
    for name in names:
        if name in seen or name in existing_names:
            skipped += 1
            continue
        seen.add(name)
        db.add(OutsourceProcessType(
            product_id=product_id,
            process_type=name,
            sort_order=next_sort,
            is_active=True,
            created_by=username,
        ))
        next_sort += 1
        created += 1

    if created:
        await db.flush()
    return {'created': created, 'skipped': skipped}

async def update_process_type(db: AsyncSession, pt_id: int, data: dict) -> dict:
    """更新 SKU 工序预设（部分更新）。"""
    pt = await db.get(OutsourceProcessType, pt_id)
    if not pt:
        raise ValueError('工序预设不存在')

    if data.get('process_type') is not None:
        new_type = data['process_type'].strip()
        if not new_type:
            raise ValueError('工序类型不能为空')
        dup = await db.execute(
            select(OutsourceProcessType.id).where(
                OutsourceProcessType.product_id == pt.product_id,
                OutsourceProcessType.process_type == new_type,
                OutsourceProcessType.id != pt.id,
            )
        )
        if dup.scalar_one_or_none():
            raise ValueError(f'该产品已配置工序「{new_type}」，请勿重复添加')
        pt.process_type = new_type
    if data.get('sort_order') is not None:
        pt.sort_order = data['sort_order']
    if data.get('is_active') is not None:
        pt.is_active = bool(data['is_active'])
    if 'remark' in data:
        pt.remark = (data['remark'] or '').strip() or None

    await db.flush()
    await db.refresh(pt)
    product = await db.get(Product, pt.product_id)
    return _serialize_process_type(pt, product)

async def delete_process_type(db: AsyncSession, pt_id: int) -> None:
    """删除 SKU 工序预设。"""
    pt = await db.get(OutsourceProcessType, pt_id)
    if not pt:
        raise ValueError('工序预设不存在')
    await db.delete(pt)
    await db.flush()

async def get_presets_for_products(db: AsyncSession, product_ids: list[int]) -> dict[int, list[OutsourceProcessType]]:
    """批量加载多个产品的启用工序预设，按产品分组并按 sort_order 排序。"""
    if not product_ids:
        return {}
    result = await db.execute(
        select(OutsourceProcessType)
        .where(
            OutsourceProcessType.product_id.in_(product_ids),
            OutsourceProcessType.is_active.is_(True),
        )
        .order_by(OutsourceProcessType.product_id, OutsourceProcessType.sort_order, OutsourceProcessType.id)
    )
    grouped: dict[int, list[OutsourceProcessType]] = {}
    for pt in result.scalars().all():
        grouped.setdefault(pt.product_id, []).append(pt)
    return grouped


# ==================== 订单外发工序 ====================