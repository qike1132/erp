"""
订单序列化器测试

验证 OrderSerializer 的正确性和一致性。
"""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from fastapi_app.services.serializers.order_serializer import (
    OrderField,
    OrderSerializer,
    SerializerConfig,
)


class TestOrderSerializer:
    """订单序列化器测试"""

    @pytest.fixture
    def mock_product(self):
        """Mock 产品对象"""
        product = MagicMock()
        product.id = 1
        product.name = "测试产品"
        product.barcode = "6901234567890"
        product.image = "test.jpg"
        return product

    @pytest.fixture
    def mock_user(self):
        """Mock 用户对象"""
        user = MagicMock()
        user.username = "admin"
        return user

    @pytest.fixture
    def mock_order(self, mock_product, mock_user):
        """Mock 订单对象"""
        order = MagicMock()
        order.id = 1
        order.order_no = "PO-20260101-0001"
        order.customer = "测试客户"
        order.order_date = datetime(2026, 1, 1, 10, 30)
        order.product_id = 1
        order.product = mock_product
        order.quantity = 50
        order.status = "待备货"
        order.note = "测试备注"
        order.order_type = "regular"
        order.country = None
        order.is_locked = False
        order.locked_by = mock_user
        order.batch_no = "BATCH-001"
        order.batch_completed_at = datetime(2026, 1, 15, 14, 0)
        return order

    @pytest.fixture
    def mock_order_minimal(self):
        """Mock 最小订单对象（无关联数据）"""
        order = MagicMock()
        order.id = 2
        order.order_no = "PO-20260101-0002"
        order.customer = "客户B"
        order.order_date = None
        order.product_id = None
        order.product = None
        order.quantity = 10
        order.status = None
        order.note = None
        order.order_type = "custom"
        order.country = "中国"
        order.is_locked = True
        order.locked_by = None
        order.batch_no = None
        order.batch_completed_at = None
        return order

    def test_list_config_basic(self, mock_order):
        """测试列表配置序列化"""
        result = OrderSerializer.serialize(mock_order, OrderSerializer.LIST_CONFIG)

        assert result["id"] == 1
        assert result["order_no"] == "PO-20260101-0001"
        assert result["customer"] == "测试客户"
        assert result["order_date"] == "2026-01-01 10:30"
        assert result["quantity"] == 50
        assert result["status"] == "待备货"
        assert result["note"] == "测试备注"
        assert result["order_type"] == "regular"
        assert result["country"] == ""
        assert result["is_locked"] is False
        assert result["deduct_quantity"] == 0

    def test_list_config_with_deduct_quantity(self, mock_order):
        """测试列表配置带抵扣数量"""
        result = OrderSerializer.serialize(
            mock_order, OrderSerializer.LIST_CONFIG, deduct_quantity=20
        )
        assert result["deduct_quantity"] == 20

    def test_list_config_product(self, mock_order):
        """测试列表配置产品信息"""
        result = OrderSerializer.serialize(mock_order, OrderSerializer.LIST_CONFIG)

        assert result["product"] is not None
        assert result["product"]["id"] == 1
        assert result["product"]["name"] == "测试产品"
        assert result["product"]["barcode"] == "6901234567890"
        assert result["product"]["image"] == "test.jpg"

    def test_list_config_locked_by(self, mock_order):
        """测试列表配置锁定人信息"""
        result = OrderSerializer.serialize(mock_order, OrderSerializer.LIST_CONFIG)
        assert result["locked_by_name"] == "admin"

    def test_batch_config(self, mock_order):
        """测试批次配置序列化"""
        result = OrderSerializer.serialize(mock_order, OrderSerializer.BATCH_CONFIG)

        assert result["id"] == 1
        assert result["order_no"] == "PO-20260101-0001"
        assert result["customer"] == "测试客户"
        assert result["order_date"] == "2026-01-01 10:30"
        assert result["product_id"] == 1
        assert result["product_name"] == "测试产品"
        assert result["quantity"] == 50
        assert result["status"] == "待备货"
        assert result["batch_no"] == "BATCH-001"
        assert result["batch_completed_at"] == "2026-01-15T14:00:00"
        assert result["is_locked"] is False

    def test_detail_config(self, mock_order):
        """测试详情配置序列化"""
        result = OrderSerializer.serialize(
            mock_order, OrderSerializer.DETAIL_CONFIG, deduct_quantity=30
        )

        assert result["id"] == 1
        assert result["deduct_quantity"] == 30
        assert result["product"] is not None
        assert result["locked_by_name"] == "admin"
        assert result["batch_no"] == "BATCH-001"
        assert result["batch_completed_at"] == "2026-01-15T14:00:00"

    def test_minimal_order(self, mock_order_minimal):
        """测试最小订单对象序列化"""
        result = OrderSerializer.serialize(
            mock_order_minimal, OrderSerializer.LIST_CONFIG
        )

        assert result["order_date"] == ""
        assert result["country"] == "中国"
        assert result["product"] is None
        assert result["locked_by_name"] is None
        assert result["note"] == ""

    def test_custom_config(self, mock_order):
        """测试自定义配置"""
        config = SerializerConfig(
            fields=[OrderField.ID, OrderField.ORDER_NO, OrderField.CUSTOMER],
            include_product=False,
            include_locked_by=False,
        )
        result = OrderSerializer.serialize(mock_order, config)

        assert "id" in result
        assert "order_no" in result
        assert "customer" in result
        assert "product" not in result
        assert "locked_by_name" not in result

    def test_none_product(self, mock_order_minimal):
        """测试无产品时的序列化"""
        result = OrderSerializer.serialize(
            mock_order_minimal, OrderSerializer.BATCH_CONFIG
        )

        assert result["product_name"] is None
        assert "product" not in result

    def test_none_locked_by(self, mock_order_minimal):
        """测试无锁定人时的序列化"""
        result = OrderSerializer.serialize(
            mock_order_minimal, OrderSerializer.LIST_CONFIG
        )

        assert result["locked_by_name"] is None

    def test_date_formatting(self, mock_order):
        """测试日期格式化"""
        result = OrderSerializer.serialize(mock_order, OrderSerializer.LIST_CONFIG)
        assert result["order_date"] == "2026-01-01 10:30"

    def test_iso_date_formatting(self, mock_order):
        """测试 ISO 日期格式化"""
        result = OrderSerializer.serialize(mock_order, OrderSerializer.BATCH_CONFIG)
        assert result["batch_completed_at"] == "2026-01-15T14:00:00"

    def test_none_date_handling(self, mock_order_minimal):
        """测试 None 日期处理"""
        result = OrderSerializer.serialize(
            mock_order_minimal, OrderSerializer.LIST_CONFIG
        )
        assert result["order_date"] == ""

    def test_none_batch_completed_at(self, mock_order_minimal):
        """测试 None 批次完成时间处理"""
        result = OrderSerializer.serialize(
            mock_order_minimal, OrderSerializer.BATCH_CONFIG
        )
        assert result["batch_completed_at"] == ""

    def test_config_immutability(self):
        """测试配置不可变性"""
        config = OrderSerializer.LIST_CONFIG

        with pytest.raises(AttributeError):
            config.fields = []

    def test_field_map_coverage(self):
        """测试字段映射覆盖所有基础字段"""
        expected_fields = [
            OrderField.ID,
            OrderField.ORDER_NO,
            OrderField.CUSTOMER,
            OrderField.ORDER_DATE,
            OrderField.PRODUCT_ID,
            OrderField.QUANTITY,
            OrderField.STATUS,
            OrderField.NOTE,
            OrderField.ORDER_TYPE,
            OrderField.COUNTRY,
            OrderField.IS_LOCKED,
            OrderField.BATCH_NO,
            OrderField.BATCH_COMPLETED_AT,
        ]

        for field in expected_fields:
            assert field in OrderSerializer._FIELD_MAP

    def test_serialize_returns_dict(self, mock_order):
        """测试序列化返回字典"""
        result = OrderSerializer.serialize(mock_order, OrderSerializer.LIST_CONFIG)
        assert isinstance(result, dict)

    def test_empty_context(self, mock_order):
        """测试空上下文"""
        result = OrderSerializer.serialize(mock_order, OrderSerializer.LIST_CONFIG)
        assert result["deduct_quantity"] == 0

    def test_context_override(self, mock_order):
        """测试上下文覆盖"""
        result = OrderSerializer.serialize(
            mock_order, OrderSerializer.LIST_CONFIG, deduct_quantity=100
        )
        assert result["deduct_quantity"] == 100


class TestSerializerConfig:
    """序列化器配置测试"""

    def test_config_creation(self):
        """测试配置创建"""
        config = SerializerConfig(
            fields=[OrderField.ID, OrderField.ORDER_NO],
            include_product=True,
            include_locked_by=True,
        )
        assert len(config.fields) == 2
        assert config.include_product is True
        assert config.include_locked_by is True

    def test_config_defaults(self):
        """测试配置默认值"""
        config = SerializerConfig(fields=[OrderField.ID])
        assert config.include_product is False
        assert config.include_locked_by is False

    def test_frozen_config(self):
        """测试配置冻结"""
        config = SerializerConfig(fields=[OrderField.ID])

        with pytest.raises(AttributeError):
            config.fields = [OrderField.ORDER_NO]

        with pytest.raises(AttributeError):
            config.include_product = True
