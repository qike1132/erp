"""
数据模型模块
包含所有数据库模型定义
"""
from .product import Product
from .order import Order
from .stock_in import StockIn
from .stock_out import StockOut
from .inventory_log import InventoryLog
from .case import Case
from .case_stock_in import CaseStockIn
from .case_stock_out import CaseStockOut
from .case_inventory_log import CaseInventoryLog
from .user import User
from .permission import Permission
from .approval import ApprovalRequest, ApprovalLog
from .customer import Customer
from .customer_access_log import CustomerAccessLog
from .staging_order import StagingOrder
from .staging_stock_in import StagingStockIn
from .staging_stock_out import StagingStockOut
from .product_material import ProductMaterial, ProductAccessory, ProductFabric, ProductPackaging, MATERIAL_CATEGORIES
from .supplier import Supplier
from .purchase_order import PurchaseOrder, PurchaseOrderItem
from .purchase_center import ModificationLog, SavedQuery
from .order_sync import OrderSyncRecord, OrderStatusLog, SyncRetryQueue, OrderSyncConfig, ORDER_STATUS_FLOW, validate_status_transition, get_action_for_transition
from .material_registration import MaterialRegistration, MaterialRegistrationItem
from .sku_batch import SkuBatch
from .production_plan import ProductionPlan, ProductionPlanLog, StagingPurchasePlan
from .purchase_plan import PurchasePlan, PurchasePlanDetail, ShipmentRecord
from .craft_work import CraftWork
from .packaging_record import PackagingRecord

__all__ = [
    'Product',
    'Order',
    'StockIn',
    'StockOut',
    'InventoryLog',
    'Case',
    'CaseStockIn',
    'CaseStockOut',
    'CaseInventoryLog',
    'User',
    'Permission',
    'ApprovalRequest',
    'ApprovalLog',
    'Customer',
    'CustomerAccessLog',
    'StagingOrder',
    'StagingStockIn',
    'StagingStockOut',
    'ProductMaterial',
    'ProductAccessory',
    'ProductFabric',
    'ProductPackaging',
    'MATERIAL_CATEGORIES',
    'Supplier',
    'PurchaseOrder',
    'PurchaseOrderItem',
    'ModificationLog',
    'SavedQuery',
    'OrderSyncRecord',
    'OrderStatusLog',
    'SyncRetryQueue',
    'OrderSyncConfig',
    'ORDER_STATUS_FLOW',
    'validate_status_transition',
    'get_action_for_transition',
    'MaterialRegistration',
    'MaterialRegistrationItem',
    'SkuBatch',
    'ProductionPlan',
    'ProductionPlanLog',
    'StagingPurchasePlan',
    'PurchasePlan',
    'PurchasePlanDetail',
    'ShipmentRecord',
    'CraftWork',
    'PackagingRecord',
]
