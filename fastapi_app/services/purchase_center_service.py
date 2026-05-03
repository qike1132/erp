"""
采购中心服务层 - 业务逻辑（重构为子模块重导出）

原始 1922 行 God File 已拆分为以下子模块：
- purchase_product_service: 产品/BOM API + 物料计算
- purchase_supplier_service: 供应商 CRUD + 信息同步
- purchase_history_service: 修改历史/保存查询/状态日志
- purchase_bom_copy_service: BOM 复制功能

采购订单、客户管理、供应商汇总等域保留在本文件中，
后续迭代逐步迁移。此文件保留所有原始导入路径的向后兼容。
"""

import html as html_module
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session, joinedload, selectinload

from fastapi_app.services import escape_like
from fastapi_app.services.purchase_bom_copy_service import (  # noqa: F401
    batch_delete_purchase_orders,
    copy_bom_to_product,
    get_bom_preview,
    search_products_for_bom_copy,
)
from fastapi_app.services.purchase_history_service import (  # noqa: F401
    delete_saved_query,
    get_modification_logs,
    get_saved_queries,
    get_status_logs,
    save_query,
    use_saved_query,
)

# 从子模块重导出已拆分的函数
from fastapi_app.services.purchase_product_service import (  # noqa: F401
    _product_has_bom,
    calculate_material,
    get_product_bom,
    get_products,
    get_products_batch_bom,
    get_products_statistics,
    get_search_suggestions,
    save_product_bom,
)
from fastapi_app.services.purchase_supplier_service import (  # noqa: F401
    create_supplier,
    delete_supplier,
    get_supplier_materials,
    get_suppliers,
    update_supplier,
)
from fastapi_app.shared_models import (
    Customer,
    MaterialRegistration,
    MaterialRegistrationItem,
    ModificationLog,
    Order,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
)

logger = logging.getLogger(__name__)


# ============================================================
# 客户管理 API (采购中心接入)
# ============================================================

def get_customers(db: Session, *, page: int = 1, per_page: int = 20,
                  status: str = 'all', keyword: str = '',
                  sort_by: str = 'name', sort_order: str = 'asc') -> dict:
    query = db.query(Customer)

    if status == 'active':
        query = query.filter(Customer.status)
    elif status == 'inactive':
        query = query.filter(not Customer.status)

    if keyword:
        query = query.filter(Customer.name.ilike(f'%{escape_like(keyword)}%'))

    sort_map = {
        'name': Customer.name,
        'create_time': Customer.create_time,
        'update_time': Customer.update_time,
    }
    sort_col = sort_map.get(sort_by, Customer.name)
    if sort_order == 'desc':
        sort_col = sort_col.desc()
    query = query.order_by(sort_col)

    total = query.count()
    customers = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        'customers': [
            {
                'id': c.id,
                'name': c.name,
                'status': c.status,
                'create_time': c.create_time.strftime('%Y-%m-%d %H:%M') if c.create_time else '',
                'update_time': c.update_time.strftime('%Y-%m-%d %H:%M') if c.update_time else '',
            }
            for c in customers
        ],
        'total': total,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
        'current_page': page,
    }


def get_customer_detail(db: Session, customer_id: int) -> dict:
    customer = db.get(Customer, customer_id)
    if not customer:
        return None
    return {'id': customer.id, 'name': customer.name, 'status': customer.status}


def batch_get_customers(db: Session, ids: list) -> list:
    if not ids:
        return []
    customers = db.query(Customer).filter(Customer.id.in_(ids)).all()
    return [{'id': c.id, 'name': c.name} for c in customers]


def get_customers_statistics(db: Session) -> dict:
    total = db.query(Customer).count()
    active = db.query(Customer).filter_by(status=True).count()
    recently_updated = db.query(Customer).filter(
        Customer.update_time >= datetime.now() - timedelta(days=30)
    ).count() if hasattr(Customer, 'update_time') else 0
    return {
        'total': total,
        'active': active,
        'inactive': total - active,
        'recently_updated': recently_updated,
    }


# ============================================================
# 采购订单 API
# ============================================================

def _generate_order_no(db: Session, prefix: str = 'PO') -> str:
    today_str = datetime.now().strftime('%Y%m%d')
    like_pattern = f'{prefix}-{today_str}-%'
    last_order = db.query(PurchaseOrder).filter(
        PurchaseOrder.order_no.like(like_pattern)
    ).order_by(PurchaseOrder.order_no.desc()).first()

    if last_order:
        seq = int(last_order.order_no.split('-')[-1]) + 1
    else:
        seq = 1

    return f'{prefix}-{today_str}-{seq:04d}'


