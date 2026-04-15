"""
API V1 路由注册
"""

from fastapi import APIRouter

from fastapi_app.api.v1.endpoints.purchase_center import router as purchase_center_router
from fastapi_app.api.v1.endpoints.batch import router as batch_router
from fastapi_app.api.v1.endpoints.staging_order import router as staging_order_router
from fastapi_app.api.v1.endpoints.staging_stockin import router as staging_stockin_router
from fastapi_app.api.v1.endpoints.staging_stockout import router as staging_stockout_router
from fastapi_app.api.v1.endpoints.product import router as product_router
from fastapi_app.api.v1.endpoints.order import router as order_router
from fastapi_app.api.v1.endpoints.stock import router as stock_router
from fastapi_app.api.v1.endpoints.user import router as user_router
from fastapi_app.api.v1.endpoints.customer import router as customer_router
from fastapi_app.api.v1.endpoints.approval import router as approval_router
from fastapi_app.api.v1.endpoints.report import router as report_router
from fastapi_app.api.v1.endpoints.case_endpoint import router as case_router
from fastapi_app.api.v1.endpoints.material_registration import router as material_reg_router
from fastapi_app.api.v1.endpoints.auxiliary import router as auxiliary_router
from fastapi_app.api.v1.endpoints.tasks import router as tasks_router
from fastapi_app.api.v1.endpoints.auth import router as auth_router
from fastapi_app.api.v1.endpoints.sku_batch import router as sku_batch_router
from fastapi_app.api.v1.endpoints.ocr_import import router as ocr_import_router
from fastapi_app.api.v1.endpoints.finance import router as finance_router
from fastapi_app.api.v1.endpoints.production_plan import router as production_plan_router
from fastapi_app.api.v1.endpoints.purchase_plan import router as purchase_plan_router
from fastapi_app.api.v1.endpoints.production_summary import router as production_summary_router

api_router = APIRouter()

# 采购中心路由 - 前缀 /api/v1/purchase-center
api_router.include_router(
    purchase_center_router,
    prefix="/purchase-center",
    tags=["采购中心"],
)

# 批量导入路由 - 前缀 /api/v1/batch
api_router.include_router(
    batch_router,
    prefix="/batch",
    tags=["批量导入"],
)

# 暂存订单路由 - 前缀 /api/v1/staging-orders
api_router.include_router(
    staging_order_router,
    prefix="/staging-orders",
    tags=["暂存订单"],
)

# 暂存备货路由 - 前缀 /api/v1/staging-stockins
api_router.include_router(
    staging_stockin_router,
    prefix="/staging-stockins",
    tags=["暂存备货"],
)

# 暂存出货路由 - 前缀 /api/v1/staging-stockouts
api_router.include_router(
    staging_stockout_router,
    prefix="/staging-stockouts",
    tags=["暂存出货"],
)

# 产品管理路由 - 前缀 /api/v1/products
api_router.include_router(
    product_router,
    prefix="/products",
    tags=["产品管理"],
)

# 订单管理路由 - 前缀 /api/v1/orders
api_router.include_router(
    order_router,
    prefix="/orders",
    tags=["订单管理"],
)

# 库存管理路由 - 前缀 /api/v1/stock
api_router.include_router(
    stock_router,
    prefix="/stock",
    tags=["库存管理"],
)

# 用户管理路由 - 前缀 /api/v1/users
api_router.include_router(
    user_router,
    prefix="/users",
    tags=["用户管理"],
)

# 客户管理路由 - 前缀 /api/v1/customers
api_router.include_router(
    customer_router,
    prefix="/customers",
    tags=["客户管理"],
)

# 审批管理路由 - 前缀 /api/v1/approvals
api_router.include_router(
    approval_router,
    prefix="/approvals",
    tags=["审批管理"],
)

# 报表统计路由 - 前缀 /api/v1/reports
api_router.include_router(
    report_router,
    prefix="/reports",
    tags=["报表统计"],
)

# 皮套管理路由 - 前缀 /api/v1/cases
api_router.include_router(
    case_router,
    prefix="/cases",
    tags=["皮套管理"],
)

# 来料登记路由 - 前缀 /api/v1/material-registrations
api_router.include_router(
    material_reg_router,
    prefix="/material-registrations",
    tags=["来料登记"],
)

# 辅助API路由 - 前缀 /api/v1/aux
api_router.include_router(
    auxiliary_router,
    prefix="/aux",
    tags=["辅助接口"],
)

# 异步任务路由 - 前缀 /api/v1/tasks
api_router.include_router(
    tasks_router,
    tags=["异步任务"],
)

# 认证与文件上传路由 - 前缀 /api/v1/auth
api_router.include_router(
    auth_router,
    prefix="/auth",
    tags=["认证与上传"],
)

# SKU批次管理路由 - 前缀 /api/v1/sku-batches
api_router.include_router(
    sku_batch_router,
    prefix="/sku-batches",
    tags=["批次管理"],
)

# OCR PDF出货单识别路由 - 前缀 /api/v1/ocr-import
api_router.include_router(
    ocr_import_router,
    prefix="/ocr-import",
    tags=["OCR识别导入"],
)

# 财务统计路由 - 前缀 /api/v1/finance
api_router.include_router(
    finance_router,
    prefix="/finance",
    tags=["财务统计"],
)

# 排产计划路由 - 前缀 /api/v1/production-plans
api_router.include_router(
    production_plan_router,
    prefix="/production-plans",
    tags=["排产计划"],
)

# 采购计划路由(重构版) - 前缀 /api/v1/plans
api_router.include_router(
    purchase_plan_router,
    prefix="/plans",
    tags=["采购计划"],
)

# 生产计划路由 - 前缀 /api/v1/production-summary
api_router.include_router(
    production_summary_router,
    prefix="/production-summary",
    tags=["生产计划"],
)
