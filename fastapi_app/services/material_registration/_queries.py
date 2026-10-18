"""物料登记查询域

从 material_registration_service.py 按职责拆出,行为与原实现完全一致。
"""
import json
import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.core.cache import cache_result
from fastapi_app.core.exceptions import BusinessError
from fastapi_app.core.float_utils import float_compare, round_qty
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.shared_models import (
    MaterialRegistration,
    MaterialRegistrationItem,
    PurchaseOrder,
    PurchaseOrderItem,
)
from fastapi_app.shared_models.order import Order
from fastapi_app.utils import calc_total_pages

logger = logging.getLogger(__name__)


def _parse_filter_date(date_str: str, field_name: str) -> date:
    """严格解析筛选日期，非法格式抛 400 业务异常（不再静默忽略）"""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        raise BusinessError(f'{field_name}格式错误，应为 YYYY-MM-DD') from None

@cache_result(key_prefix="material:registrations", ttl=30, local_ttl=10,
             key_builder=lambda **kw: f"{kw.get('page',1)}:{kw.get('per_page',20)}:{kw.get('status','')}:{kw.get('order_no','')}:{kw.get('supplier','')}:{kw.get('customer_name','')}:{kw.get('material_category','')}:{kw.get('start_date','')}:{kw.get('end_date','')}:{kw.get('exclude_completed',False)}")
async def get_registrations(db, page: int = 1, per_page: int = 20,
                           status: str = '', order_no: str = '', supplier: str = '',
                           customer_name: str = '', material_category: str = '',
                           start_date: str = '', end_date: str = '',
                           exclude_completed: bool = False) -> dict:
    """获取来料登记列表

    支持多维度筛选；当 exclude_completed=True 时排除已完成的登记（用于来料进度 tab）。
    L1 10s + L2 30s 缓存，写操作时通过 MATERIAL 域失效。
    """
    # Build filter conditions once, apply to both data query and count query
    conditions = []
    if status:
        conditions.append(MaterialRegistration.status == status)
    elif exclude_completed:
        conditions.append(MaterialRegistration.status != 'completed')
    if order_no:
        conditions.append(MaterialRegistration.purchase_order_no.ilike(f'%{escape_like(order_no)}%'))
    if supplier:
        conditions.append(MaterialRegistration.supplier_name.ilike(f'%{escape_like(supplier)}%'))
    if customer_name:
        conditions.append(PurchaseOrder.customer_name.ilike(f'%{escape_like(customer_name)}%'))
    if start_date:
        conditions.append(MaterialRegistration.registration_date >= _parse_filter_date(start_date, '开始日期'))
    if end_date:
        conditions.append(MaterialRegistration.registration_date <= _parse_filter_date(end_date, '结束日期'))
    if material_category:
        conditions.append(
            MaterialRegistration.items.any(MaterialRegistrationItem.material_category == material_category)
        )

    needs_po_join = bool(customer_name)
    base_query = select(MaterialRegistration)
    if needs_po_join:
        base_query = base_query.join(MaterialRegistration.purchase_order)
    query = base_query.options(
        selectinload(MaterialRegistration.items),
        selectinload(MaterialRegistration.purchase_order),
    ).where(*conditions)

    total_q = select(func.count(MaterialRegistration.id))
    if needs_po_join:
        total_q = total_q.join(MaterialRegistration.purchase_order)
    total_q = total_q.where(*conditions)
    total = (await db.execute(total_q)).scalar() or 0

    query = query.order_by(MaterialRegistration.create_time.desc())
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)
    result = await db.execute(query)
    registrations = list(result.scalars().all())

    return {
        'success': True,
        'registrations': [r.to_dict() for r in registrations],
        'total': total,
        'pages': calc_total_pages(total, per_page),
        'current_page': page,
    }

async def get_registration(db, reg_id: int) -> dict:
    """获取来料登记详情"""
    result = await db.execute(
        select(MaterialRegistration).options(
            selectinload(MaterialRegistration.items),
            selectinload(MaterialRegistration.purchase_order),
        ).where(MaterialRegistration.id == reg_id)
    )
    reg = result.scalar_one_or_none()
    if not reg:
        raise ValueError("来料登记不存在")
    return {'success': True, 'registration': reg.to_dict()}

