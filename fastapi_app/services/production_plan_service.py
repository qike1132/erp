"""
采购计划管理业务逻辑服务

包含排产计划 CRUD、批量上传预览、库存对比、出货进度追踪、
月度汇总统计、时间轴查询、操作日志等功能。
"""
import calendar
import io
import json
import logging
import uuid
from datetime import datetime, date, timedelta
from typing import Optional

import openpyxl
from sqlalchemy import select, func, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import (
    ProductionPlan, ProductionPlanLog, StagingPurchasePlan,
    StockOut, Product, Customer,
)
from fastapi_app.services import product_service, customer_service, stock_service

logger = logging.getLogger(__name__)


# ==================== 日期边界处理 ====================

def _last_day_of_month(year: int, month: int) -> date:
    """获取月份最后一天"""
    return date(year, month, calendar.monthrange(year, month)[1])


def _normalize_plan_date(date_str: str) -> date:
    """
    自动校准日期：4月31日→4月30日，2月30日→2月28/29日
    """
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        parts = date_str.strip().split('-')
        if len(parts) != 3:
            raise ValueError(f"日期格式不正确: {date_str}，请使用 YYYY-MM-DD 格式")
        y, m = int(parts[0]), int(parts[1])
        d = min(int(parts[2]), calendar.monthrange(y, m)[1])
        return date(y, m, d)


# ==================== CRUD ====================

async def get_plans(db: AsyncSession, year: int, month: int,
                    customer: str = '') -> list[ProductionPlan]:
    """获取指定月份的排产计划列表"""
    conditions = [
        func.year(ProductionPlan.plan_date) == year,
        func.month(ProductionPlan.plan_date) == month,
    ]
    if customer:
        conditions.append(ProductionPlan.customer_name == customer)

    result = await db.execute(
        select(ProductionPlan)
        .where(*conditions)
        .order_by(ProductionPlan.plan_date, ProductionPlan.customer_name)
    )
    return list(result.scalars().all())


async def get_plan_by_id(db: AsyncSession, plan_id: int) -> Optional[ProductionPlan]:
    """根据ID获取排产计划"""
    result = await db.execute(
        select(ProductionPlan).where(ProductionPlan.id == plan_id)
    )
    return result.scalar_one_or_none()


async def create_plan(db: AsyncSession, *, customer_name: str, product_name: str,
                      barcode: str, quantity: int, plan_date_str: str,
                      remark: str = '', created_by: str = '',
                      upload_batch: str = '') -> ProductionPlan:
    """创建排产计划"""
    # 验证客户
    customers = await customer_service.search_customers(db, customer_name)
    if customer_name not in [c.name for c in customers]:
        raise ValueError(f"客户 '{customer_name}' 不存在")

    # 验证69码
    products = await product_service.search_products(db, barcode)
    if not products:
        raise ValueError(f"69码 '{barcode}' 未找到对应产品")

    plan_date_val = _normalize_plan_date(plan_date_str)

    plan = ProductionPlan(
        customer_name=customer_name,
        product_name=product_name,
        barcode=barcode,
        quantity=quantity,
        plan_date=plan_date_val,
        status='pending',
        shipped_qty=0,
        remark=remark,
        created_by=created_by,
        upload_batch=upload_batch,
    )
    db.add(plan)
    await db.flush()
    await db.refresh(plan)

    await _log_action(db, plan.id, 'create', None, plan.to_dict(), created_by)
    await db.commit()
    logger.info(f'排产计划创建成功：{plan.customer_name} - {plan.product_name} - {plan.quantity}')
    return plan


async def update_plan(db: AsyncSession, plan_id: int, *, created_by: str = '', **kwargs) -> ProductionPlan:
    """更新排产计划"""
    plan = await get_plan_by_id(db, plan_id)
    if not plan:
        raise ValueError('排产计划不存在')

    old_data = plan.to_dict()

    for field in ('customer_name', 'product_name', 'barcode', 'quantity',
                  'plan_date', 'status', 'remark', 'shipped_qty'):
        if field in kwargs and kwargs[field] is not None:
            if field == 'plan_date':
                plan.plan_date = _normalize_plan_date(kwargs[field])
            else:
                setattr(plan, field, kwargs[field])

    plan.update_time = datetime.now()
    await db.flush()
    await db.refresh(plan)

    await _log_action(db, plan.id, 'update', old_data, plan.to_dict(), created_by)
    await db.commit()
    return plan


