"""
采购中心 — 采购订单服务

从 purchase_center_service.py 拆分为独立模块。

原始 purchase_center_service.py 使用同步 SQLAlchemy Session。
本模块已迁移至 AsyncSession 以消除同步阻塞的瓶颈。
"""
import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services import escape_like
from fastapi_app.shared_models import (
    MaterialRegistration,
    ModificationLog,
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    ProductPackaging,
    PurchaseOrder,
    PurchaseOrderItem,
)
from fastapi_app.shared_models.order import Order

logger = logging.getLogger(__name__)



async def generate_purchase_order_no(db: AsyncSession, prefix: str = 'CG') -> str:
    date_str = datetime.now().strftime('%Y%m%d')
    today_min = datetime.combine(date.today(), datetime.min.time())
    today_max = today_min + timedelta(days=1)

    result = await db.execute(
        select(func.max(PurchaseOrder.order_no)).where(
            PurchaseOrder.create_time >= today_min,
            PurchaseOrder.create_time < today_max,
            PurchaseOrder.order_no.like(f'{prefix}{date_str}%'),
        )
    )
    max_no = result.scalar()
    if max_no:
        try:
            last_seq = int(max_no[len(prefix) + len(date_str):])
            seq = str(last_seq + 1).zfill(3)
        except ValueError:
            seq = '001'
    else:
        seq = '001'
    return f'{prefix}{date_str}{seq}'


async def create_purchase_order(db: AsyncSession, data: dict, include_summary: bool = False) -> dict:
    items = data.get('items', [])
    if not items:
        raise ValueError('采购订单至少需要一条明细')

    order_no = await generate_purchase_order_no(db)
    supplier_name = items[0].get('supplier_name', '')
    supplier_id = items[0].get('supplier_id')
    customer_name = data.get('customer_name', items[0].get('customer_name', ''))

    order = PurchaseOrder(
        order_no=order_no,
        supplier_name=supplier_name,
        supplier_id=supplier_id,
        customer_name=customer_name,
        status='pending',
        remark=data.get('note', ''),
        source_order_ids=data.get('source_order_ids'),
        product_name=data.get('product_name'),
        product_quantity=data.get('product_quantity'),
    )
    db.add(order)
    try:
        await db.flush()
    except IntegrityError:
        # 并发时 order_no 可能重复，回滚后重新生成
        await db.rollback()
        order_no = await generate_purchase_order_no(db)
        order = PurchaseOrder(
            order_no=order_no,
            supplier_name=supplier_name,
            supplier_id=supplier_id,
            customer_name=customer_name,
            status='pending',
            remark=data.get('note', ''),
            source_order_ids=data.get('source_order_ids'),
            product_name=data.get('product_name'),
            product_quantity=data.get('product_quantity'),
        )
        db.add(order)
        await db.flush()

    total_amount = Decimal('0')
    for item_data in items:
        material_name = item_data.get('material_name', '')
        unit_price = Decimal(str(item_data.get('unit_price', 0)))
        quantity = Decimal(str(item_data.get('quantity', 0)))
        amount = unit_price * quantity

        poi = PurchaseOrderItem(
            order_id=order.id,
            material_name=material_name,
            material_code=item_data.get('material_code', ''),
            specification=item_data.get('specification', ''),
            unit=item_data.get('unit', ''),
            unit_price=unit_price,
            quantity=quantity,
            total_price=amount,
            supplier_name=supplier_name,
            customer_name=customer_name,
            material_category=item_data.get('category', ''),
            remark=item_data.get('remark', ''),
        )
        db.add(poi)
        total_amount += amount

    order.total_amount = total_amount
    await db.commit()

    result = {'order_no': order_no, 'id': order.id, 'total_amount': float(total_amount)}

    if include_summary:
        result['summary'] = await _build_order_summary(db, order)

    return result


