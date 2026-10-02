"""
采购计划暂存区管理与 Excel 导入

职责：Excel 解析（_load_excel_rows / _parse_excel_row / _validate_excel_row）、
    上传暂存（upload_excel）、暂存列表（get_staging_list）、暂存校验
    （validate_staging）、暂存确认（confirm_staging 及分组 helper）、
    清空暂存（clear_staging）、69码校验（validate_barcode）。

从 purchase_plan_crud.py 拆分而来，保持函数签名不变。
"""
import io
import uuid

import openpyxl
from sqlalchemy import and_, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services import customer_service, product_service
from fastapi_app.services.plan_utils import normalize_plan_date
from fastapi_app.services.purchase_plan_common import (
    _generate_plan_no,
    _invalidate_plan_caches,
    _schedule_post_commit,
    logger,
)
from fastapi_app.services.purchase_plan_order_quota import (
    check_order_remaining,
    format_without_order_error,
)
from fastapi_app.shared_models import (
    Product,
    PurchasePlan,
    PurchasePlanDetail,
    StagingPurchasePlan,
)


def _load_excel_rows(file_content: bytes) -> list[tuple]:
    """加载 Excel 文件并返回数据行(跳过表头)"""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_content), read_only=True)
    except (OSError, ValueError) as e:
        raise ValueError(f'Excel文件解析失败: {e}') from e
    try:
        ws = wb.active
        rows = list(ws.iter_rows(min_row=2, values_only=True))
    finally:
        wb.close()
    return rows


def _parse_excel_row(row: tuple, row_idx: int) -> tuple[dict, str]:
    """解析单行 Excel 数据, 返回 (字段字典, 错误信息)

    模板列：客户名称、产品名称、数量、计划日期、备注（69码已移除，产品按名称关联）。
    S10 修复：Excel 单元格可能为字符串 '10' 或浮点 10.5，
    int(row[2]) 会抛 ValueError；int(float(...)) 兼容两种格式。
    """
    try:
        customer_name = str(row[0] or '').strip()
        product_name = str(row[1] or '').strip()
        # S10: 兼容字符串数字与浮点数；负数/0 在 _validate_excel_row 中拦截
        quantity = int(float(row[2])) if row[2] not in (None, '') else 0
        plan_date_str = str(row[3] or '').strip()
        remark = str(row[4] or '').strip() if len(row) > 4 and row[4] else ''
        return {'customer_name': customer_name, 'product_name': product_name, 'barcode': '', 'quantity': quantity, 'plan_date_str': plan_date_str, 'remark': remark}, ''
    except (ValueError, IndexError) as e:
        return {}, f'第{row_idx}行: 数据格式错误 - {e}'


def _validate_excel_row(fields: dict, detected_month: str | None) -> tuple[str, str | None]:
    """校验行字段, 返回 (validation_error, new_detected_month)"""
    if not fields['customer_name']:
        return '客户名称为空', None
    if not fields['product_name']:
        return '产品名称为空', None
    if fields['quantity'] <= 0:
        return '数量必须为正整数', None
    if not fields['plan_date_str']:
        return '计划日期为空', None
    try:
        parsed_date = normalize_plan_date(fields['plan_date_str'])
        row_month = f'{parsed_date.year}-{parsed_date.month:02d}'
        if detected_month is None:
            return '', row_month
        if row_month != detected_month:
            return f'日期月份 {row_month} 与之前行月份 {detected_month} 不一致，不允许跨月', None
        return '', None
    except ValueError as e:
        return str(e), None


