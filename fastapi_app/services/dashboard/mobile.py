"""按授权范围聚合移动端看板。"""
import logging
from datetime import date, datetime

from sqlalchemy import extract, func, literal, select
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.business_time import (
    business_day_range,
    business_month_range,
    business_today,
)
from fastapi_app.core.cache import cache_result
from fastapi_app.core.float_utils import round_money
from fastapi_app.schemas.dashboard import (
    MobileDashboardData,
    MobileDashboardResponse,
    MobileDeptData,
    MobileOrderData,
    MobileProductionData,
    MobileShippingData,
    MobileStockData,
    MobileWarehouseData,
)
from fastapi_app.services.dashboard.scope import DashboardReadScope, dashboard_cache_key
from fastapi_app.shared_models import (
    Case,
    CaseMovement,
    DailyProductionRecord,
    Order,
    OrderItem,
    Product,
    PurchasePlan,
    PurchasePlanDetail,
    StockOut,
)

logger = logging.getLogger(__name__)


async def _load_stock_data(
    db: AsyncSession,
    today_start: datetime,
    today_end: datetime,
    month_start: datetime,
    stock_data: MobileStockData,
    shipping_data: MobileShippingData,
    scope: DashboardReadScope,
) -> None:
    """出库数据：合并当日/当月/总出库为单条 SUM FILTER 查询（3→1）。

    shipping_data 与 stock_data.today_* 查询完全相同，复用避免重复查询（1→0）。
    """
    try:
        price = Product.price if scope.amounts else literal(0)
        stock_stmt = (
            select(
                func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity).filter(
                    StockOut.stockout_date >= today_start, StockOut.stockout_date < today_end
                ), 0).label('today_qty'),
                func.coalesce(func.sum((StockOut.quantity - StockOut.returned_quantity) * price).filter(
                    StockOut.stockout_date >= today_start, StockOut.stockout_date < today_end
                ), 0).label('today_amt'),
                func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity).filter(
                    StockOut.stockout_date >= month_start
                ), 0).label('month_qty'),
                func.coalesce(func.sum((StockOut.quantity - StockOut.returned_quantity) * price).filter(
                    StockOut.stockout_date >= month_start
                ), 0).label('month_amt'),
                func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0).label('total_qty'),
                func.coalesce(func.sum((StockOut.quantity - StockOut.returned_quantity) * price), 0).label('total_amt'),
            )
            .join(Product, StockOut.product_id == Product.id, isouter=True)
        )
        if scope.factory:
            stock_stmt = stock_stmt.where(Product.factory == scope.factory)
        stock_row = (await db.execute(stock_stmt)).one()
        stock_data.today_quantity = int(stock_row.today_qty)
        stock_data.today_amount = round_money(float(stock_row.today_amt))
        stock_data.month_quantity = int(stock_row.month_qty)
        stock_data.month_amount = round_money(float(stock_row.month_amt))
        stock_data.total_quantity = int(stock_row.total_qty)
        stock_data.total_amount = round_money(float(stock_row.total_amt))
        # shipping_data 复用 stock 当日值
        # 业务等价性说明：移动看板中"出货"(shipping) 与"出库"(stock) 在当日维度指同一批
        # StockOut 记录（SUM(quantity) + SUM(quantity*price) WHERE stockout_date=today）。
        # 两者查询完全相同，复用避免重复查询（1→0）。
        # 注意：若未来 stock 模块增加额外过滤条件（如排除某类出库），
        # 需将 shipping 拆分为独立查询，否则 shipping 不会自动跟随变更。
        shipping_data.daily_qty = stock_data.today_quantity
        shipping_data.total_amount = stock_data.today_amount
    except (OperationalError, DisconnectionError):
        raise  # M-16 族：连接类异常交全局 503，不得吞成 0/空卡片
    except Exception as e:  # defensive: 移动看板单个数据卡片失败时继续加载其他卡片
        logger.warning("移动看板出库数据加载失败: %s", e)