async def get_purchase_orders(db: AsyncSession, *, page: int = 1, per_page: int = 20,
                              status: str = '', supplier_id: int | None = None,
                              keyword: str = '', date_from: str = '', date_to: str = '',
                              sort_by: str = 'create_time', sort_order: str = 'desc') -> dict:
    query = select(PurchaseOrder)
    count_query = select(func.count(PurchaseOrder.id))

    if status:
        query = query.where(PurchaseOrder.status == status)
        count_query = count_query.where(PurchaseOrder.status == status)
    if supplier_id:
        query = query.where(PurchaseOrder.supplier_id == supplier_id)
        count_query = count_query.where(PurchaseOrder.supplier_id == supplier_id)
    if keyword:
        like_pattern = f'%{escape_like(keyword)}%'
        query = query.where(
            or_(
                PurchaseOrder.order_no.ilike(like_pattern),
                PurchaseOrder.customer_name.ilike(like_pattern),
                PurchaseOrder.supplier_name.ilike(like_pattern),
            )
        )
        count_query = count_query.where(
            or_(
                PurchaseOrder.order_no.ilike(like_pattern),
                PurchaseOrder.customer_name.ilike(like_pattern),
                PurchaseOrder.supplier_name.ilike(like_pattern),
            )
        )
    if date_from:
        query = query.where(PurchaseOrder.create_time >= date_from)
        count_query = count_query.where(PurchaseOrder.create_time >= date_from)
    if date_to:
        query = query.where(PurchaseOrder.create_time <= f'{date_to} 23:59:59')
        count_query = count_query.where(PurchaseOrder.create_time <= f'{date_to} 23:59:59')

    sort_map = {
        'create_time': PurchaseOrder.create_time,
        'order_no': PurchaseOrder.order_no,
        'total_amount': PurchaseOrder.total_amount,
    }
    sort_col = sort_map.get(sort_by, PurchaseOrder.create_time)
    if sort_order == 'desc':
        sort_col = sort_col.desc()
    query = query.order_by(sort_col)

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    orders = result.scalars().unique().all()

    order_ids = [o.id for o in orders]

    if order_ids:
        items_result = await db.execute(
            select(PurchaseOrderItem).where(PurchaseOrderItem.order_id.in_(order_ids))
        )
        all_items = items_result.scalars().all()
        items_by_order: dict[int, list] = defaultdict(list)
        for item in all_items:
            items_by_order[item.order_id].append(item)
    else:
        items_by_order = {}

    # 回填 product_name / quantity：对这两个字段为 NULL 的采购单，
    # 通过 source_order_ids 查找关联客户订单的产品名称和数量
    source_order_map: dict[int, tuple[str, int]] = {}  # {customer_order_id: (product_name, quantity)}
    orders_needing_fill = [o for o in orders if not o.product_name and (o.source_order_ids or o.source_order_id)]
    if orders_needing_fill:
        import json as _json
        all_source_ids: set[int] = set()
        for o in orders_needing_fill:
            if o.source_order_id:
                all_source_ids.add(o.source_order_id)
            if o.source_order_ids:
                try:
                    ids = _json.loads(o.source_order_ids) if isinstance(o.source_order_ids, str) else o.source_order_ids
                    all_source_ids.update(int(x) for x in ids)
                except (ValueError, TypeError):
                    pass
        if all_source_ids:
            from fastapi_app.shared_models import Order as CustomerOrder
            cust_result = await db.execute(
                select(CustomerOrder.id, CustomerOrder.product_id, CustomerOrder.quantity)
                .where(CustomerOrder.id.in_(all_source_ids))
            )
            cust_rows = cust_result.all()
            cust_pids = list({r.product_id for r in cust_rows if r.product_id})
            pid_name_map_fill: dict[int, str] = {}
            if cust_pids:
                prod_result = await db.execute(
                    select(Product.id, Product.name).where(Product.id.in_(cust_pids))
                )
                pid_name_map_fill = dict(prod_result.all())
            for r in cust_rows:
                source_order_map[r.id] = (pid_name_map_fill.get(r.product_id, ''), r.quantity or 0)

    order_list = []
    for order in orders:
        items = items_by_order.get(order.id, [])
        product_name = order.product_name or ''
        quantity = float(order.product_quantity or 0) if order.product_quantity else 0

        # 回填：从 source_order 获取产品名称和数量
        if not product_name or not quantity:
            import json as _json
            resolved_ids: list[int] = []
            if order.source_order_id:
                resolved_ids.append(order.source_order_id)
            if order.source_order_ids:
                try:
                    ids = _json.loads(order.source_order_ids) if isinstance(order.source_order_ids, str) else order.source_order_ids
                    resolved_ids.extend(int(x) for x in ids)
                except (ValueError, TypeError):
                    pass
            # 取第一个有数据的 source order 的产品名；数量求和
            names = set()
            qty_sum = 0
            for sid in resolved_ids:
                info = source_order_map.get(sid)
                if info:
                    if info[0]:
                        names.add(info[0])
                    qty_sum += info[1]
            if not product_name and names:
                product_name = '、'.join(sorted(names)) if len(names) > 1 else next(iter(names))
            if not quantity and qty_sum:
                quantity = float(qty_sum)

        order_list.append({
            'id': order.id,
            'order_no': order.order_no,
            'supplier_name': order.supplier_name,
            'supplier_id': order.supplier_id,
            'customer_name': order.customer_name,
            'customer': order.customer_name,
            'status': order.status,
            'total_amount': float(order.total_amount or 0),
            'product_name': product_name,
            'quantity': quantity,
            'order_date': order.order_date.strftime('%Y-%m-%d') if order.order_date else '',
            'has_bom': bool(items),
            'note': order.remark or '',
            'create_time': order.create_time.strftime('%Y-%m-%d %H:%M') if order.create_time else '',
            'items': [
                {
                    'id': item.id,
                    'material_name': item.material_name,
                    'material_code': item.material_code or '',
                    'specification': item.specification or '',
                    'unit': item.unit or '',
                    'unit_price': float(item.unit_price or 0),
                    'quantity': float(item.quantity or 0),
                    'amount': float(item.total_price or 0),
                    'category': item.material_category or '',
                    'remark': item.remark or '',
                }
                for item in items
            ],
        })

    return {
        'orders': order_list,
        'total': total,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
        'current_page': page,
    }


