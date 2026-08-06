"""
API V1 路由注册
"""

from fastapi import APIRouter, Depends

from fastapi_app.api.v1.endpoints.approval import router as approval_router
from fastapi_app.api.v1.endpoints.auth import router as auth_router
from fastapi_app.api.v1.endpoints.auxiliary import router as auxiliary_router
from fastapi_app.api.v1.endpoints.backup import router as backup_router
from fastapi_app.api.v1.endpoints.batch import router as batch_router
from fastapi_app.api.v1.endpoints.case_endpoint import router as case_router
from fastapi_app.api.v1.endpoints.customer import router as customer_router
from fastapi_app.api.v1.endpoints.daily_production import router as daily_production_router
from fastapi_app.api.v1.endpoints.dashboard import router as dashboard_router
from fastapi_app.api.v1.endpoints.dead_letter import router as dead_letter_router
from fastapi_app.api.v1.endpoints.device_token import router as device_token_router
from fastapi_app.api.v1.endpoints.material_registration import router as material_reg_router
from fastapi_app.api.v1.endpoints.monitoring import router as monitoring_router
from fastapi_app.api.v1.endpoints.notification import router as notification_router
from fastapi_app.api.v1.endpoints.ocr_import import router as ocr_import_router
from fastapi_app.api.v1.endpoints.order import router as order_router
from fastapi_app.api.v1.endpoints.order_batch import router as order_batch_router
from fastapi_app.api.v1.endpoints.pattern_room import router as pattern_room_router
from fastapi_app.api.v1.endpoints.permission import router as permission_router
from fastapi_app.api.v1.endpoints.product import router as product_router
from fastapi_app.api.v1.endpoints.production_plan import router as production_plan_router
from fastapi_app.api.v1.endpoints.production_summary import router as production_summary_router
from fastapi_app.api.v1.endpoints.purchase_center import router as purchase_center_router
from fastapi_app.api.v1.endpoints.purchase_plan import router as purchase_plan_router
from fastapi_app.api.v1.endpoints.report import router as report_router
from fastapi_app.api.v1.endpoints.staging_order import router as staging_order_router
from fastapi_app.api.v1.endpoints.staging_stockin import router as staging_stockin_router
from fastapi_app.api.v1.endpoints.staging_stockout import router as staging_stockout_router
from fastapi_app.api.v1.endpoints.stock import router as stock_router
from fastapi_app.api.v1.endpoints.supplier import router as supplier_router
from fastapi_app.api.v1.endpoints.tasks import router as tasks_router
from fastapi_app.api.v1.endpoints.user import router as user_router
from fastapi_app.core.deps import get_current_user_id

api_router = APIRouter()

# 采购中心路由 - 前缀 /api/v1/purchase-center
api_router.include_router(
    purchase_center_router,
    prefix="/purchase-center",
    tags=["采购中心"],
    dependencies=[Depends(get_current_user_id)],
)

# 批量导入路由 - 前缀 /api/v1/batch
api_router.include_router(
    batch_router,
    prefix="/batch",
    tags=["批量导入"],
    dependencies=[Depends(get_current_user_id)],
)

# 暂存订单路由 - 前缀 /api/v1/staging-orders
api_router.include_router(
    staging_order_router,
    prefix="/staging-orders",
    tags=["暂存订单"],
    dependencies=[Depends(get_current_user_id)],
)

# 暂存备货路由 - 前缀 /api/v1/staging-stockins
api_router.include_router(
    staging_stockin_router,
    prefix="/staging-stockins",
    tags=["暂存备货"],
    dependencies=[Depends(get_current_user_id)],
)

# 暂存出货路由 - 前缀 /api/v1/staging-stockouts
api_router.include_router(
    staging_stockout_router,
    prefix="/staging-stockouts",
    tags=["暂存出货"],
    dependencies=[Depends(get_current_user_id)],
)

# 产品管理路由 - 前缀 /api/v1/products
api_router.include_router(
    product_router,
    prefix="/products",
    tags=["产品管理"],
    dependencies=[Depends(get_current_user_id)],
)

# 订单管理路由 - 前缀 /api/v1/orders
api_router.include_router(
    order_router,
    prefix="/orders",
    tags=["订单管理"],
    dependencies=[Depends(get_current_user_id)],
)

# 订单批次号路由 - 前缀 /api/v1/order-batch
api_router.include_router(
    order_batch_router,
    prefix="/order-batch",
    tags=["订单批次号"],
    dependencies=[Depends(get_current_user_id)],
)

# 库存管理路由 - 前缀 /api/v1/stock
api_router.include_router(
    stock_router,
    prefix="/stock",
    tags=["库存管理"],
    dependencies=[Depends(get_current_user_id)],
)

# 用户管理路由 - 前缀 /api/v1/users
api_router.include_router(
    user_router,
    prefix="/users",
    tags=["用户管理"],
    dependencies=[Depends(get_current_user_id)],
)

