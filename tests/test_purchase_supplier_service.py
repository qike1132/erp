"""purchase_supplier_service 单元测试"""
import pytest
from unittest.mock import MagicMock

from fastapi_app.services.purchase_supplier_service import get_suppliers, create_supplier


class TestPurchaseSupplierService:
    def test_get_suppliers(self):
        mock_db = MagicMock()
        s1 = MagicMock(id=1, name='Supplier A', contact_person='John', phone='123', address='Addr')
        s1.name = 'Supplier A'
        s1.contact_person = 'John'
        s1.phone = '123'
        s1.address = 'Addr'
        mock_db.query.return_value.order_by.return_value.all.return_value = [s1]
        suppliers = get_suppliers(mock_db)
        assert len(suppliers) == 1

    def test_get_suppliers_empty(self):
        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.all.return_value = []
        suppliers = get_suppliers(mock_db)
        assert len(suppliers) == 0

    def test_create_supplier(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        supplier = create_supplier(mock_db, {'name': 'New Supplier'})
        assert supplier is not None