async def get_purchase_order(db: AsyncSession, order_id: int) -> dict:
    order = await db.get(PurchaseOrder, order_id)
    if not order:
        return None

    items_result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order_id)
    )
    items = items_result.scalars().all()

    product_name = order.product_name or ''
    quantity = float(order.product_quantity or 0) if order.product_quantity else 0

    # 回填：从 source_order 获取产品名称和数量
    if not product_name or not quantity:
        import json as _json
        resolved_ids: list[int] = []
        if order.source_order_id:
            resolved_ids.append(order.source_order_id)
        if order.source_order_ids:
            try:
                ids = _json.loads(order.source_order_ids) if isinstance(order.source_order_ids, str) else order.source_order_ids
                resolved_ids.extend(int(x) for x in ids)
            except (ValueError, TypeError):
                pass
        if resolved_ids:
            from fastapi_app.shared_models import Order as CustomerOrder
            cust_result = await db.execute(
                select(CustomerOrder.id, CustomerOrder.product_id, CustomerOrder.quantity)
                .where(CustomerOrder.id.in_(resolved_ids))
            )
            cust_rows = cust_result.all()
            cust_pids = list({r.product_id for r in cust_rows if r.product_id})
            pid_name_map: dict[int, str] = {}
            if cust_pids:
                prod_result = await db.execute(
                    select(Product.id, Product.name).where(Product.id.in_(cust_pids))
                )
                pid_name_map = dict(prod_result.all())
            names = set()
            qty_sum = 0
            for r in cust_rows:
                pname = pid_name_map.get(r.product_id, '')
                if pname:
                    names.add(pname)
                qty_sum += r.quantity or 0
            if not product_name and names:
                product_name = '、'.join(sorted(names)) if len(names) > 1 else next(iter(names))
            if not quantity and qty_sum:
                quantity = float(qty_sum)

    return {
        'id': order.id,
        'order_no': order.order_no,
        'supplier_name': order.supplier_name,
        'supplier_id': order.supplier_id,
        'customer_name': order.customer_name,
        'customer': order.customer_name,
        'status': order.status,
        'total_amount': float(order.total_amount or 0),
        'product_name': product_name,
        'quantity': quantity,
        'order_date': order.order_date.strftime('%Y-%m-%d') if order.order_date else '',
        'note': order.remark or '',
        'create_time': order.create_time.strftime('%Y-%m-%d %H:%M') if order.create_time else '',
        'items': [
            {
                'id': item.id,
                'material_name': item.material_name,
                'material_code': item.material_code or '',
                'specification': item.specification or '',
                'unit': item.unit or '',
                'unit_price': float(item.unit_price or 0),
                'quantity': float(item.quantity or 0),
                'amount': float(item.total_price or 0),
                'category': item.material_category or '',
                'remark': item.remark or '',
            }
            for item in items
        ],
    }


async def update_purchase_order(db: AsyncSession, order_id: int, data: dict, username: str = 'unknown') -> dict:
    order = await db.get(PurchaseOrder, order_id)
    if not order:
        raise ValueError('采购订单不存在')

    if 'customer_name' in data:
        order.customer_name = data['customer_name']
    if 'supplier_name' in data:
        order.supplier_name = data['supplier_name']
    if 'note' in data:
        order.remark = data['note']
    if 'status' in data:
        order.status = data['status']

    items_data = data.get('items')
    if items_data is not None:
        existing_items_result = await db.execute(
            select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order_id)
        )
        existing_items = {item.id for item in existing_items_result.scalars().all()}

        total_amount = Decimal('0')
        updated_ids = set()

        for item_data in items_data:
            item_id = item_data.get('id')
            if item_id:
                item = await db.get(PurchaseOrderItem, item_id)
                if item and item.order_id == order_id:
                    updated_ids.add(item_id)
            else:
                item = PurchaseOrderItem(order_id=order_id)

            item.material_name = item_data.get('material_name', '')
            item.material_code = item_data.get('material_code', '')
            item.specification = item_data.get('specification', '')
            item.unit = item_data.get('unit', '')
            item.unit_price = Decimal(str(item_data.get('unit_price', 0)))
            item.quantity = Decimal(str(item_data.get('quantity', 0)))
            item.total_price = item.unit_price * item.quantity
            item.material_category = item_data.get('category', '')
            item.remark = item_data.get('remark', '')
            item.supplier_name = order.supplier_name
            item.customer_name = order.customer_name

            if not item_id:
                db.add(item)
            total_amount += item.total_price

        to_delete_ids = existing_items - updated_ids
        if to_delete_ids:
            await db.execute(
                delete(PurchaseOrderItem).where(PurchaseOrderItem.id.in_(to_delete_ids))
            )

        order.total_amount = total_amount

    await db.commit()

    db.add(ModificationLog(
        target_type='purchase_order',
        target_id=order_id,
        field_name='update',
        old_value=f'订单{order.order_no}已更新',
        new_value=json.dumps({
            'status': order.status,
            'total_amount': float(order.total_amount or 0),
        }, ensure_ascii=False),
        modifier_name=username,
    ))

    return {'id': order.id, 'order_no': order.order_no, 'status': order.status}


async def delete_purchase_order(db: AsyncSession, order_id: int) -> dict:
    order = await db.get(PurchaseOrder, order_id)
    if not order:
        raise ValueError('采购订单不存在')

    items_result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order_id)
    )
    for item in items_result.scalars().all():
        await db.delete(item)

    await db.delete(order)
    await db.commit()
    return {'id': order_id, 'order_no': order.order_no}


