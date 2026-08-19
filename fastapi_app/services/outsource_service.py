"""
湖北外发业务逻辑服务

职责：
- SKU 工序预设管理（outsource_process_type）：按产品固定配置外发工序类型
- 订单外发工序管理（order_outsource_process）：计划/实际完成时间、状态流转
- 返单自动带出：订单创建时根据 SKU 预设自动生成外发工序（幂等）
- 进度看板：聚合订单 + 工序，输出时间轴/进度条所需数据
"""
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.services import escape_like
from fastapi_app.shared_models import (
    Order,
    OrderItem,
    OrderOutsourceProcess,
    OutsourceProcessType,
    Product,
)

logger = logging.getLogger(__name__)


# ==================== 序列化辅助 ====================

def _fmt_dt(dt: datetime | None) -> str | None:
    """格式化 datetime 为 'YYYY-MM-DD HH:MM'；naive UTC 按 UTC 直接格式化。"""
    if dt is None:
        return None
    return dt.strftime('%Y-%m-%d %H:%M')


def _serialize_process_type(pt: OutsourceProcessType, product: Product | None = None) -> dict:
    product = product or pt.product
    return {
        'id': pt.id,
        'product_id': pt.product_id,
        'product_name': product.name if product else None,
        'product_barcode': product.barcode if product else None,
        'factory': product.factory if product else None,
        'process_type': pt.process_type,
        'sort_order': pt.sort_order or 0,
        'is_active': bool(pt.is_active),
        'remark': pt.remark,
        'created_by': pt.created_by,
        'create_time': _fmt_dt(pt.create_time),
        'update_time': _fmt_dt(pt.update_time),
    }


def _serialize_order_process(p: OrderOutsourceProcess) -> dict:
    return {
        'id': p.id,
        'order_id': p.order_id,
        'order_item_id': p.order_item_id,
        'product_id': p.product_id,
        'product_name': p.product_name,
        'process_type': p.process_type,
        'sort_order': p.sort_order or 0,
        'status': p.status,
        'planned_start_time': _fmt_dt(p.planned_start_time),
        'planned_end_time': _fmt_dt(p.planned_end_time),
        'actual_start_time': _fmt_dt(p.actual_start_time),
        'actual_end_time': _fmt_dt(p.actual_end_time),
        'remark': p.remark,
        'created_by': p.created_by,
        'create_time': _fmt_dt(p.create_time),
        'update_time': _fmt_dt(p.update_time),
    }


# ==================== 湖北外发订单列表 ====================

async def list_outsource_orders(
    db: AsyncSession, *, page: int = 1, per_page: int = 50,
    customer: str | None = None, process_status: str | None = None,
) -> dict:
    """湖北工厂订单+备货合并列表（强制 factory=湖北）。

    复用 order_crud.get_beile_orders_with_stockins，与 beile-order 页面
    保持完全一致的筛选逻辑与返回结构；并为每个订单附加外发工序进度统计
    （total/completed/progress/current_process/status_label），供订单列表
    直接展示进度条，无需再单独打开看板。

    process_status：按订单外发工序整体状态过滤（pending/in_progress/completed），
    需跨页统计，故先取全量合并列表附加进度后过滤再分页；未配置工序的订单
    不属于任何状态（未配置是独立状态，仅在无状态筛选时展示）。
    """
    from fastapi_app.services.order_crud import get_beile_orders_with_stockins
    if process_status:
        all_data = await get_beile_orders_with_stockins(
            db, page=1, per_page=500, customer=customer, factory='湖北',
        )
        await _attach_progress_to_orders(db, all_data['items'])
        filtered = [
            row for row in all_data['items']
            if _matches_process_status(row, process_status)
        ]
        total = len(filtered)
        start = (page - 1) * per_page
        return {
            'items': filtered[start:start + per_page],
            'total': total,
            'page': page,
            'per_page': per_page,
        }

    data = await get_beile_orders_with_stockins(
        db, page=page, per_page=per_page, customer=customer, factory='湖北',
    )
    await _attach_progress_to_orders(db, data['items'])
    return data


