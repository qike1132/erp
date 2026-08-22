"""
共享数据模型

使用纯 SQLAlchemy 2.0 声明式模型，所有 FastAPI 服务共享同一套模型定义。

注意：此处必须全量导入所有模型，不能改为惰性导入（__getattr__）。
原因：SQLAlchemy 在模型类定义时（即模块导入时）将表信息注册到 Base.metadata。
若使用惰性导入，未被显式访问的模型不会注册到 metadata，导致：
  1. Base.metadata.create_all() 无法创建未访问模型的表
  2. Alembic autogenerate 无法检测未访问模型的变更
  3. 关联关系（ForeignKey）可能因目标表未注册而报错
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 声明式基类"""
    pass


# 全量导入所有模型，确保 Base.metadata 注册所有表（详见模块文档字符串）
from fastapi_app.shared_models.approval import ApprovalLog, ApprovalRequest
from fastapi_app.shared_models.audit_log import AuditLog
from fastapi_app.shared_models.backup_record import BackupRecord
from fastapi_app.shared_models.case import Case
from fastapi_app.shared_models.case_inventory_log import CaseInventoryLog
from fastapi_app.shared_models.case_stock_in import CaseStockIn
from fastapi_app.shared_models.case_stock_out import CaseStockOut
from fastapi_app.shared_models.country import Country
from fastapi_app.shared_models.craft_work import CraftWork
from fastapi_app.shared_models.customer import Customer
from fastapi_app.shared_models.customer_access_log import CustomerAccessLog
from fastapi_app.shared_models.customer_sampling import (
    CUSTOMER_SAMPLING_ACTIONS,
    CUSTOMER_SAMPLING_CHANGE_TYPES,
    CustomerSamplingChangeLog,
    CustomerSamplingFabricVersion,
    CustomerSamplingPart,
    CustomerSamplingProject,
    CustomerSamplingRole,
)
from fastapi_app.shared_models.daily_production_record import DailyProductionRecord
from fastapi_app.shared_models.device_token import DeviceToken
from fastapi_app.shared_models.file_record import FileRecord
from fastapi_app.shared_models.inventory_log import InventoryLog
from fastapi_app.shared_models.material_registration import MaterialRegistration, MaterialRegistrationItem
from fastapi_app.shared_models.notification import Notification
from fastapi_app.shared_models.order import Order
from fastapi_app.shared_models.order_batch_audit import OrderBatchAuditLog
from fastapi_app.shared_models.order_item import OrderItem
from fastapi_app.shared_models.order_status_log import OrderStatusLog
from fastapi_app.shared_models.order_sync import OrderSyncConfig, OrderSyncRecord, SyncRetryQueue
from fastapi_app.shared_models.outsource import (
    OUTSOURCE_PROCESS_STATUS_LABELS,
    OUTSOURCE_PROCESS_STATUSES,
    OrderOutsourceProcess,
    OrderOutsourceProcessFlow,
    OutsourceProcessType,
)
from fastapi_app.shared_models.packaging_record import PackagingRecord
from fastapi_app.shared_models.pattern_maker import PatternMaker
from fastapi_app.shared_models.permission import Permission
from fastapi_app.shared_models.product import Product
from fastapi_app.shared_models.product_material import (
    MATERIAL_CATEGORIES,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
)
from fastapi_app.shared_models.production_plan import ProductionPlan, ProductionPlanLog, StagingPurchasePlan
from fastapi_app.shared_models.purchase_center import ModificationLog, SavedQuery
from fastapi_app.shared_models.purchase_order import PurchaseOrder, PurchaseOrderItem
from fastapi_app.shared_models.purchase_plan import PurchasePlan, PurchasePlanDetail, ShipmentRecord
from fastapi_app.shared_models.staging_order import StagingOrder
from fastapi_app.shared_models.staging_stock_in import StagingStockIn
from fastapi_app.shared_models.staging_stock_out import StagingStockOut
from fastapi_app.shared_models.stock_in import StockIn
from fastapi_app.shared_models.stock_out import StockOut
from fastapi_app.shared_models.stock_return import StockReturn
from fastapi_app.shared_models.supplier import Supplier
from fastapi_app.shared_models.user import User, user_permission

__all__ = [
    'CUSTOMER_SAMPLING_ACTIONS',
    'CUSTOMER_SAMPLING_CHANGE_TYPES',
    'MATERIAL_CATEGORIES',
    'OUTSOURCE_PROCESS_STATUSES',
    'OUTSOURCE_PROCESS_STATUS_LABELS',
    'ApprovalLog',
    'ApprovalRequest',
    'AuditLog',
    'BackupRecord',
    'Base',
    'Case',
    'CaseInventoryLog',
    'CaseStockIn',
    'CaseStockOut',
    'Country',
    'CraftWork',
    'Customer',
    'CustomerAccessLog',
    'CustomerSamplingChangeLog',
    'CustomerSamplingFabricVersion',
    'CustomerSamplingPart',
    'CustomerSamplingProject',
    'CustomerSamplingRole',
    'DailyProductionRecord',
    'DeviceToken',
    'FileRecord',
    'InventoryLog',
    'MaterialRegistration',
    'MaterialRegistrationItem',
    'ModificationLog',
    'Notification',
    'Order',
    'OrderBatchAuditLog',
    'OrderItem',
    'OrderOutsourceProcess',
    'OrderOutsourceProcessFlow',
    'OrderStatusLog',
    'OrderSyncConfig',
    'OrderSyncRecord',
    'OutsourceProcessType',
    'PackagingRecord',
    'PatternMaker',
    'Permission',
    'Product',
    'ProductAccessory',
    'ProductFabric',
    'ProductMaterial',
    'ProductionPlan',
    'ProductionPlanLog',
    'PurchaseOrder',
    'PurchaseOrderItem',
    'PurchasePlan',
    'PurchasePlanDetail',
    'SavedQuery',
    'ShipmentRecord',
    'StagingOrder',
    'StagingPurchasePlan',
    'StagingStockIn',
    'StagingStockOut',
    'StockIn',
    'StockOut',
    'StockReturn',
    'Supplier',
    'SyncRetryQueue',
    'User',
    'user_permission',
]