async def upload_excel(db: AsyncSession, file_content: bytes, session_id: str, created_by: str='') -> dict:
    """解析Excel文件，写入暂存表，返回预览数据"""
    batch_id = str(uuid.uuid4())[:8]
    rows = _load_excel_rows(file_content)
    if not rows:
        raise ValueError('Excel文件无数据行')
    detected_month = None
    staging_records = []
    errors = []
    success_count = 0
    for i, row in enumerate(rows, start=2):
        if not row or all(c is None for c in row):
            continue
        fields, parse_error = _parse_excel_row(row, i)
        if parse_error:
            errors.append(parse_error)
            continue
        validation_error, new_month = _validate_excel_row(fields, detected_month)
        if new_month:
            detected_month = new_month
        # 校验失败：记录错误并跳过该行，避免使用 date.today() 产生错误的默认日期
        if validation_error:
            errors.append(f'第{i}行: {validation_error}')
            continue
        record = StagingPurchasePlan(session_id=session_id, customer_name=fields['customer_name'], product_name=fields['product_name'], barcode=fields['barcode'], quantity=fields['quantity'], plan_date=normalize_plan_date(fields['plan_date_str']), plan_month=detected_month, remark=fields['remark'], is_validated=0, validation_error=validation_error, upload_batch_id=batch_id)
        db.add(record)
        staging_records.append(record)
        success_count += 1
    await db.flush()
    is_async = len(staging_records) > 500
    return {'batch_id': batch_id, 'total': len(staging_records), 'success_count': success_count, 'error_count': len(errors), 'errors': errors, 'is_async': is_async, 'detected_month': detected_month}

async def get_staging_list(db: AsyncSession, session_id: str) -> list[dict]:
    """获取暂存区预览数据"""
    result = await db.execute(select(StagingPurchasePlan).where(StagingPurchasePlan.session_id == session_id).order_by(StagingPurchasePlan.id))
    records = result.scalars().all()
    return [r.to_dict() for r in records]

async def validate_staging(db: AsyncSession, session_id: str) -> dict:
    """验证暂存数据：检查客户和产品是否存在

    返回 errors 明细供前端展示/导出错误清单。errors[].seq 为数据在导入批次中的
    行序号（1 起，按暂存表 id 升序，即 Excel 数据行顺序），非 Excel 物理行号；
    上传阶段产生的错误其 message 已自带「第N行」物理行号。
    """
    result = await db.execute(select(StagingPurchasePlan).where(StagingPurchasePlan.session_id == session_id).order_by(StagingPurchasePlan.id))
    records = result.scalars().all()
    all_customers = await customer_service.get_active_customer_names(db)
    customer_map = {c['name']: c for c in all_customers}
    products = await product_service.get_products(db)
    product_name_set = {p['name'] for p in products}
    valid_count = 0
    error_count = 0
    for record in records:
        errors_list = []
        if record.validation_error:
            errors_list.append(record.validation_error)
        if record.customer_name not in customer_map:
            fuzzy = [c['name'] for c in all_customers if record.customer_name in c['name']]
            hint = f"，相似: {', '.join(fuzzy[:3])}" if fuzzy else ''
            errors_list.append(f"客户 '{record.customer_name}' 不存在{hint}")
        if not record.product_name:
            errors_list.append('产品名称为空')
        elif record.product_name not in product_name_set:
            errors_list.append(f"产品 '{record.product_name}' 未找到对应产品")
        if errors_list:
            # P2-A2 类型收窄：is_validated 为 Boolean 列，False/0 在 PG 与真值判断上等价
            record.is_validated = False
            record.validation_error = '; '.join(errors_list)
            error_count += 1
        else:
            record.is_validated = True
            record.validation_error = None
            valid_count += 1
    records_to_check = [r for r in records if r.is_validated]
    if records_to_check:
        # 2026-09 修订：准入条件由「库存充足」改为「订单余量 > 0」——
        # 暂存记录自带客户名，故按 (客户, 产品) 校验（原先的库存校验只按产品，
        # 跨客户聚合，与本页的客户维度计划语义不符）。
        no_order = await check_order_remaining(db, [{'customer_name': r.customer_name or '', 'product_name': r.product_name or ''} for r in records_to_check])
        no_order_set = {(it['customer_name'], it['product_name']) for it in no_order}
        for r in records_to_check:
            if (r.customer_name or '', r.product_name or '') in no_order_set:
                r.is_validated = False
                r.validation_error = f"客户 '{r.customer_name}' 的产品 '{r.product_name}' 没有订单余量（订单已发完或不存在），无法添加计划"
                valid_count -= 1
                error_count += 1
    await db.flush()
    error_details = [
        {
            'seq': seq,
            'customer_name': r.customer_name or '',
            'product_name': r.product_name or '',
            'barcode': r.barcode or '',
            'quantity': int(r.quantity or 0),
            'plan_date': r.plan_date.isoformat() if r.plan_date else '',
            'message': r.validation_error or '未通过校验',
        }
        for seq, r in enumerate(records, start=1)
        if not r.is_validated
    ]
    return {'total': len(records), 'valid_count': valid_count, 'error_count': error_count, 'errors': error_details}

