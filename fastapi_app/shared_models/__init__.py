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
from fastapi_app.shared_models.app_version import AppVersion
from fastapi_app.shared_models.approval import ApprovalLog, ApprovalRequest
from fastapi_app.shared_models.audit_log import AuditLog
from fastapi_app.shared_models.backup_record import BackupRecord
from fastapi_app.shared_models.backup_schedule import BackupSchedule
from fastapi_app.shared_models.backup_settings import BackupSettings
from fastapi_app.shared_models.case import Case
from fastapi_app.shared_models.case_movement import DIRECTION_IN, DIRECTION_OUT, CaseMovement
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
from fastapi_app.shared_models.file_record import FileRecord
from fastapi_app.shared_models.finished_stock_remark import FinishedStockRemark
from fastapi_app.shared_models.import_file_registry import ImportFileRegistry
from fastapi_app.shared_models.inventory_log import InventoryLog
from fastapi_app.shared_models.material_registration import MaterialRegistration, MaterialRegistrationItem
from fastapi_app.shared_models.notification import Notification
from fastapi_app.shared_models.numbering_audit import NumberingAudit
from fastapi_app.shared_models.numbering_counter import NumberingCounter
from fastapi_app.shared_models.order import Order
from fastapi_app.shared_models.order_batch_audit import OrderBatchAuditLog
from fastapi_app.shared_models.order_item import OrderItem
from fastapi_app.shared_models.order_status_log import OrderStatusLog
from fastapi_app.shared_models.order_sync import OrderSyncConfig, OrderSyncRecord, SyncRetryQueue
from fastapi_app.shared_models.outsource import (
    SHIPMENT_STATUS_RECEIVED,
    SHIPMENT_STATUS_SHIPPED,
    OrderOutsourceProcess,
    OrderOutsourceProcessFlow,
    OutsourceProcessType,
    OutsourceShipment,
    OutsourceShipmentItem,
)
from fastapi_app.shared_models.packaging_record import PackagingRecord
from fastapi_app.shared_models.pattern_maker import PatternMaker
from fastapi_app.shared_models.permission import Permission
from fastapi_app.shared_models.product import Product
from fastapi_app.shared_models.product_customer import ProductCustomer
from fastapi_app.shared_models.product_material import (
    MATERIAL_CATEGORIES,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    ProductRole,
    Role,
)
from fastapi_app.shared_models.production_plan import ProductionPlan, ProductionPlanLog, StagingPurchasePlan
from fastapi_app.shared_models.purchase_center import ModificationLog, SavedQuery
from fastapi_app.shared_models.purchase_order import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderSku,
    PurchaseOrderStatus,
)
from fastapi_app.shared_models.purchase_order_generate_attempt import PurchaseOrderGenerateAttempt
from fastapi_app.shared_models.purchase_plan import PurchasePlan, PurchasePlanDetail, ShipmentRecord
from fastapi_app.shared_models.staging_order import StagingOrder
from fastapi_app.shared_models.staging_stock_in import StagingStockIn
from fastapi_app.shared_models.staging_stock_out import StagingStockOut
from fastapi_app.shared_models.stock_in import StockIn
from fastapi_app.shared_models.stock_out import StockOut
from fastapi_app.shared_models.stock_return import StockReturn
from fastapi_app.shared_models.supplier import Supplier
from fastapi_app.shared_models.user import User, user_permission
from fastapi_app.shared_models.web_vital import WebVital

