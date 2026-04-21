"""
数据验证框架
提供统一的数据验证机制
"""
from functools import wraps
from typing import Dict, Any, List, Optional
import re


class ValidationError(Exception):
    """验证错误异常"""
    def __init__(self, errors: Dict[str, str]):
        self.errors = errors
        super().__init__(str(errors))


class Validator:
    """验证器基类"""
    
    def __init__(self):
        self.errors = {}
    
    def validate_required(self, value: Any, field_name: str) -> bool:
        """验证必填字段"""
        if value is None or (isinstance(value, str) and not value.strip()):
            self.errors[field_name] = f'{field_name}不能为空'
            return False
        return True
    
    def validate_string(self, value: Any, field_name: str, 
                       min_length: int = None, max_length: int = None) -> bool:
        """验证字符串"""
        if not isinstance(value, str):
            self.errors[field_name] = f'{field_name}必须是字符串'
            return False
        
        if min_length and len(value) < min_length:
            self.errors[field_name] = f'{field_name}长度不能小于{min_length}'
            return False
        
        if max_length and len(value) > max_length:
            self.errors[field_name] = f'{field_name}长度不能超过{max_length}'
            return False
        
        return True
    
    def validate_integer(self, value: Any, field_name: str,
                        min_value: int = None, max_value: int = None) -> bool:
        """验证整数"""
        try:
            int_value = int(value)
        except (ValueError, TypeError):
            self.errors[field_name] = f'{field_name}必须是有效的整数'
            return False
        
        if min_value is not None and int_value < min_value:
            self.errors[field_name] = f'{field_name}不能小于{min_value}'
            return False
        
        if max_value is not None and int_value > max_value:
            self.errors[field_name] = f'{field_name}不能大于{max_value}'
            return False
        
        return True
    
    def validate_float(self, value: Any, field_name: str,
                      min_value: float = None, max_value: float = None) -> bool:
        """验证浮点数"""
        try:
            float_value = float(value)
        except (ValueError, TypeError):
            self.errors[field_name] = f'{field_name}必须是有效的数字'
            return False
        
        if min_value is not None and float_value < min_value:
            self.errors[field_name] = f'{field_name}不能小于{min_value}'
            return False
        
        if max_value is not None and float_value > max_value:
            self.errors[field_name] = f'{field_name}不能大于{max_value}'
            return False
        
        return True
    
    def validate_email(self, value: str, field_name: str) -> bool:
        """验证邮箱"""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, value):
            self.errors[field_name] = f'{field_name}不是有效的邮箱地址'
            return False
        return True
    
    def validate_phone(self, value: str, field_name: str) -> bool:
        """验证手机号"""
        pattern = r'^1[3-9]\d{9}$'
        if not re.match(pattern, value):
            self.errors[field_name] = f'{field_name}不是有效的手机号'
            return False
        return True
    
    def validate_in_list(self, value: Any, field_name: str, 
                        allowed_values: List[Any]) -> bool:
        """验证值在允许列表中"""
        if value not in allowed_values:
            self.errors[field_name] = f'{field_name}必须是以下值之一: {allowed_values}'
            return False
        return True
    
    def is_valid(self) -> bool:
        """检查是否验证通过"""
        return len(self.errors) == 0
    
    def get_errors(self) -> Dict[str, str]:
        """获取错误信息"""
        return self.errors


class ProductValidator(Validator):
    """产品验证器"""
    
    def validate_create(self, data: Dict) -> bool:
        """验证创建产品"""
        # 验证产品名称
        if not self.validate_required(data.get('name'), '产品名称'):
            pass
        elif not self.validate_string(data.get('name'), '产品名称', 1, 100):
            pass
        
        # 验证条码
        if data.get('barcode'):
            self.validate_string(data.get('barcode'), '条码', 1, 50)
        
        # 验证库存
        if data.get('initial_stock') is not None:
            self.validate_integer(data.get('initial_stock'), '初始库存', 0)
        
        if data.get('current_stock') is not None:
            self.validate_integer(data.get('current_stock'), '当前库存', 0)
        
        return self.is_valid()
    
    def validate_update(self, data: Dict) -> bool:
        """验证更新产品"""
        # 名称可选,但如果提供了就验证
        if data.get('name'):
            self.validate_string(data.get('name'), '产品名称', 1, 100)
        
        if data.get('barcode'):
            self.validate_string(data.get('barcode'), '条码', 1, 50)
        
        if data.get('initial_stock') is not None:
            self.validate_integer(data.get('initial_stock'), '初始库存', 0)
        
        if data.get('current_stock') is not None:
            self.validate_integer(data.get('current_stock'), '当前库存', 0)
        
        return self.is_valid()