def _summarize_process_progress(processes: list[OrderOutsourceProcess]) -> dict:
    """计算工序进度统计（总数/完成数/开始数/进度/当前工序/状态标签）。"""
    total = len(processes)
    completed = sum(1 for p in processes if p.status == 'completed')
    started = sum(1 for p in processes if p.status != 'pending')
    progress = round(completed * 100 / total) if total else 0

    current_process = None
    for p in processes:
        if p.status != 'completed':
            current_process = p.process_type
            break

    if total == 0:
        status_label = '未配置工序'
    elif completed == total:
        status_label = '外发完成'
    elif started > 0:
        status_label = f'进行中（{current_process}）'
    else:
        status_label = '待开始'

    return {
        'total_processes': total,
        'completed_processes': completed,
        'started_processes': started,
        'progress': progress,
        'current_process': current_process,
        'status_label': status_label,
    }


def _matches_process_status(row: dict, status: str) -> bool:
    """按订单外发工序整体状态过滤。

    - pending 待开始：已配置工序且全部未开始
    - in_progress 进行中：有工序已开始但未全部完成
    - completed 已完成：全部工序完成
    未配置工序（total=0）不属于任何状态。
    """
    total = row.get('total_processes', 0)
    if total == 0:
        return False
    completed = row.get('completed_processes', 0)
    started = row.get('started_processes', 0)
    if status == 'completed':
        return completed == total
    if status == 'in_progress':
        return started > 0 and completed < total
    if status == 'pending':
        return started == 0
    return True


async def _attach_progress_to_orders(db: AsyncSession, items: list[dict]) -> None:
    """为订单列表条目附加外发工序进度统计（就地修改，仅订单记录；备货记录无工序）。"""
    order_ids = [row['id'] for row in items if row.get('record_type') == 'order']
    if not order_ids:
        return

    result = await db.execute(
        select(OrderOutsourceProcess)
        .where(OrderOutsourceProcess.order_id.in_(order_ids))
        .order_by(
            OrderOutsourceProcess.order_id,
            OrderOutsourceProcess.order_item_id,
            OrderOutsourceProcess.sort_order,
            OrderOutsourceProcess.id,
        )
    )
    processes_by_order: dict[int, list[OrderOutsourceProcess]] = {}
    # 记录每个订单中有工序的 SKU (order_item_id 集合)
    process_item_ids_by_order: dict[int, set[int]] = {}
    for p in result.scalars().all():
        processes_by_order.setdefault(p.order_id, []).append(p)
        if p.order_item_id is not None:
            process_item_ids_by_order.setdefault(p.order_id, set()).add(p.order_item_id)

    for row in items:
        # 为每个 SKU 标记是否有外发工序
        if row.get('items'):
            item_ids_with_processes = process_item_ids_by_order.get(row['id'], set())
            for sku in row['items']:
                sku['has_processes'] = sku['id'] in item_ids_with_processes

        if row.get('record_type') != 'order':
            row['total_processes'] = 0
            row['completed_processes'] = 0
            row['started_processes'] = 0
            row['progress'] = 0
            row['current_process'] = None
            row['status_label'] = '未配置工序'
            continue
        row.update(_summarize_process_progress(processes_by_order.get(row['id'], [])))


# ==================== SKU 工序预设 ====================

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

async def _load_order_with_skus(db: AsyncSession, order_id: int) -> Order | None:
    """加载订单并显式 eager-load items/product 关系。

    异步 SQLAlchemy 下关系默认 lazy：直接访问未加载的 order.items 会抛
    MissingGreenlet。订单创建路径中 items 是单独 flush 的，order 对象上的
    items 集合可能从未填充——必须通过查询重新加载才能拿到完整 SKU 明细。
    """
    result = await db.execute(
        select(Order)
        .options(
            joinedload(Order.product),
            selectinload(Order.items),
        )
        .where(Order.id == order_id)
    )
    return result.unique().scalar_one_or_none()


def _collect_order_skus(order: Order) -> list[tuple[int | None, int, str | None]]:
    """收集订单 SKU 维度列表 [(order_item_id, product_id, product_name)]。

    多 SKU 订单（有 OrderItem）按明细遍历；单 SKU 旧订单回退到 order.product_id。
    """
    items: list[OrderItem] = list(order.items or [])
    if items:
        return [(it.id, it.product_id, it.product_name) for it in items]
    return [(None, order.product_id, getattr(order.product, 'name', None) if order.product else None)]