def _compute_pct(ordered: float, received: float) -> float:
    """计算完成百分比：全部到货返回 100，否则上限 99.9（与前端 computePct 对齐）"""
    if ordered <= 0:
        return 0.0
    if received >= ordered:
        return 100.0
    return min(round_qty(received / ordered * 100, precision_digits=1), 99.9)

@cache_result(key_prefix="material:supplier_detail", ttl=30, local_ttl=10,
             key_builder=lambda **kw: kw.get('order_no', ''))
async def get_supplier_detail(db, order_no: str) -> dict:
    """获取按供应商分组的来料聚合详情（服务端预聚合，消除前端 60+ 行同步计算）。

    查询指定 order_no 的未完成登记，遍历所有 items（排除 filling 类），
    按 reg.supplier_name 分组，组内按 material_name 合并数量并计算进度。
    L1 10s + L2 30s 缓存，写操作时通过 MATERIAL 域失效。
    """
    query = (
        select(MaterialRegistration)
        .options(selectinload(MaterialRegistration.items))
        .where(
            MaterialRegistration.purchase_order_no == order_no,
            MaterialRegistration.status != 'completed',
        )
    )
    result = await db.execute(query)
    registrations = list(result.scalars().all())

    # supplier_name -> {material_name -> mat_info}
    supplier_map: dict[str, dict[str, dict]] = {}

    for reg in registrations:
        sup_name = reg.supplier_name or '未指定'
        mat_map = supplier_map.setdefault(sup_name, {})
        for item in reg.items:
            if (item.material_category or '') == 'filling':
                continue
            ordered = float(item.ordered_quantity or 0)
            received = float(item.received_quantity or 0)
            mat_name = item.material_name
            existing = mat_map.get(mat_name)
            if existing:
                existing['ordered'] += ordered
                existing['received'] += received
                existing['remaining'] = existing['ordered'] - existing['received']
                existing['pct'] = _compute_pct(existing['ordered'], existing['received'])
                existing['sub_items'].append({'id': item.id, 'ordered': ordered, 'received': received})
            else:
                mat_map[mat_name] = {
                    'name': mat_name,
                    'ordered': ordered,
                    'received': received,
                    'remaining': ordered - received,
                    'pct': _compute_pct(ordered, received),
                    'sub_items': [{'id': item.id, 'ordered': ordered, 'received': received}],
                    'unit': item.unit or '',
                    'spec': item.specification or '',
                }

    all_ordered = 0.0
    all_received = 0.0
    supplier_groups = []
    for sup_name, mat_map in supplier_map.items():
        items = list(mat_map.values())
        o_total = sum(m['ordered'] for m in items)
        r_total = sum(m['received'] for m in items)
        all_ordered += o_total
        all_received += r_total
        # ordered/received 为 Numeric(12,2) 经 float 聚合，用 2 位精度比较避免表示噪声
        all_complete = all(float_compare(m['received'], m['ordered'], precision_digits=2) >= 0 for m in items)
        supplier_groups.append({
            'supplier_name': sup_name,
            'items': items,
            'total_ordered': o_total,
            'total_received': r_total,
            'pct': _compute_pct(o_total, o_total if all_complete else r_total),
        })

    all_complete = all(
        float_compare(m['received'], m['ordered'], precision_digits=2) >= 0
        for g in supplier_groups
        for m in g['items']
    )
    total_pct = _compute_pct(all_ordered, all_ordered if all_complete else all_received)

    return {
        'success': True,
        'supplier_groups': supplier_groups,
        'total_ordered': all_ordered,
        'total_received': all_received,
        'total_pct': total_pct,
    }

async def get_available_purchase_orders(db, status: str = 'pending') -> dict:
    """获取可用于来料登记的采购订单"""
    query = select(PurchaseOrder).options(joinedload(PurchaseOrder.items))
    if status:
        query = query.where(PurchaseOrder.status == status)
    query = query.order_by(PurchaseOrder.create_time.desc()).limit(50)
    result = await db.execute(query)
    orders = list(result.unique().scalars().all())

    return {
        'success': True,
        'orders': [{
            'id': o.id, 'order_no': o.order_no, 'supplier_name': o.supplier_name,
            'customer_name': o.customer_name,
            'order_date': o.order_date.strftime('%Y-%m-%d') if o.order_date else None,
            'status': o.status, 'item_count': len(o.items),
            'items': [i.to_dict() for i in o.items],
        } for o in orders]
    }