async def complete_purchase_order(db: AsyncSession, order_id: int, username: str = 'unknown') -> dict:
    order = await db.get(PurchaseOrder, order_id)
    if not order:
        raise ValueError('采购订单不存在')
    if order.status not in ('pending', 'confirmed'):
        raise ValueError(f'订单{order.order_no}状态不允许完成')

    items_result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order_id)
    )
    items = items_result.scalars().all()

    now = datetime.now()
    for item in items:
        reg = MaterialRegistration(
            order_id=order_id,
            material_name=item.material_name,
            material_code=item.material_code or '',
            specification=item.specification or '',
            unit=item.unit or '',
            quantity=item.quantity,
            unit_price=item.unit_price,
            category=item.material_category or '',
            supplier_name=order.supplier_name or '',
            supplier_id=order.supplier_id,
            customer_name=order.customer_name or '',
            registration_date=now,
            remark=item.remark or '',
            purchase_order_no=order.order_no,
        )
        db.add(reg)

        query = select(func.coalesce(func.sum(MaterialRegistration.quantity), 0)).where(
            MaterialRegistration.material_name == item.material_name,
            MaterialRegistration.material_code == item.material_code,
        )
        cumulative_result = await db.execute(query)
        cumulative = cumulative_result.scalar() or 0

        arrived_result = await db.execute(
            select(func.coalesce(func.sum(MaterialRegistration.quantity), 0)).where(
                MaterialRegistration.material_name == item.material_name,
                MaterialRegistration.material_code == item.material_code,
                MaterialRegistration.registration_status == 'arrived',
            )
        )
        arrived_qty = arrived_result.scalar() or 0

        existing = item.material_code and item.material_name
        is_arrived = cumulative >= item.quantity
        deficit = max(0, int(item.quantity) - cumulative) if existing else 0

        db.add(ModificationLog(
            target_type='purchase_item',
            target_id=item.id,
            field_name='completion',
            old_value=f'{item.material_name}(待完成)',
            new_value=json.dumps({
                'arrived_qty': str(arrived_qty),
                'total_qty': str(cumulative),
                'is_arrived': is_arrived,
                'deficit': deficit,
            }, ensure_ascii=False),
            modifier_name=username,
        ))

    order.status = 'completed'
    order.completed_at = now
    await db.commit()
    return {'id': order.id, 'order_no': order.order_no, 'status': 'completed'}


async def batch_complete_purchase_orders(db: AsyncSession, order_ids: list, username: str = 'unknown') -> dict:
    """
    批量完成采购订单并登记来料。

    优化：一次查询获取所有订单，避免 N+1。
    """
    if not order_ids:
        raise ValueError('请选择要完成的订单')

    result = await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.id.in_(order_ids))
    )
    orders = {o.id: o for o in result.scalars().all()}

    completed = 0
    errors = []
    now = datetime.now()

    for oid in order_ids:
        try:
            order = orders.get(oid)
            if not order:
                errors.append(f'订单{oid}不存在')
                continue
            if order.status not in ('pending', 'confirmed'):
                errors.append(f'订单{order.order_no}状态不允许完成')
                continue

            items_result = await db.execute(
                select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == oid)
            )
            items = items_result.scalars().all()

            for item in items:
                reg = MaterialRegistration(
                    order_id=oid,
                    material_name=item.material_name,
                    material_code=item.material_code or '',
                    specification=item.specification or '',
                    unit=item.unit or '',
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    category=item.material_category or '',
                    supplier_name=order.supplier_name or '',
                    supplier_id=order.supplier_id,
                    customer_name=order.customer_name or '',
                    registration_date=now,
                    remark=item.remark or '',
                    purchase_order_no=order.order_no,
                )
                db.add(reg)

            order.status = 'completed'
            order.completed_at = now
            completed += 1
        except (ValueError, TypeError) as e:
            errors.append(f'订单处理失败: {str(e)}')

    await db.commit()
    return {'completed': completed, 'errors': errors}


