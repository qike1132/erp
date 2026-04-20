"""
产品管理路由蓝图
API路由已迁移至 FastAPI:
  - /search → /api/v1/products/search
  - /available-stock → /api/v1/products/available-stock
此文件仅保留页面渲染路由
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import db
from app.models import Product, InventoryLog
from app.utils.permission_decorators import api_permission_required
from utils.sanitizer import sanitize_plain_text
from fastapi_app.shared.stock_concurrency import get_product_for_update_sync

product_bp = Blueprint('product', __name__, url_prefix='/product')

PER_PAGE = 20  # 每页显示条数（服务端分页）


@product_bp.route('/list', methods=['GET', 'POST'])
@api_permission_required('product_manage')
def products():
    """产品列表和添加"""
    page = max(1, request.args.get('page', 1, type=int) or 1)
    base_query = db.select(Product).order_by(Product.create_time.desc())

    if request.method == 'POST':
        name = sanitize_plain_text(request.form.get('name', '').strip())
        barcode = sanitize_plain_text(request.form.get('barcode', '').strip())
        image = sanitize_plain_text(request.form.get('image', ''))
        price_str = request.form.get('price', '0').strip()
        price = float(price_str) if price_str else 0
        initial_stock = int(request.form.get('initial_stock', 0) or 0)

        if not name:
            flash('产品名称不能为空！', 'error')
            pagination = db.paginate(base_query, page=page, per_page=PER_PAGE)
            return render_template('product.html', products=pagination.items, pagination=pagination), 400

        existing_product = Product.query.filter(db.func.lower(Product.name) == db.func.lower(name)).first()
        if existing_product:
            flash(f'产品名称"{name}"已存在，每个产品名称必须是唯一的！', 'error')
            pagination = db.paginate(base_query, page=page, per_page=PER_PAGE)
            return render_template('product.html', products=pagination.items, pagination=pagination), 400

        product = Product(
            name=name,
            barcode=barcode,
            price=price,
            image=image,
            initial_stock=initial_stock,
            current_stock=initial_stock
        )
        db.session.add(product)
        db.session.flush()

        if initial_stock > 0:
            log = InventoryLog(
                product_id=product.id,
                change_type='初始库存',
                change_quantity=initial_stock,
                related_id=str(product.id),
                note='初始库存设置'
            )
            db.session.add(log)

        db.session.commit()
        flash('产品添加成功！', 'success')
        return redirect(url_for('product.products'))

    pagination = db.paginate(base_query, page=page, per_page=PER_PAGE)
    return render_template('product.html', products=pagination.items, pagination=pagination)


@product_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@api_permission_required('product_manage')
def edit_product(id):
    """编辑产品"""
    product = get_product_for_update_sync(db.session, id)

    if request.method == 'POST':
        new_name = sanitize_plain_text(request.form['name'])

        existing_product = Product.query.filter(
            db.func.lower(Product.name) == db.func.lower(new_name),
            Product.id != id
        ).first()
        if existing_product:
            flash(f'产品名称"{new_name}"已存在，每个产品名称必须是唯一的！', 'error')
            return render_template('edit_product.html', product=product), 400

        product.name = new_name
        product.barcode = sanitize_plain_text(request.form['barcode'])
        product.image = sanitize_plain_text(request.form.get('image', product.image))
        price_str = request.form.get('price', '').strip()
        if price_str:
            product.price = float(price_str)

        if 'initial_stock' in request.form:
            try:
                new_initial = int(request.form['initial_stock'])
            except (ValueError, TypeError):
                flash('初始库存必须为有效数字！', 'error')
                return render_template('edit_product.html', product=product), 400
            stock_change = new_initial - product.initial_stock
            if stock_change != 0:
                product.initial_stock = new_initial
                product.current_stock += stock_change
                log = InventoryLog(
                    product_id=product.id,
                    change_type='初始库存调整',
                    change_quantity=stock_change,
                    related_id=str(product.id),
                    note='初始库存调整'
                )
                db.session.add(log)

        db.session.commit()
        flash('产品编辑成功！', 'success')
        page = max(1, request.args.get('page', 1, type=int) or 1)
        return redirect(url_for('product.products', page=page))

    return render_template('edit_product.html', product=product)

