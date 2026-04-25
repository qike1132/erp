"""
FastAPI 页面路由 — 全部重定向到 Next.js 前端

所有页面请求统一重定向到 Next.js 前端（端口 3000）。
"""

import logging
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_NEXTJS_URL = "http://localhost:3000"


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """登录页 → Next.js"""
    return RedirectResponse(url=f"{_NEXTJS_URL}/login", status_code=302)


@router.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    """首页仪表盘 → Next.js"""
    return RedirectResponse(url=_NEXTJS_URL, status_code=302)


@router.get("/order/list", response_class=HTMLResponse)
async def order_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/order/list", status_code=302)


@router.get("/order/edit/{order_id}", response_class=HTMLResponse)
async def edit_order_page(request: Request, order_id: int):
    return RedirectResponse(url=f"{_NEXTJS_URL}/order/edit/{order_id}", status_code=302)


@router.get("/order/my-approvals", response_class=HTMLResponse)
async def my_approvals_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/order/my-approvals", status_code=302)


@router.get("/stock/stockins", response_class=HTMLResponse)
async def stockin_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/stock/stockins", status_code=302)


@router.get("/stock/edit-stockin/{stockin_id}", response_class=HTMLResponse)
async def edit_stockin_page(request: Request, stockin_id: int):
    return RedirectResponse(url=f"{_NEXTJS_URL}/stock/edit-stockin/{stockin_id}", status_code=302)


@router.get("/stock/stockouts", response_class=HTMLResponse)
async def stockout_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/stock/stockouts", status_code=302)


@router.get("/stock/edit-stockout/{stockout_id}", response_class=HTMLResponse)
async def edit_stockout_page(request: Request, stockout_id: int):
    return RedirectResponse(url=f"{_NEXTJS_URL}/stock/edit-stockout/{stockout_id}", status_code=302)


@router.get("/stock/inventory", response_class=HTMLResponse)
async def inventory_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/stock/inventory", status_code=302)


@router.get("/product/list", response_class=HTMLResponse)
async def product_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/product/list", status_code=302)


@router.get("/product/edit/{product_id}", response_class=HTMLResponse)
async def edit_product_page(request: Request, product_id: int):
    return RedirectResponse(url=f"{_NEXTJS_URL}/product/edit/{product_id}", status_code=302)


@router.get("/customer/list", response_class=HTMLResponse)
async def customer_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/customer/list", status_code=302)


@router.get("/customer/edit/{customer_id}", response_class=HTMLResponse)
async def edit_customer_page(request: Request, customer_id: int):
    return RedirectResponse(url=f"{_NEXTJS_URL}/customer/edit/{customer_id}", status_code=302)


@router.get("/customer-order/", response_class=HTMLResponse)
async def customer_order_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/customer-order", status_code=302)


@router.get("/supplier/list", response_class=HTMLResponse)
async def supplier_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/supplier/list", status_code=302)


@router.get("/supplier/edit/{supplier_id}", response_class=HTMLResponse)
async def edit_supplier_page(request: Request, supplier_id: int):
    return RedirectResponse(url=f"{_NEXTJS_URL}/supplier/edit/{supplier_id}", status_code=302)


@router.get("/user/list", response_class=HTMLResponse)
async def user_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/user/list", status_code=302)


@router.get("/user/edit/{edit_user_id}", response_class=HTMLResponse)
async def edit_user_page(request: Request, edit_user_id: int):
    return RedirectResponse(url=f"{_NEXTJS_URL}/user/edit/{edit_user_id}", status_code=302)


@router.get("/permission/list", response_class=HTMLResponse)
async def permission_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/permission/list", status_code=302)


@router.get("/approval/list", response_class=HTMLResponse)
async def approval_list_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/approval/list", status_code=302)


@router.get("/approval/detail/{approval_id}", response_class=HTMLResponse)
async def approval_detail_page(request: Request, approval_id: int):
    return RedirectResponse(url=f"{_NEXTJS_URL}/approval/detail/{approval_id}", status_code=302)


@router.get("/finance/statistics", response_class=HTMLResponse)
async def finance_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/finance/statistics", status_code=302)


@router.get("/report/reports", response_class=HTMLResponse)
async def report_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/report/reports", status_code=302)


@router.get("/material/calculator", response_class=HTMLResponse)
async def material_calculator_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/material/calculator", status_code=302)


@router.get("/material-registration/page", response_class=HTMLResponse)
async def material_registration_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/material-registration", status_code=302)


@router.get("/material/orders", response_class=HTMLResponse)
async def purchase_orders_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/material/orders", status_code=302)


@router.get("/material/orders/{order_id}", response_class=HTMLResponse)
async def purchase_order_detail_page(request: Request, order_id: int):
    return RedirectResponse(url=f"{_NEXTJS_URL}/material/orders/{order_id}", status_code=302)


@router.get("/purchase-center/", response_class=HTMLResponse)
async def purchase_center_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/purchase-center", status_code=302)


@router.get("/plans/list", response_class=HTMLResponse)
async def purchase_plan_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/plans/list", status_code=302)


@router.get("/production-plan/list", response_class=HTMLResponse)
async def production_plan_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/production-plan/list", status_code=302)


@router.get("/production-summary/list", response_class=HTMLResponse)
async def production_summary_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/production-summary/list", status_code=302)


@router.get("/case/", response_class=HTMLResponse)
async def case_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/case", status_code=302)


@router.get("/case/out", response_class=HTMLResponse)
async def case_out_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/case/out", status_code=302)


@router.get("/case/inventory", response_class=HTMLResponse)
async def case_inventory_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/case/inventory", status_code=302)


@router.get("/batch/management", response_class=HTMLResponse)
async def batch_management_page(request: Request):
    return RedirectResponse(url=f"{_NEXTJS_URL}/batch/management", status_code=302)
