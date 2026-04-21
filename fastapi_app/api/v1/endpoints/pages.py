"""
FastAPI 页面路由（替代 Flask 页面渲染）

所有页面路由的统一入口，替代 Flask Blueprint 的 render_template() 功能。
每个路由负责：认证检查 → 数据准备 → 模板渲染。
"""

import logging
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.concurrency import run_in_threadpool

from fastapi_app.core.templates import templates
from fastapi_app.core.deps import get_current_user_id
from fastapi_app.core.nav_context import get_nav_sections

logger = logging.getLogger(__name__)

router = APIRouter()


async def _page_context(request: Request, user_id: int = None, db=None) -> dict:
    """构建页面模板的通用上下文变量"""
    from fastapi_app.core.database import SyncSessionLocal
    from fastapi_app.shared_models import User
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    # 导航数据可能涉及 sync DB 查询（缓存未命中时），放到线程池执行
    nav_sections = await run_in_threadpool(get_nav_sections)

    ctx = {
        "request": request,
        "nav_sections": nav_sections,
        "current_path": request.url.path,
        "ASSET_VERSION": "2.5",
        "user_id": None,
        "username": "",
        "is_super": False,
        "permissions": [],
    }

    if user_id:
        own_db = db is None
        if own_db:
            db = SyncSessionLocal()

        def _fetch_user_info(db=db):
            try:
                result = db.execute(
                    select(User)
                    .options(selectinload(User.permissions))
                    .where(User.id == user_id)
                )
                user = result.unique().scalar_one_or_none()
                if user and user.status:
                    return {
                        "user_id": user.id,
                        "username": user.username,
                        "is_super": user.is_super,
                        "permissions": [p.code for p in user.permissions] if user.permissions else [],
                    }
            finally:
                if own_db:
                    db.close()
            return None

        user_info = await run_in_threadpool(_fetch_user_info)
        if user_info:
            ctx.update(user_info)
            ctx["user_permissions"] = user_info.get("permissions", [])

    return ctx


# ==================== 登录页 ====================

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """登录页面"""
    # 如果已登录，重定向到首页
    try:
        user_id = await get_current_user_id(request)
        if user_id:
            return RedirectResponse(url="/", status_code=303)
    except HTTPException:
        pass

    ctx = await _page_context(request)
    return templates.TemplateResponse(request, "login.html", ctx)


# ==================== 首页/仪表盘 ====================