def create_purchase_order(db: Session, data: dict, user_id: int, username: str) -> dict:
    items_data = data.get('items', [])
    if not items_data:
        raise ValueError('没有采购项')

    order_no = _generate_order_no(db)
    supplier_name = data.get('supplier_name', '')
    supplier_id = data.get('supplier_id')
    remark = data.get('remark', '')

    order_items = []

    for item_data in items_data:
        item = PurchaseOrderItem(
            product_name=item_data.get('product_name', ''),
            barcode=item_data.get('barcode', ''),
            customer_name=item_data.get('customer_name', ''),
            material_code=item_data.get('material_code', ''),
            material_name=item_data.get('material_name', ''),
            material_category=item_data.get('material_category', ''),
            specification=item_data.get('specification', ''),
            quantity=Decimal(str(item_data.get('quantity', 0))),
            unit=item_data.get('unit', ''),
            unit_usage=Decimal(str(item_data.get('unit_usage', 0))),
            unit_price=Decimal(str(item_data.get('unit_price', 0))),
            supplier_name=item_data.get('supplier_name', supplier_name),
            remark=item_data.get('remark', ''),
        )
        item.total_price = item.quantity * item.unit_price
        order_items.append(item)

    # 从 items_data 中提取关联信息
    source_order_id = None
    product_name = ''
    order_quantity = None
    customer_name = data.get('customer_name', '')
    for item_data in items_data:
        if item_data.get('source_order_id'):
            source_order_id = item_data['source_order_id']
        if item_data.get('product_name'):
            product_name = item_data['product_name']
        if not customer_name and item_data.get('customer_name'):
            customer_name = item_data['customer_name']
        if order_quantity is None and item_data.get('order_quantity') is not None:
            order_quantity = item_data['order_quantity']

    # product_quantity 使用原始订单的产品数量（而非物料数量总和）
    product_quantity = Decimal(str(order_quantity)) if order_quantity is not None else Decimal('0')

    order = PurchaseOrder(
        order_no=order_no,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        customer_name=customer_name,
        source_order_id=source_order_id,
        product_name=product_name,
        product_quantity=product_quantity,
        status='待处理',
        remark=remark,
        created_by=user_id,
    )
    db.add(order)
    db.flush()

    for item in order_items:
        item.order_id = order.id
        db.add(item)

    # 不在此处更新销售订单状态，由 one_click_generate_order 统一处理
    # 旧逻辑：每个供应商分组都设置 status='部分备货'，导致 one_click_generate_order
    # 中的最终状态检查 order.status == '待备货' 永远为 False，订单停在'部分备货'

    db.flush()
    return {'id': order.id, 'order_no': order_no}


def one_click_generate_order(db: Session, order_ids: list, user_id: int, username: str) -> dict:
    """一键审核：每个销售订单生成一个采购订单，包含该产品所有BOM物料"""
    if not order_ids:
        raise ValueError('请选择订单')

    orders = db.query(Order).filter(Order.id.in_(order_ids)).all()
    if not orders:
        raise ValueError('未找到订单')

    created_orders = []
    skipped_orders = []

    # 幂等检查：批量查询已有采购订单的 source_order_id，防止并发重复创建
    existing_po_order_ids = set(
        row[0] for row in
        db.query(PurchaseOrder.source_order_id)
        .filter(PurchaseOrder.source_order_id.in_(order_ids))
        .all()
    )

    for order in orders:
        # 跳过已有采购订单的销售订单（幂等保护）
        if order.id in existing_po_order_ids:
            skipped_orders.append({
                'order_id': order.id,
                'order_no': order.order_no,
                'reason': '该订单已生成采购订单，不可重复审核',
            })
            continue

        product = db.query(Product).options(
            selectinload(Product.material),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
            selectinload(Product.packagings),
        ).get(order.product_id)

        if not product or not product.has_bom():
            skipped_orders.append({
                'order_id': order.id,
                'order_no': order.order_no,
                'product_name': product.name if product else '未知产品',
                'reason': '该产品未配置BOM表，无法审核',
            })
            continue

        all_materials = product.get_all_materials()
        items = []
        # 取第一个有供应商名称的物料作为采购订单的 supplier_name
        first_supplier_name = ''
        for mat in all_materials:
            supplier = mat.get('supplier_name', '') or '未指定供应商'
            if not first_supplier_name and supplier and supplier != '未指定供应商':
                first_supplier_name = supplier
            items.append({
                'product_id': product.id,
                'product_name': product.name,
                'barcode': product.barcode or '',
                'customer_name': order.customer,
                'material_name': mat.get('material_name', ''),
                'material_category': mat.get('category', ''),
                'specification': mat.get('specification', ''),
                'unit_usage': float(mat.get('quantity', 0) or mat.get('unit_usage', 0)),
                'quantity': float(mat.get('quantity', 0) or mat.get('unit_usage', 0)) * order.quantity,
                'unit': mat.get('unit', ''),
                'supplier_name': supplier,
                'source_order_id': order.id,
                'order_quantity': order.quantity,
            })

        result = create_purchase_order(db, {
            'supplier_name': first_supplier_name,
            'items': items,
        }, user_id, username)
        created_orders.append(result)

        # 同步客户订单状态：审核通过 → 待出货
        if order.status is None:
            order.status = '待出货'
            db.add(order)

    # 如果所有订单都被跳过，抛出明确错误（必须在commit前，确保rollback有效）
    if not created_orders and skipped_orders:
        reasons = '；'.join(f"{s['order_no']}: {s['reason']}" for s in skipped_orders)
        raise ValueError(reasons)

    db.commit()

    return {
        'created_count': len(created_orders),
        'orders': created_orders,
    }