async def sync_outsource_processes_for_order(
    db: AsyncSession, order: Order, username: str | None = None,
) -> tuple[int, int]:
    """根据 SKU 预设为订单自动生成外发工序（返单自动带出）。

    幂等：已存在 (order_id, order_item_id, product_id, process_type) 的跳过。
    未配置预设的产品不生成任何工序。返回 (created, skipped)。
    """
    # 重新查询并 eager-load items/product：
    # 1) 创建路径中 order.items 集合可能未填充（items 单独 flush），直接读取会漏 SKU
    # 2) 异步下 lazy 关系直接访问会抛 MissingGreenlet
    if getattr(order, 'id', None) is not None:
        loaded = await _load_order_with_skus(db, order.id)
        if loaded is not None:
            order = loaded

    skus = _collect_order_skus(order)
    if not skus:
        return 0, 0

    product_ids = list({pid for _item_id, pid, _name in skus})
    presets = await get_presets_for_products(db, product_ids)
    if not presets:
        return 0, 0

    # 已存在工序（幂等去重）
    existing_result = await db.execute(
        select(
            OrderOutsourceProcess.order_item_id,
            OrderOutsourceProcess.product_id,
            OrderOutsourceProcess.process_type,
        ).where(OrderOutsourceProcess.order_id == order.id)
    )
    existing = {
        (row[0], row[1], row[2])  # 兼容 SQLAlchemy Row（下标访问）与测试 mock 元组
        for row in existing_result.all()
    }

    created = 0
    skipped = 0
    for item_id, product_id, product_name in skus:
        for preset in presets.get(product_id, []):
            key = (item_id, product_id, preset.process_type)
            if key in existing:
                skipped += 1
                continue
            db.add(OrderOutsourceProcess(
                order_id=order.id,
                order_item_id=item_id,
                product_id=product_id,
                product_name=product_name,
                process_type=preset.process_type,
                sort_order=preset.sort_order or 0,
                status='pending',
                created_by=username,
            ))
            created += 1

    if created:
        await db.flush()
    return created, skipped


async def auto_generate_for_order(
    db: AsyncSession, order: Order, username: str | None = None,
) -> None:
    """防御性封装：订单创建时自动带出外发工序（返单自动带出）。

    供 order_crud.create_order / order_batch_create / staging_service 在事务内调用。
    失败仅记录日志，绝不影响订单创建主流程。
    """
    try:
        created, skipped = await sync_outsource_processes_for_order(db, order, username)
        if created:
            logger.info(
                "订单 %s 自动生成外发工序 %d 道（跳过 %d）",
                getattr(order, 'order_no', order.id), created, skipped,
            )
    except (SQLAlchemyError, OSError):  # defensive: 外发工序生成失败不影响订单创建
        # 仅捕获基础设施异常；编程错误（KeyError 等）自然抛出，避免被静默吞噬
        logger.exception(
            "订单 %s 自动生成外发工序失败", getattr(order, 'order_no', order.id),
        )


async def generate_order_processes(
    db: AsyncSession, order_id: int, username: str | None = None,
) -> dict:
    """为已有订单按 SKU 预设生成外发工序（返回 created/skipped 统计）。

    注意：订单列表（beile-list）的 items 可能含备货记录，其 id 是 StockIn.id
    而非 Order.id——此处用 Order 主键查询，备货记录将返回「订单不存在」。
    """
    order = await _load_order_with_skus(db, order_id)
    if not order or order.is_deleted:
        raise ValueError('订单不存在')

    created, skipped = await sync_outsource_processes_for_order(db, order, username)
    return {'created': created, 'skipped': skipped}


async def list_order_processes(db: AsyncSession, order_id: int) -> list[dict]:
    """查询订单外发工序（按 SKU + 工序顺序排序）。"""
    result = await db.execute(
        select(OrderOutsourceProcess)
        .where(OrderOutsourceProcess.order_id == order_id)
        .order_by(
            OrderOutsourceProcess.order_item_id,
            OrderOutsourceProcess.sort_order,
            OrderOutsourceProcess.id,
        )
    )
    processes = result.scalars().all()
    return [_serialize_order_process(p) for p in processes]