@router.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    """首页仪表盘（统计数据缓存5分钟，活动数据实时查询）"""
    # 页面路由：未登录时重定向到登录页，而非返回 401 JSON
    try:
        user_id = await get_current_user_id(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=303)

    from fastapi_app.core.database import SyncSessionLocal
    from fastapi_app.shared_models import Order, StockIn, StockOut, ApprovalRequest, Product, PurchaseOrder
    from sqlalchemy import select, func, and_
    from datetime import date, timedelta
    import json

    db = SyncSessionLocal()
    try:
        ctx = await _page_context(request, user_id, db=db)
        ctx["is_home"] = True

        # 统计数据使用 Redis 缓存（TTL 5分钟），减少首页 DB 查询
        _CACHE_KEY = "dashboard:stats"
        _CACHE_TTL = 300  # 5 minutes

        def _get_cached_stats():
            try:
                from utils.redis_cache import redis_cache
                cached = redis_cache.get(_CACHE_KEY)
                if cached:
                    return json.loads(cached)
            except Exception:
                pass
            return None

        def _set_cached_stats(data):
            try:
                from utils.redis_cache import redis_cache
                redis_cache.set(_CACHE_KEY, json.dumps(data, default=str), timeout=_CACHE_TTL)
            except Exception:
                pass

        dashboard_stats = await run_in_threadpool(_get_cached_stats)

        if dashboard_stats is None:
            def _fetch_stats(db=db):
                try:
                    today = date.today()
                    yesterday = today - timedelta(days=1)

                    data = {}
                    data["order_today"] = db.query(func.count(Order.id)).filter(Order.order_date >= today).scalar() or 0
                    data["stockin_today"] = db.query(func.count(StockIn.id)).filter(StockIn.stockin_date >= today).scalar() or 0
                    data["stockout_today"] = db.query(func.count(StockOut.id)).filter(StockOut.stockout_date >= today).scalar() or 0
                    data["pending_approvals"] = db.query(func.count(ApprovalRequest.id)).filter(ApprovalRequest.status == "pending").scalar() or 0

                    data["order_yesterday"] = db.query(func.count(Order.id)).filter(
                        and_(Order.order_date >= yesterday, Order.order_date < today)).scalar() or 0
                    data["stockin_yesterday"] = db.query(func.count(StockIn.id)).filter(
                        and_(StockIn.stockin_date >= yesterday, StockIn.stockin_date < today)).scalar() or 0
                    data["stockout_yesterday"] = db.query(func.count(StockOut.id)).filter(
                        and_(StockOut.stockout_date >= yesterday, StockOut.stockout_date < today)).scalar() or 0

                    data["low_stock_count"] = db.query(func.count(Product.id)).filter(Product.current_stock <= 10).scalar() or 0
                    data["pending_purchases"] = db.query(func.count(PurchaseOrder.id)).filter(
                        PurchaseOrder.status.in_(["pending", "partial"])).scalar() or 0

                    data["pending_materials"] = 0  # TODO: 来料待接收统计待接入
                    return data
                except Exception as e:
                    logger.warning("首页统计加载失败: %s [%s]", e, type(e).__name__)
                    return dict(order_today=0, stockin_today=0, stockout_today=0, pending_approvals=0,
                                order_yesterday=0, stockin_yesterday=0, stockout_yesterday=0,
                                low_stock_count=0, pending_purchases=0, pending_materials=0)

            dashboard_stats = await run_in_threadpool(_fetch_stats)
            await run_in_threadpool(_set_cached_stats, dashboard_stats)

        # 活动数据实时查询（数据量小，不缓存）
        def _fetch_activities(db=db):
            try:
                recent_orders = db.query(Order).order_by(Order.order_date.desc()).limit(4).all()
                recent_stockins = db.query(StockIn).order_by(StockIn.stockin_date.desc()).limit(3).all()
                recent_stockouts = db.query(StockOut).order_by(StockOut.stockout_date.desc()).limit(3).all()
                recent_approvals = db.query(ApprovalRequest).order_by(ApprovalRequest.request_time.desc()).limit(3).all()

                activities = []
                for o in recent_orders:
                    activities.append({"type": "order", "time": str(o.order_date) if o.order_date else "",
                                       "status": o.status or "", "title": f"订单 {o.order_no}", "desc": f"订单 {o.order_no}"})
                for s in recent_stockins:
                    activities.append({"type": "stockin", "time": str(s.stockin_date) if s.stockin_date else "",
                                       "status": "已备货", "title": f"入库 {s.stockin_no}", "desc": f"入库 {s.stockin_no}"})
                for s in recent_stockouts:
                    activities.append({"type": "stockout", "time": str(s.stockout_date) if s.stockout_date else "",
                                       "status": "已出货", "title": f"出库 {s.stockout_no}", "desc": f"出库 {s.stockout_no}"})
                for a in recent_approvals:
                    activities.append({"type": "approval", "time": str(a.request_time) if a.request_time else "",
                                       "status": a.status or "待审批", "title": "审批请求", "desc": "审批请求"})

                activities.sort(key=lambda x: x["time"], reverse=True)
                return activities[:8]
            except Exception as e:
                logger.warning("首页活动加载失败: %s [%s]", e, type(e).__name__)
                return []

        activities = await run_in_threadpool(_fetch_activities)
        dashboard_stats["activities"] = activities

        ctx.update(dashboard_stats)
        ctx["today"] = date.today()
        ctx["timedelta"] = timedelta

        return templates.TemplateResponse(request, "index.html", ctx)
    finally:
        db.close()


# ==================== 纯页面壳（数据由 API 加载） ====================

async def _require_login(request: Request) -> int:
    """页面路由认证守卫：未登录时抛出 303 重定向异常，已登录返回 user_id

    作为 Depends 使用：抛出 HTTPException 时 FastAPI 会短路跳过端点函数。
    全局异常处理器会将 303 + Location 头转为真正的 RedirectResponse。
    """
    try:
        return await get_current_user_id(request)
    except HTTPException:
        raise HTTPException(status_code=303, headers={"Location": "/login"})


async def _shell_page(template_name: str, request: Request, user_id: int, extra_ctx: dict = None):
    """渲染纯页面壳（无服务端数据，所有数据由前端 API 加载）"""
    ctx = await _page_context(request, user_id)
    if extra_ctx:
        ctx.update(extra_ctx)
    return templates.TemplateResponse(request, template_name, ctx)


@router.get("/order/list", response_class=HTMLResponse)
async def order_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("order.html", request, user_id)

@router.get("/order/edit/{order_id}", response_class=HTMLResponse)
async def edit_order_page(request: Request, order_id: int, user_id=Depends(_require_login)):
    return await _shell_page("edit_order.html", request, user_id, {"order_id": order_id})

@router.get("/order/my-approvals", response_class=HTMLResponse)
async def my_approvals_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("my_approvals.html", request, user_id)

@router.get("/stock/stockins", response_class=HTMLResponse)
async def stockin_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("stockin.html", request, user_id)

@router.get("/stock/edit-stockin/{stockin_id}", response_class=HTMLResponse)
async def edit_stockin_page(request: Request, stockin_id: int, user_id=Depends(_require_login)):
    return await _shell_page("edit_stockin.html", request, user_id, {"stockin_id": stockin_id})

@router.get("/stock/stockouts", response_class=HTMLResponse)
async def stockout_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("stockout.html", request, user_id)

@router.get("/stock/edit-stockout/{stockout_id}", response_class=HTMLResponse)
async def edit_stockout_page(request: Request, stockout_id: int, user_id=Depends(_require_login)):
    return await _shell_page("edit_stockout.html", request, user_id, {"stockout_id": stockout_id})

@router.get("/stock/inventory", response_class=HTMLResponse)
async def inventory_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("inventory.html", request, user_id)