def get_purchase_orders(db: Session, *, page: int = 1, per_page: int = 50,
                        status: str = '', customer: str = '', product_name: str = '',
                        start_date: str = '', end_date: str = '', order_no: str = '',
                        supplier: str = '') -> dict:
    query = db.query(PurchaseOrder).options(
        selectinload(PurchaseOrder.items)
    )

    if status:
        query = query.filter(PurchaseOrder.status == status)
    else:
        query = query.filter(PurchaseOrder.status != '已完成')

    if customer:
        query = query.filter(PurchaseOrder.customer_name.ilike(f'%{escape_like(customer)}%'))
    if product_name:
        product_subq = db.query(PurchaseOrderItem.order_id).filter(
            PurchaseOrderItem.product_name.ilike(f'%{escape_like(product_name)}%')
        ).distinct().subquery()
        query = query.filter(PurchaseOrder.id.in_(product_subq))
    if supplier:
        query = query.filter(PurchaseOrder.supplier_name.ilike(f'%{escape_like(supplier)}%'))
    if order_no:
        query = query.filter(PurchaseOrder.order_no.ilike(f'%{escape_like(order_no)}%'))
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(PurchaseOrder.create_time >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(PurchaseOrder.create_time < ed)
        except ValueError:
            pass

    query = query.order_by(PurchaseOrder.create_time.desc())
    total = query.count()
    orders = query.offset((page - 1) * per_page).limit(per_page).all()

    source_ids = [o.source_order_id for o in orders if o.source_order_id]
    source_order_map: dict[int, Order] = {}
    if source_ids:
        source_orders = db.query(Order).filter(Order.id.in_(source_ids)).all()
        source_order_map = {so.id: so for so in source_orders}

    return {
        'orders': [
            {
                'id': o.id,
                'order_no': o.order_no,
                'source_order_no': source_order_map[o.source_order_id].order_no if o.source_order_id and o.source_order_id in source_order_map else '',
                'supplier_name': o.supplier_name,
                'customer_name': o.customer_name or (source_order_map[o.source_order_id].customer if o.source_order_id and o.source_order_id in source_order_map else '') or (o.items[0].customer_name if o.items else '') or '',
                'product_name': o.product_name or (o.items[0].product_name if o.items else '') or '',
                'quantity': float(o.product_quantity) if o.product_quantity is not None else None,
                'order_date': o.order_date.strftime('%Y-%m-%d') if o.order_date else '',
                'status': o.status,
                'total_amount': sum(float(item.total_price) if item.total_price else 0 for item in o.items),
                'item_count': len(o.items),
                'create_time': o.create_time.strftime('%Y-%m-%d %H:%M') if o.create_time else '',
                'remark': o.remark or '',
            }
            for o in orders
        ],
        'total': total,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
        'current_page': page,
    }


def get_purchase_order(db: Session, order_id: int) -> dict:
    order = db.query(PurchaseOrder).options(
        selectinload(PurchaseOrder.items)
    ).get(order_id)
    if not order:
        return None
    return {
        'id': order.id,
        'order_no': order.order_no,
        'supplier_name': order.supplier_name,
        'supplier_contact_person': getattr(order, 'supplier_contact_person', ''),
        'supplier_phone': getattr(order, 'supplier_phone', ''),
        'supplier_address': getattr(order, 'supplier_address', ''),
        'customer_name': order.customer_name,
        'product_name': order.product_name,
        'quantity': float(order.product_quantity) if order.product_quantity else None,
        'order_date': order.order_date.strftime('%Y-%m-%d') if order.order_date else '',
        'status': order.status,
        'total_amount': sum(float(item.total_price) if item.total_price else 0 for item in order.items),
        'remark': order.remark or '',
        'create_time': order.create_time.strftime('%Y-%m-%d %H:%M') if order.create_time else '',
        'items': [
            {
                'id': item.id,
                'product_name': item.product_name,
                'barcode': item.barcode,
                'material_name': item.material_name,
                'quantity': float(item.quantity) if item.quantity else 0,
                'unit': item.unit,
                'unit_price': float(item.unit_price) if item.unit_price else 0,
                'total_price': float(item.total_price) if item.total_price else 0,
                'supplier_name': item.supplier_name,
                'customer_name': item.customer_name,
                'remark': item.remark or '',
            }
            for item in order.items
        ],
    }


def update_purchase_order(db: Session, order_id: int, data: dict, username: str) -> dict:
    order = db.get(PurchaseOrder, order_id)
    if not order:
        raise ValueError('采购订单不存在')

    if 'status' in data:
        old_status = order.status
        order.status = data['status']
        db.add(ModificationLog(
            target_type='purchase_order', target_id=order_id,
            field_name='status', old_value=old_status, new_value=data['status'],
            modifier_name=username,
        ))

    if 'remark' in data:
        order.remark = data['remark']

    if 'supplier_name' in data:
        order.supplier_name = data['supplier_name']

    if 'customer_name' in data:
        order.customer_name = data['customer_name']

    db.commit()
    return {'id': order_id, 'order_no': order.order_no}


def delete_purchase_order(db: Session, order_id: int) -> dict:
    order = db.get(PurchaseOrder, order_id)
    if not order:
        raise ValueError('采购订单不存在')

    # 删除采购订单后，关联的销售订单会自动回到"审核订单"列表
    # （因为不再有 PurchaseOrder.source_order_id 指向它）

    db.delete(order)
    db.commit()
    return {'id': order_id}


def _sync_order_to_material_registration(db: Session, order, user_id: int):
    """将已完成的采购订单同步到来料登记系统"""
    items = db.query(PurchaseOrderItem).filter_by(order_id=order.id).all()
    if not items:
        return

    registration = MaterialRegistration(
        purchase_order_id=order.id,
        purchase_order_no=order.order_no,
        supplier_id=order.supplier_id,
        supplier_name=order.supplier_name,
        status='pending',
        created_by=user_id,
    )
    db.add(registration)
    db.flush()

    for item in items:
        reg_item = MaterialRegistrationItem(
            registration_id=registration.id,
            material_name=item.material_name or item.product_name,
            ordered_quantity=float(item.quantity) if item.quantity else 0,
            received_quantity=0,
            unit=item.unit or '',
        )
        db.add(reg_item)

    db.flush()


def complete_purchase_order(db: Session, order_id: int, user_id: int, username: str) -> dict:
    order = db.get(PurchaseOrder, order_id)
    if not order:
        raise ValueError('采购订单不存在')
    if order.status == '已完成':
        raise ValueError('订单已完成')

    old_status = order.status
    order.status = '已完成'
    order.completed_at = datetime.now()
    order.completed_by = username
    db.add(ModificationLog(
        target_type='purchase_order', target_id=order_id,
        field_name='status', old_value=old_status or '', new_value='已完成',
        modifier_name=username,
    ))

    _sync_order_to_material_registration(db, order, user_id)

    # 同步客户订单状态：采购完成下单 → 已出货
    synced_orders = []
    if order.source_order_id:
        source_order = db.get(Order, order.source_order_id)
        if source_order and source_order.status == '待出货':
            source_order.status = '已出货'
            db.add(source_order)
            synced_orders.append(source_order)
    if order.source_order_ids:
        try:
            for sid in json.loads(order.source_order_ids):
                if sid:
                    so = db.get(Order, sid)
                    if so and so.status == '待出货':
                        so.status = '已出货'
                        db.add(so)
                        synced_orders.append(so)
        except (json.JSONDecodeError, TypeError):
            pass

    db.commit()
    return {'id': order_id, 'status': '已完成'}


def batch_complete_purchase_orders(db: Session, ids: list, user_id: int, username: str) -> dict:
    if not ids:
        raise ValueError('请选择订单')

    completed = []
    errors = []
    for oid in ids:
        try:
            result = complete_purchase_order(db, oid, user_id, username)
            completed.append(result)
        except (ValueError, TypeError, RuntimeError) as e:
            errors.append({'id': oid, 'error': str(e)})

    return {'completed_count': len(completed), 'errors': errors}


def get_completed_purchase_orders(db: Session, *, page: int = 1, per_page: int = 50,
                                  order_no: str = '', customer_name: str = '',
                                  product_name: str = '', supplier_name: str = '',
                                  barcode: str = '', material_name: str = '',
                                  start_date: str = '', end_date: str = '') -> dict:
    query = db.query(PurchaseOrder).options(
        selectinload(PurchaseOrder.items)
    ).filter(PurchaseOrder.status == '已完成')

    if order_no:
        query = query.filter(PurchaseOrder.order_no.ilike(f'%{escape_like(order_no)}%'))
    if customer_name:
        query = query.filter(PurchaseOrder.customer_name.ilike(f'%{escape_like(customer_name)}%'))
    if supplier_name:
        query = query.filter(PurchaseOrder.supplier_name.ilike(f'%{escape_like(supplier_name)}%'))
    if barcode:
        query = query.filter(PurchaseOrder.items.any(PurchaseOrderItem.barcode.ilike(f'%{escape_like(barcode)}%')))
    if product_name:
        query = query.filter(PurchaseOrder.items.any(PurchaseOrderItem.product_name.ilike(f'%{escape_like(product_name)}%')))
    if material_name:
        query = query.filter(PurchaseOrder.items.any(PurchaseOrderItem.material_name.ilike(f'%{escape_like(material_name)}%')))
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(PurchaseOrder.create_time >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(PurchaseOrder.create_time < ed)
        except ValueError:
            pass

    query = query.order_by(PurchaseOrder.create_time.desc())
    total = query.count()
    orders = query.offset((page - 1) * per_page).limit(per_page).all()

    # 批量查询源订单用于回退 customer_name
    source_ids = [o.source_order_id for o in orders if o.source_order_id]
    source_order_map = {}
    if source_ids:
        for so in db.query(Order).filter(Order.id.in_(source_ids)).all():
            source_order_map[so.id] = so

    return {
        'orders': [
            {
                'id': o.id,
                'order_no': o.order_no,
                'source_order_no': source_order_map[o.source_order_id].order_no if o.source_order_id and o.source_order_id in source_order_map else '',
                'supplier_name': o.supplier_name,
                'customer_name': o.customer_name or (source_order_map[o.source_order_id].customer if o.source_order_id and o.source_order_id in source_order_map else '') or (o.items[0].customer_name if o.items else '') or '',
                'product_name': o.product_name or (o.items[0].product_name if o.items else '') or '',
                'quantity': float(o.product_quantity) if o.product_quantity is not None else sum(float(item.quantity) if item.quantity else 0 for item in o.items),
                'total_amount': sum(float(item.total_price) if item.total_price else 0 for item in o.items),
                'order_date': o.create_time.strftime('%Y-%m-%d') if o.create_time else '',
                'create_time': o.create_time.strftime('%Y-%m-%d %H:%M') if o.create_time else '',
                'completed_at': o.completed_at.strftime('%Y-%m-%d %H:%M') if o.completed_at else '',
                'items': [
                    {
                        'id': item.id,
                        'product_name': item.product_name,
                        'material_name': item.material_name,
                        'barcode': item.barcode,
                        'quantity': float(item.quantity) if item.quantity else 0,
                        'unit': item.unit,
                        'supplier_name': item.supplier_name,
                    }
                    for item in o.items
                ],
            }
            for o in orders
        ],
        'total': total,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
        'current_page': page,
    }


def export_completed_orders(db: Session, data: dict) -> str:
    orders_data = get_completed_purchase_orders(db, page=1, per_page=10000, **data)
    if not orders_data['orders']:
        return '<p>没有数据</p>'

    html = '<table border="1" cellpadding="5"><tr><th>订单号</th><th>供应商</th><th>客户</th><th>产品</th><th>物料</th><th>数量</th><th>单位</th></tr>'
    for order in orders_data['orders']:
        for item in order.get('items', []):
            html += f'<tr><td>{html_module.escape(order["order_no"] or "")}</td><td>{html_module.escape(order["supplier_name"] or "")}</td><td>{html_module.escape(order["customer_name"] or "")}</td><td>{html_module.escape(item["product_name"] or "")}</td><td>{html_module.escape(item["material_name"] or "")}</td><td>{item["quantity"]}</td><td>{html_module.escape(item["unit"] or "")}</td></tr>'
    html += '</table>'
    return html


# ============================================================
# 未处理订单 API
# ============================================================

def get_unprocessed_orders(db: Session, *, customer: str = '', page: int = 1, per_page: int = 50) -> dict:
    """获取未审核订单（未生成采购订单的销售订单）"""
    # 使用 NOT EXISTS 替代 NOT IN，性能更优（可利用索引提前终止扫描）
    from sqlalchemy import exists as sa_exists
    from sqlalchemy import select
    po_exists = sa_exists(
        select(PurchaseOrder.id).where(PurchaseOrder.source_order_id == Order.id)
    )

    query = db.query(Order).options(
        joinedload(Order.product),
    ).filter(
        Order.is_deleted == False,  # noqa: E712
        ~po_exists,  # 没有关联的采购订单
    )

    if customer:
        query = query.filter(Order.customer.ilike(f'%{escape_like(customer)}%'))

    query = query.order_by(Order.order_date.desc())
    total = query.count()
    orders = query.offset((page - 1) * per_page).limit(per_page).all()

    # 收集所有 product_id，批量查询 has_bom 标记（避免依赖 ORM 关系加载状态）
    product_ids = list({o.product_id for o in orders if o.product_id})
    bom_product_ids = set()
    if product_ids:
        from fastapi_app.services.purchase_product_service import _batch_check_bom_exists
        bom_product_ids = _batch_check_bom_exists(db, product_ids)

    result = []
    for order in orders:
        product = order.product
        has_bom = order.product_id in bom_product_ids

        result.append({
            'id': order.id,
            'order_no': order.order_no,
            'customer': order.customer,
            'product_name': product.name if product else '',
            'quantity': order.quantity,
            'order_date': order.order_date.strftime('%Y-%m-%d') if order.order_date else '',
            'create_time': order.order_date.strftime('%Y-%m-%d %H:%M') if order.order_date else '',
            'has_bom': has_bom,
        })

    return {
        'orders': result,
        'total': total,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
        'current_page': page,
    }


# ============================================================
# 供应商汇总 (供 endpoint 层调用)
# ============================================================

def query_supplier_groups(db: Session, order_ids: list) -> list:
    """按供应商维度查询并分组采购订单物料，相同物料自动合并数量"""
    if not order_ids:
        return []

    orders = db.query(PurchaseOrder).filter(PurchaseOrder.id.in_(order_ids)).all()
    items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.order_id.in_(order_ids)).all()
    order_map = {o.id: o for o in orders}

    supplier_groups = {}
    supplier_redundant_info = {}

    for item in items:
        order = order_map.get(item.order_id)
        if not order:
            continue

        supplier_name = item.supplier_name or order.supplier_name or '未指定供应商'
        if supplier_name not in supplier_groups:
            supplier_groups[supplier_name] = {
                'supplier_name': supplier_name,
                'items': [],
                'orders': set(),
            }
            supplier_redundant_info[supplier_name] = {
                'contact_person': order.supplier_contact_person,
                'phone': order.supplier_phone,
                'address': order.supplier_address,
            }

        # 相同物料合并
        item_key = (item.material_name, item.specification or '', item.unit or '')
        found = False
        for existing_item in supplier_groups[supplier_name]['items']:
            if (existing_item['material_name'], existing_item['specification'], existing_item['unit']) == item_key:
                existing_item['quantity'] += Decimal(str(item.quantity)) if item.quantity else Decimal('0')
                existing_item['order_count'] += 1
                found = True
                break

        if not found:
            supplier_groups[supplier_name]['items'].append({
                'material_name': item.material_name,
                'specification': item.specification or '',
                'unit': item.unit or '',
                'quantity': Decimal(str(item.quantity)) if item.quantity else Decimal('0'),
                'material_category': item.material_category or '',
                'order_count': 1,
            })

        supplier_groups[supplier_name]['orders'].add(order.order_no)

    # 从 Supplier 表获取完整供应商信息，冗余字段作为回退
    supplier_names = [name for name in supplier_groups if name != '未指定供应商']
    supplier_record_map = {}
    if supplier_names:
        supplier_records = db.query(Supplier).filter(Supplier.name.in_(supplier_names)).all()
        supplier_record_map = {s.name: s for s in supplier_records}

    result = []
    for supplier_name, group in supplier_groups.items():
        record = supplier_record_map.get(supplier_name)
        redundant = supplier_redundant_info.get(supplier_name, {})
        if record:
            contact = record.contact_person or ''
            phone = record.phone or ''
            address = record.address or ''
        else:
            contact = redundant.get('contact_person') or ''
            phone = redundant.get('phone') or ''
            address = redundant.get('address') or ''

        items_list = []
        for it in group['items']:
            it['quantity'] = float(it['quantity'])
            items_list.append(it)

        result.append({
            'supplier_name': supplier_name,
            'supplier_id': record.id if record else None,
            'contact_person': contact,
            'phone': phone,
            'address': address,
            'items': items_list,
            'orders': sorted(group['orders']),
            'order_count': len(group['orders']),
        })

    return sorted(result, key=lambda x: x['supplier_name'])


def get_factory_order_summary(db: Session, order_ids: list) -> dict:
    """获取工厂内部采购订单汇总

    逻辑：按(客户, 产品) → 供应商 → 物料 三级分组，
    同一供应商下的相同物料自动合并数量。
    自动关联同源订单（共享同一 source_order_id 的采购订单一并纳入）。
    """
    if not order_ids:
        return {'groups': [], 'order_count': 0}

    orders = db.query(PurchaseOrder).filter(PurchaseOrder.id.in_(order_ids)).all()

    # 自动关联同源订单：选中订单的 source_order_id 对应的其他采购订单也纳入汇总
    source_order_ids = list({o.source_order_id for o in orders if o.source_order_id})
    if source_order_ids:
        related_orders = db.query(PurchaseOrder).filter(
            PurchaseOrder.source_order_id.in_(source_order_ids)
        ).all()
        related_order_ids = {o.id for o in related_orders}
        all_order_ids = list(set(order_ids) | related_order_ids)
    else:
        all_order_ids = list(order_ids)

    if len(all_order_ids) != len(order_ids):
        orders = db.query(PurchaseOrder).filter(PurchaseOrder.id.in_(all_order_ids)).all()

    items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.order_id.in_(all_order_ids)).all()
    order_map = {o.id: o for o in orders}

    # 加载原始销售订单，用于获取准确的 customer / product 信息
    source_ids = [o.source_order_id for o in orders if o.source_order_id]
    source_orders = db.query(Order).filter(Order.id.in_(source_ids)).all() if source_ids else []
    source_order_map = {o.id: o for o in source_orders}

    grouped_data = {}
    order_count_map = {}

    for item in items:
        order = order_map.get(item.order_id)
        if not order:
            continue

        # 从原始销售订单解析 customer / product，比 PurchaseOrderItem 上的冗余字段更准确
        source_order = source_order_map.get(order.source_order_id) if order.source_order_id else None
        product_name = order.product_name
        if not product_name and source_order and source_order.product:
            product_name = source_order.product.name
        elif not product_name:
            product_name = order.customer_name or '未指定产品'

        product_qty = order.product_quantity
        if not product_qty and source_order:
            product_qty = source_order.quantity

        customer_name = source_order.customer if source_order else (order.customer_name or '未指定客户')
        supplier_name = item.supplier_name or order.supplier_name or '未指定供应商'
        fabric_name = item.material_name or '未指定布料'
        fabric_spec = item.specification or ''
        fabric_qty = item.quantity or 0

        customer_product_key = (customer_name, product_name)
        supplier_key = supplier_name

        if customer_product_key not in grouped_data:
            grouped_data[customer_product_key] = {}
            order_count_map[customer_product_key] = {'order_count': 0, 'total_fabric_qty': 0, 'product_quantity': product_qty}

        if supplier_key not in grouped_data[customer_product_key]:
            grouped_data[customer_product_key][supplier_key] = {}

        # 同一供应商下相同物料合并数量
        fabric_key = (fabric_name, fabric_spec, item.unit or '')
        if fabric_key not in grouped_data[customer_product_key][supplier_key]:
            grouped_data[customer_product_key][supplier_key][fabric_key] = {
                'item_id': item.id,
                'item_ids': [item.id],
                'fabric_name': fabric_name,
                'specification': fabric_spec,
                'quantity': float(fabric_qty) if fabric_qty else 0,
                'unit': item.unit or '',
                'original_quantities': {str(item.id): float(fabric_qty) if fabric_qty else 0},
            }
        else:
            existing = grouped_data[customer_product_key][supplier_key][fabric_key]
            existing['item_ids'].append(item.id)
            existing['quantity'] = (float(existing['quantity']) if existing['quantity'] else 0) + (float(fabric_qty) if fabric_qty else 0)
            existing['original_quantities'][str(item.id)] = float(fabric_qty) if fabric_qty else 0

        order_count_map[customer_product_key]['total_fabric_qty'] += float(fabric_qty) if fabric_qty else 0

    # 统计每个 (客户, 产品) 分组下的订单数量
    for order in orders:
        source_order = source_order_map.get(order.source_order_id) if order.source_order_id else None
        product_name = order.product_name
        if not product_name and source_order and source_order.product:
            product_name = source_order.product.name
        elif not product_name:
            product_name = order.customer_name or '未指定产品'
        customer_name = source_order.customer if source_order else (order.customer_name or '未指定客户')
        cp_key = (customer_name, product_name)
        if cp_key in order_count_map:
            order_count_map[cp_key]['order_count'] += 1

    # 组装最终结构
    result_list = []
    for (customer_name, product_name), supplier_dict in grouped_data.items():
        order_info = order_count_map[(customer_name, product_name)]
        suppliers_list = []
        for supplier_name, fabric_dict in supplier_dict.items():
            fabrics_list = list(fabric_dict.values())
            for f in fabrics_list:
                f['quantity'] = round(f['quantity'], 2)
            suppliers_list.append({
                'supplier_name': supplier_name,
                'fabrics': fabrics_list,
            })
        result_list.append({
            'customer_name': customer_name,
            'product_name': product_name,
            'order_quantity': order_info['order_count'],
            'product_quantity': order_info['product_quantity'],
            'suppliers': suppliers_list,
            'total_fabric_qty': order_info['total_fabric_qty'],
        })

    return {
        'groups': result_list,
        'order_count': len(orders),
    }