__all__ = [
    'CUSTOMER_SAMPLING_ACTIONS',
    'CUSTOMER_SAMPLING_CHANGE_TYPES',
    'DIRECTION_IN',
    'DIRECTION_OUT',
    'MATERIAL_CATEGORIES',
    'SHIPMENT_STATUS_RECEIVED',
    'SHIPMENT_STATUS_SHIPPED',
    'AppVersion',
    'ApprovalLog',
    'ApprovalRequest',
    'AuditLog',
    'BackupRecord',
    'BackupSchedule',
    'BackupSettings',
    'Base',
    'Case',
    'CaseMovement',
    'CraftWork',
    'Customer',
    'CustomerAccessLog',
    'CustomerSamplingChangeLog',
    'CustomerSamplingFabricVersion',
    'CustomerSamplingPart',
    'CustomerSamplingProject',
    'CustomerSamplingRole',
    'DailyProductionRecord',
    'FileRecord',
    'FinishedStockRemark',
    'ImportFileRegistry',
    'InventoryLog',
    'MaterialRegistration',
    'MaterialRegistrationItem',
    'ModificationLog',
    'Notification',
    'NumberingAudit',
    'NumberingCounter',
    'Order',
    'OrderBatchAuditLog',
    'OrderItem',
    'OrderOutsourceProcess',
    'OrderOutsourceProcessFlow',
    'OrderStatusLog',
    'OrderSyncConfig',
    'OrderSyncRecord',
    'OutsourceProcessType',
    'OutsourceShipment',
    'OutsourceShipmentItem',
    'PackagingRecord',
    'PatternMaker',
    'Permission',
    'Product',
    'ProductAccessory',
    'ProductCustomer',
    'ProductFabric',
    'ProductMaterial',
    'ProductRole',
    'ProductionPlan',
    'ProductionPlanLog',
    'PurchaseOrder',
    'PurchaseOrderGenerateAttempt',
    'PurchaseOrderItem',
    'PurchaseOrderSku',
    'PurchaseOrderStatus',
    'PurchasePlan',
    'PurchasePlanDetail',
    'Role',
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
    'WebVital',
    'user_permission',
]


# ---- PG-only 表达式索引守卫（2026-11-01，迁移 pg_standalone_107 / P3）----
# 编号查询族表达式索引（idx_*_no_date_seq）的列表达式与谓词使用 PostgreSQL
# 专用的 split_part / 正则操作符。SQLite 测试后端没有这些函数，
# ``Base.metadata.create_all`` / ``Table.create()`` 时会报
# "no such function: split_part"（曾致 132 个测试失败，2026-11-01）。
# 模型声明保留（PG 建表 / drift 对账正常），仅在 create 面对非 PG 连接时
# 临时摘除、建表后恢复。同时挂 MetaData 级与 Table 级事件：create_all 走
# MetaData 级、单表 Table.create()（部分测试 fixture）走 Table 级；两条路径
# 都触发时摘除/恢复幂等，不会重复。
from sqlalchemy import Table as _SaTable
from sqlalchemy import event as _sa_event

_PG_ONLY_INDEX_SUFFIX = '_no_date_seq'
_pg_only_index_stash: list = []


def _stash_pg_only_indexes_for(connection, tables):
    """非 PG 连接：从给定表摘除 PG-only 表达式索引（幂等）。"""
    if connection.dialect.name == 'postgresql':
        return
    for table in tables:
        for idx in list(table.indexes):
            if idx.name and idx.name.endswith(_PG_ONLY_INDEX_SUFFIX):
                table.indexes.remove(idx)
                _pg_only_index_stash.append((table, idx))


def _restore_pg_only_indexes_for(connection):
    """非 PG 连接：恢复此前摘除的 PG-only 索引（幂等）。"""
    if connection.dialect.name == 'postgresql':
        return
    while _pg_only_index_stash:
        table, idx = _pg_only_index_stash.pop()
        table.indexes.add(idx)


@_sa_event.listens_for(Base.metadata, 'before_create')
def _stash_pg_only_indexes_metadata(metadata, connection, **kw):
    _stash_pg_only_indexes_for(connection, list(metadata.tables.values()))


@_sa_event.listens_for(Base.metadata, 'after_create')
def _restore_pg_only_indexes_metadata(metadata, connection, **kw):
    _restore_pg_only_indexes_for(connection)


@_sa_event.listens_for(_SaTable, 'before_create')
def _stash_pg_only_indexes_table(target, connection, **kw):
    _stash_pg_only_indexes_for(connection, [target])


@_sa_event.listens_for(_SaTable, 'after_create')
def _restore_pg_only_indexes_table(target, connection, **kw):
    _restore_pg_only_indexes_for(connection)