# 客户管理路由 - 前缀 /api/v1/customers
api_router.include_router(
    customer_router,
    prefix="/customers",
    tags=["客户管理"],
    dependencies=[Depends(get_current_user_id)],
)

# 供应商管理路由 - 前缀 /api/v1/suppliers
api_router.include_router(
    supplier_router,
    prefix="/suppliers",
    tags=["供应商管理"],
    dependencies=[Depends(get_current_user_id)],
)

# 审批管理路由 - 前缀 /api/v1/approvals
api_router.include_router(
    approval_router,
    prefix="/approvals",
    tags=["审批管理"],
    dependencies=[Depends(get_current_user_id)],
)

# 报表统计路由 - 前缀 /api/v1/reports
api_router.include_router(
    report_router,
    prefix="/reports",
    tags=["报表统计"],
    dependencies=[Depends(get_current_user_id)],
)

# 皮套管理路由 - 前缀 /api/v1/cases
api_router.include_router(
    case_router,
    prefix="/cases",
    tags=["皮套管理"],
    dependencies=[Depends(get_current_user_id)],
)

# 来料登记路由 - 前缀 /api/v1/material-registrations
api_router.include_router(
    material_reg_router,
    prefix="/material-registrations",
    tags=["来料登记"],
    dependencies=[Depends(get_current_user_id)],
)

# 辅助API路由 - 前缀 /api/v1/aux
api_router.include_router(
    auxiliary_router,
    prefix="/aux",
    tags=["辅助接口"],
    dependencies=[Depends(get_current_user_id)],
)

# 异步任务路由 - 前缀 /api/v1/tasks
api_router.include_router(
    tasks_router,
    prefix="/tasks",
    tags=["异步任务"],
    dependencies=[Depends(get_current_user_id)],
)

# 认证与文件上传路由 - 前缀 /api/v1/auth (无默认认证，登录/登出需公开)
api_router.include_router(
    auth_router,
    prefix="/auth",
    tags=["认证与上传"],
)

# OCR PDF出货单识别路由 - 前缀 /api/v1/ocr-import
api_router.include_router(
    ocr_import_router,
    prefix="/ocr-import",
    tags=["OCR识别导入"],
    dependencies=[Depends(get_current_user_id)],
)

# 排产计划路由 - 前缀 /api/v1/production-plans
api_router.include_router(
    production_plan_router,
    prefix="/production-plans",
    tags=["排产计划"],
    dependencies=[Depends(get_current_user_id)],
)

# 采购计划路由(重构版) - 前缀 /api/v1/plans
api_router.include_router(
    purchase_plan_router,
    prefix="/plans",
    tags=["采购计划"],
    dependencies=[Depends(get_current_user_id)],
)

# 生产报表路由（重构版）- 前缀 /api/v1/daily-production
api_router.include_router(
    daily_production_router,
    prefix="/daily-production",
    tags=["生产报表"],
    dependencies=[Depends(get_current_user_id)],
)

# 生产计划路由 - 前缀 /api/v1/production-summary
api_router.include_router(
    production_summary_router,
    prefix="/production-summary",
    tags=["生产计划"],
    dependencies=[Depends(get_current_user_id)],
)

# 仪表盘路由 - 前缀 /api/v1/dashboard
api_router.include_router(
    dashboard_router,
    prefix="/dashboard",
    tags=["仪表盘"],
    dependencies=[Depends(get_current_user_id)],
)

# 设备令牌注册路由 - 前缀 /api/v1/device
api_router.include_router(
    device_token_router,
    prefix="/device",
    tags=["设备管理"],
    dependencies=[Depends(get_current_user_id)],
)

# 权限管理路由 - 前缀 /api/v1/permissions
api_router.include_router(
    permission_router,
    prefix="/permissions",
    tags=["权限管理"],
    dependencies=[Depends(get_current_user_id)],
)

# 数据备份路由 - 前缀 /api/v1/backup
api_router.include_router(
    backup_router,
    prefix="/backup",
    tags=["数据备份"],
    dependencies=[Depends(get_current_user_id)],
)

# 性能监控路由 - 前缀 /api/v1/monitoring
api_router.include_router(
    monitoring_router,
    prefix="/monitoring",
    tags=["性能监控"],
    dependencies=[Depends(get_current_user_id)],
)

# 死信队列路由 - 前缀 /api/v1/dead-letter
api_router.include_router(
    dead_letter_router,
    prefix="/dead-letter",
    tags=["死信队列"],
    dependencies=[Depends(get_current_user_id)],
)

# 板房管理路由 - 前缀 /api/v1/pattern-room
api_router.include_router(
    pattern_room_router,
    prefix="/pattern-room",
    tags=["板房管理"],
    dependencies=[Depends(get_current_user_id)],
)

# 通知中心路由 - 前缀 /api/v1/notifications
api_router.include_router(
    notification_router,
    prefix="/notifications",
    tags=["notifications"],
    dependencies=[Depends(get_current_user_id)],
)
