"""
ERP系统领域边界定义

采用模块化单体(Modular Monolith)架构，按业务领域划分模块边界。
每个领域模块定义清晰的接口(服务层)，跨域通信通过领域事件而非直接调用。

模块拆分优先级（按业务耦合度从低到高）：
1. 通知域(notification) - 最独立，仅被其他域调用，不依赖其他域
2. 备份域(backup) - 独立后台任务，仅依赖基础设施
3. 认证域(auth) - 用户+权限，被所有域依赖但不依赖业务域
4. 产品域(product) - 基础主数据，被库存/订单/采购依赖
5. 库存域(inventory) - 入库+出库+退料，依赖产品域
6. 订单域(order) - 依赖产品+库存+客户
7. 采购域(purchase) - 依赖产品+供应商，与订单域松耦合
8. 生产域(production) - 依赖采购+订单
9. 报表域(report) - 跨域只读聚合，依赖所有业务域
"""

from enum import Enum


class Domain(str, Enum):
    AUTH = 'auth'
    PRODUCT = 'product'
    INVENTORY = 'inventory'
    ORDER = 'order'
    PURCHASE = 'purchase'
    PRODUCTION = 'production'
    CUSTOMER = 'customer'
    APPROVAL = 'approval'
    BACKUP = 'backup'
    NOTIFICATION = 'notification'
    REPORT = 'report'
    CASE = 'case'
    MATERIAL = 'material'


DOMAIN_DEPENDENCIES = {
    Domain.AUTH: [],
    Domain.PRODUCT: [Domain.AUTH],
    Domain.CUSTOMER: [Domain.AUTH],
    Domain.INVENTORY: [Domain.AUTH, Domain.PRODUCT],
    Domain.ORDER: [Domain.AUTH, Domain.PRODUCT, Domain.INVENTORY, Domain.CUSTOMER],
    Domain.PURCHASE: [Domain.AUTH, Domain.PRODUCT, Domain.CUSTOMER],
    Domain.PRODUCTION: [Domain.AUTH, Domain.PURCHASE, Domain.ORDER],
    Domain.APPROVAL: [Domain.AUTH],
    Domain.BACKUP: [Domain.AUTH],
    Domain.NOTIFICATION: [],
    Domain.REPORT: [Domain.AUTH, Domain.PRODUCT, Domain.INVENTORY, Domain.ORDER, Domain.PURCHASE],
    Domain.CASE: [Domain.AUTH, Domain.PRODUCT, Domain.INVENTORY],
    Domain.MATERIAL: [Domain.AUTH, Domain.PRODUCT],
}

DOMAIN_SERVICE_MAP = {
    Domain.AUTH: ['user_service', 'permission'],
    Domain.PRODUCT: ['product_service', 'product_search_service'],
    Domain.CUSTOMER: ['customer_service', 'customer_search_service'],
    Domain.INVENTORY: ['stock_service'],
    Domain.ORDER: ['order_service', 'order_batch_service', 'order_purchase_sync'],
    Domain.PURCHASE: ['purchase_order_service', 'purchase_plan_service', 'purchase_center_service',
                      'purchase_bom_copy_service', 'purchase_customer_service', 'purchase_history_service',
                      'purchase_product_service', 'purchase_supplier_service'],
    Domain.PRODUCTION: ['production_plan_service', 'production_summary_service', 'daily_production_service'],
    Domain.APPROVAL: ['approval_service'],
    Domain.BACKUP: ['backup_service'],
    Domain.NOTIFICATION: ['notification_service', 'fcm_service'],
    Domain.REPORT: ['report_service'],
    Domain.CASE: ['case_service'],
    Domain.MATERIAL: ['material_registration_service'],
}

DOMAIN_API_PREFIX = {
    Domain.AUTH: '/api/v1/users',
    Domain.PRODUCT: '/api/v1/products',
    Domain.CUSTOMER: '/api/v1/customers',
    Domain.INVENTORY: '/api/v1/stock',
    Domain.ORDER: '/api/v1/orders',
    Domain.PURCHASE: '/api/v1/plans',
    Domain.PRODUCTION: '/api/v1/production-plans',
    Domain.APPROVAL: '/api/v1/approvals',
    Domain.BACKUP: '/api/v1/backup',
    Domain.NOTIFICATION: '/ws/',
    Domain.REPORT: '/api/v1/reports',
    Domain.CASE: '/api/v1/cases',
    Domain.MATERIAL: '/api/v1/material-registrations',
}