async def get_purchase_order_items(db, order_id: int) -> dict:
    """获取采购订单物料明细"""
    po = await db.get(PurchaseOrder, order_id)
    if not po:
        raise ValueError("采购订单不存在")
    result = await db.execute(
        # limit(5000)：单采购订单明细的行数上界（批次1 防护，正常订单远低于此）
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order_id).limit(5000)
    )
    items = list(result.scalars().all())
    return {'success': True, 'items': [item.to_dict() for item in items]}

async def preview_purchase_order(db, order_no: str) -> dict:
    """采购订单快速预览"""
    result = await db.execute(
        select(PurchaseOrder)
        .options(joinedload(PurchaseOrder.items))
        .where(PurchaseOrder.order_no == order_no)
    )
    order = result.unique().scalar_one_or_none()
    if not order:
        raise ValueError("订单不存在")

    # Fetch source sales orders info
    source_orders = {}
    source_order_ids = set()
    if order.source_order_id:
        source_order_ids.add(order.source_order_id)
    if order.source_order_ids:
        try:
            for sid in json.loads(order.source_order_ids):
                if sid:
                    source_order_ids.add(sid)
        except (json.JSONDecodeError, TypeError):
            pass  # defensive: 异常静默处理,不影响主流程
    if source_order_ids:
        so_result = await db.execute(
            select(Order).options(joinedload(Order.product)).where(Order.id.in_(source_order_ids))
        )
        for so in so_result.unique().scalars().all():
            source_orders[so.id] = so

    order_dict = order.to_dict(source_orders=source_orders)
    order_dict['source_order_ids'] = order.source_order_ids

    # Enrich source order details for display
    source_details = []
    for so in source_orders.values():
        detail: dict = {'id': so.id, 'order_no': so.order_no}
        if hasattr(so, 'product') and so.product:
            detail['product_name'] = so.product.name
        if hasattr(so, 'quantity') and so.quantity:
            detail['quantity'] = float(so.quantity)
        detail['customer_name'] = so.customer if hasattr(so, 'customer') else None
        source_details.append(detail)
    order_dict['source_orders'] = source_details

    return {'success': True, 'order': order_dict}