@router.get("/product/list", response_class=HTMLResponse)
async def product_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("product.html", request, user_id)

@router.get("/product/edit/{product_id}", response_class=HTMLResponse)
async def edit_product_page(request: Request, product_id: int, user_id=Depends(_require_login)):
    return await _shell_page("edit_product.html", request, user_id, {"product_id": product_id})

@router.get("/customer/list", response_class=HTMLResponse)
async def customer_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("customer.html", request, user_id)

@router.get("/customer/edit/{customer_id}", response_class=HTMLResponse)
async def edit_customer_page(request: Request, customer_id: int, user_id=Depends(_require_login)):
    return await _shell_page("edit_customer.html", request, user_id, {"customer_id": customer_id})

@router.get("/customer-order/", response_class=HTMLResponse)
async def customer_order_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("customer_order.html", request, user_id)

@router.get("/supplier/list", response_class=HTMLResponse)
async def supplier_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("supplier.html", request, user_id)

@router.get("/supplier/edit/{supplier_id}", response_class=HTMLResponse)
async def edit_supplier_page(request: Request, supplier_id: int, user_id=Depends(_require_login)):
    return await _shell_page("edit_supplier.html", request, user_id, {"supplier_id": supplier_id})

@router.get("/user/list", response_class=HTMLResponse)
async def user_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("user.html", request, user_id)

@router.get("/user/edit/{edit_user_id}", response_class=HTMLResponse)
async def edit_user_page(request: Request, edit_user_id: int, user_id=Depends(_require_login)):
    return await _shell_page("edit_user.html", request, user_id, {"edit_user_id": edit_user_id})

@router.get("/permission/list", response_class=HTMLResponse)
async def permission_page(request: Request, target_user_id: int = Query(None), _uid=Depends(_require_login)):
    """权限设置页面 — 需要 user 对象和权限列表"""
    from fastapi_app.core.database import SyncSessionLocal
    from fastapi_app.shared_models import User, Permission
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    db = SyncSessionLocal()
    try:
        ctx = await _page_context(request, _uid, db=db)

        def _fetch_data(db=db, tid=target_user_id):
            target_user = None
            user_permission_ids = []
            if tid:
                result = db.execute(
                    select(User).options(selectinload(User.permissions)).where(User.id == tid)
                )
                target_user = result.unique().scalar_one_or_none()
                if target_user:
                    user_permission_ids = [p.id for p in target_user.permissions]

            all_perms = db.execute(select(Permission).where(Permission.parent_id.is_(None)).order_by(Permission.sort_order)).scalars().all()
            return target_user, user_permission_ids, all_perms

        target_user, user_permission_ids, all_perms = await run_in_threadpool(_fetch_data)
        ctx["user"] = target_user
        ctx["user_permission_ids"] = user_permission_ids
        ctx["permissions"] = all_perms
        return templates.TemplateResponse(request, "permission.html", ctx)
    finally:
        db.close()

@router.get("/approval/list", response_class=HTMLResponse)
async def approval_list_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("approval_list.html", request, user_id)

@router.get("/approval/detail/{approval_id}", response_class=HTMLResponse)
async def approval_detail_page(request: Request, approval_id: int, user_id=Depends(_require_login)):
    return await _shell_page("approval_detail.html", request, user_id, {"approval_id": approval_id})

@router.get("/finance/statistics", response_class=HTMLResponse)
async def finance_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("finance.html", request, user_id)

@router.get("/report/reports", response_class=HTMLResponse)
async def report_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("reports.html", request, user_id)

@router.get("/material/calculator", response_class=HTMLResponse)
async def material_calculator_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("material_calculator.html", request, user_id)

@router.get("/material-registration/page", response_class=HTMLResponse)
async def material_registration_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("material_registration.html", request, user_id)

@router.get("/material/orders", response_class=HTMLResponse)
async def purchase_orders_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("purchase_orders.html", request, user_id)

@router.get("/material/orders/{order_id}", response_class=HTMLResponse)
async def purchase_order_detail_page(request: Request, order_id: int, user_id=Depends(_require_login)):
    return await _shell_page("purchase_order_detail.html", request, user_id, {"order_id": order_id})

@router.get("/purchase-center/", response_class=HTMLResponse)
async def purchase_center_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("purchase_center.html", request, user_id)

@router.get("/plans/list", response_class=HTMLResponse)
async def purchase_plan_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("purchase_plan_new.html", request, user_id)

@router.get("/production-plan/list", response_class=HTMLResponse)
async def production_plan_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("production_plan.html", request, user_id)

@router.get("/production-summary/list", response_class=HTMLResponse)
async def production_summary_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("production_summary.html", request, user_id)

@router.get("/case/", response_class=HTMLResponse)
async def case_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("case.html", request, user_id)

@router.get("/case/out", response_class=HTMLResponse)
async def case_out_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("case_out.html", request, user_id)

@router.get("/case/inventory", response_class=HTMLResponse)
async def case_inventory_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("case_inventory.html", request, user_id)

@router.get("/batch/management", response_class=HTMLResponse)
async def batch_management_page(request: Request, user_id=Depends(_require_login)):
    return await _shell_page("batch_management.html", request, user_id)
