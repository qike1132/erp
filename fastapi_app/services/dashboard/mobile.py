"""移动端数据看板(单次聚合所有板块)

从 dashboard_service.py 按主题拆出,行为与原实现完全一致。
"""
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from fastapi_app.shared_models import (
    Case,
    CaseStockIn,
    CaseStockOut,
    DailyProductionRecord,
    Order,
    OrderItem,
    Product,
    PurchasePlan,
    PurchasePlanDetail,
    StockOut,
)

logger = logging.getLogger(__name__)


@cache_result(key_prefix="dashboard:mobile", ttl=30, local_ttl=30,
              key_builder=lambda **kwargs: f"d{kwargs.get('query_date', '')}")  # sql-safe: escape_like/绑定参数/常量片段
async def fetch_mobile_dashboard(
    query_date: str | None,
    db: AsyncSession,
    departments: set[str] | None = None,
) -> dict:
    """移动端数据看板（一次聚合所有板块数据）

    优化：合并 StockOut 当日/当月/总出库为 SUM FILTER（3→1）、shipping 复用 stock 当日值（1→0）、
    合并 Order 当日+总金额为 SUM FILTER（3→1）、合并库存数量+金额（2→1）、
    合并 CaseStockIn/Out 数量+金额（4→2）。总往返从 15~16 次降至 8~9 次。

    注：SQLAlchemy AsyncSession 不支持 asyncio.gather 并发（单连接非线程安全），
    使用 SQL 层 SUM FILTER 合并优于多 session 并发，避免连接池压力。

    返回 dict（model_dump）以兼容 cache_result 的 JSON 序列化。
    endpoint 层负责重新构造 MobileDashboardResponse。

    departments 为 None 时行为与改动前完全一致（生产卡片不加部门条件）；
    否则生产卡片只聚合给定部门，空集按"无可见部门"处理（in_([]) 恒假，fail-closed）。
    """
    if query_date:
        try:
            selected_date = datetime.strptime(query_date, "%Y-%m-%d").date()
        except ValueError:
            selected_date = date.today()
    else:
        selected_date = date.today()

    today = selected_date
    today_start = datetime(today.year, today.month, today.day, 0, 0, 0)
    tomorrow = today + timedelta(days=1)
    today_end = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0)

    stock_data = MobileStockData()
    production_data = MobileProductionData()
    shipping_data = MobileShippingData()
    order_data = MobileOrderData()
    warehouse_data = MobileWarehouseData()

    try:
        # 1. 出库数据：合并当日/当月/总出库为单条 SUM FILTER 查询（3→1）
        # shipping_data 与 stock_data.today_* 查询完全相同，复用避免重复查询（1→0）
        month_start = datetime(selected_date.year, selected_date.month, 1, 0, 0, 0)

        stock_row = (await db.execute(
            select(
                func.coalesce(func.sum(StockOut.quantity).filter(
                    StockOut.stockout_date >= today_start, StockOut.stockout_date < today_end
                ), 0).label('today_qty'),
                func.coalesce(func.sum(StockOut.quantity * Product.price).filter(
                    StockOut.stockout_date >= today_start, StockOut.stockout_date < today_end
                ), 0).label('today_amt'),
                func.coalesce(func.sum(StockOut.quantity).filter(
                    StockOut.stockout_date >= month_start
                ), 0).label('month_qty'),
                func.coalesce(func.sum(StockOut.quantity * Product.price).filter(
                    StockOut.stockout_date >= month_start
                ), 0).label('month_amt'),
                func.coalesce(func.sum(StockOut.quantity), 0).label('total_qty'),
                func.coalesce(func.sum(StockOut.quantity * Product.price), 0).label('total_amt'),
            )
            .join(Product, StockOut.product_id == Product.id, isouter=True)
        )).one()
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
    except Exception as e:  # defensive: 移动看板单个数据卡片失败时继续加载其他卡片
        logger.warning("移动看板出库数据加载失败: %s", e)

    try:
        # 2. 生产数据：指定日期各部门生产汇总（从DailyProductionRecord读取实际部门数据）
        dpr_stmt = (
            select(
                DailyProductionRecord.department,
                func.coalesce(func.sum(DailyProductionRecord.quantity), 0),
                func.coalesce(func.sum(DailyProductionRecord.quantity * DailyProductionRecord.unit_price), 0),
            )
            .where(extract('year', DailyProductionRecord.production_date) == today.year)
            .where(extract('month', DailyProductionRecord.production_date) == today.month)
            .where(extract('day', DailyProductionRecord.production_date) == today.day)
            .group_by(DailyProductionRecord.department)
        )
        if departments is not None:
            dpr_stmt = dpr_stmt.where(
                DailyProductionRecord.department.in_(sorted(departments))
            )
        dpr_result = await db.execute(dpr_stmt)
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
            any_stmt = (
                select(
                    DailyProductionRecord.department,
                    func.coalesce(func.sum(DailyProductionRecord.quantity), 0),
                    func.coalesce(func.sum(DailyProductionRecord.quantity * DailyProductionRecord.unit_price), 0),
                )
                .where(extract('year', DailyProductionRecord.production_date) == today.year)
                .where(extract('month', DailyProductionRecord.production_date) == today.month)
                .group_by(DailyProductionRecord.department)
                .limit(3)
            )
            if departments is not None:
                any_stmt = any_stmt.where(
                    DailyProductionRecord.department.in_(sorted(departments))
                )
            any_result = await db.execute(any_stmt)
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
    except Exception as e:  # defensive: 移动看板单个数据卡片失败时继续加载其他卡片
        logger.warning("移动看板生产数据加载失败: %s", e, exc_info=True)

    # 3. 出货数据：复用 stock_data.today_* 值（查询结构与 stock 当日完全相同，已在步骤 1 设置）

    try:
        # 4. 订单数据：合并当日+总订单件数+总金额为 SUM FILTER（3→1），合并库存数量+金额（2→1）
        # 全部基于 OrderItem 展开聚合，与 total_amount 的"件数×单价"语义保持一致：
        #   - total_qty = SUM(oi.quantity)   总订单商品件数（= 用户期望的"总订单数量"）
        #   - total_amt = SUM(oi.quantity * price)  总订单商品金额
        # 历史上 total_qty 误用 count(Order.id)（订单个数，21），与总额 8 千万量级明显不匹配；
        # 改为件数后与 daily_qty/daily_amount 维度一致，并与 total_amount 形成"件数×单价≈总额"。
        # COUNT(Order.id) 单独查询已废弃（行数膨胀 + 多一次 DB 往返）。
        order_row = (await db.execute(
            select(
                func.coalesce(func.sum(OrderItem.quantity).filter(
                    Order.order_date >= today_start, Order.order_date < today_end
                ), 0).label('daily_qty'),
                func.coalesce(func.sum(OrderItem.quantity * Product.price).filter(
                    Order.order_date >= today_start, Order.order_date < today_end
                ), 0).label('daily_amt'),
                func.coalesce(func.sum(OrderItem.quantity), 0).label('total_qty'),
                func.coalesce(func.sum(OrderItem.quantity * Product.price), 0).label('total_amt'),
            )
            .join(OrderItem, OrderItem.order_id == Order.id, isouter=True)
            .join(Product, OrderItem.product_id == Product.id, isouter=True)
            .where(Order.is_deleted.isnot(True))
        )).one()
        order_data.daily_qty = int(order_row.daily_qty)
        order_data.daily_amount = round_money(float(order_row.daily_amt))
        order_data.total_qty = int(order_row.total_qty)
        order_data.total_amount = round_money(float(order_row.total_amt))

        # 产品总库存数量 + 金额合并（2→1）
        inv_row = (await db.execute(
            select(
                func.coalesce(func.sum(Product.current_stock), 0).label('inv_qty'),
                func.coalesce(func.sum(Product.current_stock * Product.price), 0).label('inv_amt'),
            )
        )).one()
        order_data.total_inventory = int(inv_row.inv_qty)
        order_data.total_inventory_amount = round_money(float(inv_row.inv_amt))
    except Exception as e:  # defensive: 移动看板单个数据卡片失败时继续加载其他卡片
        logger.warning("移动看板订单数据加载失败: %s", e)

    try:
        # 5. 皮套仓储：合并 CaseStockIn 数量+金额（2→1）、CaseStockOut 数量+金额（2→1）
        csi_row = (await db.execute(
            select(
                func.coalesce(func.sum(CaseStockIn.quantity), 0).label('qty'),
                func.coalesce(func.sum(CaseStockIn.quantity * Product.price), 0).label('amt'),
            )
            .join(Case, CaseStockIn.case_id == Case.id)
            .join(Product, Case.product_id == Product.id, isouter=True)
            .where(CaseStockIn.stockin_date >= today_start)
            .where(CaseStockIn.stockin_date < today_end)
        )).one()
        warehouse_data.in_qty = int(csi_row.qty)
        warehouse_data.in_amount = round_money(float(csi_row.amt))

        cso_row = (await db.execute(
            select(
                func.coalesce(func.sum(CaseStockOut.quantity), 0).label('qty'),
                func.coalesce(func.sum(CaseStockOut.quantity * Product.price), 0).label('amt'),
            )
            .join(Case, CaseStockOut.case_id == Case.id)
            .join(Product, Case.product_id == Product.id, isouter=True)
            .where(CaseStockOut.stockout_date >= today_start)
            .where(CaseStockOut.stockout_date < today_end)
        )).one()
        warehouse_data.out_qty = int(cso_row.qty)
        warehouse_data.out_amount = round_money(float(cso_row.amt))
    except Exception as e:  # defensive: 移动看板单个数据卡片失败时继续加载其他卡片
        logger.warning("移动看板仓储数据加载失败: %s", e)

    # 6. 生产计划数据
    plans_data = {"plans": [], "monthly_summary": None}
    try:
        now = datetime.now()
        year = now.year
        month = now.month

        # 直接从 purchase_plan_details 表获取生产计划数据
        logger.info(f"从 purchase_plan_details 读取生产计划: year={year}, month={month}")
        ppd_result = await db.execute(
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
        rows = ppd_result.all()
        logger.info(f"purchase_plan_details 查询返回 {len(rows)} 条")
        item_list = []
        total_plan_qty = 0
        total_shipped_qty = 0
        for row in rows:
            qty = int(row.quantity or 0)
            shipped = int(row.shipped_qty or 0)
            total_plan_qty += qty
            total_shipped_qty += shipped
            plan_date_str = row.plan_date.isoformat() if row.plan_date else ""
            logger.info(f"  详情: customer={row.customer_name}, product={row.product_name}, qty={qty}, date={plan_date_str}")
            item_list.append({
                "id": row.id,
                "customer_name": row.customer_name or "",
                "product_name": row.product_name or "",
                "barcode": row.barcode or "",
                "quantity": qty,
                "inventory_qty": 0,
                "shipped_qty": shipped,
                "remaining_qty": qty - shipped,
                "diff": qty,
                "stock_status": "warning",
                "shipment_status": "pending" if shipped == 0 else ("completed" if shipped >= qty else "partial"),
                "plan_date": plan_date_str,
                "status": "pending",
                "remark": row.remark or "",
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
    except Exception as e:  # defensive: 移动看板单个数据卡片失败时继续加载其他卡片
        logger.warning("移动看板生产计划数据加载失败", exc_info=True)
        if hasattr(e, '__cause__') and e.__cause__:
            logger.warning(f"  原因: {e.__cause__}")

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
