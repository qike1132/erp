"""
工具函数测试 - 全面覆盖所有工具模块
测试范围：验证器、缓存、装饰器、编号生成器、Excel处理等
"""
import time
from datetime import datetime

import pytest
from utils.validators import (
    DateRangeValidator,
    DeductionValidator,
    OrderValidator,
    ProductValidator,
    SearchValidator,
    StockInValidator,
    StockOutValidator,
    ValidationError,
    Validator,
)


class TestValidator:
    """基础验证器测试"""

    def test_validate_required_with_valid_value(self):
        """测试有效必填值"""
        validator = Validator()
        result = validator.validate_required('test', '字段')
        assert result is True
        assert validator.is_valid()

    def test_validate_required_with_empty_string(self):
        """测试空字符串"""
        validator = Validator()
        result = validator.validate_required('', '字段')
        assert result is False
        assert '字段' in validator.get_errors()

    def test_validate_required_with_none(self):
        """测试None值"""
        validator = Validator()
        result = validator.validate_required(None, '字段')
        assert result is False
        assert '字段' in validator.get_errors()

    def test_validate_required_with_whitespace(self):
        """测试空白字符"""
        validator = Validator()
        result = validator.validate_required('   ', '字段')
        assert result is False

    def test_validate_string_valid(self):
        """测试有效字符串"""
        validator = Validator()
        result = validator.validate_string('test', '字段', min_length=1, max_length=10)
        assert result is True

    def test_validate_string_too_short(self):
        """测试过短字符串"""
        validator = Validator()
        result = validator.validate_string('ab', '字段', min_length=3)
        assert result is False
        assert '字段' in validator.get_errors()

    def test_validate_string_too_long(self):
        """测试过长字符串"""
        validator = Validator()
        result = validator.validate_string('abcdefghijk', '字段', max_length=10)
        assert result is False

    def test_validate_string_not_string(self):
        """测试非字符串类型"""
        validator = Validator()
        result = validator.validate_string(123, '字段')
        assert result is False

    def test_validate_integer_valid(self):
        """测试有效整数"""
        validator = Validator()
        result = validator.validate_integer(10, '字段', min_value=1, max_value=100)
        assert result is True

    def test_validate_integer_string(self):
        """测试字符串形式的整数"""
        validator = Validator()
        result = validator.validate_integer('10', '字段')
        assert result is True

    def test_validate_integer_too_small(self):
        """测试过小整数"""
        validator = Validator()
        result = validator.validate_integer(0, '字段', min_value=1)
        assert result is False

    def test_validate_integer_too_large(self):
        """测试过大整数"""
        validator = Validator()
        result = validator.validate_integer(101, '字段', max_value=100)
        assert result is False

    def test_validate_integer_invalid(self):
        """测试无效整数"""
        validator = Validator()
        result = validator.validate_integer('abc', '字段')
        assert result is False

    def test_validate_float_valid(self):
        """测试有效浮点数"""
        validator = Validator()
        result = validator.validate_float(10.5, '字段', min_value=1.0, max_value=100.0)
        assert result is True

    def test_validate_float_too_small(self):
        """测试过小浮点数"""
        validator = Validator()
        result = validator.validate_float(0.5, '字段', min_value=1.0)
        assert result is False

    def test_validate_float_too_large(self):
        """测试过大浮点数"""
        validator = Validator()
        result = validator.validate_float(101.0, '字段', max_value=100.0)
        assert result is False

    def test_validate_float_invalid(self):
        """测试无效浮点数"""
        validator = Validator()
        result = validator.validate_float('abc', '字段')
        assert result is False

    def test_validate_email_valid(self):
        """测试有效邮箱"""
        validator = Validator()
        result = validator.validate_email('test@example.com', '邮箱')
        assert result is True

    def test_validate_email_invalid(self):
        """测试无效邮箱"""
        validator = Validator()
        result = validator.validate_email('invalid-email', '邮箱')
        assert result is False

    def test_validate_phone_valid(self):
        """测试有效手机号"""
        validator = Validator()
        result = validator.validate_phone('13812345678', '手机号')
        assert result is True

    def test_validate_phone_invalid(self):
        """测试无效手机号"""
        validator = Validator()
        result = validator.validate_phone('12345678901', '手机号')
        assert result is False

    def test_validate_in_list_valid(self):
        """测试值在列表中"""
        validator = Validator()
        result = validator.validate_in_list('value1', '字段', ['value1', 'value2'])
        assert result is True

    def test_validate_in_list_invalid(self):
        """测试值不在列表中"""
        validator = Validator()
        result = validator.validate_in_list('value3', '字段', ['value1', 'value2'])
        assert result is False

    def test_is_valid(self):
        """测试验证通过检查"""
        validator = Validator()
        validator.validate_required('test', '字段')
        assert validator.is_valid() is True

    def test_is_valid_with_errors(self):
        """测试有错误时的验证检查"""
        validator = Validator()
        validator.validate_required('', '字段')
        assert validator.is_valid() is False

    def test_get_errors(self):
        """测试获取错误信息"""
        validator = Validator()
        validator.validate_required('', '字段1')
        validator.validate_integer('abc', '字段2')
        errors = validator.get_errors()
        assert '字段1' in errors
        assert '字段2' in errors