def save_factory_summary_edits(db: Session, edits: list) -> dict:
    for edit in edits:
        item_ids = edit.get('item_ids') or ([edit.get('item_id')] if edit.get('item_id') else [])
        if not item_ids:
            continue
        new_quantity = edit.get('quantity')
        if new_quantity is None:
            continue
        # 如果合并了多个 item，按原始数量比例分配新总量
        items = [db.get(PurchaseOrderItem, iid) for iid in item_ids]
        items = [i for i in items if i is not None]
        if not items:
            continue
        if len(items) == 1:
            items[0].quantity = Decimal(str(new_quantity))
        else:
            original_total = sum(float(i.quantity or 0) for i in items)
            if original_total > 0:
                remaining = float(new_quantity)
                for idx, item in enumerate(items):
                    if idx < len(items) - 1:
                        ratio = float(item.quantity or 0) / original_total
                        share = round(remaining * ratio, 2)
                        item.quantity = Decimal(str(share))
                        remaining -= share
                    else:
                        # 最后一个 item 获得余量，避免浮点累积误差
                        item.quantity = Decimal(str(round(remaining, 2)))
            else:
                # 原始总量为 0 时平均分配
                per_item = round(float(new_quantity) / len(items), 2)
                remaining = float(new_quantity)
                for idx, item in enumerate(items):
                    if idx < len(items) - 1:
                        item.quantity = Decimal(str(per_item))
                        remaining -= per_item
                    else:
                        item.quantity = Decimal(str(round(remaining, 2)))
    db.commit()
    return {'saved': True}