async def _load_production_data(
    db: AsyncSession,
    today: date,
    scope: DashboardReadScope,
    production_data: MobileProductionData,
) -> None:
    """生产数据：指定日期各部门生产汇总（从 DailyProductionRecord 读取实际部门数据）。"""
    try:
        month_stmt = (
            select(
                DailyProductionRecord.department,
                func.coalesce(func.sum(DailyProductionRecord.quantity), 0),
                func.coalesce(func.sum(DailyProductionRecord.quantity * DailyProductionRecord.unit_price), 0),
            )
            .where(extract('year', DailyProductionRecord.production_date) == today.year)
            .where(extract('month', DailyProductionRecord.production_date) == today.month)
            .group_by(DailyProductionRecord.department)
        )
        if scope.departments is not None:
            month_stmt = month_stmt.where(DailyProductionRecord.department.in_(scope.departments))
        if scope.factory:
            month_stmt = month_stmt.join(Product, Product.id == DailyProductionRecord.product_id).where(
                Product.factory == scope.factory,
            )
        dpr_result = await db.execute(month_stmt.where(DailyProductionRecord.production_date == today))
        dept_map: dict[str, dict] = {}
        total_val = 0.0

        dept_name_map = {'filling': '充棉部', 'handcraft': '手工部', 'packaging': '包装部'}
        for row in dpr_result.all():
            dept_code = row[0] or 'other'
            dept = dept_name_map.get(dept_code, dept_code)
            qty = int(row[1] or 0)
            val = float(row[2] or 0)
            dept_map[dept] = {"name": dept, "daily_output": qty, "output_value": round_money(val)}
            total_val += val

        production_data.total_value = round_money(total_val)

        if not dept_map:
            # 当月兜底：当日无行时退到当月汇总。必须同样收窄到可见部门，
            # 否则单部门用户会从这里看到其他部门的月内数据。
            any_result = await db.execute(month_stmt.limit(3))
            for row in any_result.all():
                dept_code = row[0] or 'other'
                dept = dept_name_map.get(dept_code, dept_code)
                if dept not in dept_map:
                    qty = int(row[1] or 0)
                    val = float(row[2] or 0)
                    dept_map[dept] = {"name": dept, "daily_output": qty, "output_value": round_money(val)}
                    total_val += val
            production_data.total_value = round_money(total_val)

        for d in dept_map.values():
            d["output_value"] = round_money(d["output_value"])
            production_data.departments.append(MobileDeptData(**d))
        logger.info(f"生产数据加载完成: {len(production_data.departments)}个部门, 总值{production_data.total_value}")
    except (OperationalError, DisconnectionError):
        raise  # M-16 族：连接类异常交全局 503
    except Exception as e:  # defensive: 移动看板单个数据卡片失败时继续加载其他卡片
        logger.warning("移动看板生产数据加载失败: %s", e, exc_info=True)


async def _load_order_data(
    db: AsyncSession,
    today_start: datetime,
    today_end: datetime,
    order_data: MobileOrderData,
    scope: DashboardReadScope,
) -> None:
    """按订单明细聚合件数与金额；混厂订单只累计本厂明细。"""
    try:
        price = Product.price if scope.amounts else literal(0)
        order_stmt = (
            select(
                func.coalesce(func.sum(OrderItem.quantity).filter(
                    Order.order_date >= today_start, Order.order_date < today_end
                ), 0).label('daily_qty'),
                func.coalesce(func.sum(OrderItem.quantity * price).filter(
                    Order.order_date >= today_start, Order.order_date < today_end
                ), 0).label('daily_amt'),
                func.coalesce(func.sum(OrderItem.quantity), 0).label('total_qty'),
                func.coalesce(func.sum(OrderItem.quantity * price), 0).label('total_amt'),
            )
            .join(OrderItem, OrderItem.order_id == Order.id, isouter=True)
            .join(Product, OrderItem.product_id == Product.id, isouter=True)
            .where(Order.is_deleted.isnot(True))
        )
        if scope.factory:
            order_stmt = order_stmt.where(Product.factory == scope.factory)
        order_row = (await db.execute(order_stmt)).one()
        order_data.daily_qty = int(order_row.daily_qty)
        order_data.daily_amount = round_money(float(order_row.daily_amt))
        order_data.total_qty = int(order_row.total_qty)
        order_data.total_amount = round_money(float(order_row.total_amt))

    except (OperationalError, DisconnectionError):
        raise  # M-16 族：连接类异常交全局 503
    except Exception as e:  # defensive: 移动看板单个数据卡片失败时继续加载其他卡片
        logger.warning("移动看板订单数据加载失败: %s", e)


