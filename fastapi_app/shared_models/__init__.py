"""
共享数据模型

使用纯 SQLAlchemy 2.0 声明式模型，脱离 Flask-SQLAlchemy 依赖。
这些模型映射到与 Flask 应用相同的数据库表，两者可同时使用。
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 声明式基类"""
    pass


# 导入所有模型（确保 Base.metadata 注册了所有表）
from fastapi_app.shared_models.app_version import AppVersion
from fastapi_app.shared_models.approval import ApprovalLog, ApprovalRequest
from fastapi_app.shared_models.case import Case
from fastapi_app.shared_models.case_inventory_log import CaseInventoryLog
from fastapi_app.shared_models.case_stock_in import CaseStockIn
from fastapi_app.shared_models.case_stock_out import CaseStockOut
from fastapi_app.shared_models.craft_work import CraftWork
from fastapi_app.shared_models.daily_production_record import DailyProductionRecord
from fastapi_app.shared_models.customer import Customer
from fastapi_app.shared_models.customer_access_log import CustomerAccessLog
from fastapi_app.shared_models.inventory_log import InventoryLog
from fastapi_app.shared_models.material_registration import MaterialRegistration, MaterialRegistrationItem
from fastapi_app.shared_models.order import Order
from fastapi_app.shared_models.order_status_log import OrderStatusLog
from fastapi_app.shared_models.order_sync import OrderSyncConfig, OrderSyncRecord, SyncRetryQueue
from fastapi_app.shared_models.packaging_record import PackagingRecord
from fastapi_app.shared_models.permission import Permission
from fastapi_app.shared_models.product import Product
from fastapi_app.shared_models.product_material import (
    MATERIAL_CATEGORIES,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    ProductPackaging,
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
    'AppVersion',
    'Base',
    'Product',
    'Order',
    'StockIn',
    'StockOut',
    'StockReturn',
    'InventoryLog',
    'User',
    'user_permission',
    'Permission',
    'PurchaseOrder',
    'PurchaseOrderItem',
    'StagingOrder',
    'StagingStockIn',
    'StagingStockOut',
    'Customer',
    'ApprovalRequest',
    'ApprovalLog',
    'OrderSyncRecord',
    'SyncRetryQueue',
    'OrderSyncConfig',
    'Case',
    'CaseStockIn',
    'CaseStockOut',
    'CaseInventoryLog',
    'MaterialRegistration',
    'MaterialRegistrationItem',
    'Supplier',
    'ProductMaterial',
    'ProductFabric',
    'ProductAccessory',
    'ProductPackaging',
    'MATERIAL_CATEGORIES',
    'ModificationLog',
    'SavedQuery',
    'OrderStatusLog',
    'CustomerAccessLog',
    'ProductionPlan',
    'ProductionPlanLog',
    'StagingPurchasePlan',
    'PurchasePlan',
    'PurchasePlanDetail',
    'ShipmentRecord',
    'CraftWork',
    'DailyProductionRecord',
    'PackagingRecord',
]