async def delete_plan(db: AsyncSession, plan_id: int, *, operator: str = '') -> None:
    """删除排产计划"""
    plan = await get_plan_by_id(db, plan_id)
    if not plan:
        raise ValueError('排产计划不存在')

    old_data = plan.to_dict()
    await db.execute(delete(ProductionPlanLog).where(ProductionPlanLog.plan_id == plan_id))
    await db.delete(plan)
    await _log_action(db, plan_id, 'delete', old_data, None, operator)
    await db.commit()
    logger.info(f'排产计划删除成功：ID={plan_id}')


# ==================== 库存对比 + 出货进度 ====================

async def get_plans_with_inventory(db: AsyncSession, year: int, month: int,
                                   customer: str = '') -> dict:
    """
    获取排产计划列表，关联库存和出货数据

    匹配规则：customer_name + product_name 精确匹配
    """
    plans = await get_plans(db, year, month, customer)

    # 获取库存数据
    try:
        inventory_result = await stock_service.get_inventory(db)
        inventory_map = _build_inventory_map(inventory_result['inventory_data'])
    except Exception as e:
        logger.warning(f'获取库存数据失败: {e}')
        inventory_map = {}

    # 获取当月出货数据
    try:
        shipped_map = await _calc_all_shipped_qty(db, year, month)
    except Exception as e:
        logger.warning(f'获取出货数据失败: {e}')
        shipped_map = {}

    plan_list = []
    for plan in plans:
        key = (plan.customer_name, plan.product_name)
        inventory_qty = inventory_map.get(key, 0)
        shipped_qty = shipped_map.get(key, 0)
        remaining_qty = plan.quantity - shipped_qty

        # 更新 shipped_qty 缓存字段
        if plan.shipped_qty != shipped_qty:
            plan.shipped_qty = shipped_qty

        plan_list.append({
            'id': plan.id,
            'customer_name': plan.customer_name,
            'product_name': plan.product_name,
            'barcode': plan.barcode,
            'quantity': plan.quantity,
            'inventory_qty': inventory_qty,
            'shipped_qty': shipped_qty,
            'remaining_qty': remaining_qty,
            'diff': plan.quantity - inventory_qty,
            'stock_status': _calc_stock_status(plan.quantity, inventory_qty),
            'shipment_status': _calc_shipment_status(plan.quantity, shipped_qty),
            'plan_date': plan.plan_date.isoformat() if plan.plan_date else '',
            'status': plan.status,
            'remark': plan.remark or '',
            'upload_batch': plan.upload_batch or '',
            'create_time': plan.create_time.strftime('%Y-%m-%d %H:%M:%S') if plan.create_time else '',
            'update_time': plan.update_time.strftime('%Y-%m-%d %H:%M:%S') if plan.update_time else '',
            'created_by': plan.created_by or '',
        })

    # flush updated shipped_qty
    await db.flush()

    monthly_summary = _calc_monthly_summary(plan_list)

    return {
        'plans': plan_list,
        'monthly_summary': monthly_summary,
        'total': len(plan_list),
    }


async def _calc_all_shipped_qty(db: AsyncSession, year: int, month: int) -> dict:
    """
    计算当月所有客户+产品的已出货总量

    查询 stock_out 全表（含独立出货和订单抵扣）
    返回: {(customer_name, product_name): total_shipped_qty}
    """
    start = date(year, month, 1)
    end = _last_day_of_month(year, month)

    # 查询当月所有出货记录（含所有类型）
    result = await db.execute(
        select(
            StockOut.customer,
            Product.name.label('product_name'),
            func.coalesce(func.sum(StockOut.quantity), 0).label('total_qty'),
        )
        .join(Product, StockOut.product_id == Product.id)
        .where(
            and_(
                func.date(StockOut.stockout_date) >= start,
                func.date(StockOut.stockout_date) <= end,
                StockOut.customer.isnot(None),
                StockOut.customer != '',
            )
        )
        .group_by(StockOut.customer, Product.name)
    )

    return {
        (row.customer, row.product_name): row.total_qty
        for row in result.all()
    }