async def _load_inventory_data(db: AsyncSession, order_data: MobileOrderData, scope: DashboardReadScope) -> None:
    try:
        price = Product.price if scope.amounts else literal(0)
        stmt = select(
            func.coalesce(func.sum(Product.current_stock), 0).label('inv_qty'),
            func.coalesce(func.sum(Product.current_stock * price), 0).label('inv_amt'),
        )
        if scope.factory:
            stmt = stmt.where(Product.factory == scope.factory)
        inv_row = (await db.execute(stmt)).one()
        order_data.total_inventory = int(inv_row.inv_qty)
        order_data.total_inventory_amount = round_money(float(inv_row.inv_amt))
    except (OperationalError, DisconnectionError):
        raise
    except Exception:  # defensive: 单个数据卡片失败时继续加载其他卡片
        logger.warning("移动看板库存数据加载失败", exc_info=True)


async def _load_warehouse_data(
    db: AsyncSession,
    today_start: datetime,
    today_end: datetime,
    warehouse_data: MobileWarehouseData,
    scope: DashboardReadScope,
) -> None:
    """皮套仓储入库、出库数量及金额。"""
    try:
        price = Product.price if scope.amounts else literal(0)
        stmt = (
            select(
                func.coalesce(func.sum(CaseMovement.quantity), 0).label('qty'),
                func.coalesce(func.sum(CaseMovement.quantity * price), 0).label('amt'),
            )
            .join(Case, CaseMovement.case_id == Case.id)
            .outerjoin(Product, Case.product_id == Product.id)
            .where(CaseMovement.movement_date >= today_start, CaseMovement.movement_date < today_end)
        )
        if scope.factory:
            stmt = stmt.where(Product.factory == scope.factory)
        csi_row = (await db.execute(stmt.where(CaseMovement.direction == 'in'))).one()
        warehouse_data.in_qty = int(csi_row.qty)
        warehouse_data.in_amount = round_money(float(csi_row.amt))
        cso_row = (await db.execute(stmt.where(CaseMovement.direction == 'out'))).one()
        warehouse_data.out_qty = int(cso_row.qty)
        warehouse_data.out_amount = round_money(float(cso_row.amt))
    except (OperationalError, DisconnectionError):
        raise  # M-16 族：连接类异常交全局 503
    except Exception as e:  # defensive: 移动看板单个数据卡片失败时继续加载其他卡片
        logger.warning("移动看板仓储数据加载失败: %s", e)