async def get_completed_purchase_orders(
    db: AsyncSession, *, page: int = 1, per_page: int = 20,
    supplier_id: int | None = None, keyword: str = '',
    date_from: str = '', date_to: str = '',
    quick_filter: str = '', is_arrived: str = '',
    sort_by: str = 'completed_at', sort_order: str = 'desc',
) -> dict:
    query = select(PurchaseOrder).where(PurchaseOrder.status == 'completed')
    count_query = select(func.count(PurchaseOrder.id)).where(PurchaseOrder.status == 'completed')

    if supplier_id:
        query = query.where(PurchaseOrder.supplier_id == supplier_id)
        count_query = count_query.where(PurchaseOrder.supplier_id == supplier_id)
    if keyword:
        like_pattern = f'%{escape_like(keyword)}%'
        query = query.where(
            or_(
                PurchaseOrder.order_no.ilike(like_pattern),
                PurchaseOrder.customer_name.ilike(like_pattern),
                PurchaseOrder.supplier_name.ilike(like_pattern),
            )
        )
        count_query = count_query.where(
            or_(
                PurchaseOrder.order_no.ilike(like_pattern),
                PurchaseOrder.customer_name.ilike(like_pattern),
                PurchaseOrder.supplier_name.ilike(like_pattern),
            )
        )
    if date_from:
        query = query.where(PurchaseOrder.completed_at >= date_from)
        count_query = count_query.where(PurchaseOrder.completed_at >= date_from)
    if date_to:
        query = query.where(PurchaseOrder.completed_at <= f'{date_to} 23:59:59')
        count_query = count_query.where(PurchaseOrder.completed_at <= f'{date_to} 23:59:59')

    if quick_filter == 'today':
        today = date.today()
        query = query.where(PurchaseOrder.completed_at >= today)
        count_query = count_query.where(PurchaseOrder.completed_at >= today)
    elif quick_filter == 'week':
        week_ago = date.today() - timedelta(days=7)
        query = query.where(PurchaseOrder.completed_at >= week_ago)
        count_query = count_query.where(PurchaseOrder.completed_at >= week_ago)
    elif quick_filter == 'month':
        month_ago = date.today() - timedelta(days=30)
        query = query.where(PurchaseOrder.completed_at >= month_ago)
        count_query = count_query.where(PurchaseOrder.completed_at >= month_ago)

    sort_map = {
        'completed_at': PurchaseOrder.completed_at,
        'order_no': PurchaseOrder.order_no,
        'total_amount': PurchaseOrder.total_amount,
    }
    sort_col = sort_map.get(sort_by, PurchaseOrder.completed_at)
    if sort_order == 'desc':
        sort_col = sort_col.desc()
    query = query.order_by(sort_col)

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    orders = result.scalars().unique().all()

    order_ids = [o.id for o in orders]

    if order_ids:
        items_result = await db.execute(
            select(PurchaseOrderItem).where(PurchaseOrderItem.order_id.in_(order_ids))
        )
        all_items = items_result.scalars().all()
        items_by_order: dict[int, list] = defaultdict(list)
        for item in all_items:
            items_by_order[item.order_id].append(item)

        regs_result = await db.execute(
            select(
                MaterialRegistration.material_name,
                MaterialRegistration.material_code,
                func.sum(MaterialRegistration.quantity).label('total'),
            ).where(
                MaterialRegistration.order_id.in_(order_ids),
                MaterialRegistration.registration_status == 'arrived',
            ).group_by(
                MaterialRegistration.material_name,
                MaterialRegistration.material_code,
            )
        )
        arrived_map = {
            (r.material_name, r.material_code): int(r.total or 0)
            for r in regs_result
        }
    else:
        items_by_order = {}
        arrived_map = {}

    order_list = []
    for order in orders:
        items = items_by_order.get(order.id, [])
        item_list = []
        for item in items:
            required = int(item.quantity or 0)
            key = (item.material_name, item.material_code)
            arrived = arrived_map.get(key, 0)
            item_list.append({
                'id': item.id,
                'material_name': item.material_name,
                'material_code': item.material_code or '',
                'specification': item.specification or '',
                'unit': item.unit or '',
                'unit_price': float(item.unit_price or 0),
                'quantity': float(item.quantity or 0),
                'amount': float(item.total_price or 0),
                'category': item.material_category or '',
                'remark': item.remark or '',
                'is_arrived': required > 0 and arrived >= required,
                'deficit': max(0, required - arrived) if required > 0 else 0,
            })
        order_list.append({
            'id': order.id,
            'order_no': order.order_no,
            'supplier_name': order.supplier_name,
            'supplier_id': order.supplier_id,
            'customer_name': order.customer_name,
            'customer': order.customer_name,
            'status': order.status,
            'total_amount': float(order.total_amount or 0),
            'product_name': order.product_name or '',
            'quantity': float(order.product_quantity or 0) if order.product_quantity else 0,
            'order_date': order.order_date.strftime('%Y-%m-%d') if order.order_date else '',
            'note': order.remark or '',
            'create_time': order.create_time.strftime('%Y-%m-%d %H:%M') if order.create_time else '',
            'completed_at': order.completed_at.strftime('%Y-%m-%d %H:%M') if order.completed_at else '',
            'items': item_list,
        })

    return {
        'orders': order_list,
        'total': total,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
        'current_page': page,
    }


async def get_supplier_order_summary(db: AsyncSession, supplier_id: int | None = None) -> dict:
    query = select(
        PurchaseOrder.supplier_name,
        PurchaseOrder.supplier_id,
        func.count(PurchaseOrder.id).label('order_count'),
        func.sum(PurchaseOrder.total_amount).label('total_amount'),
    )

    if supplier_id:
        query = query.where(PurchaseOrder.supplier_id == supplier_id)
    query = query.where(PurchaseOrder.status == 'completed').group_by(
        PurchaseOrder.supplier_name, PurchaseOrder.supplier_id,
    )

    result = await db.execute(query)
    rows = result.all()

    return {
        'summary': [
            {
                'supplier_name': r.supplier_name,
                'supplier_id': r.supplier_id,
                'order_count': r.order_count,
                'total_amount': float(r.total_amount or 0),
            }
            for r in rows
        ],
    }


async def get_factory_order_summary(
    db: AsyncSession, order_ids: list | None = None,
) -> dict:
    query = select(
        PurchaseOrder.id,
        PurchaseOrder.order_no,
    )
    if order_ids:
        query = query.where(PurchaseOrder.id.in_(order_ids))
    result = await db.execute(query)
    orders = result.all()

    summary = []
    order_ids = [order_row.id for order_row in orders]

    if order_ids:
        items_result = await db.execute(
            select(PurchaseOrderItem).where(PurchaseOrderItem.order_id.in_(order_ids))
        )
        all_items = items_result.scalars().all()
        items_by_order: dict[int, list] = {}
        for item in all_items:
            items_by_order.setdefault(item.order_id, []).append(item)
    else:
        items_by_order = {}

    for order_row in orders:
        oid = order_row.id
        items = items_by_order.get(oid, [])
        summary.append({
            'id': oid,
            'order_no': order_row.order_no,
            'items': [
                {
                    'material_name': i.material_name,
                    'material_code': i.material_code or '',
                    'specification': i.specification or '',
                    'unit': i.unit or '',
                    'quantity': float(i.quantity or 0),
                }
                for i in items
            ],
        })
    return {'summary': summary}


