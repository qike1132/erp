"""
采购计划主单与明细 CRUD 操作

职责：采购计划主单的创建、更新、删除、明细增删改，以及相关的
    数据校验（_validate_plan_month / _validate_details_cross_month /
     _validate_products_exist / _validate_order_remaining）、
    主单持久化（含编号冲突重试 _persist_plan_with_retry）。

从 purchase_plan_crud.py 拆分而来，保持函数签名不变。
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.notification_service import StockEvent, publish_stock_event
from fastapi_app.services.plan_utils import normalize_plan_date
from fastapi_app.services.purchase_plan_common import (
    _generate_plan_no,
    _invalidate_plan_caches,
    _log_action,
    _schedule_post_commit,
    logger,
)
from fastapi_app.services.purchase_plan_order_quota import (
    check_order_remaining,
    format_without_order_error,
)
from fastapi_app.shared_models import (
    Customer,
    Product,
    PurchasePlan,
    PurchasePlanDetail,
)


class PlanExistsError(ValueError):
    """该客户当月已存在采购计划（uq_ppl_month_customer 唯一约束冲突）"""


def _validate_plan_month(plan_month: str) -> tuple[int, int]:
    """验证并解析计划月份格式，返回(year, month)"""
    ym_parts = plan_month.split('-')
    if len(ym_parts) != 2:
        raise ValueError(f'月份格式不正确: {plan_month}，请使用 YYYY-MM 格式')
    return int(ym_parts[0]), int(ym_parts[1])


def _validate_details_cross_month(details: list[dict], target_year: int, target_month: int, plan_month: str) -> None:
    """验证明细日期不跨月"""
    for d in details:
        plan_date_val = normalize_plan_date(d['plan_date'])
        if plan_date_val.year != target_year or plan_date_val.month != target_month:
            raise ValueError(f"计划日期 {d['plan_date']} 与计划月份 {plan_month} 不一致，不允许跨月")


async def _validate_products_exist(db: AsyncSession, details: list[dict]) -> None:
    """验证明细中产品（barcode/product_name）均存在"""
    barcodes_to_check = list({d.get('barcode', '') for d in details if d.get('barcode')})
    if barcodes_to_check:
        result = await db.execute(select(Product.barcode).where(Product.barcode.in_(barcodes_to_check)))
        existing = {row[0] for row in result.all()}
        for d in details:
            barcode = d.get('barcode', '')
            if barcode and barcode not in existing:
                raise ValueError(f"69码 '{barcode}' 未找到对应产品")
    names_to_check = list({d.get('product_name', '') for d in details if not d.get('barcode') and d.get('product_name')})
    if names_to_check:
        result = await db.execute(select(Product.name).where(Product.name.in_(names_to_check)))
        existing = {row[0] for row in result.all()}
        for d in details:
            pname = d.get('product_name', '')
            if not d.get('barcode') and pname and pname not in existing:
                raise ValueError(f"产品 '{pname}' 未找到对应记录")


async def _validate_order_remaining(db: AsyncSession, customer_name: str, details: list[dict], action: str) -> None:
    """准入校验：明细必须对应「订单余量 > 0」的客户+产品

    取代原库存校验（2026-09 用户裁决）：库存是备货进度，不是「能不能排产」
    的准入条件；只要该客户该产品还有未发完的订单数量就允许添加计划。
    明细只带产品名，客户名由主单维度传入。

    Args:
        db: 异步数据库会话。
        customer_name: 计划所属客户名。
        details: 明细列表，需含 product_name 键。
        action: 错误文案中的动作词，如「无法创建出货计划」。

    Raises:
        ValueError: 存在无订单余量的明细时，文案列出全部客户/产品组合。
    """
    items = [{'customer_name': customer_name, 'product_name': d.get('product_name', '')} for d in details]
    missing = await check_order_remaining(db, items)
    if missing:
        raise ValueError(f'以下客户/产品没有订单余量，{action}：{format_without_order_error(missing)}')


async def _persist_plan_with_retry(db: AsyncSession, *, customer_id: int, customer_name: str, plan_month: str, remark: str, upload_batch: str, created_by: str) -> PurchasePlan:
    """创建主单记录，含编号冲突重试（最多3次）

    IntegrityError 区分两类冲突：
        - uq_ppl_month_customer：该客户当月已有计划，重试无意义 → 抛 PlanExistsError
        - plan_no 唯一冲突：编号生成竞态 → 重试生成新编号
    """
    for attempt in range(3):
        plan_no = await _generate_plan_no()
        try:
            async with db.begin_nested():
                plan = PurchasePlan(plan_no=plan_no, plan_month=plan_month, customer_id=customer_id, customer_name=customer_name, status='pending', remark=remark, upload_batch=upload_batch, created_by=created_by)
                db.add(plan)
                await db.flush()
            return plan
        except IntegrityError as e:
            err_msg = str(e.orig) if e.orig else str(e)
            # uq_ppl_month_customer 唯一约束：重试新 plan_no 仍会失败，直接终止
            if 'uq_ppl_month_customer' in err_msg or 'purchase_plans_customer_id_plan_month_key' in err_msg:
                raise PlanExistsError(f'该客户当月已存在采购计划：customer_id={customer_id} plan_month={plan_month}') from None
            # plan_no 唯一冲突 → 重试生成新编号
            if attempt == 2:
                raise ValueError('单号生成冲突，请勿重复提交') from None
            logger.warning(f'plan_no {plan_no} 冲突，重试({attempt + 1}/3)')

    # 防御性兜底：循环内每个分支要么 return 要么 raise，此处**不可达**。
    # 保留它的理由是把「第 3 次必 raise」这一隐式不变式显式化 ——
    # 否则若将来有人改动循环边界（如 range(3) → range(4)）或删掉 attempt==2 分支，
    # 函数会**静默返回 None**，调用方 `plan.id` 抛 AttributeError，极难定位。
    # （mypy 的 `return` 检查也依赖它才能确认返回契约成立。）
    raise ValueError('单号生成冲突，请勿重复提交')


async def create_plan(db: AsyncSession, *, customer_id: int, customer_name: str, plan_month: str, details: list[dict], remark: str='', created_by: str='', upload_batch: str='') -> dict:
    """
    创建采购计划主单 + 明细

    details 格式: [{'product_id': int, 'product_name': str, 'barcode': str,
                     'quantity': int, 'plan_date': str, 'remark': str}]
    """
    customer = await db.execute(select(Customer).where(Customer.id == customer_id))
    if not customer.scalar_one_or_none():
        raise ValueError(f'客户ID {customer_id} 不存在')
    target_year, target_month = _validate_plan_month(plan_month)
    _validate_details_cross_month(details, target_year, target_month, plan_month)
    await _validate_products_exist(db, details)
    await _validate_order_remaining(db, customer_name, details, '无法创建出货计划')
    plan = await _persist_plan_with_retry(db, customer_id=customer_id, customer_name=customer_name, plan_month=plan_month, remark=remark, upload_batch=upload_batch, created_by=created_by)
    for d in details:
        plan_date_val = normalize_plan_date(d['plan_date'])
        detail = PurchasePlanDetail(plan_id=plan.id, product_id=d['product_id'], product_name=d['product_name'], barcode=d['barcode'], plan_date=plan_date_val, quantity=d['quantity'], shipped_qty=0, remark=d.get('remark', ''))
        db.add(detail)
    await _log_action(db, plan.id, 'create', None, plan.to_dict(), created_by)
    await db.flush()

    async def _post_commit():
        await _invalidate_plan_caches(plan_month)
        await publish_stock_event(StockEvent.SHIPMENT_PLAN_UPLOADED, {'plan_id': plan.id, 'plan_no': plan.plan_no, 'customer_name': customer_name, 'detail_count': len(details)})
    _schedule_post_commit(db, _post_commit)

    logger.info(f'采购计划创建成功：{plan.plan_no} - {customer_name} - {len(details)}条明细')
    return {'plan_id': plan.id, 'plan_no': plan.plan_no}

async def update_plan(db: AsyncSession, plan_id: int, *, created_by: str='', **kwargs) -> dict:
    """更新采购计划主单信息（状态、备注等）"""
    result = await db.execute(select(PurchasePlan).where(PurchasePlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise ValueError('采购计划不存在')
    old_data = plan.to_dict()
    for field in ('status', 'remark'):
        if field in kwargs and kwargs[field] is not None:
            setattr(plan, field, kwargs[field])
    await db.flush()
    await _log_action(db, plan.id, 'update', old_data, plan.to_dict(), created_by)
    await db.flush()

    async def _post_commit():
        await _invalidate_plan_caches(plan.plan_month)
        await publish_stock_event(StockEvent.SHIPMENT_PLAN_UPLOADED, {'plan_id': plan.id, 'operation': 'update'})
    _schedule_post_commit(db, _post_commit)

    return plan.to_dict()

async def delete_plan(db: AsyncSession, plan_id: int, *, operator: str='') -> None:
    """删除采购计划主单及明细"""
    result = await db.execute(select(PurchasePlan).where(PurchasePlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise ValueError('采购计划不存在')
    old_data = plan.to_dict()
    plan_month = plan.plan_month
    await db.delete(plan)
    await _log_action(db, plan.id, 'delete', old_data, None, operator)
    await db.flush()

    async def _post_commit():
        await _invalidate_plan_caches(plan_month)
        await publish_stock_event(StockEvent.STOCK_CHANGED, {'plan_id': plan_id, 'operation': 'delete', 'customer_name': old_data.get('customer_name', '')})
    _schedule_post_commit(db, _post_commit)

    logger.info(f'采购计划删除成功：ID={plan_id}')

async def update_detail(db: AsyncSession, detail_id: int, *, created_by: str='', **kwargs) -> dict:
    """更新单条明细

    2026-09 修订：数量增加不再校验库存，改为校验「订单余量 > 0」
    （与 create_plan / add_details 同一准入口径）。
    """
    result = await db.execute(select(PurchasePlanDetail).where(PurchasePlanDetail.id == detail_id))
    detail = result.scalar_one_or_none()
    if not detail:
        raise ValueError('明细记录不存在')
    # 获取 plan_month（用于缓存清除）与 customer_name（用于订单余量校验）
    plan_result = await db.execute(select(PurchasePlan.plan_month, PurchasePlan.customer_name).where(PurchasePlan.id == detail.plan_id))
    plan_month_row = plan_result.first()

    # 数量增加时仍需准入校验：该客户+该产品必须有订单余量
    new_quantity = kwargs.get('quantity')
    if new_quantity is not None and new_quantity > detail.quantity and plan_month_row:
        await _validate_order_remaining(db, plan_month_row[1], [{'product_name': detail.product_name}], '无法增加数量')

    for field in ('quantity', 'plan_date', 'remark'):
        if field in kwargs and kwargs[field] is not None:
            if field == 'plan_date':
                detail.plan_date = normalize_plan_date(kwargs[field])
            else:
                setattr(detail, field, kwargs[field])
    # 第八轮审计：create/add_details 都有跨月校验，update_detail 漏了 —— 改期到别的月时
    # 日历按 plan_month 取数、按 plan_date 落格，数字静默丢失/不一致。
    if detail.plan_date is not None and plan_month_row:
        expected = plan_month_row[0]  # 'YYYY-MM'
        y, m = (int(x) for x in expected.split('-'))
        if detail.plan_date.year != y or detail.plan_date.month != m:
            raise ValueError(
                f'计划日期 {detail.plan_date.isoformat()} 与计划月份 {expected} 不一致，不允许跨月'
            )
    await db.flush()

    async def _post_commit():
        if plan_month_row:
            await _invalidate_plan_caches(plan_month_row[0])
        await publish_stock_event(StockEvent.SHIPMENT_PLAN_UPLOADED, {'detail_id': detail_id, 'operation': 'update_detail'})
    _schedule_post_commit(db, _post_commit)

    return detail.to_dict()

async def delete_detail(db: AsyncSession, detail_id: int) -> None:
    """删除单条明细"""
    result = await db.execute(select(PurchasePlanDetail).where(PurchasePlanDetail.id == detail_id))
    detail = result.scalar_one_or_none()
    if not detail:
        raise ValueError('明细记录不存在')
    plan_result = await db.execute(select(PurchasePlan.plan_month).where(PurchasePlan.id == detail.plan_id))
    plan_month_row = plan_result.first()
    await db.delete(detail)
    await db.flush()

    async def _post_commit():
        if plan_month_row:
            await _invalidate_plan_caches(plan_month_row[0])
        await publish_stock_event(StockEvent.STOCK_CHANGED, {'detail_id': detail_id, 'operation': 'delete_detail'})
    _schedule_post_commit(db, _post_commit)

async def add_details(db: AsyncSession, plan_id: int, details: list[dict]) -> dict:
    """向主单追加明细

    2026-09 修订：不再校验库存，改为校验「订单余量 > 0」，
    与 create_plan 行为一致。
    """
    result = await db.execute(select(PurchasePlan).where(PurchasePlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise ValueError('采购计划不存在')
    ym_parts = plan.plan_month.split('-')
    target_year, target_month = (int(ym_parts[0]), int(ym_parts[1]))
    await _validate_products_exist(db, details)
    await _validate_order_remaining(db, plan.customer_name, details, '无法追加明细')
    added = 0
    for d in details:
        plan_date_val = normalize_plan_date(d['plan_date'])
        if plan_date_val.year != target_year or plan_date_val.month != target_month:
            raise ValueError(f"计划日期 {d['plan_date']} 与主单月份 {plan.plan_month} 不一致")
        detail = PurchasePlanDetail(plan_id=plan_id, product_id=d['product_id'], product_name=d['product_name'], barcode=d['barcode'], plan_date=plan_date_val, quantity=d['quantity'], shipped_qty=0, remark=d.get('remark', ''))
        db.add(detail)
        added += 1
    await db.flush()

    async def _post_commit():
        await _invalidate_plan_caches(plan.plan_month)
    _schedule_post_commit(db, _post_commit)

    return {'added_count': added}