class OrderValidator(Validator):
    """订单验证器"""
    
    def validate_create(self, data: Dict) -> bool:
        """验证创建订单"""
        # 验证客户名称
        if not self.validate_required(data.get('customer'), '客户名称'):
            pass
        elif not self.validate_string(data.get('customer'), '客户名称', 1, 100):
            pass
        
        # 验证产品ID
        if not self.validate_required(data.get('product_id'), '产品ID'):
            pass
        else:
            self.validate_integer(data.get('product_id'), '产品ID', 1)
        
        # 验证数量
        if not self.validate_required(data.get('quantity'), '数量'):
            pass
        else:
            self.validate_integer(data.get('quantity'), '数量', 1)
        
        # 验证状态
        if data.get('status'):
            self.validate_in_list(data.get('status'), '状态', 
                                ['待备货', '部分备货', '已备货', '待出货', '已出货', '已取消'])
        
        return self.is_valid()


class StockInValidator(Validator):
    """备货验证器"""
    
    def validate_create(self, data: Dict) -> bool:
        """验证创建备货"""
        # 验证客户名称
        if not self.validate_required(data.get('customer'), '客户名称'):
            pass
        elif not self.validate_string(data.get('customer'), '客户名称', 1, 100):
            pass
        
        # 验证产品ID
        if not self.validate_required(data.get('product_id'), '产品ID'):
            pass
        else:
            self.validate_integer(data.get('product_id'), '产品ID', 1)
        
        # 验证数量
        if not self.validate_required(data.get('quantity'), '数量'):
            pass
        else:
            self.validate_integer(data.get('quantity'), '数量', 1)
        
        return self.is_valid()


class StockOutValidator(Validator):
    """出货验证器"""
    
    def validate_create(self, data: Dict) -> bool:
        """验证创建出货"""
        # 验证产品ID
        if not self.validate_required(data.get('product_id'), '产品ID'):
            pass
        else:
            self.validate_integer(data.get('product_id'), '产品ID', 1)
        
        # 验证数量
        if not self.validate_required(data.get('quantity'), '数量'):
            pass
        else:
            self.validate_integer(data.get('quantity'), '数量', 1)
        
        # 验证客户名称(可选)
        if data.get('customer'):
            self.validate_string(data.get('customer'), '客户名称', 1, 100)
        
        return self.is_valid()


class DeductionValidator(Validator):
    """抵扣验证器"""
    
    def validate_deduction(self, data: Dict) -> bool:
        """验证抵扣参数"""
        # 验证订单ID
        if not self.validate_required(data.get('order_id'), '订单ID'):
            pass
        else:
            self.validate_integer(data.get('order_id'), '订单ID', 1)
        
        # 验证抵扣数量（可选）
        if data.get('deduct_quantity') is not None:
            self.validate_integer(data.get('deduct_quantity'), '抵扣数量', 1)
        
        return self.is_valid()