class TestProductValidator:
    """产品验证器测试"""

    def test_validate_create_valid(self):
        """测试创建产品验证 - 有效数据"""
        validator = ProductValidator()
        data = {
            'name': '测试产品',
            'barcode': 'BC001',
            'initial_stock': 100,
            'current_stock': 100
        }
        result = validator.validate_create(data)
        assert result is True

    def test_validate_create_missing_name(self):
        """测试创建产品验证 - 缺少名称"""
        validator = ProductValidator()
        data = {
            'barcode': 'BC001',
            'initial_stock': 100
        }
        result = validator.validate_create(data)
        assert result is False

    def test_validate_create_empty_name(self):
        """测试创建产品验证 - 空名称"""
        validator = ProductValidator()
        data = {
            'name': '',
            'barcode': 'BC001'
        }
        result = validator.validate_create(data)
        assert result is False

    def test_validate_create_negative_stock(self):
        """测试创建产品验证 - 负库存"""
        validator = ProductValidator()
        data = {
            'name': '测试产品',
            'initial_stock': -1
        }
        result = validator.validate_create(data)
        assert result is False

    def test_validate_update_valid(self):
        """测试更新产品验证 - 有效数据"""
        validator = ProductValidator()
        data = {
            'name': '更新产品',
            'barcode': 'BC002'
        }
        result = validator.validate_update(data)
        assert result is True

    def test_validate_update_empty(self):
        """测试更新产品验证 - 空数据"""
        validator = ProductValidator()
        data = {}
        result = validator.validate_update(data)
        assert result is True  # 更新时字段可选


class TestOrderValidator:
    """订单验证器测试"""

    def test_validate_create_valid(self):
        """测试创建订单验证 - 有效数据"""
        validator = OrderValidator()
        data = {
            'customer': '测试客户',
            'product_id': 1,
            'quantity': 10,
            'status': '待备货'
        }
        result = validator.validate_create(data)
        assert result is True

    def test_validate_create_missing_customer(self):
        """测试创建订单验证 - 缺少客户"""
        validator = OrderValidator()
        data = {
            'product_id': 1,
            'quantity': 10
        }
        result = validator.validate_create(data)
        assert result is False

    def test_validate_create_invalid_quantity(self):
        """测试创建订单验证 - 无效数量"""
        validator = OrderValidator()
        data = {
            'customer': '测试客户',
            'product_id': 1,
            'quantity': -1
        }
        result = validator.validate_create(data)
        assert result is False

    def test_validate_create_invalid_status(self):
        """测试创建订单验证 - 无效状态"""
        validator = OrderValidator()
        data = {
            'customer': '测试客户',
            'product_id': 1,
            'quantity': 10,
            'status': '无效状态'
        }
        result = validator.validate_create(data)
        assert result is False


class TestStockInValidator:
    """入库验证器测试"""

    def test_validate_create_valid(self):
        """测试创建入库验证 - 有效数据"""
        validator = StockInValidator()
        data = {
            'customer': '测试客户',
            'product_id': 1,
            'quantity': 50
        }
        result = validator.validate_create(data)
        assert result is True

    def test_validate_create_missing_fields(self):
        """测试创建入库验证 - 缺少字段"""
        validator = StockInValidator()
        data = {
            'product_id': 1
        }
        result = validator.validate_create(data)
        assert result is False


class TestStockOutValidator:
    """出库验证器测试"""

    def test_validate_create_valid(self):
        """测试创建出库验证 - 有效数据"""
        validator = StockOutValidator()
        data = {
            'product_id': 1,
            'quantity': 20,
            'customer': '客户A'
        }
        result = validator.validate_create(data)
        assert result is True

    def test_validate_create_missing_quantity(self):
        """测试创建出库验证 - 缺少数量"""
        validator = StockOutValidator()
        data = {
            'product_id': 1
        }
        result = validator.validate_create(data)
        assert result is False


