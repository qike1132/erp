"""
供应商管理路由蓝图

API路由已迁移至 FastAPI:
  - GET  /api/v1/purchase-center/api/suppliers
  - POST /api/v1/purchase-center/api/suppliers
  - PUT  /api/v1/purchase-center/api/suppliers/{id}
  - DELETE /api/v1/aux/supplier/{id}
此文件仅保留页面渲染路由
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import db
from app.models import Supplier
from app.models import (
    ProductMaterial, ProductFabric, ProductAccessory, ProductPackaging,
    PurchaseOrder, PurchaseOrderItem, MaterialRegistration
)
from app.utils.permission_decorators import page_permission_required
from utils.sanitizer import sanitize_plain_text

supplier_bp = Blueprint('supplier', __name__, url_prefix='/supplier')


@supplier_bp.route('/list', methods=['GET', 'POST'])
@page_permission_required('product_manage')
def suppliers():
    """供应商列表和添加"""
    if request.method == 'POST':
        name = sanitize_plain_text(request.form.get('name', '').strip())
        contact_person = sanitize_plain_text(request.form.get('contact_person', '').strip())
        phone = sanitize_plain_text(request.form.get('phone', '').strip())
        address = sanitize_plain_text(request.form.get('address', '').strip())
        remark = sanitize_plain_text(request.form.get('remark', '').strip())

        if not name:
            flash('供应商名称不能为空', 'error')
            return redirect(url_for('supplier.suppliers'))

        existing = Supplier.query.filter_by(name=name).first()
        if existing:
            flash('供应商名称已存在', 'error')
            return redirect(url_for('supplier.suppliers'))

        supplier = Supplier(
            name=name,
            contact_person=contact_person,
            phone=phone,
            address=address,
            remark=remark
        )
        db.session.add(supplier)
        db.session.commit()
        flash('供应商添加成功！', 'success')
        return redirect(url_for('supplier.suppliers'))

    suppliers = Supplier.query.order_by(Supplier.created_at.desc()).all()
    return render_template('supplier.html', suppliers=suppliers)


@supplier_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@page_permission_required('product_manage')
def edit_supplier(id):
    """编辑供应商"""
    supplier = Supplier.query.get_or_404(id)

    if request.method == 'POST':
        name = sanitize_plain_text(request.form.get('name', '').strip())
        contact_person = sanitize_plain_text(request.form.get('contact_person', '').strip())
        phone = sanitize_plain_text(request.form.get('phone', '').strip())
        address = sanitize_plain_text(request.form.get('address', '').strip())
        remark = sanitize_plain_text(request.form.get('remark', '').strip())

        if not name:
            flash('供应商名称不能为空', 'error')
            return render_template('edit_supplier.html', supplier=supplier)

        existing = Supplier.query.filter(Supplier.name == name, Supplier.id != id).first()
        if existing:
            flash('供应商名称已存在', 'error')
            return render_template('edit_supplier.html', supplier=supplier)

        # 记录旧值用于同步
        old_name = supplier.name

        supplier.name = name
        supplier.contact_person = contact_person
        supplier.phone = phone
        supplier.address = address
        supplier.remark = remark

        # 同步供应商信息到所有关联表
        _sync_supplier_info(supplier, old_name)

        db.session.commit()
        flash('供应商编辑成功！', 'success')
        return redirect(url_for('supplier.suppliers'))

    return render_template('edit_supplier.html', supplier=supplier)



def _sync_supplier_info(supplier, old_name):
    """供应商信息变更后，同步所有冗余的供应商字段到关联表

    同步字段: supplier_name, supplier_contact_person, supplier_phone, supplier_address
    目标表: BOM物料表(仅name), 采购订单(全部4字段), 采购订单明细/来料登记(仅name)
    """
    sid = supplier.id
    new_name = supplier.name
    new_contact = supplier.contact_person
    new_phone = supplier.phone
    new_address = supplier.address

    # BOM 物料表 — 按 supplier_id 匹配
    for Model in (ProductMaterial, ProductFabric, ProductAccessory, ProductPackaging):
        Model.query.filter_by(supplier_id=sid).update({'supplier_name': new_name})
        # 同时按旧 supplier_name 匹配（兼容 supplier_id 为空的历史数据）
        if old_name != new_name:
            Model.query.filter(
                Model.supplier_name == old_name,
                Model.supplier_id.is_(None)
            ).update({'supplier_name': new_name})

    # 采购订单 — 按 supplier_id 匹配，含全部供应商冗余字段
    PurchaseOrder.query.filter_by(supplier_id=sid).update({
        'supplier_name': new_name,
        'supplier_contact_person': new_contact,
        'supplier_phone': new_phone,
        'supplier_address': new_address,
    })
    # 同时按旧 supplier_name 匹配无 supplier_id 的历史数据
    if old_name != new_name:
        PurchaseOrder.query.filter(
            PurchaseOrder.supplier_name == old_name,
            PurchaseOrder.supplier_id.is_(None)
        ).update({
            'supplier_name': new_name,
            'supplier_contact_person': new_contact,
            'supplier_phone': new_phone,
            'supplier_address': new_address,
        })
    else:
        # 名称未变但联系人/电话/地址可能变了，也需同步
        PurchaseOrder.query.filter(
            PurchaseOrder.supplier_name == new_name,
            PurchaseOrder.supplier_id.is_(None)
        ).update({
            'supplier_contact_person': new_contact,
            'supplier_phone': new_phone,
            'supplier_address': new_address,
        })

    # 采购订单明细 — 无 supplier_id，按旧 supplier_name 匹配
    if old_name != new_name:
        PurchaseOrderItem.query.filter_by(supplier_name=old_name).update({'supplier_name': new_name})

    # 来料登记 — 按 supplier_id 匹配
    MaterialRegistration.query.filter_by(supplier_id=sid).update({'supplier_name': new_name})
    if old_name != new_name:
        MaterialRegistration.query.filter(
            MaterialRegistration.supplier_name == old_name,
            MaterialRegistration.supplier_id.is_(None)
        ).update({'supplier_name': new_name})