class CustomerValidator(Validator):
    """客户验证器"""
    
    def validate_create(self, data: Dict) -> bool:
        """验证创建客户"""
        if not self.validate_required(data.get('name'), '客户名称'):
            pass
        elif not self.validate_string(data.get('name'), '客户名称', 1, 100):
            pass
        
        if data.get('customer_code'):
            self.validate_string(data.get('customer_code'), '客户编码', 1, 50)
        
        if data.get('contact'):
            self.validate_string(data.get('contact'), '联系人', 1, 50)
        
        if data.get('phone'):
            if not self.validate_string(data.get('phone'), '联系电话', 1, 20):
                pass
        
        if data.get('address'):
            self.validate_string(data.get('address'), '地址', 1, 200)
        
        return self.is_valid()
    
    def validate_update(self, data: Dict) -> bool:
        """验证更新客户"""
        if data.get('name'):
            self.validate_string(data.get('name'), '客户名称', 1, 100)
        
        if data.get('customer_code'):
            self.validate_string(data.get('customer_code'), '客户编码', 1, 50)
        
        if data.get('contact'):
            self.validate_string(data.get('contact'), '联系人', 1, 50)
        
        if data.get('phone'):
            self.validate_string(data.get('phone'), '联系电话', 1, 20)
        
        if data.get('address'):
            self.validate_string(data.get('address'), '地址', 1, 200)
        
        return self.is_valid()
    
    def validate_sync(self, data: Dict) -> bool:
        """验证同步参数"""
        if data.get('customer_ids'):
            if not isinstance(data.get('customer_ids'), list):
                self.errors['customer_ids'] = '客户ID列表必须是数组'
            else:
                for cid in data.get('customer_ids'):
                    if not isinstance(cid, int) or cid < 1:
                        self.errors['customer_ids'] = '客户ID必须是正整数'
                        break
        
        if data.get('force') is not None:
            if not isinstance(data.get('force'), bool):
                self.errors['force'] = 'force参数必须是布尔值'
        
        return self.is_valid()
    
    def validate_query(self, data: Dict) -> bool:
        """验证查询参数"""
        if data.get('page') is not None:
            self.validate_integer(data.get('page'), '页码', 1)
        
        if data.get('per_page') is not None:
            self.validate_integer(data.get('per_page'), '每页数量', 1, 100)
        
        if data.get('status') is not None:
            if data.get('status') not in ['active', 'inactive', 'all']:
                self.errors['status'] = '状态参数必须是 active、inactive 或 all'
        
        if data.get('keyword'):
            self.validate_string(data.get('keyword'), '搜索关键词', 1, 100)
        
        return self.is_valid()


class SearchValidator(Validator):
    """搜索验证器"""
    
    def validate_search(self, data: Dict) -> bool:
        """验证搜索参数"""
        # 验证搜索关键词
        keyword = data.get('q') or data.get('keyword') or data.get('query')
        if keyword:
            self.validate_string(keyword, '搜索关键词', 1, 100)
        
        # 验证分页参数
        if data.get('page') is not None:
            self.validate_integer(data.get('page'), '页码', 1)
        
        if data.get('per_page') is not None:
            self.validate_integer(data.get('per_page'), '每页数量', 1, 100)
        
        return self.is_valid()


class DateRangeValidator(Validator):
    """日期范围验证器"""
    
    def validate_date_range(self, data: Dict) -> bool:
        """验证日期范围参数"""
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        if start_date:
            try:
                from datetime import datetime
                datetime.strptime(start_date, '%Y-%m-%d')
            except ValueError:
                self.errors['start_date'] = '开始日期格式无效，应为YYYY-MM-DD'
        
        if end_date:
            try:
                from datetime import datetime
                datetime.strptime(end_date, '%Y-%m-%d')
            except ValueError:
                self.errors['end_date'] = '结束日期格式无效，应为YYYY-MM-DD'
        
        # 验证日期范围是否合理
        if start_date and end_date and not self.errors:
            if start_date > end_date:
                self.errors['date_range'] = '开始日期不能晚于结束日期'
        
        return self.is_valid()


def validate_request(validator_class, method='create'):
    """请求验证装饰器 (FastAPI 兼容)"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # 在 FastAPI 中，验证应使用 Pydantic schemas 在请求层面完成
            # 此装饰器保留为兼容，实际验证逻辑已移至 Pydantic
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


# 使用示例
if __name__ == '__main__':
    # 测试产品验证
    validator = ProductValidator()
    data = {
        'name': '测试产品',
        'barcode': '6901234567890',
        'initial_stock': 100,
        'current_stock': 100
    }
    
    if validator.validate_create(data):
        print("验证通过")
    else:
        print("验证失败:", validator.get_errors())