def get_supplier_order_summary(db: Session, order_ids: list) -> dict:
    """获取供应商采购订单汇总 - 按物料维度汇总

    逻辑：按 (material_name, spec, unit, supplier) 分组汇总数量，
    每个物料记录其来源订单明细。
    自动关联同源订单。
    """
    if not order_ids:
        return {'materials': [], 'order_count': 0}

    orders = db.query(PurchaseOrder).filter(PurchaseOrder.id.in_(order_ids)).all()

    # 自动关联同源订单
    source_order_ids = list({o.source_order_id for o in orders if o.source_order_id})
    if source_order_ids:
        related_orders = db.query(PurchaseOrder).filter(
            PurchaseOrder.source_order_id.in_(source_order_ids)
        ).all()
        related_order_ids = {o.id for o in related_orders}
        all_order_ids = list(set(order_ids) | related_order_ids)
    else:
        all_order_ids = list(order_ids)

    if len(all_order_ids) != len(order_ids):
        orders = db.query(PurchaseOrder).filter(PurchaseOrder.id.in_(all_order_ids)).all()

    items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.order_id.in_(all_order_ids)).all()
    order_map = {o.id: o for o in orders}

    material_summary = {}
    for item in items:
        order = order_map.get(item.order_id)
        sname = item.supplier_name or (order.supplier_name if order else '') or '未指定'
        spec = item.specification or ''
        unit = item.unit or ''
        key = (item.material_name, spec, unit, sname)
        if key not in material_summary:
            material_summary[key] = {
                'material_name': item.material_name,
                'specification': spec,
                'unit': unit,
                'supplier_name': sname,
                'category': item.material_category or '',
                'total_quantity': Decimal('0'),
                'orders': [],
            }
        material_summary[key]['total_quantity'] += Decimal(str(item.quantity)) if item.quantity else Decimal('0')
        material_summary[key]['orders'].append({
            'order_no': order.order_no if order else '',
            'product_name': item.product_name or (order.product_name if order else ''),
            'quantity': float(item.quantity) if item.quantity else 0,
        })

    materials = list(material_summary.values())
    for m in materials:
        qty = float(m.pop('total_quantity'))
        m['total_quantity'] = round(qty, 2) if qty != int(qty) else int(qty)

    return {'materials': materials, 'order_count': len(orders)}


