"""
采购中心 FastAPI 端点（模块化拆分）

原 purchase_center.py (1400+ LOC) 拆分为：
- schemas.py        → Pydantic 请求模型
- product_routes.py → 产品/BOM 相关路由
- supplier_routes.py → 供应商相关路由
- customer_routes.py → 客户管理相关路由
- order_routes.py    → 采购订单 CRUD 路由
- print_routes.py    → 汇总打印 / Excel 导出路由
- misc_routes.py     → 修改日志/保存查询/状态日志等辅助路由
- export_utils.py    → Excel 导出工具函数
"""

from fastapi import APIRouter

from fastapi_app.api.v1.endpoints.purchase_center.customer_routes import router as customer_router
from fastapi_app.api.v1.endpoints.purchase_center.misc_routes import router as misc_router
from fastapi_app.api.v1.endpoints.purchase_center.order_routes import router as order_router
from fastapi_app.api.v1.endpoints.purchase_center.print_routes import router as print_router
from fastapi_app.api.v1.endpoints.purchase_center.product_routes import router as product_router
from fastapi_app.api.v1.endpoints.purchase_center.supplier_routes import router as supplier_router

router = APIRouter()
router.include_router(product_router)
router.include_router(supplier_router)
router.include_router(customer_router)
router.include_router(order_router)
router.include_router(print_router)
router.include_router(misc_router)