async def save_factory_summary_edits(
    db: AsyncSession, data: list, username: str = 'unknown',
) -> dict:
    updated = 0
    for entry in data:
        oid = entry.get('id')
        order = await db.get(PurchaseOrder, oid)
        if not order:
            continue

        items_data = entry.get('items', [])
        for item_entry in items_data:
            mid = item_entry.get('id')
            item = await db.get(PurchaseOrderItem, mid) if mid else None
            if item and item.order_id == oid:
                if 'quantity' in item_entry:
                    item.quantity = Decimal(str(item_entry['quantity']))
                    item.total_price = item.unit_price * item.quantity
                updated += 1
    await db.commit()
    return {'updated_count': updated}


async def export_completed_orders(
    db: AsyncSession, *, supplier_id: int | None = None,
    date_from: str = '', date_to: str = '',
) -> list:
    query = select(PurchaseOrder).where(PurchaseOrder.status == 'completed')
    if supplier_id:
        query = query.where(PurchaseOrder.supplier_id == supplier_id)
    if date_from:
        query = query.where(PurchaseOrder.completed_at >= date_from)
    if date_to:
        query = query.where(PurchaseOrder.completed_at <= f'{date_to} 23:59:59')
    query = query.order_by(PurchaseOrder.completed_at.desc())

    result = await db.execute(query)
    orders = result.scalars().unique().all()

    rows = []
    order_ids = [o.id for o in orders]

    if order_ids:
        items_result = await db.execute(
            select(PurchaseOrderItem).where(PurchaseOrderItem.order_id.in_(order_ids))
        )
        all_items = items_result.scalars().all()
        items_by_order: dict[int, list] = {}
        for item in all_items:
            items_by_order.setdefault(item.order_id, []).append(item)
    else:
        items_by_order = {}

    for order in orders:
        items = items_by_order.get(order.id, [])
        for item in items:
            rows.append({
                'order_no': order.order_no,
                'supplier_name': order.supplier_name,
                'customer_name': order.customer_name,
                'material_name': item.material_name,
                'material_code': item.material_code or '',
                'specification': item.specification or '',
                'unit': item.unit or '',
                'quantity': float(item.quantity or 0),
                'unit_price': float(item.unit_price or 0),
                'amount': float(item.total_price or 0),
                'completed_at': order.completed_at.strftime('%Y-%m-%d') if order.completed_at else '',
            })
    return rows


async def get_unprocessed_orders(
    db: AsyncSession, *, page: int = 1, per_page: int = 20,
) -> dict:
    """获取未处理订单列表——直接读取客户订单表（Order），不依赖 sync 机制

    与旧版备份项目一致：采购中心直接查询 status='待备货' 的客户订单，
    无需等待 sync_order_create 同步，确保任何路径创建的订单都能立即可见。
    """
    from fastapi_app.shared_models import Order as CustomerOrder
    from fastapi_app.shared_models import Product

    # 查询所有待备货且未删除的客户订单
    query = select(CustomerOrder).where(
        CustomerOrder.status == '待备货',
        CustomerOrder.is_deleted == False,  # noqa: E712
    ).order_by(CustomerOrder.order_date.desc())

    count_query = select(func.count(CustomerOrder.id)).where(
        CustomerOrder.status == '待备货',
        CustomerOrder.is_deleted == False,  # noqa: E712
    )

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    orders = result.scalars().unique().all()

    # 批量查询产品名称（避免 lazy load）
    product_ids = list({o.product_id for o in orders})
    pid_name_map: dict[int, str] = {}
    if product_ids:
        prod_result = await db.execute(
            select(Product.id, Product.name).where(Product.id.in_(product_ids))
        )
        pid_name_map = dict(prod_result.all())

    # 批量查询 BOM 信息：检查每个产品是否配置了任何类型的物料
    bom_product_ids: set[int] = set()
    if product_ids:
        filling_result = await db.execute(
            select(ProductMaterial.product_id).where(ProductMaterial.product_id.in_(product_ids))
        )
        bom_product_ids |= {row[0] for row in filling_result}

        fabric_result = await db.execute(
            select(ProductFabric.product_id).where(ProductFabric.product_id.in_(product_ids))
        )
        bom_product_ids |= {row[0] for row in fabric_result}

        accessory_result = await db.execute(
            select(ProductAccessory.product_id).where(ProductAccessory.product_id.in_(product_ids))
        )
        bom_product_ids |= {row[0] for row in accessory_result}

        packaging_result = await db.execute(
            select(ProductPackaging.product_id).where(ProductPackaging.product_id.in_(product_ids))
        )
        bom_product_ids |= {row[0] for row in packaging_result}

    return {
        'orders': [
            {
                'id': o.id,
                'source_order_id': o.id,
                'order_no': o.order_no,
                'customer': o.customer,
                'customer_name': o.customer,
                'product_id': o.product_id,
                'product_name': pid_name_map.get(o.product_id, '未知产品'),
                'quantity': o.quantity,
                'order_date': o.order_date.strftime('%Y-%m-%d') if o.order_date else '',
                'has_bom': o.product_id in bom_product_ids,
                'create_time': o.order_date.strftime('%Y-%m-%d %H:%M') if o.order_date else '',
                'status': 'pending',
            }
            for o in orders
        ],
        'total': total,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
        'current_page': page,
    }