def get_completed_order_suggestions(db: Session, field: str, keyword: str, limit: int = 10) -> list:
    if not keyword or not field:
        return []

    field_map = {
        'order_no': PurchaseOrder.order_no,
        'customer_name': PurchaseOrder.customer_name,
        'product_name': PurchaseOrderItem.product_name,
        'supplier_name': PurchaseOrder.supplier_name,
        'material_name': PurchaseOrderItem.material_name,
    }

    col = field_map.get(field)
    if not col:
        return []

    if field in ('product_name', 'material_name'):
        query = db.query(col).filter(
            PurchaseOrderItem.order_id == PurchaseOrder.id,
            PurchaseOrder.status == '已完成',
            col.ilike(f'%{escape_like(keyword)}%'),
        ).distinct().limit(limit)
    else:
        query = db.query(col).filter(
            PurchaseOrder.status == '已完成',
            col.ilike(f'%{escape_like(keyword)}%'),
        ).distinct().limit(limit)

    return [row[0] for row in query.all()]


def get_completed_order_quick_filters() -> list:
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    month_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    return [
        {'id': 'today', 'name': '今天', 'filters': {'start_date': today, 'end_date': today}},
        {'id': 'yesterday', 'name': '昨天', 'filters': {'start_date': yesterday, 'end_date': yesterday}},
        {'id': 'week', 'name': '近7天', 'filters': {'start_date': week_ago, 'end_date': today}},
        {'id': 'month', 'name': '近30天', 'filters': {'start_date': month_ago, 'end_date': today}},
    ]
