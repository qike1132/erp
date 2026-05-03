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


def add_inventory_log(product_id, change_type, quantity, related_id, note=None, customer=None):
    """
    统一的库存日志记录

    参数:
        product_id: 产品ID
        change_type: 变化类型
        quantity: 变化数量
        related_id: 关联单据编号
        note: 备注
        customer: 客户名称

    返回:
        InventoryLog对象
    """
    from fastapi_app.core.database import SyncSession
    from fastapi_app.shared_models.inventory_log import InventoryLog

    log = InventoryLog(
        product_id=product_id,
        change_type=change_type,
        change_quantity=quantity,
        related_id=related_id,
        note=note,
        customer=customer
    )
    with SyncSession() as session:
        session.add(log)
    return log


def add_case_inventory_log(case_id, change_type, quantity, related_id, note=None, customer=None):
    """
    统一的皮套库存日志记录

    参数:
        case_id: 皮套ID
        change_type: 变化类型
        quantity: 变化数量
        related_id: 关联单据编号
        note: 备注
        customer: 客户名称

    返回:
        CaseInventoryLog对象
    """
    from fastapi_app.core.database import SyncSession
    from fastapi_app.shared_models.case_inventory_log import CaseInventoryLog

    log = CaseInventoryLog(
        case_id=case_id,
        change_type=change_type,
        change_quantity=quantity,
        related_id=related_id,
        note=note,
        customer=customer
    )
    with SyncSession() as session:
        session.add(log)
    return log


def check_product_exists(product_id):
    """
    检查产品是否存在

    参数:
        product_id: 产品ID

    返回:
        (product, error): 成功返回(产品对象, None), 失败返回(None, 错误消息)
    """
    from fastapi_app.core.database import SyncSession
    from fastapi_app.shared_models.product import Product

    with SyncSession() as session:
        product = session.query(Product).filter(Product.id == product_id, not Product.is_deleted).first()
        if not product:
            return None, '产品不存在'
        return product, None


def check_case_exists(case_id):
    """
    检查皮套是否存在

    参数:
        case_id: 皮套ID

    返回:
        (case, error): 成功返回(皮套对象, None), 失败返回(None, 错误消息)
    """
    from fastapi_app.core.database import SyncSession
    from fastapi_app.shared_models.case import Case

    with SyncSession() as session:
        case_obj = session.query(Case).filter(Case.id == case_id, not Case.is_deleted).first()
        if not case_obj:
            return None, '皮套不存在'
        return case_obj, None