def _build_inventory_map(inventory_data: list) -> dict:
    """构建库存查找字典 key=(customer, product_name) value=total_stock"""
    mapping = {}
    for item in inventory_data:
        key = (item['customer'], item['product_name'])
        stock = item.get('total_stock', 0) or 0
        if isinstance(stock, str):
            try:
                stock = int(stock)
            except (ValueError, TypeError):
                stock = 0
        mapping[key] = mapping.get(key, 0) + stock
    return mapping


def _calc_stock_status(plan_qty: int, inventory_qty: int) -> str:
    """排产 > 库存 → warning, 否则 normal"""
    return 'warning' if plan_qty > inventory_qty else 'normal'


def _calc_shipment_status(plan_qty: int, shipped_qty: int) -> str:
    """出货进度状态: completed/partial/pending"""
    if shipped_qty >= plan_qty:
        return 'completed'
    elif shipped_qty > 0:
        return 'partial'
    return 'pending'


def _calc_monthly_summary(plan_list: list) -> dict:
    """当月汇总统计（含库存对比+出货进度汇总）"""
    total_plan_qty = 0
    total_inventory_qty = 0
    total_shipped_qty = 0
    warning_count = 0

    customer_summary = {}
    for p in plan_list:
        total_plan_qty += p['quantity']
        total_inventory_qty += p['inventory_qty']
        total_shipped_qty += p['shipped_qty']
        if p['stock_status'] == 'warning':
            warning_count += 1

        cn = p['customer_name']
        if cn not in customer_summary:
            customer_summary[cn] = {
                'plan_qty': 0, 'inventory_qty': 0,
                'shipped_qty': 0, 'remaining_qty': 0, 'warning_count': 0,
            }
        cs = customer_summary[cn]
        cs['plan_qty'] += p['quantity']
        cs['inventory_qty'] += p['inventory_qty']
        cs['shipped_qty'] += p['shipped_qty']
        cs['remaining_qty'] += p['remaining_qty']
        if p['stock_status'] == 'warning':
            cs['warning_count'] += 1

    return {
        'total_plan_qty': total_plan_qty,
        'total_inventory_qty': total_inventory_qty,
        'total_shipped_qty': total_shipped_qty,
        'total_remaining_qty': total_plan_qty - total_shipped_qty,
        'total_diff': total_plan_qty - total_inventory_qty,
        'warning_count': warning_count,
        'customer_summary': customer_summary,
    }


# ==================== 时间轴查询 ====================

async def get_timeline(db: AsyncSession, year: int, month: int,
                       customer: str = '') -> dict:
    """
    时间轴数据：按日期+客户维度聚合，用于日历热力图
    """
    plans = await get_plans(db, year, month, customer)

    # 获取库存和出货
    try:
        inventory_result = await stock_service.get_inventory(db)
        inventory_map = _build_inventory_map(inventory_result['inventory_data'])
    except Exception:
        inventory_map = {}

    try:
        shipped_map = await _calc_all_shipped_qty(db, year, month)
    except Exception:
        shipped_map = {}

    # 按日期聚合
    days_in_month = calendar.monthrange(year, month)[1]
    timeline = {}
    customer_set = set()

    for day in range(1, days_in_month + 1):
        d = date(year, month, day)
        timeline[d.isoformat()] = {
            'date': d.isoformat(),
            'day': day,
            'plans': [],
            'total_plan_qty': 0,
            'has_warning': False,
        }

    for plan in plans:
        key = (plan.customer_name, plan.product_name)
        inv_qty = inventory_map.get(key, 0)
        shp_qty = shipped_map.get(key, 0)
        is_warning = plan.quantity > inv_qty

        date_str = plan.plan_date.isoformat() if plan.plan_date else ''
        if date_str in timeline:
            timeline[date_str]['plans'].append({
                'id': plan.id,
                'customer_name': plan.customer_name,
                'product_name': plan.product_name,
                'barcode': plan.barcode,
                'quantity': plan.quantity,
                'inventory_qty': inv_qty,
                'shipped_qty': shp_qty,
                'remaining_qty': plan.quantity - shp_qty,
                'stock_status': _calc_stock_status(plan.quantity, inv_qty),
            })
            timeline[date_str]['total_plan_qty'] += plan.quantity
            if is_warning:
                timeline[date_str]['has_warning'] = True

        customer_set.add(plan.customer_name)

    return {
        'year': year,
        'month': month,
        'days_in_month': days_in_month,
        'timeline': list(timeline.values()),
        'customers': sorted(customer_set),
    }