def _group_staging_records(valid_records: list) -> dict[tuple[str, str], list]:
    """按 (customer_name, plan_month) 分组"""
    groups: dict[tuple[str, str], list] = {}
    for record in valid_records:
        key = (record.customer_name, record.plan_month or '')
        groups.setdefault(key, []).append(record)
    return groups


async def _get_or_create_plan_for_group(
    db: AsyncSession,
    customer_id: int,
    customer_name: str,
    plan_month: str,
    batch_id: str,
    created_by: str,
) -> PurchasePlan:
    """获取或创建指定客户+月份的采购计划主单

    B2 修复：
        1. SELECT 时附加 with_for_update() 行级锁，防止并发 confirm_staging
           双双通过 "不存在" 检查后各自创建主单。
        2. 数据库侧新增 UNIQUE(customer_id, plan_month) 索引（migration
           pg_standalone_018），作为最后防线；并发 INSERT 触发 IntegrityError
           时重试 SELECT 读取已创建的主单。
    N3 修复：删除循环末尾不可达的 raise。
        —— 2026-09-14 修订：该 raise 已恢复。删除它使「第 3 次必 raise」
        变成隐式约定（mypy 也会报 Missing return statement）；恢复后既显式化
        不变式，又避免将来改动循环边界时静默返回 None。
    """
    # with_for_update 锁住已存在行；若不存在则不锁任何行，依赖唯一索引兜底
    existing = await db.execute(
        select(PurchasePlan)
        .where(and_(PurchasePlan.customer_id == customer_id, PurchasePlan.plan_month == plan_month))
        .with_for_update()
    )
    existing_plan = existing.scalar_one_or_none()
    if existing_plan:
        return existing_plan
    for _attempt in range(3):
        plan_no = await _generate_plan_no()
        try:
            async with db.begin_nested():
                plan = PurchasePlan(plan_no=plan_no, plan_month=plan_month, customer_id=customer_id, customer_name=customer_name, status='pending', upload_batch=batch_id, created_by=created_by)
                db.add(plan)
                await db.flush()
            return plan
        except IntegrityError as e:
            err_msg = str(e.orig) if e.orig else str(e)
            # uq_ppl_month_customer: 并发 confirm_staging 已创建相同 (customer_id, plan_month) 主单
            # → 重试 SELECT 读取已存在的主单，避免重复创建
            if 'uq_ppl_month_customer' in err_msg or 'purchase_plans_customer_id_plan_month_key' in err_msg:
                re_fetch = await db.execute(  # batch-loop: 有意逐行处理,非 N+1
                    select(PurchasePlan)
                    .where(and_(PurchasePlan.customer_id == customer_id, PurchasePlan.plan_month == plan_month))
                )
                re_plan = re_fetch.scalar_one_or_none()
                if re_plan:
                    logger.info(f'_get_or_create_plan_for_group: 并发冲突，重用已存在主单 customer_id={customer_id} plan_month={plan_month}')
                    return re_plan
                # 极端情况：唯一索引未创建但 plan_no 冲突 → 走原重试逻辑
            # plan_no 唯一约束冲突 → 重试生成新编号
            if _attempt == 2:
                raise ValueError('单号生成冲突，请勿重复提交') from None
            logger.warning(f'confirm_staging: plan_no {plan_no} 冲突，重试({_attempt + 1}/3)')

    # 防御性兜底：循环内每个分支要么 return 要么 raise，此处**不可达**。
    # （原 docstring 的「N3 修复：删除循环末尾不可达的 raise」把它当作死代码删掉，
    #  但那样「第 3 次必 raise」就变成隐式约定 —— 一旦循环边界被改动，
    #  函数会静默返回 None，调用方拿到 None 而非 PurchasePlan。
    #  保留它既显式化不变式，也让 mypy 能确认返回契约成立。）
    raise ValueError('单号生成冲突，请勿重复提交')


