"""
工具函数单元测试
测试number_generator、decorators等工具模块
"""
import pytest
from datetime import datetime
from unittest.mock import Mock
from utils.number_generator import generate_number, generate_order_number, generate_stockin_number
from utils.decorators import api_success, api_error, validate_int_field


@pytest.mark.unit
class TestNumberGenerator:
    """编号生成器测试"""
    
    def test_generate_number_first_of_day(self, test_app):
        """测试当天第一个编号"""
        with test_app.app_context():
            from app import db
            
            # Mock查询返回空列表
            mock_model = Mock()
            mock_model.query.filter.return_value.order_by.return_value.all.return_value = []
            
            number = generate_number('PO', mock_model, 'order_date', 'order_no', db)
            
            today_str = datetime.now().strftime('%Y%m%d')
            assert number == f'PO-{today_str}-001'
    
    def test_generate_number_sequential(self, test_app):
        """测试序号递增"""
        with test_app.app_context():
            from app import db
            
            # Mock查询返回已有记录
            mock_record = Mock()
            mock_record.order_no = f'PO-{datetime.now().strftime("%Y%m%d")}-005'
            
            mock_model = Mock()
            mock_model.query.filter.return_value.order_by.return_value.all.return_value = [mock_record]
            
            number = generate_number('PO', mock_model, 'order_date', 'order_no', db)
            
            today_str = datetime.now().strftime('%Y%m%d')
            assert number == f'PO-{today_str}-006'
    
    def test_generate_number_format(self, test_app):
        """测试编号格式"""
        with test_app.app_context():
            from app import db
            
            mock_model = Mock()
            mock_model.query.filter.return_value.order_by.return_value.all.return_value = []
            
            number = generate_number('SI', mock_model, 'stockin_date', 'stockin_no', db)
            
            # 验证格式: PREFIX-YYYYMMDD-XXX
            parts = number.split('-')
            assert len(parts) == 3
            assert parts[0] == 'SI'
            assert len(parts[1]) == 8  # YYYYMMDD
            assert len(parts[2]) == 3  # XXX
    
    def test_generate_order_number(self, test_app):
        """测试订单编号生成"""
        with test_app.app_context():
            from app import db
            
            mock_model = Mock()
            mock_model.query.filter.return_value.order_by.return_value.all.return_value = []
            
            number = generate_order_number(db, mock_model)
            assert number.startswith('PO-')
    
    def test_generate_stockin_number(self, test_app):
        """测试备货编号生成"""
        with test_app.app_context():
            from app import db
            
            mock_model = Mock()
            mock_model.query.filter.return_value.order_by.return_value.all.return_value = []
            
            number = generate_stockin_number(db, mock_model)
            assert number.startswith('SI-')


@pytest.mark.unit
class TestDecorators:
    """装饰器测试"""
    
    def test_api_success(self, test_app):
        """测试成功响应格式"""
        with test_app.app_context():
            result = api_success({'data': 'test'}, '操作成功')
            assert result.json['success'] is True
            assert result.json['message'] == '操作成功'
            assert result.json['data'] == 'test'
    
    def test_api_error(self, test_app):
        """测试错误响应格式"""
        with test_app.app_context():
            result = api_error('操作失败', Exception('测试错误'))
            assert result.json['success'] is False
            assert result.json['message'] == '操作失败'
            assert '测试错误' in result.json['error']
    
    def test_validate_int_field_valid(self):
        """测试整数字段验证 - 有效值"""
        data = {'quantity': '10'}
        value, error = validate_int_field(data, 'quantity', '数量')
        assert value == 10
        assert error is None
    
    def test_validate_int_field_empty(self):
        """测试整数字段验证 - 空值"""
        data = {'quantity': ''}
        value, error = validate_int_field(data, 'quantity', '数量')
        assert value is None
        assert '不能为空' in error
    
    def test_validate_int_field_invalid(self):
        """测试整数字段验证 - 无效值"""
        data = {'quantity': 'abc'}
        value, error = validate_int_field(data, 'quantity', '数量')
        assert value is None
        assert '必须是有效的数字' in error
    
    def test_validate_int_field_min_value(self):
        """测试整数字段验证 - 最小值"""
        data = {'quantity': '-5'}
        value, error = validate_int_field(data, 'quantity', '数量', min_value=0)
        assert value is None
        assert '不能小于' in error
    
    def test_validate_int_field_max_value(self):
        """测试整数字段验证 - 最大值"""
        data = {'quantity': '1000'}
        value, error = validate_int_field(data, 'quantity', '数量', max_value=100)
        assert value is None
        assert '不能大于' in error


@pytest.mark.unit
class TestExcelHandler:
    """Excel处理工具测试"""
    
    def test_excel_handler_import(self):
        """测试Excel处理模块导入"""
        try:
            from utils.excel_handler import ExcelHandler
            assert ExcelHandler is not None
        except ImportError:
            pytest.skip("ExcelHandler not available")


@pytest.mark.unit
class TestBatchHandler:
    """批量处理工具测试"""
    
    def test_batch_handler_import(self):
        """测试批量处理模块导入"""
        try:
            from utils.batch_handler import BatchHandler
            assert BatchHandler is not None
        except ImportError:
            pytest.skip("BatchHandler not available")
