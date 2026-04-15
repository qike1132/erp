"""
客户管理路由蓝图
API路由已迁移至 FastAPI:
  - /toggle-status/<id> → /api/v1/customers/toggle-status/{id}
  - /api/list → /api/v1/customers/list
  - /api/search → /api/v1/customers/search
  - /api/active-names → /api/v1/customers/active-names
  - /api/access-stats, /api/customer-stats/<id>, /api/sync-check → 无前端调用,已移除
此文件仅保留页面渲染路由
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from app import db
from app.models import Customer
from app.utils.permission_decorators import page_permission_required
from utils.sanitizer import sanitize_plain_text

customer_bp = Blueprint('customer', __name__, url_prefix='/customer')


@customer_bp.route('/list', methods=['GET', 'POST'])
@page_permission_required('customer_manage')
def customers():
    """客户列表和添加"""
    if request.method == 'POST':
        name = sanitize_plain_text(request.form.get('name', '').strip())
        contact = sanitize_plain_text(request.form.get('contact', '').strip())
        phone = sanitize_plain_text(request.form.get('phone', '').strip())
        address = sanitize_plain_text(request.form.get('address', '').strip())
        note = sanitize_plain_text(request.form.get('note', '').strip())

        if not name:
            flash('客户名称不能为空', 'error')
            return redirect(url_for('customer.customers'))

        existing = Customer.query.filter_by(name=name).first()
        if existing:
            flash('客户名称已存在', 'error')
            return redirect(url_for('customer.customers'))

        customer = Customer(
            name=name,
            contact=contact,
            phone=phone,
            address=address,
            note=note
        )
        db.session.add(customer)
        db.session.commit()
        flash('客户添加成功！', 'success')
        return redirect(url_for('customer.customers'))

    customers = Customer.query.order_by(Customer.create_time.desc()).all()
    return render_template('customer.html', customers=customers)


@customer_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@page_permission_required('customer_manage')
def edit_customer(id):
    """编辑客户"""
    customer = Customer.query.get_or_404(id)

    if request.method == 'POST':
        name = sanitize_plain_text(request.form.get('name', '').strip())
        contact = sanitize_plain_text(request.form.get('contact', '').strip())
        phone = sanitize_plain_text(request.form.get('phone', '').strip())
        address = sanitize_plain_text(request.form.get('address', '').strip())
        note = sanitize_plain_text(request.form.get('note', '').strip())
        status = request.form.get('status') == 'on'

        if not name:
            flash('客户名称不能为空', 'error')
            return render_template('edit_customer.html', customer=customer)

        existing = Customer.query.filter(Customer.name == name, Customer.id != id).first()
        if existing:
            flash('客户名称已存在', 'error')
            return render_template('edit_customer.html', customer=customer)

        customer.name = name
        customer.contact = contact
        customer.phone = phone
        customer.address = address
        customer.note = note
        customer.status = status

        db.session.commit()
        flash('客户编辑成功！', 'success')
        return redirect(url_for('customer.customers'))

    return render_template('edit_customer.html', customer=customer)


@customer_bp.route('/delete/<int:id>')
@page_permission_required('customer_manage')
def delete_customer(id):
    """删除客户"""
    customer = Customer.query.get_or_404(id)

    from app.models import Order, StockIn, StockOut
    has_orders = Order.query.filter_by(customer=customer.name).first()
    has_stockins = StockIn.query.filter_by(customer=customer.name).first()
    has_stockouts = StockOut.query.filter_by(customer=customer.name).first()

    if has_orders or has_stockins or has_stockouts:
        flash('该客户已有相关单据，无法删除！建议禁用该客户。', 'error')
        return redirect(url_for('customer.customers'))

    db.session.delete(customer)
    db.session.commit()
    flash('客户删除成功！', 'success')
    return redirect(url_for('customer.customers'))