async def _load_plans_data(db: AsyncSession, plans_data: dict[str, object], factory: str) -> None:
    """生产计划数据：从 purchase_plan_details 读取当月的生产计划明细与汇总。"""
    try:
        # 2026-10-17 审计 AUD-23：当月口径同样取业务时区（此前 datetime.now()
        # 取服务器本地时区，是 dashboard 内第二处不同源）。
        today = business_today()
        year = today.year
        month = today.month

        # 直接从 purchase_plan_details 表获取生产计划数据
        logger.info(f"从 purchase_plan_details 读取生产计划: year={year}, month={month}")
        stmt = (
            select(
                PurchasePlanDetail.id,
                PurchasePlan.customer_name,
                PurchasePlanDetail.product_name,
                PurchasePlanDetail.barcode,
                PurchasePlanDetail.quantity,
                PurchasePlanDetail.shipped_qty,
                PurchasePlanDetail.plan_date,
                PurchasePlanDetail.remark,
            )
            .join(PurchasePlan, PurchasePlanDetail.plan_id == PurchasePlan.id)
            .where(
                extract('year', PurchasePlanDetail.plan_date) == year,
                extract('month', PurchasePlanDetail.plan_date) == month,
            )
            .order_by(PurchasePlanDetail.plan_date, PurchasePlan.customer_name)
        )
        if factory:
            stmt = stmt.join(Product, Product.id == PurchasePlanDetail.product_id).where(Product.factory == factory)
        rows = (await db.execute(stmt)).all()
        logger.info(f"purchase_plan_details 查询返回 {len(rows)} 条")
        item_list = []
        total_plan_qty = 0
        total_shipped_qty = 0
        for ppd_row in rows:
            qty = int(ppd_row.quantity or 0)
            shipped = int(ppd_row.shipped_qty or 0)
            total_plan_qty += qty
            total_shipped_qty += shipped
            plan_date_str = ppd_row.plan_date.isoformat() if ppd_row.plan_date else ""
            logger.info(f"  详情: customer={ppd_row.customer_name}, product={ppd_row.product_name}, qty={qty}, date={plan_date_str}")
            item_list.append({
                "id": ppd_row.id,
                "customer_name": ppd_row.customer_name or "",
                "product_name": ppd_row.product_name or "",
                "barcode": ppd_row.barcode or "",
                "quantity": qty,
                "inventory_qty": 0,
                "shipped_qty": shipped,
                "remaining_qty": qty - shipped,
                "diff": qty,
                "stock_status": "warning",
                "shipment_status": "pending" if shipped == 0 else ("completed" if shipped >= qty else "partial"),
                "plan_date": plan_date_str,
                "status": "pending",
                "remark": ppd_row.remark or "",
            })
        plans_data["plans"] = item_list
        plans_data["monthly_summary"] = {
            "total_plan_qty": total_plan_qty,
            "total_inventory_qty": 0,
            "total_shipped_qty": total_shipped_qty,
            "total_remaining_qty": total_plan_qty - total_shipped_qty,
            "total_diff": total_plan_qty,
            "warning_count": len(item_list),
            "customer_summary": {},
        }
        logger.info(f"生产计划数据准备完成: {len(item_list)} 条")
    except (OperationalError, DisconnectionError):
        raise  # M-16 族：连接类异常交全局 503
    except Exception as e:  # defensive: 移动看板单个数据卡片失败时继续加载其他卡片
        logger.warning("移动看板生产计划数据加载失败", exc_info=True)
        if hasattr(e, '__cause__') and e.__cause__:
            logger.warning(f"  原因: {e.__cause__}")


@cache_result(key_prefix="dashboard:mobile", ttl=30, local_ttl=30, key_builder=dashboard_cache_key)
async def fetch_mobile_dashboard(query_date: str | None, db: AsyncSession, scope: DashboardReadScope) -> dict:
    """只查询获准的数据来源；其他板块保留响应结构及默认值。"""
    if query_date:
        try:
            selected_date = datetime.strptime(query_date, "%Y-%m-%d").date()
        except ValueError:
            selected_date = business_today()
    else:
        selected_date = business_today()

    # 2026-10-17 审计 AUD-23：与桌面端统一用业务时区日界（此前用服务器本地
    # date.today()，与桌面端 UTC 日界分叉）。
    today = selected_date
    today_start, today_end = business_day_range(today)
    month_start, _ = business_month_range(selected_date)

    stock_data = MobileStockData()
    production_data = MobileProductionData()
    shipping_data = MobileShippingData()
    order_data = MobileOrderData()
    warehouse_data = MobileWarehouseData()
    # 6. 生产计划数据（失败时保持默认空结构）
    plans_data: dict[str, object] = {"plans": [], "monthly_summary": None}

    if scope.stockout:
        await _load_stock_data(db, today_start, today_end, month_start, stock_data, shipping_data, scope)
    if scope.departments != ():
        await _load_production_data(db, today, scope, production_data)
    if scope.orders:
        await _load_order_data(db, today_start, today_end, order_data, scope)
    if scope.inventory:
        await _load_inventory_data(db, order_data, scope)
    if scope.warehouse:
        await _load_warehouse_data(db, today_start, today_end, warehouse_data, scope)
    if scope.plans:
        await _load_plans_data(db, plans_data, scope.factory)

    return MobileDashboardResponse(
        success=True,
        data=MobileDashboardData(
            stock=stock_data,
            production=production_data,
            shipping=shipping_data,
            orders=order_data,
            warehouse=warehouse_data,
            production_plans=plans_data,
        )
    ).model_dump()
