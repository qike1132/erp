"""订单数据序列化器

统一订单数据转换逻辑，支持基于配置的字段选择和关联加载。
替代原有的 _order_to_dict 和 _order_batch_to_dict 重复实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi_app.shared_models import Order


class OrderField(Enum):
    """订单字段枚举"""

    ID = "id"
    ORDER_NO = "order_no"
    CUSTOMER = "customer"
    ORDER_DATE = "order_date"
    PRODUCT_ID = "product_id"
    PRODUCT = "product"
    PRODUCT_NAME = "product_name"
    QUANTITY = "quantity"
    DEDUCT_QUANTITY = "deduct_quantity"
    STATUS = "status"
    NOTE = "note"
    ORDER_TYPE = "order_type"
    COUNTRY = "country"
    IS_LOCKED = "is_locked"
    LOCKED_BY_NAME = "locked_by_name"
    BATCH_NO = "batch_no"
    BATCH_COMPLETED_AT = "batch_completed_at"


@dataclass(frozen=True)
class SerializerConfig:
    """序列化器配置

    Attributes:
        fields: 需要序列化的字段列表
        include_product: 是否包含产品详情对象
        include_locked_by: 是否包含锁定人信息
    """

    fields: list[OrderField]
    include_product: bool = False
    include_locked_by: bool = False


class OrderSerializer:
    """统一订单数据序列化器

    提供基于配置的订单数据转换能力，替代原有的多处重复实现。

    Usage:
        # 列表场景
        data = OrderSerializer.serialize(order, OrderSerializer.LIST_CONFIG)

        # 详情场景
        data = OrderSerializer.serialize(
            order, OrderSerializer.DETAIL_CONFIG, deduct_quantity=10
        )

        # 批次场景
        data = OrderSerializer.serialize(order, OrderSerializer.BATCH_CONFIG)
    """

    # 预定义配置：列表展示（订单管理页面）
    LIST_CONFIG = SerializerConfig(
        fields=[
            OrderField.ID,
            OrderField.ORDER_NO,
            OrderField.CUSTOMER,
            OrderField.ORDER_DATE,
            OrderField.PRODUCT,
            OrderField.QUANTITY,
            OrderField.DEDUCT_QUANTITY,
            OrderField.STATUS,
            OrderField.NOTE,
            OrderField.ORDER_TYPE,
            OrderField.COUNTRY,
            OrderField.IS_LOCKED,
            OrderField.LOCKED_BY_NAME,
        ],
        include_product=True,
        include_locked_by=True,
    )

    # 预定义配置：批次管理
    BATCH_CONFIG = SerializerConfig(
        fields=[
            OrderField.ID,
            OrderField.ORDER_NO,
            OrderField.CUSTOMER,
            OrderField.ORDER_DATE,
            OrderField.PRODUCT_ID,
            OrderField.PRODUCT_NAME,
            OrderField.QUANTITY,
            OrderField.STATUS,
            OrderField.BATCH_NO,
            OrderField.BATCH_COMPLETED_AT,
            OrderField.IS_LOCKED,
        ]
    )

    # 预定义配置：详情展示
    DETAIL_CONFIG = SerializerConfig(
        fields=[
            OrderField.ID,
            OrderField.ORDER_NO,
            OrderField.CUSTOMER,
            OrderField.ORDER_DATE,
            OrderField.PRODUCT,
            OrderField.QUANTITY,
            OrderField.DEDUCT_QUANTITY,
            OrderField.STATUS,
            OrderField.NOTE,
            OrderField.ORDER_TYPE,
            OrderField.COUNTRY,
            OrderField.IS_LOCKED,
            OrderField.LOCKED_BY_NAME,
            OrderField.BATCH_NO,
            OrderField.BATCH_COMPLETED_AT,
        ],
        include_product=True,
        include_locked_by=True,
    )

    # 基础字段到模型属性的映射
    _FIELD_MAP: dict[OrderField, str] = {
        OrderField.ID: "id",
        OrderField.ORDER_NO: "order_no",
        OrderField.CUSTOMER: "customer",
        OrderField.ORDER_DATE: "order_date",
        OrderField.PRODUCT_ID: "product_id",
        OrderField.QUANTITY: "quantity",
        OrderField.STATUS: "status",
        OrderField.NOTE: "note",
        OrderField.ORDER_TYPE: "order_type",
        OrderField.COUNTRY: "country",
        OrderField.IS_LOCKED: "is_locked",
        OrderField.BATCH_NO: "batch_no",
        OrderField.BATCH_COMPLETED_AT: "batch_completed_at",
    }

    @classmethod
    def serialize(
        cls, order: "Order", config: SerializerConfig, **context
    ) -> dict:
        """序列化订单对象

        Args:
            order: 订单模型实例
            config: 序列化配置
            **context: 额外上下文数据（如 deduct_quantity）

        Returns:
            序列化后的字典数据
        """
        result: dict = {}

        # 处理基础字段
        for field in config.fields:
            attr_name = cls._FIELD_MAP.get(field)
            if attr_name:
                value = getattr(order, attr_name, None)
                result[attr_name] = cls._format_value(field, value)

        # 处理特殊字段
        if OrderField.DEDUCT_QUANTITY in config.fields:
            result["deduct_quantity"] = context.get("deduct_quantity", 0)

        if OrderField.PRODUCT in config.fields:
            if config.include_product and order.product:
                result["product"] = {
                    "id": order.product.id,
                    "name": order.product.name,
                    "barcode": order.product.barcode or "",
                    "image": order.product.image or "",
                }
            else:
                result["product"] = None

        if OrderField.PRODUCT_NAME in config.fields:
            if order.product:
                result["product_name"] = order.product.name
            else:
                result["product_name"] = None

        if OrderField.LOCKED_BY_NAME in config.fields:
            if config.include_locked_by and order.locked_by:
                result["locked_by_name"] = order.locked_by.username
            else:
                result["locked_by_name"] = None

        return result

    @classmethod
    def _format_value(cls, field: OrderField, value):
        """格式化字段值

        Args:
            field: 字段枚举
            value: 原始值

        Returns:
            格式化后的值
        """
        if value is None:
            return ""

        if field == OrderField.ORDER_DATE:
            return value.strftime("%Y-%m-%d %H:%M")

        if field == OrderField.BATCH_COMPLETED_AT:
            return value.isoformat()

        return value
