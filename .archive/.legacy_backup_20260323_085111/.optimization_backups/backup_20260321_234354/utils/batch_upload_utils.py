"""
批量上传工具模块

提供批量上传数据时的验证、解析、错误处理和事务处理功能。
"""

import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from functools import wraps

try:
    import pandas as pd
    from openpyxl import load_workbook
except ImportError:
    raise ImportError("请安装 pandas 和 openpyxl: pip install pandas openpyxl")

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import SQLAlchemyError


class BatchUploadError(Exception):
    """批量上传异常类"""
    def __init__(self, message: str, errors: List[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or []


def validate_customer_name(customer_name: str) -> Tuple[bool, str]:
    """
    验证客户名称
    
    参数:
        customer_name: 客户名称字符串
        
    返回:
        Tuple[bool, str]: (是否有效，错误信息)
        
    验证规则:
        1. 不能为空
        2. 长度在 2-100 个字符之间
        3. 只能包含中文、英文、数字、空格和常见标点符号
    """
    if not customer_name or not customer_name.strip():
        return False, "客户名称不能为空"
    
    customer_name = customer_name.strip()
    
    if len(customer_name) < 2:
        return False, "客户名称至少需要 2 个字符"
    
    if len(customer_name) > 100:
        return False, "客户名称不能超过 100 个字符"
    
    # 允许中文、英文、数字、空格和常见标点符号
    pattern = r'^[\u4e00-\u9fa5a-zA-Z0-9\s\-\_\.\,\(\)\（\）]+$'
    if not re.match(pattern, customer_name):
        return False, "客户名称包含非法字符"
    
    return True, ""


def validate_product(product_identifier: str, db: SQLAlchemy, Product_model=None) -> Tuple[bool, Optional[int], str]:
    """
    验证产品名称并返回产品 ID
    
    参数:
        product_identifier: 产品名称或条形码
        db: SQLAlchemy 数据库实例
        Product_model: Product 模型类（可选，避免循环导入）
        
    返回:
        Tuple[bool, Optional[int], str]: (是否有效，产品 ID, 错误信息)
        
    验证规则:
        1. 不能为空
        2. 产品必须存在于数据库中
        3. 支持通过产品名称或条形码查找
    """
    if not product_identifier or not product_identifier.strip():
        return False, None, "产品名称不能为空"
    
    product_identifier = product_identifier.strip()
    
    try:
        # 如果没有传入 Product 模型，则从 app 导入
        if Product_model is None:
            from app import Product as Product_model
        
        # 尝试通过名称或条形码查找产品
        product = Product_model.query.filter(
            (Product_model.name == product_identifier) | 
            (Product_model.barcode == product_identifier)
        ).first()
        
        if not product:
            return False, None, f"产品不存在：{product_identifier}"
        
        return True, product.id, ""
        
    except SQLAlchemyError as e:
        return False, None, f"数据库查询失败：{str(e)}"
    except Exception as e:
        return False, None, f"验证产品时发生错误：{str(e)}"


def validate_quantity(quantity: Any, field_name: str = "数量") -> Tuple[bool, Optional[int], str]:
    """
    验证数量
    
    参数:
        quantity: 数量值（可以是字符串或数字）
        field_name: 字段名称，用于错误提示
        
    返回:
        Tuple[bool, Optional[int], str]: (是否有效，转换后的整数，错误信息)
        
    验证规则:
        1. 不能为空
        2. 必须是整数或可转换为整数的字符串
        3. 必须大于 0
    """
    if quantity is None or (isinstance(quantity, str) and not quantity.strip()):
        return False, None, f"{field_name}不能为空"
    
    try:
        quantity_int = int(quantity)
        
        if quantity_int <= 0:
            return False, None, f"{field_name}必须大于 0"
        
        return True, quantity_int, ""
        
    except ValueError:
        return False, None, f"{field_name}必须是有效的整数"
    except Exception as e:
        return False, None, f"验证{field_name}时发生错误：{str(e)}"


def validate_date(date_value: Any, field_name: str = "日期", 
                  date_format: str = None) -> Tuple[bool, Optional[datetime], str]:
    """
    验证日期格式
    
    参数:
        date_value: 日期值（可以是字符串、datetime 对象或 Excel 日期）
        field_name: 字段名称，用于错误提示
        date_format: 日期格式字符串，如 "%Y-%m-%d" 或 "%Y/%m/%d"
        
    返回:
        Tuple[bool, Optional[datetime], str]: (是否有效，转换后的 datetime 对象，错误信息)
        
    验证规则:
        1. 不能为空
        2. 必须是有效的日期格式
        3. 支持多种日期格式
    """
    if date_value is None or (isinstance(date_value, str) and not date_value.strip()):
        return False, None, f"{field_name}不能为空"
    
    try:
        # 如果已经是 datetime 对象
        if isinstance(date_value, datetime):
            return True, date_value, ""
        
        # 如果是 Excel 日期（数字格式）
        if isinstance(date_value, (int, float)):
            try:
                # Excel 日期从 1899-12-30 开始
                from datetime import timedelta
                base_date = datetime(1899, 12, 30)
                date_value = base_date + timedelta(days=date_value)
                return True, date_value, ""
            except Exception:
                return False, None, f"{field_name}格式不正确"
        
        # 字符串日期
        date_str = str(date_value).strip()
        
        # 尝试多种日期格式
        formats = [
            "%Y-%m-%d",           # 2024-01-15
            "%Y/%m/%d",           # 2024/01/15
            "%Y-%m-%d %H:%M:%S",  # 2024-01-15 10:30:00
            "%Y/%m/%d %H:%M:%S",  # 2024/01/15 10:30:00
            "%d-%m-%Y",           # 15-01-2024
            "%d/%m/%Y",           # 15/01/2024
            "%m-%d-%Y",           # 01-15-2024
            "%m/%d/%Y",           # 01/15/2024
        ]
        
        # 特殊处理中文日期格式（因为 %Y年%m月%d日 格式在 strptime 中可能不工作）
        chinese_pattern = r'(\d{4}) 年 (\d{1,2}) 月 (\d{1,2}) 日'
        chinese_match = re.match(chinese_pattern, date_str)
        if chinese_match:
            try:
                year, month, day = map(int, chinese_match.groups())
                date_obj = datetime(year, month, day)
                return True, date_obj, ""
            except ValueError:
                pass
        
        # 特殊处理中文日期时间格式
        chinese_datetime_pattern = r'(\d{4}) 年 (\d{1,2}) 月 (\d{1,2}) 日 (\d{1,2}):(\d{1,2}):(\d{1,2})'
        chinese_datetime_match = re.match(chinese_datetime_pattern, date_str)
        if chinese_datetime_match:
            try:
                year, month, day, hour, minute, second = map(int, chinese_datetime_match.groups())
                date_obj = datetime(year, month, day, hour, minute, second)
                return True, date_obj, ""
            except ValueError:
                pass
        
        # 如果指定了格式，优先使用指定格式
        if date_format:
            formats.insert(0, date_format)
        
        for fmt in formats:
            try:
                date_obj = datetime.strptime(date_str, fmt)
                return True, date_obj, ""
            except ValueError:
                continue
        
        return False, None, f"{field_name}格式不正确，支持格式：YYYY-MM-DD, YYYY/MM/DD 等"
        
    except Exception as e:
        return False, None, f"验证{field_name}时发生错误：{str(e)}"


def parse_excel_file(file_path: str, sheet_name: str = None) -> Tuple[bool, List[Dict[str, Any]], str]:
    """
    解析 Excel 文件返回数据列表
    
    参数:
        file_path: Excel 文件路径
        sheet_name: 工作表名称，默认为第一个工作表
        
    返回:
        Tuple[bool, List[Dict[str, Any]], str]: (是否成功，数据列表，错误信息)
        
    功能:
        1. 读取 Excel 文件
        2. 自动识别表头
        3. 返回字典列表
    """
    try:
        # 读取 Excel 文件
        if sheet_name:
            df = pd.read_excel(file_path, sheet_name=sheet_name)
        else:
            # 读取第一个工作表
            excel_file = pd.ExcelFile(file_path)
            sheet_name = excel_file.sheet_names[0]
            df = pd.read_excel(file_path, sheet_name=sheet_name)
        
        # 转换为字典列表
        data_list = df.to_dict(orient='records')
        
        # 清理数据：去除空值和空格
        for row in data_list:
            for key, value in row.items():
                if isinstance(value, str):
                    row[key] = value.strip() if value else None
                elif pd.isna(value):
                    row[key] = None
        
        return True, data_list, ""
        
    except FileNotFoundError:
        return False, [], f"文件不存在：{file_path}"
    except Exception as e:
        return False, [], f"解析 Excel 文件失败：{str(e)}"


def generate_error_report(errors: List[Dict[str, Any]], 
                         output_format: str = 'text') -> str:
    """
    生成错误报告
    
    参数:
        errors: 错误列表，每个错误是一个字典，包含：
            - row: 行号
            - field: 字段名
            - value: 原始值
            - message: 错误信息
        output_format: 输出格式 ('text', 'html', 'json')
        
    返回:
        str: 格式化的错误报告
        
    功能:
        1. 按行号分组错误
        2. 生成易读的错误报告
        3. 支持多种输出格式
    """
    if not errors:
        if output_format == 'json':
            return '{"success": true, "message": "无错误"}'
        elif output_format == 'html':
            return '<div class="alert alert-success">无错误</div>'
        else:
            return "无错误"
    
    # 按行号分组错误
    errors_by_row = {}
    for error in errors:
        row = error.get('row', 0)
        if row not in errors_by_row:
            errors_by_row[row] = []
        errors_by_row[row].append(error)
    
    if output_format == 'json':
        import json
        report = {
            'success': False,
            'total_errors': len(errors),
            'total_rows': len(errors_by_row),
            'errors': []
        }
        for row, row_errors in sorted(errors_by_row.items()):
            report['errors'].append({
                'row': row,
                'error_count': len(row_errors),
                'details': row_errors
            })
        return json.dumps(report, ensure_ascii=False, indent=2)
    
    elif output_format == 'html':
        html = ['<div class="error-report">']
        html.append(f'<h4>发现 {len(errors)} 个错误，涉及 {len(errors_by_row)} 行</h4>')
        html.append('<table class="table table-bordered">')
        html.append('<thead><tr><th>行号</th><th>字段</th><th>值</th><th>错误信息</th></tr></thead>')
        html.append('<tbody>')
        
        for row, row_errors in sorted(errors_by_row.items()):
            for i, error in enumerate(row_errors):
                html.append('<tr>')
                if i == 0:
                    html.append(f'<td rowspan="{len(row_errors)}">{row}</td>')
                html.append(f'<td>{error.get("field", "")}</td>')
                html.append(f'<td>{error.get("value", "")}</td>')
                html.append(f'<td class="text-danger">{error.get("message", "")}</td>')
                html.append('</tr>')
        
        html.append('</tbody></table></div>')
        return ''.join(html)
    
    else:  # text format
        lines = [f"发现 {len(errors)} 个错误，涉及 {len(errors_by_row)} 行", "=" * 50]
        for row, row_errors in sorted(errors_by_row.items()):
            lines.append(f"\n第 {row} 行:")
            for error in row_errors:
                lines.append(f"  - 字段：{error.get('field', '')}")
                lines.append(f"    值：{error.get('value', '')}")
                lines.append(f"    错误：{error.get('message', '')}")
        return '\n'.join(lines)


def transactional(func):
    """
    事务处理装饰器
    
    用于自动处理数据库事务，确保数据一致性。
    如果函数执行成功则提交事务，失败则回滚事务。
    
    使用示例:
        @transactional
        def batch_save_data(data, db):
            # 数据库操作
            pass
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # 从参数中获取 db 实例
        db = None
        for arg in args:
            if isinstance(arg, SQLAlchemy):
                db = arg
                break
        if not db and 'db' in kwargs:
            db = kwargs['db']
        
        if not db:
            raise ValueError("必须提供 SQLAlchemy 数据库实例")
        
        try:
            # 执行函数
            result = func(*args, **kwargs)
            # 提交事务
            db.session.commit()
            return result
        except Exception as e:
            # 回滚事务
            db.session.rollback()
            # 包装异常信息
            raise BatchUploadError(f"批量保存失败：{str(e)}") from e
    
    return wrapper


def batch_save_with_transaction(data_list: List[Dict[str, Any]], 
                                db: SQLAlchemy,
                                model_class: Any,
                                mapping: Dict[str, str],
                                validate_func: callable = None) -> Tuple[bool, List[Dict[str, Any]], str]:
    """
    使用事务处理批量保存数据
    
    参数:
        data_list: 数据列表
        db: SQLAlchemy 数据库实例
        model_class: 数据库模型类
        mapping: 字段映射字典，Excel 字段名 -> 模型字段名
        validate_func: 验证函数（可选），用于验证每行数据
        
    返回:
        Tuple[bool, List[Dict[str, Any]], str]: (是否成功，错误列表，错误信息)
        
    功能:
        1. 自动开启事务
        2. 逐行验证数据
        3. 批量插入/更新数据
        4. 失败时自动回滚
        5. 记录详细错误信息
    """
    errors = []
    success_count = 0
    
    try:
        for idx, row_data in enumerate(data_list, start=2):  # 从第 2 行开始（第 1 行是表头）
            try:
                # 数据验证
                if validate_func:
                    is_valid, error_msg = validate_func(row_data)
                    if not is_valid:
                        errors.append({
                            'row': idx,
                            'field': '整行',
                            'value': str(row_data),
                            'message': error_msg
                        })
                        continue
                
                # 字段映射和转换
                mapped_data = {}
                for excel_field, model_field in mapping.items():
                    # 直接尝试从 row_data 获取值
                    value = row_data.get(excel_field)
                    
                    if value is not None:
                        mapped_data[model_field] = value
                
                # 创建或更新记录
                # 这里假设使用 'id' 或 'no' 字段作为唯一标识
                unique_field = None
                for field in ['no', 'order_no', 'stockin_no', 'stockout_no']:
                    if field in mapped_data:
                        unique_field = field
                        break
                
                if unique_field:
                    # 更新现有记录
                    existing = model_class.query.filter_by(
                        **{unique_field: mapped_data[unique_field]}
                    ).first()
                    
                    if existing:
                        for key, value in mapped_data.items():
                            setattr(existing, key, value)
                    else:
                        # 创建新记录
                        new_record = model_class(**mapped_data)
                        db.session.add(new_record)
                else:
                    # 创建新记录
                    new_record = model_class(**mapped_data)
                    db.session.add(new_record)
                
                success_count += 1
                
            except Exception as e:
                errors.append({
                    'row': idx,
                    'field': '保存',
                    'value': str(row_data),
                    'message': str(e)
                })
        
        # 如果有任何错误，抛出异常触发回滚
        if errors:
            raise BatchUploadError(
                f"部分数据保存失败，成功 {success_count} 条，失败 {len(errors)} 条",
                errors
            )
        
        return True, [], ""
        
    except BatchUploadError:
        # 重新抛出，由装饰器处理回滚
        raise
    except Exception as e:
        db.session.rollback()
        return False, [], f"批量保存失败：{str(e)}"


def validate_batch_data(data_list: List[Dict[str, Any]], 
                       validators: Dict[str, callable],
                       db: SQLAlchemy = None) -> Tuple[bool, List[Dict[str, Any]], str]:
    """
    批量验证数据
    
    参数:
        data_list: 数据列表
        validators: 验证函数字典，字段名 -> 验证函数
        db: SQLAlchemy 数据库实例（可选）
        
    返回:
        Tuple[bool, List[Dict[str, Any]], str]: (是否全部验证通过，错误列表，错误信息)
        
    功能:
        1. 对每行数据应用所有验证器
        2. 收集所有验证错误
        3. 返回详细的错误报告
    """
    errors = []
    
    for idx, row_data in enumerate(data_list, start=2):  # 从第 2 行开始
        for field, validator in validators.items():
            value = row_data.get(field)
            
            # 跳过空值验证（如果需要必填，应该在 validator 中处理）
            if value is None:
                continue
            
            try:
                # 调用验证函数
                if field == 'customer':
                    is_valid, error_msg = validator(value)
                    if not is_valid:
                        errors.append({
                            'row': idx,
                            'field': field,
                            'value': value,
                            'message': error_msg
                        })
                elif field in ['product', 'product_id', 'product_name'] or 'product' in field.lower() or '产品' in field:
                    # 检查验证函数是否需要 db 参数
                    import inspect
                    sig = inspect.signature(validator)
                    if len(sig.parameters) >= 2:
                        is_valid, product_id, error_msg = validator(value, db)
                    else:
                        # 如果验证函数已经绑定了 db，直接调用
                        is_valid, product_id, error_msg = validator(value)
                    
                    if not is_valid:
                        errors.append({
                            'row': idx,
                            'field': field,
                            'value': value,
                            'message': error_msg
                        })
                    else:
                        # 保存产品 ID 供后续使用
                        row_data['_product_id'] = product_id
                elif field in ['quantity', 'qty']:
                    is_valid, int_value, error_msg = validator(value, field)
                    if not is_valid:
                        errors.append({
                            'row': idx,
                            'field': field,
                            'value': value,
                            'message': error_msg
                        })
                    else:
                        # 保存转换后的整数值
                        row_data[f'_{field}_int'] = int_value
                elif field in ['date', 'order_date', 'stockin_date', 'stockout_date']:
                    is_valid, date_obj, error_msg = validator(value, field)
                    if not is_valid:
                        errors.append({
                            'row': idx,
                            'field': field,
                            'value': value,
                            'message': error_msg
                        })
                    else:
                        # 保存转换后的日期对象
                        row_data[f'_{field}_obj'] = date_obj
                else:
                    # 通用验证
                    result = validator(value)
                    if isinstance(result, tuple) and len(result) >= 2:
                        is_valid, error_msg = result[0], result[1] if len(result) > 1 else ""
                        if not is_valid:
                            errors.append({
                                'row': idx,
                                'field': field,
                                'value': value,
                                'message': error_msg
                            })
                            
            except Exception as e:
                errors.append({
                    'row': idx,
                    'field': field,
                    'value': value,
                    'message': f"验证出错：{str(e)}"
                })
    
    if errors:
        return False, errors, f"验证失败，共发现 {len(errors)} 个错误"
    
    return True, [], ""