async def get_customer_summary(db: AsyncSession, year: int, month: int) -> dict:
    """客户汇总数据"""
    result = await get_plans_with_inventory(db, year, month)
    return result['monthly_summary']


# ==================== 批量上传与预览 ====================

async def upload_excel(db: AsyncSession, file_content: bytes,
                       session_id: str) -> dict:
    """
    解析Excel文件，写入暂存表，返回预览数据
    """
    batch_id = str(uuid.uuid4())[:8]

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_content), read_only=True)
    except Exception as e:
        raise ValueError(f"Excel文件解析失败: {e}")

    try:
        ws = wb.active
        rows = list(ws.iter_rows(min_row=2, values_only=True))  # 跳过标题行
    finally:
        wb.close()

    if not rows:
        raise ValueError("Excel文件无数据行")

    staging_records = []
    errors = []
    success_count = 0

    for i, row in enumerate(rows, start=2):
        if not row or all(c is None for c in row):
            continue

        try:
            customer_name = str(row[0] or '').strip()
            product_name = str(row[1] or '').strip()
            barcode = str(row[2] or '').strip()
            quantity = int(row[3]) if row[3] else 0
            plan_date_str = str(row[4] or '').strip()
            remark = str(row[5] or '').strip() if len(row) > 5 and row[5] else ''
        except (ValueError, IndexError) as e:
            errors.append(f"第{i}行: 数据格式错误 - {e}")
            continue

        # 基础验证
        validation_error = ''
        if not customer_name:
            validation_error = '客户名称为空'
        elif not product_name:
            validation_error = '产品名称为空'
        elif not barcode:
            validation_error = '69码为空'
        elif quantity <= 0:
            validation_error = '数量必须为正数'
        elif not plan_date_str:
            validation_error = '计划日期为空'
        else:
            try:
                _normalize_plan_date(plan_date_str)
            except ValueError as e:
                validation_error = str(e)

        record = StagingPurchasePlan(
            session_id=session_id,
            customer_name=customer_name,
            product_name=product_name,
            barcode=barcode,
            quantity=quantity,
            plan_date=_normalize_plan_date(plan_date_str) if not validation_error else date.today(),
            remark=remark,
            is_validated=0 if validation_error else 1,  # 基础验证通过则为1，深度验证在validate阶段
            validation_error=validation_error,
            upload_batch_id=batch_id,
        )
        db.add(record)
        staging_records.append(record)
        if not validation_error:
            success_count += 1

    await db.flush()

    return {
        'batch_id': batch_id,
        'total': len(staging_records),
        'success_count': success_count,
        'error_count': len(errors),
        'errors': errors,
    }


async def get_staging_list(db: AsyncSession, session_id: str) -> list[dict]:
    """获取暂存区预览数据"""
    result = await db.execute(
        select(StagingPurchasePlan)
        .where(StagingPurchasePlan.session_id == session_id)
        .order_by(StagingPurchasePlan.id)
    )
    records = result.scalars().all()
    return [r.to_dict() for r in records]