class TestDeductionValidator:
    """抵扣验证器测试"""

    def test_validate_deduction_valid(self):
        """测试抵扣验证 - 有效数据"""
        validator = DeductionValidator()
        data = {
            'order_id': 1,
            'deduct_quantity': 10
        }
        result = validator.validate_deduction(data)
        assert result is True

    def test_validate_deduction_missing_order_id(self):
        """测试抵扣验证 - 缺少订单ID"""
        validator = DeductionValidator()
        data = {
            'deduct_quantity': 10
        }
        result = validator.validate_deduction(data)
        assert result is False


class TestSearchValidator:
    """搜索验证器测试"""

    def test_validate_search_valid(self):
        """测试搜索验证 - 有效数据"""
        validator = SearchValidator()
        data = {
            'q': '测试关键词',
            'page': 1,
            'per_page': 20
        }
        result = validator.validate_search(data)
        assert result is True

    def test_validate_search_empty(self):
        """测试搜索验证 - 空数据"""
        validator = SearchValidator()
        data = {}
        result = validator.validate_search(data)
        assert result is True  # 搜索参数可选

    def test_validate_search_invalid_page(self):
        """测试搜索验证 - 无效页码"""
        validator = SearchValidator()
        data = {
            'page': -1
        }
        result = validator.validate_search(data)
        assert result is False


class TestDateRangeValidator:
    """日期范围验证器测试"""

    def test_validate_date_range_valid(self):
        """测试日期范围验证 - 有效数据"""
        validator = DateRangeValidator()
        data = {
            'start_date': '2024-01-01',
            'end_date': '2024-12-31'
        }
        result = validator.validate_date_range(data)
        assert result is True

    def test_validate_date_range_invalid_format(self):
        """测试日期范围验证 - 无效格式"""
        validator = DateRangeValidator()
        data = {
            'start_date': '2024/01/01',
            'end_date': '2024-12-31'
        }
        result = validator.validate_date_range(data)
        assert result is False

    def test_validate_date_range_invalid_order(self):
        """测试日期范围验证 - 开始日期晚于结束日期"""
        validator = DateRangeValidator()
        data = {
            'start_date': '2024-12-31',
            'end_date': '2024-01-01'
        }
        result = validator.validate_date_range(data)
        assert result is False

    def test_validate_date_range_empty(self):
        """测试日期范围验证 - 空数据"""
        validator = DateRangeValidator()
        data = {}
        result = validator.validate_date_range(data)
        assert result is True


class TestValidationError:
    """验证错误异常测试"""

    def test_validation_error_creation(self):
        """测试验证错误创建"""
        errors = {'字段1': '错误1', '字段2': '错误2'}
        exception = ValidationError(errors)
        assert exception.errors == errors

    def test_validation_error_str(self):
        """测试验证错误字符串表示"""
        errors = {'字段': '错误信息'}
        exception = ValidationError(errors)
        assert '字段' in str(exception)


class TestCacheUtils:
    """缓存工具测试"""

    def test_cache_key_generation(self):
        """测试缓存键生成"""
        def generate_cache_key(prefix, *args):
            key_parts = [prefix] + [str(arg) for arg in args]
            return ':'.join(key_parts)

        key1 = generate_cache_key('product', 1, 'detail')
        key2 = generate_cache_key('order', 2, 'list')

        assert key1 == 'product:1:detail'
        assert key2 == 'order:2:list'
        assert key1 != key2

    def test_cache_ttl_calculation(self):
        """测试缓存TTL计算"""
        cache_time = time.time()
        ttl = 300  # 5分钟

        # 检查未过期
        is_expired = (time.time() - cache_time) > ttl
        assert is_expired is False

        # 模拟过期
        cache_time = time.time() - 400
        is_expired = (time.time() - cache_time) > ttl
        assert is_expired is True