def _create_details_for_group(
    db: AsyncSession,
    plan: PurchasePlan,
    group_records: list,
    name_to_product: dict,
) -> int:
    """为分组创建明细, 返回创建数量"""
    created = 0
    for record in group_records:
        product = name_to_product.get(record.product_name)
        detail = PurchasePlanDetail(plan_id=plan.id, product_id=product.id if product else 0, product_name=record.product_name, barcode='', plan_date=record.plan_date, quantity=record.quantity, shipped_qty=0, remark=record.remark or '')
        db.add(detail)
        created += 1
    return created


async def confirm_staging(db: AsyncSession, session_id: str, batch_id: str='', created_by: str='', selected_ids: list[int] | None=None) -> dict:
    """
    确认暂存数据，按客户分组创建主单+明细

    同一客户+同月份的记录归入同一个主单
    """
    conditions = [StagingPurchasePlan.session_id == session_id]
    if batch_id:
        conditions.append(StagingPurchasePlan.upload_batch_id == batch_id)
    result = await db.execute(select(StagingPurchasePlan).where(*conditions))
    records = result.scalars().all()
    if not records:
        raise ValueError('暂存区无数据')
    if selected_ids:
        records = [r for r in records if r.id in selected_ids]
    valid_records = [r for r in records if r.is_validated]
    if not valid_records:
        raise ValueError('所有数据验证未通过，无法保存')
    # 2026-09 修订：确认前不再校验库存，改为校验订单余量（与 validate_staging 同口径）
    no_order = await check_order_remaining(db, [{'customer_name': r.customer_name or '', 'product_name': r.product_name or ''} for r in valid_records])
    if no_order:
        raise ValueError(f'以下客户/产品没有订单余量，无法确认：{format_without_order_error(no_order)}')
    groups = _group_staging_records(valid_records)
    all_customers = await customer_service.get_active_customer_names(db)
    customer_id_map = {c['name']: c['id'] for c in all_customers}
    names = list({r.product_name for r in valid_records if r.product_name})
    product_result = await db.execute(select(Product).where(Product.name.in_(names)))
    name_to_product = {p.name: p for p in product_result.scalars().all()}
    created_plans = []
    created_details = 0
    for (customer_name, plan_month), group_records in groups.items():
        if not plan_month:
            continue
        customer_id = customer_id_map.get(customer_name)
        if not customer_id:
            continue
        plan = await _get_or_create_plan_for_group(db, customer_id, customer_name, plan_month, batch_id, created_by)
        created_details += _create_details_for_group(db, plan, group_records, name_to_product)
        created_plans.append({'plan_id': plan.id, 'plan_no': plan.plan_no})
    # 只删**本次真正确认**的行。原先用 *conditions（session_id [+ batch_id]）无条件删除，
    # 未勾选的行会被一并物理删除 → 部分确认时静默丢数据，与接口契约
    # 「仅确认选中的ID列表」不符。（无法建单的分组其行不会进 valid_records，予以保留。）
    confirmed_ids = [r.id for r in valid_records]
    await db.execute(delete(StagingPurchasePlan).where(StagingPurchasePlan.id.in_(confirmed_ids)))
    await db.flush()
    # 清除所有涉及月份的缓存（confirm_staging 可能跨多月），延迟到事务提交成功后执行
    affected_months = {pm for _, pm in groups if pm}

    async def _post_commit():
        for pm in affected_months:
            await _invalidate_plan_caches(pm)
    _schedule_post_commit(db, _post_commit)

    logger.info(f'暂存数据确认保存：{len(created_plans)}个主单，{created_details}条明细')
    return {'created_plans': created_plans, 'created_count': created_details, 'skipped_count': len(records) - len(valid_records)}

async def clear_staging(db: AsyncSession, session_id: str) -> None:
    """清空暂存区"""
    await db.execute(delete(StagingPurchasePlan).where(StagingPurchasePlan.session_id == session_id))
    await db.flush()

async def validate_barcode(db: AsyncSession, barcode: str) -> dict:
    """验证69码，返回关联的产品信息"""
    result = await db.execute(select(Product).where(Product.barcode == barcode))
    product = result.scalar_one_or_none()
    if not product:
        return {'valid': False, 'product_name': None, 'message': f"69码 '{barcode}' 未找到对应产品"}
    return {'valid': True, 'product_name': product.name, 'product_id': product.id, 'message': '验证通过'}
