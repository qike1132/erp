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

import json
import logging
import html as html_module
import re
from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_, and_, func, text
from sqlalchemy.orm import Session, joinedload, selectinload

from fastapi_app.shared_models import (
    Product, Order, Customer,
    PurchaseOrder, PurchaseOrderItem,
    ProductMaterial, ProductFabric, ProductAccessory, ProductPackaging,
    Supplier, ModificationLog, SavedQuery, OrderStatusLog,
    MaterialRegistration, MaterialRegistrationItem,
    MATERIAL_CATEGORIES,
)
from fastapi_app.services import escape_like

# 从子模块重导出已拆分的函数
from fastapi_app.services.purchase_product_service import (  # noqa: F401
    _product_has_bom,
    get_products,
    get_products_batch_bom,
    get_search_suggestions,
    get_products_statistics,
    get_product_bom,
    save_product_bom,
    calculate_material,
)
from fastapi_app.services.purchase_supplier_service import (  # noqa: F401
    get_suppliers,
    create_supplier,
    update_supplier,
    delete_supplier,
    get_supplier_materials,
)
from fastapi_app.services.purchase_history_service import (  # noqa: F401
    get_modification_logs,
    get_saved_queries,
    save_query,
    delete_saved_query,
    use_saved_query,
    get_status_logs,
)
from fastapi_app.services.purchase_bom_copy_service import (  # noqa: F401
    search_products_for_bom_copy,
    get_bom_preview,
    copy_bom_to_product,
    batch_delete_purchase_orders,
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
        query = query.filter(Customer.status == True)
    elif status == 'inactive':
        query = query.filter(Customer.status == False)

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

def _generate_order_no(db: Session, prefix: str = 'CG') -> str:
    today_str = datetime.now().strftime('%Y%m%d')
    like_pattern = f'{prefix}{today_str}%'
    last_order = db.query(PurchaseOrder).filter(
        PurchaseOrder.order_no.like(like_pattern)
    ).order_by(PurchaseOrder.order_no.desc()).first()

    if last_order:
        seq = int(last_order.order_no[-4:]) + 1
    else:
        seq = 1

    return f'{prefix}{today_str}{seq:04d}'


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
    product_quantity = Decimal('0')
    customer_name = data.get('customer_name', '')
    for item_data in items_data:
        if item_data.get('source_order_id'):
            source_order_id = item_data['source_order_id']
        if item_data.get('product_name'):
            product_name = item_data['product_name']
        product_quantity += Decimal(str(item_data.get('quantity', 0)))

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

    # 更新关联的销售订单状态
    source_order_ids = set()
    for item_data in items_data:
        oid = item_data.get('source_order_id')
        if oid:
            source_order_ids.add(oid)

    for oid in source_order_ids:
        source_order = db.get(Order, oid)
        if source_order and source_order.status == '待备货':
            source_order.status = '部分备货'

    db.commit()
    return {'id': order.id, 'order_no': order_no}


def one_click_generate_order(db: Session, order_ids: list, user_id: int, username: str) -> dict:
    if not order_ids:
        raise ValueError('请选择订单')

    orders = db.query(Order).filter(Order.id.in_(order_ids)).all()
    if not orders:
        raise ValueError('未找到订单')

    supplier_items = {}
    processed_order_ids = set()

    for order in orders:
        product = db.query(Product).options(
            selectinload(Product.material),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
            selectinload(Product.packagings),
        ).get(order.product_id)

        if not product or not product.has_bom():
            continue

        processed_order_ids.add(order.id)

        all_materials = product.get_all_materials()
        for mat in all_materials:
            sname = mat.get('supplier_name', '') or '未指定供应商'
            if sname not in supplier_items:
                supplier_items[sname] = []
            supplier_items[sname].append({
                'product_id': product.id,
                'product_name': product.name,
                'barcode': product.barcode or '',
                'customer_name': order.customer,
                'material_name': mat.get('name', ''),
                'material_category': mat.get('category', ''),
                'quantity': float(mat.get('quantity_per_unit', 0)) * order.quantity,
                'unit': mat.get('unit', ''),
                'supplier_name': sname,
                'source_order_id': order.id,
            })

    created_orders = []
    for supplier_name, items in supplier_items.items():
        result = create_purchase_order(db, {
            'supplier_name': supplier_name,
            'items': items,
        }, user_id, username)
        created_orders.append(result)

    # 更新原始订单状态（仅更新成功生成采购项的订单）
    for order in orders:
        if order.id in processed_order_ids and order.status == '待备货':
            order.status = '已备货'
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
        query = query.filter(PurchaseOrder.items.any(PurchaseOrderItem.product_name.ilike(f'%{escape_like(product_name)}%')))
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

    return {
        'orders': [
            {
                'id': o.id,
                'order_no': o.order_no,
                'supplier_name': o.supplier_name,
                'customer_name': o.customer_name,
                'product_name': o.product_name,
                'quantity': float(o.product_quantity) if o.product_quantity else None,
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

    # 回滚关联订单状态（通过 source_order_id 和 source_order_ids）
    source_order_ids = set()
    if order.source_order_id:
        source_order_ids.add(order.source_order_id)
    if order.source_order_ids:
        try:
            for oid in json.loads(order.source_order_ids):
                if isinstance(oid, int):
                    source_order_ids.add(oid)
        except (json.JSONDecodeError, TypeError):
            pass

    for oid in source_order_ids:
        source_order = db.get(Order, oid)
        if source_order:
            source_order.status = '待备货'

    db.delete(order)
    db.commit()
    return {'id': order_id}


def _sync_order_to_material_registration(db: Session, order, user_id: int):
    """将已完成的采购订单同步到来料登记系统"""
    items = db.query(PurchaseOrderItem).filter_by(order_id=order.id).all()
    if not items:
        return

    registration = MaterialRegistration(
        registration_no=f'MR{datetime.now().strftime("%Y%m%d")}{order.id:04d}',
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

    order.status = '已完成'
    db.add(ModificationLog(
        target_type='purchase_order', target_id=order_id,
        field_name='status', old_value='处理中', new_value='已完成',
        modifier_name=username,
    ))

    _sync_order_to_material_registration(db, order, user_id)
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
        except Exception as e:
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
    if barcode or product_name or material_name:
        query = query.filter(PurchaseOrder.items.any())
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

    return {
        'orders': [
            {
                'id': o.id,
                'order_no': o.order_no,
                'supplier_name': o.supplier_name,
                'customer_name': o.customer_name,
                'total_amount': sum(float(item.total_price) if item.total_price else 0 for item in o.items),
                'create_time': o.create_time.strftime('%Y-%m-%d %H:%M') if o.create_time else '',
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
    query = db.query(Order).options(
        joinedload(Order.product),
    ).filter(Order.status == '待备货')

    if customer:
        query = query.filter(Order.customer.ilike(f'%{escape_like(customer)}%'))

    query = query.order_by(Order.order_date.desc())
    total = query.count()
    orders = query.offset((page - 1) * per_page).limit(per_page).all()

    result = []
    for order in orders:
        product = order.product
        has_bom = product.has_bom() if product else False
        if not has_bom:
            continue

        result.append({
            'id': order.id,
            'order_no': order.order_no,
            'customer': order.customer,
            'product_name': product.name if product else '',
            'quantity': order.quantity,
            'order_date': order.order_date.strftime('%Y-%m-%d') if order.order_date else '',
            'has_bom': has_bom,
        })

    return {
        'orders': result,
        'total': len(result),
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
        'current_page': page,
    }


# ============================================================
# 供应商汇总 (供 endpoint 层调用)
# ============================================================

def query_supplier_groups(db: Session, order_ids: list) -> list:
    if not order_ids:
        return []

    items = db.query(PurchaseOrderItem).filter(
        PurchaseOrderItem.order_id.in_(order_ids)
    ).all()

    groups = {}
    for item in items:
        sname = item.supplier_name or '未指定'
        if sname not in groups:
            supplier = db.query(Supplier).filter_by(name=sname).first()
            groups[sname] = {
                'supplier_name': sname,
                'supplier_id': supplier.id if supplier else None,
                'contact_person': supplier.contact_person if supplier else '',
                'phone': supplier.phone if supplier else '',
                'items': [],
            }
        groups[sname]['items'].append({
            'product_name': item.product_name,
            'material_name': item.material_name,
            'quantity': float(item.quantity) if item.quantity else 0,
            'unit': item.unit,
            'customer_name': item.customer_name,
        })

    return list(groups.values())


def get_factory_order_summary(db: Session, order_ids: list) -> dict:
    if not order_ids:
        return {'groups': [], 'order_count': 0}

    items = db.query(PurchaseOrderItem).filter(
        PurchaseOrderItem.order_id.in_(order_ids)
    ).all()

    # 获取关联订单的 product_quantity
    orders = db.query(PurchaseOrder).filter(
        PurchaseOrder.id.in_(order_ids)
    ).all()
    order_qty_map = {o.id: float(o.product_quantity) if o.product_quantity else 0 for o in orders}

    # 按 customer_name|product_name 分组，再按 supplier_name 分组
    customer_product_map = {}
    for item in items:
        key = f"{item.customer_name}|{item.product_name}"
        if key not in customer_product_map:
            customer_product_map[key] = {
                'customer_name': item.customer_name,
                'product_name': item.product_name,
                'order_ids': set(),
                'suppliers_map': {},
            }

        group = customer_product_map[key]
        group['order_ids'].add(item.order_id)
        sname = item.supplier_name or '未指定'
        if sname not in group['suppliers_map']:
            group['suppliers_map'][sname] = {
                'supplier_name': sname,
                'fabrics': [],
            }

        group['suppliers_map'][sname]['fabrics'].append({
            'fabric_name': item.material_name,
            'specification': item.specification,
            'quantity': float(item.quantity) if item.quantity else 0,
            'unit': item.unit,
            'item_id': item.id,
            'item_ids': [item.id],
            'original_quantities': {str(item.id): float(item.quantity) if item.quantity else 0},
        })

    # 组装最终结构
    groups = []
    for group in customer_product_map.values():
        suppliers = list(group.pop('suppliers_map').values())
        # 计算 product_quantity：仅汇总该 group 关联订单的数量
        group_order_ids = group.pop('order_ids')
        groups.append({
            'customer_name': group['customer_name'],
            'product_name': group['product_name'],
            'product_quantity': sum(order_qty_map.get(oid, 0) for oid in group_order_ids),
            'suppliers': suppliers,
        })

    return {'groups': groups, 'order_count': len(order_ids)}


def save_factory_summary_edits(db: Session, edits: list) -> dict:
    for edit in edits:
        item_id = edit.get('id')
        if not item_id:
            continue
        item = db.get(PurchaseOrderItem, item_id)
        if item:
            if 'quantity' in edit:
                item.quantity = Decimal(str(edit['quantity']))
            if 'remark' in edit:
                item.remark = edit['remark']
    db.commit()
    return {'saved': True}


def get_supplier_order_summary(db: Session, order_ids: list) -> dict:
    if not order_ids:
        return {'materials': [], 'order_count': 0}

    items = db.query(PurchaseOrderItem).filter(
        PurchaseOrderItem.order_id.in_(order_ids)
    ).all()

    # 按 supplier_name + material_name + specification + unit 汇总，计算 total_quantity
    material_map = {}
    for item in items:
        sname = item.supplier_name or '未指定'
        spec = item.specification or ''
        unit = item.unit or ''
        key = f"{sname}|{item.material_name}|{spec}|{unit}"
        if key not in material_map:
            material_map[key] = {
                'supplier_name': sname,
                'material_name': item.material_name,
                'specification': spec,
                'total_quantity': Decimal('0'),
                'unit': unit,
            }
        material_map[key]['total_quantity'] += Decimal(str(item.quantity)) if item.quantity else Decimal('0')

    # total_quantity 转换为 float 输出，Decimal 累加已保证精度
    for m in material_map.values():
        qty = float(m['total_quantity'])
        m['total_quantity'] = round(qty, 2) if qty != int(qty) else int(qty)

    return {'materials': list(material_map.values()), 'order_count': len(order_ids)}


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
    return [
        {'label': '今天', 'start': datetime.now().strftime('%Y-%m-%d'), 'end': datetime.now().strftime('%Y-%m-%d')},
        {'label': '昨天', 'start': (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'), 'end': (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')},
        {'label': '近7天', 'start': (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'), 'end': datetime.now().strftime('%Y-%m-%d')},
        {'label': '近30天', 'start': (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'), 'end': datetime.now().strftime('%Y-%m-%d')},
    ]