async def get_history(db, page: int = 1, per_page: int = 20,
                      order_no: str = '', supplier: str = '',
                      customer_name: str = '', material_category: str = '',
                      start_date: str = '', end_date: str = '') -> dict:
    # Build filter conditions (shared between count and data queries)
    conditions = [MaterialRegistration.status == 'completed']

    if order_no:
        conditions.append(MaterialRegistration.purchase_order_no.ilike(f'%{escape_like(order_no)}%'))
    if supplier:
        conditions.append(MaterialRegistration.supplier_name.ilike(f'%{escape_like(supplier)}%'))
    if customer_name:
        conditions.append(PurchaseOrder.customer_name.ilike(f'%{escape_like(customer_name)}%'))
    if start_date:
        conditions.append(MaterialRegistration.registration_date >= _parse_filter_date(start_date, '开始日期'))
    if end_date:
        conditions.append(MaterialRegistration.registration_date <= _parse_filter_date(end_date, '结束日期'))
    if material_category:
        conditions.append(
            MaterialRegistration.items.any(MaterialRegistrationItem.material_category == material_category)
        )

    # customer_name 筛选需要 JOIN purchase_order；count 与 data 查询共用同一 JOIN 决策
    needs_po_join = bool(customer_name)

    # Count query — no eager loading, just count
    count_query = select(func.count(MaterialRegistration.id))
    if needs_po_join:
        count_query = count_query.join(MaterialRegistration.purchase_order)
    count_query = count_query.where(*conditions)
    total = (await db.execute(count_query)).scalar() or 0

    # Data query — DB-level pagination with eager loading only for the page
    offset = (page - 1) * per_page
    data_query = select(MaterialRegistration).options(
        selectinload(MaterialRegistration.items),
        joinedload(MaterialRegistration.purchase_order),
    )
    if needs_po_join:
        data_query = data_query.join(MaterialRegistration.purchase_order)
    data_query = (
        data_query.where(*conditions)
        .order_by(MaterialRegistration.update_time.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(data_query)
    page_regs = list(result.unique().scalars().all())

    return {
        'success': True,
        'registrations': [r.to_dict() for r in page_regs],
        'total': total,
        'pages': calc_total_pages(total, per_page),
        'current_page': page,
    }

async def get_suggestions(db, field: str, keyword: str, limit: int = 10) -> dict:
    """获取搜索联想建议"""
    if not field or not keyword or len(keyword) < 1:
        return {'success': True, 'suggestions': []}

    suggestions = []
    try:
        if field == 'order_no':
            result = await db.execute(
                select(MaterialRegistration.purchase_order_no)
                .where(MaterialRegistration.purchase_order_no.ilike(f'%{escape_like(keyword)}%'))
                .distinct().limit(limit)
            )
            suggestions = [r[0] for r in result.all() if r[0]]
        elif field == 'supplier':
            result = await db.execute(
                select(MaterialRegistration.supplier_name)
                .where(MaterialRegistration.supplier_name.ilike(f'%{escape_like(keyword)}%'))
                .distinct().limit(limit)
            )
            suggestions = [r[0] for r in result.all() if r[0]]
        elif field == 'material_name':
            result = await db.execute(
                select(MaterialRegistrationItem.material_name)
                .where(MaterialRegistrationItem.material_name.ilike(f'%{escape_like(keyword)}%'))
                .distinct().limit(limit)
            )
            suggestions = [r[0] for r in result.all() if r[0]]
    except (OperationalError, DisconnectionError) as e:
        logger.error(f"获取联想建议失败: {e}")

    return {'success': True, 'suggestions': suggestions[:limit]}

@cache_result(key_prefix="material:overview", ttl=60, local_ttl=15,
             key_builder=lambda *a, **kw: "global")
async def get_stats_overview(db) -> dict:
    """统计概览（L1 15s + L2 60s 缓存，写操作时通过 MATERIAL 域失效）"""
    status_counts_result = await db.execute(
        select(MaterialRegistration.status, func.count())
        .where(MaterialRegistration.status.in_(['pending', 'partial', 'completed']))
        .group_by(MaterialRegistration.status)
    )
    status_counts = {row[0]: row[1] for row in status_counts_result}
    pending = status_counts.get('pending', 0)
    partial = status_counts.get('partial', 0)
    completed = status_counts.get('completed', 0)
    total_all_num = sum(status_counts.values())

    totals_result = await db.execute(
        select(
            func.sum(MaterialRegistrationItem.ordered_quantity),
            func.sum(MaterialRegistrationItem.received_quantity),
        )
    )
    totals_row = totals_result.one()
    total_ordered = totals_row[0] or 0
    total_received = totals_row[1] or 0

    today = datetime.now(UTC).replace(tzinfo=None).date()
    week_ago = today - timedelta(days=7)

    recent = (await db.execute(
        select(func.count()).where(MaterialRegistration.registration_date >= week_ago)
    )).scalar() or 0

    return {
        'success': True,
        'overview': {
            'total': total_all_num, 'pending': pending, 'partial': partial,
            'completed': completed,
            'total_ordered': float(total_ordered),
            'total_received': float(total_received),
            'total_remaining': float(total_ordered) - float(total_received),
            'overall_progress': min(round_qty(float(total_received) / float(total_ordered or 1) * 100, precision_digits=1), 99.9) if completed < total_all_num else (100.0 if total_all_num > 0 else 0),
            'recent_registrations': recent,
        }
    }

@cache_result(key_prefix="material:distribution", ttl=60, local_ttl=15,
             key_builder=lambda *a, **kw: "global")
async def get_stats_distribution(db) -> dict:
    """状态分布（L1 15s + L2 60s 缓存，写操作时通过 MATERIAL 域失效）"""
    status_counts_result = await db.execute(
        select(MaterialRegistration.status, func.count())
        .where(MaterialRegistration.status.in_(['pending', 'partial', 'completed']))
        .group_by(MaterialRegistration.status)
    )
    status_counts = {row[0]: row[1] for row in status_counts_result}
    pending = status_counts.get('pending', 0)
    partial = status_counts.get('partial', 0)
    completed = status_counts.get('completed', 0)

    month_ago = datetime.now(UTC).replace(tzinfo=None).date() - timedelta(days=30)
    overdue_items = (await db.execute(
        select(func.count(MaterialRegistrationItem.id)).where(
            MaterialRegistrationItem.ordered_quantity > MaterialRegistrationItem.received_quantity,
            MaterialRegistration.registration_date < month_ago
        ).join(MaterialRegistration)
    )).scalar() or 0

    return {
        'success': True,
        'distribution': [
            {'status': 'pending', 'count': pending},
            {'status': 'partial', 'count': partial},
            {'status': 'completed', 'count': completed},
            {'status': 'overdue', 'count': overdue_items},
        ]
    }

@cache_result(key_prefix="material:trend", ttl=60, local_ttl=15,
             key_builder=lambda **kwargs: str(kwargs.get('days', 30)))
async def get_stats_trend(db, days: int = 30) -> dict:
    """趋势数据（SQL GROUP BY 替代全量 ORM 加载，L1 15s + L2 60s 缓存）"""
    # 2026-10-18 OCR 评审：registered 按 registration_date（写入时用 UTC 日期）
    # 分桶，received 必须用同一个 UTC 日边界，否则两条曲线差一天。
    end_date = datetime.now(UTC).replace(tzinfo=None).date()
    start_date = end_date - timedelta(days=days)

    # 生成完整日期骨架
    date_map = {}
    current = start_date
    while current <= end_date:
        date_map[current.strftime('%Y-%m-%d')] = {'registered': 0, 'received': 0}
        current += timedelta(days=1)

    # SQL 聚合：只返回 date + count，不加载 ORM 对象
    reg_counts = (await db.execute(
        select(MaterialRegistration.registration_date, func.count())
        .where(
            MaterialRegistration.registration_date >= start_date,
            MaterialRegistration.registration_date <= end_date
        )
        .group_by(MaterialRegistration.registration_date)
    )).all()

    for reg_date, cnt in reg_counts:
        key = reg_date.strftime('%Y-%m-%d') if reg_date else None
        if key and key in date_map:
            date_map[key]['registered'] = cnt

    # 2026-10-17 审计 P2-09：received 此前从未赋值（恒为 0 骨架值）。
    # 口径：当天完成的来料登记数（status=completed，按 update_time 的日期归档——
    # 完成时间没有独立列，update_time 是唯一可用近似）。
    # 2026-10-18 OCR 评审：必须显式 `AT TIME ZONE 'UTC'` 再取 date。
    # update_time 是 timestamptz，裸 `func.date(update_time)` 由 PostgreSQL 按
    # **会话时区**（本库为 Asia/Shanghai）取日界，而 registered 侧的
    # registration_date 是 Date 列、写入端用 `datetime.now(UTC).date()`
    # （services/material_registration/_commands.py 与模型 default）→ 裸 date() 会让
    # received 比 registered 整体晚一天（UTC 00:00–08:00 完成的登记落到次日），
    # 两条曲线错位一天。转成 UTC 日期后与 registered 同边界。
    # （副作用：该表达式无法走索引，只扫 30 天窗口，可接受。）
    recv_counts = (await db.execute(
        select(func.date(MaterialRegistration.update_time.op('AT TIME ZONE')('UTC')), func.count())
        .where(
            MaterialRegistration.status == 'completed',
            func.date(MaterialRegistration.update_time.op('AT TIME ZONE')('UTC')) >= start_date,
            func.date(MaterialRegistration.update_time.op('AT TIME ZONE')('UTC')) <= end_date,
        )
        .group_by(func.date(MaterialRegistration.update_time.op('AT TIME ZONE')('UTC')))
    )).all()

    for recv_date, cnt in recv_counts:
        key = recv_date.strftime('%Y-%m-%d') if recv_date else None
        if key and key in date_map:
            date_map[key]['received'] = cnt

    trend = [{'date': k, **v} for k, v in sorted(date_map.items())]

    return {'success': True, 'trend': trend}