async def validate_staging(db: AsyncSession, session_id: str) -> dict:
    """验证暂存数据：检查客户和产品是否存在"""
    result = await db.execute(
        select(StagingPurchasePlan)
        .where(StagingPurchasePlan.session_id == session_id)
    )
    records = result.scalars().all()

    # 预加载客户和产品
    all_customers = await customer_service.get_customers(db)
    customer_names = {c.name for c in all_customers}

    all_products = await product_service.get_products(db)
    barcode_set = {p['barcode'] for p in all_products if p.get('barcode')}
    product_name_map = {p['barcode']: p['name'] for p in all_products if p.get('barcode')}

    valid_count = 0
    error_count = 0

    for record in records:
        errors = []
        if record.validation_error:
            errors.append(record.validation_error)

        if record.customer_name not in customer_names:
            errors.append(f"客户 '{record.customer_name}' 不存在")

        if record.barcode not in barcode_set:
            errors.append(f"69码 '{record.barcode}' 未找到产品")
        elif not record.product_name and record.barcode in product_name_map:
            record.product_name = product_name_map[record.barcode]

        if errors:
            record.is_validated = 0
            record.validation_error = '; '.join(errors)
            error_count += 1
        else:
            record.is_validated = 1
            record.validation_error = None
            valid_count += 1

    await db.flush()

    return {
        'total': len(records),
        'valid_count': valid_count,
        'error_count': error_count,
    }


async def confirm_staging(db: AsyncSession, session_id: str,
                          batch_id: str = '', created_by: str = '') -> dict:
    """确认暂存数据，批量写入正式表"""
    conditions = [StagingPurchasePlan.session_id == session_id]
    if batch_id:
        conditions.append(StagingPurchasePlan.upload_batch_id == batch_id)

    result = await db.execute(
        select(StagingPurchasePlan).where(*conditions)
    )
    records = result.scalars().all()

    if not records:
        raise ValueError('暂存区无数据')

    # 仅确认验证通过的记录
    valid_records = [r for r in records if r.is_validated]
    if not valid_records:
        raise ValueError('所有数据验证未通过，无法保存')

    created_count = 0
    for record in valid_records:
        plan = ProductionPlan(
            customer_name=record.customer_name,
            product_name=record.product_name,
            barcode=record.barcode,
            quantity=record.quantity,
            plan_date=record.plan_date,
            status='pending',
            shipped_qty=0,
            remark=record.remark or '',
            created_by=created_by,
            upload_batch=record.upload_batch_id,
        )
        db.add(plan)
        created_count += 1

    # 清空该批暂存数据
    await db.execute(
        delete(StagingPurchasePlan).where(*conditions)
    )

    await db.commit()
    logger.info(f'暂存数据确认保存：{created_count} 条')

    return {
        'created_count': created_count,
        'skipped_count': len(records) - len(valid_records),
    }


async def clear_staging(db: AsyncSession, session_id: str) -> None:
    """清空暂存区"""
    await db.execute(
        delete(StagingPurchasePlan).where(StagingPurchasePlan.session_id == session_id)
    )
    await db.commit()


# ==================== 69码验证 ====================

async def validate_barcode(db: AsyncSession, barcode: str) -> dict:
    """验证69码，返回关联的产品信息"""
    products = await product_service.search_products(db, barcode)
    if not products:
        return {'valid': False, 'product_name': None, 'message': f"69码 '{barcode}' 未找到对应产品"}

    exact = [p for p in products if p.get('barcode') == barcode]
    p = exact[0] if exact else products[0]
    return {'valid': True, 'product_name': p['name'], 'message': '验证通过'}


# ==================== 操作日志 ====================

async def _log_action(db: AsyncSession, plan_id: int, action: str,
                      old_value: dict | None, new_value: dict | None,
                      operator: str) -> None:
    """记录操作日志"""
    log = ProductionPlanLog(
        plan_id=plan_id,
        action=action,
        old_value=json.dumps(old_value, ensure_ascii=False) if old_value else None,
        new_value=json.dumps(new_value, ensure_ascii=False) if new_value else None,
        operator=operator,
    )
    db.add(log)
    await db.flush()
