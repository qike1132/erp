"""
统一的装饰器和工具函数
用于减少代码重复,提高可维护性
"""
from datetime import datetime
from functools import wraps


def db_transaction(func):
    """
    数据库事务装饰器
    自动处理提交和回滚,减少重复的try-except代码
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            print(f"{func.__name__}错误: {e}")
            import traceback
            print(traceback.format_exc())
            return {'success': False, 'message': f'{func.__name__}失败', 'error': str(e)}
    return wrapper


def api_success(data=None, message='操作成功', **kwargs):
    """
    统一的成功响应格式

    参数:
        data: 返回的数据字典
        message: 成功消息
        **kwargs: 其他需要添加到响应中的字段

    返回:
        字典响应
    """
    response = {'success': True, 'message': message}
    if data:
        response.update(data)
    response.update(kwargs)
    return response


def api_error(message='操作失败', error=None, **kwargs):
    """
    统一的错误响应格式

    参数:
        message: 错误消息
        error: 异常对象或错误字符串
        **kwargs: 其他需要添加到响应中的字段

    返回:
        字典响应
    """
    response = {'success': False, 'message': message}
    if error:
        response['error'] = str(error)
    response.update(kwargs)
    return response


def validate_int_field(data, field_name, error_message, min_value=None, max_value=None):
    """
    统一的整数字段验证

    参数:
        data: 数据字典
        field_name: 字段名
        error_message: 错误消息前缀
        min_value: 最小值(可选)
        max_value: 最大值(可选)

    返回:
        (value, error): 成功返回(值, None), 失败返回(None, 错误消息)
    """
    value_str = str(data.get(field_name, '')).strip()

    if not value_str:
        return None, f'{error_message}不能为空'

    try:
        value = int(float(value_str))  # 支持浮点数转整数

        if min_value is not None and value < min_value:
            return None, f'{error_message}不能小于{min_value}'

        if max_value is not None and value > max_value:
            return None, f'{error_message}不能大于{max_value}'

        return value, None
    except (ValueError, TypeError):
        return None, f'{error_message}必须是有效的数字'


def parse_date(date_str, default=None):
    """
    统一的日期解析

    参数:
        date_str: 日期字符串(格式: YYYY-MM-DD)
        default: 解析失败时的默认值

    返回:
        datetime对象
    """
    if not date_str or not str(date_str).strip():
        return default or datetime.now()

    try:
        return datetime.strptime(str(date_str).strip(), '%Y-%m-%d')
    except ValueError:
        return default or datetime.now()