async def update_order_process(db: AsyncSession, process_id: int, data: dict) -> dict:
    """更新订单外发工序（计划时间/工序类型/备注，部分更新）。"""
    p = await db.get(OrderOutsourceProcess, process_id)
    if not p:
        raise ValueError('外发工序不存在')

    if data.get('process_type') is not None:
        new_type = data['process_type'].strip()
        if not new_type:
            raise ValueError('工序类型不能为空')
        p.process_type = new_type
    if data.get('sort_order') is not None:
        p.sort_order = data['sort_order']
    if 'planned_start_time' in data:
        p.planned_start_time = data['planned_start_time']
    if 'planned_end_time' in data:
        p.planned_end_time = data['planned_end_time']
    if 'remark' in data:
        p.remark = (data['remark'] or '').strip() or None

    await db.flush()
    await db.refresh(p)
    return _serialize_order_process(p)


async def start_order_process(db: AsyncSession, process_id: int, username: str | None = None) -> dict:
    """开始外发工序：记录实际开始时间，状态 → in_progress。"""
    p = await db.get(OrderOutsourceProcess, process_id)
    if not p:
        raise ValueError('外发工序不存在')
    if p.status == 'completed':
        raise ValueError('该工序已完成，无法重复开始')

    p.status = 'in_progress'
    p.actual_start_time = datetime.now(UTC).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
    p.remark = p.remark or (f'由 {username} 开始' if username else '')
    await db.flush()
    await db.refresh(p)
    return _serialize_order_process(p)


async def complete_order_process(db: AsyncSession, process_id: int, username: str | None = None) -> dict:
    """完成外发工序：记录实际完成时间，状态 → completed。"""
    p = await db.get(OrderOutsourceProcess, process_id)
    if not p:
        raise ValueError('外发工序不存在')
    if p.status == 'completed':
        raise ValueError('该工序已完成，无需重复操作')

    now = datetime.now(UTC).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
    if not p.actual_start_time:
        # 未点击开始时直接完成：视为开始即完成
        p.actual_start_time = now
    p.actual_end_time = now
    p.status = 'completed'
    await db.flush()
    await db.refresh(p)
    return _serialize_order_process(p)


async def delete_order_process(db: AsyncSession, process_id: int) -> None:
    """删除订单外发工序。"""
    p = await db.get(OrderOutsourceProcess, process_id)
    if not p:
        raise ValueError('外发工序不存在')
    await db.delete(p)
    await db.flush()


# ==================== 进度看板 ====================

async def get_kanban(
    db: AsyncSession, *, page: int = 1, per_page: int = 20,
    customer: str | None = None,
) -> dict:
    """订单进度看板：湖北工厂订单 + 各 SKU 外发工序状态。

    每个订单条目包含：
    - 下单时间/客户/产品
    - processes: 按 SKU 排序的工序（计划/实际完成时间、状态）
    - progress: 完成工序占比（0-100）
    - current_process: 当前进行中（或下一个待开始）的工序
    """
    orders_data = await list_outsource_orders(
        db, page=page, per_page=per_page, customer=customer,
    )
    items: list[dict] = []
    order_ids = [row['id'] for row in orders_data['items']]

    processes_by_order: dict[int, list[OrderOutsourceProcess]] = {}
    if order_ids:
        proc_result = await db.execute(
            select(OrderOutsourceProcess)
            .where(OrderOutsourceProcess.order_id.in_(order_ids))
            .order_by(
                OrderOutsourceProcess.order_id,
                OrderOutsourceProcess.order_item_id,
                OrderOutsourceProcess.sort_order,
                OrderOutsourceProcess.id,
            )
        )
        for p in proc_result.scalars().all():
            processes_by_order.setdefault(p.order_id, []).append(p)

    for row in orders_data['items']:
        processes = processes_by_order.get(row['id'], [])
        summary = _summarize_process_progress(processes)
        total = summary['total_processes']
        completed = summary['completed_processes']
        current_process = summary['current_process']
        status_label = summary['status_label']

        items.append({
            'id': row['id'],
            'order_no': row['order_no'],
            'customer': row['customer'],
            'order_date': row.get('order_date', ''),
            'record_type': row.get('record_type', 'order'),
            'products': [
                {'product_id': sku['product_id'], 'product_name': sku['product_name'],
                 'quantity': sku['quantity']}
                for sku in (row.get('items') or [])
            ],
            'processes': [_serialize_order_process(p) for p in processes],
            'total_processes': total,
            'completed_processes': completed,
            'progress': summary['progress'],
            'current_process': current_process,
            'status_label': status_label,
        })

    return {
        'items': items,
        'total': orders_data['total'],
        'page': page,
        'per_page': per_page,
    }