async def get_completed_order_suggestions(
    db: AsyncSession, keyword: str,
) -> list:
    if not keyword:
        return []
    like_pattern = f'%{escape_like(keyword)}%'
    result = await db.execute(
        select(PurchaseOrder.order_no, PurchaseOrder.id).where(
            PurchaseOrder.status == 'completed',
            or_(
                PurchaseOrder.order_no.ilike(like_pattern),
                PurchaseOrder.supplier_name.ilike(like_pattern),
            ),
        ).limit(10)
    )
    return [{'order_no': r.order_no, 'id': r.id} for r in result]


async def get_completed_order_quick_filters(db: AsyncSession) -> dict:
    today = date.today()
    today_count_result = await db.execute(
        select(func.count(PurchaseOrder.id)).where(
            PurchaseOrder.status == 'completed',
            PurchaseOrder.completed_at >= today,
        )
    )
    week_count_result = await db.execute(
        select(func.count(PurchaseOrder.id)).where(
            PurchaseOrder.status == 'completed',
            PurchaseOrder.completed_at >= today - timedelta(days=7),
        )
    )
    month_count_result = await db.execute(
        select(func.count(PurchaseOrder.id)).where(
            PurchaseOrder.status == 'completed',
            PurchaseOrder.completed_at >= today - timedelta(days=30),
        )
    )
    return {
        'today': today_count_result.scalar() or 0,
        'week': week_count_result.scalar() or 0,
        'month': month_count_result.scalar() or 0,
    }




async def generate_purchase_orders_from_customer_orders(
    db: AsyncSession, order_ids: list[int],
) -> dict:
    if not order_ids:
        raise ValueError('未选择任何订单')

    cust_result = await db.execute(
        select(Order).where(Order.id.in_(order_ids))
    )
    cust_orders = cust_result.scalars().all()

    invalid_orders = [o for o in cust_orders if o.status != '待备货']
    if invalid_orders:
        raise ValueError(f'订单 {invalid_orders[0].order_no} 当前状态为"{invalid_orders[0].status}"，仅"待备货"状态可审核')

    product_ids = list({o.product_id for o in cust_orders})
    pid_name_map: dict[int, str] = {}
    if product_ids:
        prod_result = await db.execute(
            select(Product.id, Product.name).where(Product.id.in_(product_ids))
        )
        pid_name_map = dict(prod_result.all())

    filling_map: dict[int, list] = {}
    fabric_map: dict[int, list] = {}
    accessory_map: dict[int, list] = {}
    packaging_map: dict[int, list] = {}

    if product_ids:
        fill_result = await db.execute(
            select(ProductMaterial).where(ProductMaterial.product_id.in_(product_ids))
        )
        for row in fill_result.scalars().all():
            filling_map.setdefault(row.product_id, []).append(row)

        fab_result = await db.execute(
            select(ProductFabric).where(ProductFabric.product_id.in_(product_ids))
        )
        for row in fab_result.scalars().all():
            fabric_map.setdefault(row.product_id, []).append(row)

        acc_result = await db.execute(
            select(ProductAccessory).where(ProductAccessory.product_id.in_(product_ids))
        )
        for row in acc_result.scalars().all():
            accessory_map.setdefault(row.product_id, []).append(row)

        pkg_result = await db.execute(
            select(ProductPackaging).where(ProductPackaging.product_id.in_(product_ids))
        )
        for row in pkg_result.scalars().all():
            packaging_map.setdefault(row.product_id, []).append(row)

    items = []
    for cust_order in cust_orders:
        pid = cust_order.product_id
        customer_name = cust_order.customer
        product_name = pid_name_map.get(pid, '未知产品')

        for bom in filling_map.get(pid, []):
            qty = float(bom.cotton_usage or 0) * cust_order.quantity
            items.append({
                'material_name': product_name + '-填充物',
                'material_code': bom.material_code or '',
                'specification': bom.specification or '',
                'unit': bom.unit or '克',
                'unit_price': 0,
                'quantity': qty,
                'supplier_name': bom.supplier_name or '',
                'supplier_id': bom.supplier_id,
                'customer_name': customer_name,
                'category': 'filling',
                'unit_usage': float(bom.cotton_usage or 0),
            })

        for fabric in fabric_map.get(pid, []):
            qty = float(fabric.quantity or 0) * cust_order.quantity
            items.append({
                'material_name': fabric.fabric_name or '面料',
                'material_code': fabric.material_code or '',
                'specification': fabric.specification or '',
                'unit': fabric.unit or '米',
                'unit_price': 0,
                'quantity': qty,
                'supplier_name': fabric.supplier_name or '',
                'supplier_id': fabric.supplier_id,
                'customer_name': customer_name,
                'category': 'fabric',
                'unit_usage': float(fabric.quantity or 0),
            })

        for acc in accessory_map.get(pid, []):
            qty = float(acc.quantity or 0) * cust_order.quantity
            items.append({
                'material_name': acc.accessory_name or '配件',
                'material_code': acc.material_code or '',
                'specification': acc.specification or '',
                'unit': acc.unit or '个',
                'unit_price': 0,
                'quantity': qty,
                'supplier_name': acc.supplier_name or '',
                'supplier_id': acc.supplier_id,
                'customer_name': customer_name,
                'category': 'accessory',
                'unit_usage': float(acc.quantity or 0),
            })

        for pkg in packaging_map.get(pid, []):
            qty = float(pkg.quantity or 0) * cust_order.quantity
            items.append({
                'material_name': pkg.packaging_name or '包装',
                'material_code': pkg.material_code or '',
                'specification': pkg.specification or '',
                'unit': pkg.unit or '个',
                'unit_price': 0,
                'quantity': qty,
                'supplier_name': pkg.supplier_name or '',
                'supplier_id': pkg.supplier_id,
                'customer_name': customer_name,
                'category': 'packaging',
                'unit_usage': float(pkg.quantity or 0),
            })

    if not items:
        raise ValueError('所选订单的产品未配置BOM物料，无法生成采购单')

    result = await one_click_generate_order(
        db, items,
        customer_name=cust_orders[0].customer if cust_orders else '',
        source_order_ids=[o.id for o in cust_orders],
        product_name='、'.join(sorted(pid_name_map.values())) if len(pid_name_map) > 1 else next(iter(pid_name_map.values())) if pid_name_map else '',
        product_quantity=sum(o.quantity for o in cust_orders),
    )

    processed_order_ids = [o.id for o in cust_orders]
    for cust_order in cust_orders:
        cust_order.status = '已备货'

    await cleanup_orphan_pending_purchase_orders(db, processed_order_ids)

    await db.commit()
    return result