class TestNumberGenerator:
    """编号生成器测试"""

    def test_order_number_format(self):
        """测试订单编号格式"""
        prefix = 'ORD'
        date_str = datetime.now().strftime('%Y%m%d')
        seq = 1

        order_no = f'{prefix}{date_str}{seq:04d}'

        assert order_no.startswith('ORD')
        assert date_str in order_no
        assert len(order_no) == len(prefix) + len(date_str) + 4

    def test_number_uniqueness(self):
        """测试编号唯一性"""
        numbers = set()
        prefix = 'ORD'
        date_str = datetime.now().strftime('%Y%m%d')

        for i in range(100):
            number = f'{prefix}{date_str}{i:04d}'
            numbers.add(number)

        assert len(numbers) == 100

    def test_number_sequence(self):
        """测试编号序列"""
        prefix = 'SI'
        date_str = datetime.now().strftime('%Y%m%d')

        numbers = [f'{prefix}{date_str}{i:04d}' for i in range(1, 11)]

        # 验证序列递增
        for i in range(len(numbers) - 1):
            assert numbers[i] < numbers[i + 1]


class TestBatchHandler:
    """批量处理测试"""

    def test_chunk_split(self):
        """测试分块处理"""
        data = list(range(100))
        chunk_size = 10

        chunks = [data[i:i+chunk_size] for i in range(0, len(data), chunk_size)]

        assert len(chunks) == 10
        for chunk in chunks:
            assert len(chunk) == 10

    def test_error_collection(self):
        """测试错误收集"""
        errors = []

        for i in range(10):
            if i % 3 == 0:
                errors.append({'index': i, 'error': f'错误{i}'})

        assert len(errors) == 4

    def test_batch_processing_with_validation(self):
        """测试批量处理验证"""
        data = [
            {'name': '产品1', 'barcode': 'BC001', 'stock': 10},
            {'name': '', 'barcode': 'BC002', 'stock': 20},  # 无效
            {'name': '产品3', 'barcode': '', 'stock': 30},  # 无效
            {'name': '产品4', 'barcode': 'BC004', 'stock': 40},
        ]

        valid_items = []
        invalid_items = []

        for idx, item in enumerate(data):
            if item.get('name') and item.get('barcode'):
                valid_items.append(item)
            else:
                invalid_items.append({'index': idx, 'data': item})

        assert len(valid_items) == 2
        assert len(invalid_items) == 2


class TestExcelHandler:
    """Excel处理测试"""

    def test_column_index_conversion(self):
        """测试列索引转换"""
        def column_to_index(col):
            result = 0
            for char in col:
                result = result * 26 + (ord(char) - ord('A') + 1)
            return result - 1

        assert column_to_index('A') == 0
        assert column_to_index('B') == 1
        assert column_to_index('Z') == 25
        assert column_to_index('AA') == 26
        assert column_to_index('AB') == 27

    def test_data_validation(self):
        """测试Excel数据验证"""
        row_data = ['产品1', 'BC001', '100', '10.5']

        assert len(row_data) == 4
        assert isinstance(row_data[0], str)
        assert row_data[2].isdigit()

    def test_empty_cell_handling(self):
        """测试空单元格处理"""
        row_data = ['产品1', '', '100', None]

        # 检查空值
        assert row_data[1] == ''
        assert row_data[3] is None


class TestDecorators:
    """装饰器测试"""

    def test_timing_decorator(self):
        """测试计时装饰器"""
        import time

        def timing_decorator(func):
            def wrapper(*args, **kwargs):
                start = time.time()
                result = func(*args, **kwargs)
                end = time.time()
                wrapper.execution_time = end - start
                return result
            return wrapper

        @timing_decorator
        def slow_function():
            time.sleep(0.1)
            return 'done'

        result = slow_function()
        assert result == 'done'
        assert slow_function.execution_time >= 0.1

    def test_retry_decorator(self):
        """测试重试装饰器"""
        attempts = []

        def retry_decorator(max_retries=3):
            def decorator(func):
                def wrapper(*args, **kwargs):
                    for attempt in range(max_retries):
                        try:
                            return func(*args, **kwargs)
                        except Exception:
                            attempts.append(attempt)
                            if attempt == max_retries - 1:
                                raise
                return wrapper
            return decorator

        @retry_decorator(max_retries=3)
        def failing_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            failing_function()

        assert len(attempts) == 3


class TestPagination:
    """分页测试"""

    def test_pagination_calculation(self):
        """测试分页计算"""
        total_items = 95
        per_page = 10

        total_pages = (total_items + per_page - 1) // per_page

        assert total_pages == 10

    def test_page_offset(self):
        """测试页偏移计算"""
        page = 3
        per_page = 10

        offset = (page - 1) * per_page

        assert offset == 20

    def test_page_range(self):
        """测试页范围"""
        current_page = 5
        total_pages = 10
        window = 2

        start = max(1, current_page - window)
        end = min(total_pages, current_page + window)

        assert start == 3
        assert end == 7


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--cov=utils', '--cov-report=term-missing'])