async def one_click_generate_order(
    db: AsyncSession, items: list, supplier_stats: dict | None = None,
    customer_name: str = '', source_order_ids: list[int] | None = None,
    product_name: str = '', product_quantity: int | float = 0,
) -> dict:
    if not items:
        raise ValueError('物料列表为空')

    import json as _json
    source_ids_json = _json.dumps(source_order_ids) if source_order_ids else None

    supplier_groups: dict[str, list] = defaultdict(list)
    for item in items:
        key = f"{item.get('supplier_name', '')}|{item.get('customer_name', '')}"
        supplier_groups[key].append(item)

    generated_orders = []
    for _key, group_items in supplier_groups.items():
        order = await create_purchase_order(db, {
            'items': group_items,
            'customer_name': customer_name or group_items[0].get('customer_name', ''),
            'note': '一键生成',
            'source_order_ids': source_ids_json,
            'product_name': product_name,
            'product_quantity': product_quantity,
        }, include_summary=False)
        generated_orders.append(order)

    return {'orders': generated_orders, 'count': len(generated_orders)}


async def query_supplier_groups(db: AsyncSession, keyword: str = '') -> list:
    """查询供应商分组列表"""
    query = select(
        PurchaseOrder.supplier_name,
        PurchaseOrder.supplier_id,
        func.count(PurchaseOrder.id).label('order_count'),
        func.sum(PurchaseOrder.total_amount).label('total_amount'),
    ).where(PurchaseOrder.status == 'completed')

    if keyword:
        like_pattern = f'%{escape_like(keyword)}%'
        query = query.where(PurchaseOrder.supplier_name.ilike(like_pattern))

    query = query.group_by(PurchaseOrder.supplier_name, PurchaseOrder.supplier_id)
    query = query.order_by(func.sum(PurchaseOrder.total_amount).desc())
    result = await db.execute(query)
    rows = result.all()

    return [
        {
            'supplier_name': r.supplier_name,
            'supplier_id': r.supplier_id,
            'order_count': r.order_count,
            'total_amount': float(r.total_amount or 0),
        }
        for r in rows
    ]


async def _build_order_summary(db: AsyncSession, order) -> dict:
    """构建订单汇总信息"""
    total_items = 0
    total_quantity = 0
    categories: dict[str, int] = defaultdict(int)

    items_result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order.id)
    )
    for item in items_result.scalars().all():
        total_items += 1
        total_quantity += int(item.quantity or 0)
        cat = item.material_category or 'other'
        categories[cat] += 1

    return {
        'order_no': order.order_no,
        'total_items': total_items,
        'total_quantity': total_quantity,
        'categories': dict(categories),
        'total_amount': float(order.total_amount or 0),
    }


async def cleanup_orphan_pending_purchase_orders(
    db: AsyncSession, order_ids: list[int],
) -> None:
    """清理关联指定客户订单的 pending 采购订单（同时处理 source_order_id 和 source_order_ids）"""
    if not order_ids:
        return

    # 先查 source_order_ids (JSON 列) 可能关联的 — 用列查询避免加载完整 ORM 对象
    result2 = await db.execute(
        select(PurchaseOrder.id, PurchaseOrder.source_order_ids).where(
            PurchaseOrder.source_order_ids.isnot(None),
            PurchaseOrder.status == 'pending',
        )
    )
    json_match_ids: list[int] = []
    for row in result2.all():
        try:
            ids = json.loads(row.source_order_ids)
            if any(i in order_ids for i in ids):
                json_match_ids.append(row.id)
        except (ValueError, TypeError):
            logger.warning('PurchaseOrder %s has invalid source_order_ids: %s', row.id, row.source_order_ids)

    # 合并 source_order_id (int 列) 直接匹配的 + JSON 匹配的，统一 ORM 删除以触发 cascade
    all_ids = set(json_match_ids) | set(order_ids)  # order_ids 用于 source_order_id IN 查询
    if not all_ids:
        return
    result = await db.execute(
        select(PurchaseOrder).where(
            PurchaseOrder.status == 'pending',
            (PurchaseOrder.source_order_id.in_(order_ids)) | (PurchaseOrder.id.in_(json_match_ids)),
        )
    )
    for po in result.scalars().all():
        await db.delete(po)
