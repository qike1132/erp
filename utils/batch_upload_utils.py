"""
批量上传工具模块

提供批量上传数据时的验证、解析、错误处理和事务处理功能。
"""

import re
from collections.abc import Callable
from datetime import datetime
from functools import wraps
from typing import Any

try:
    import openpyxl  # noqa: F401 - 依赖可用性探测（与 polars 同组导入）
    import polars as pl
except ImportError as err:
    raise ImportError("请安装 polars 和 openpyxl: pip install polars openpyxl") from err

try:
    from charset_normalizer import from_bytes as cn_from_bytes
except ImportError:
    cn_from_bytes = None

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


class BatchUploadError(Exception):
    """批量上传异常类"""
    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or []


def validate_customer_name(customer_name: str) -> tuple[bool, str]:
    """
    验证客户名称

    参数:
        customer_name: 客户名称字符串

    返回:
        Tuple[bool, str]: (是否有效，错误信息)
    """
    if not customer_name or not customer_name.strip():
        return False, "客户名称不能为空"

    customer_name = customer_name.strip()

    if len(customer_name) < 2:
        return False, "客户名称至少需要 2 个字符"

    if len(customer_name) > 100:
        return False, "客户名称不能超过 100 个字符"

    pattern = r'^[\u4e00-\u9fa5a-zA-Z0-9\s\-\_\.\,\(\)\（\）]+$'
    if not re.match(pattern, customer_name):
        return False, "客户名称包含非法字符"

    return True, ""


def validate_product(product_identifier: str, db_session: Session, product_model=None) -> tuple[bool, int | None, str]:
    """
    验证产品名称并返回产品 ID

    参数:
        product_identifier: 产品名称或条形码
        db_session: SQLAlchemy Session
        Product_model: Product 模型类（可选）

    返回:
        Tuple[bool, Optional[int], str]: (是否有效，产品 ID, 错误信息)
    """
    if not product_identifier or not product_identifier.strip():
        return False, None, "产品名称不能为空"

    product_identifier = product_identifier.strip()

    from utils.sanitizer import sanitize_plain_text
    product_identifier = sanitize_plain_text(product_identifier)

    if len(product_identifier) > 200:
        return False, None, "产品名称过长（最大200字符）"

    try:
        if product_model is None:
            from fastapi_app.shared_models.product import Product as Product_model

        product = db_session.query(Product_model).filter(
            (Product_model.name == product_identifier) |
            (Product_model.barcode == product_identifier)
        ).first()

        if not product:
            return False, None, f"产品不存在：{product_identifier}"

        return True, product.id, ""

    except SQLAlchemyError as e:
        return False, None, f"数据库查询失败：{e!s}"
    except Exception as e:
        return False, None, f"验证产品时发生错误：{e!s}"


def validate_quantity(quantity: Any, field_name: str = "数量") -> tuple[bool, int | None, str]:
    """验证数量"""
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
        return False, None, f"验证{field_name}时发生错误：{e!s}"


def validate_date(date_value: Any, field_name: str = "日期",
                  date_format: str | None = None) -> tuple[bool, datetime | None, str]:
    """验证日期格式"""
    if date_value is None or (isinstance(date_value, str) and not date_value.strip()):
        return False, None, f"{field_name}不能为空"

    try:
        if isinstance(date_value, datetime):
            return True, date_value, ""

        if isinstance(date_value, (int, float)):
            try:
                from datetime import timedelta
                base_date = datetime(1899, 12, 30)
                date_value = base_date + timedelta(days=date_value)
                return True, date_value, ""
            except Exception:
                return False, None, f"{field_name}格式不正确"

        date_str = str(date_value).strip()

        formats = [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%m-%d-%Y",
            "%m/%d/%Y",
        ]

        chinese_pattern = r'(\d{4})年(\d{1,2})月(\d{1,2})日'
        chinese_match = re.match(chinese_pattern, date_str)
        if chinese_match:
            try:
                year, month, day = map(int, chinese_match.groups())
                date_obj = datetime(year, month, day)
                return True, date_obj, ""
            except ValueError:
                pass

        chinese_datetime_pattern = r'(\d{4})年(\d{1,2})月(\d{1,2})日 (\d{1,2}):(\d{1,2}):(\d{1,2})'
        chinese_datetime_match = re.match(chinese_datetime_pattern, date_str)
        if chinese_datetime_match:
            try:
                year, month, day, hour, minute, second = map(int, chinese_datetime_match.groups())
                date_obj = datetime(year, month, day, hour, minute, second)
                return True, date_obj, ""
            except ValueError:
                pass

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
        return False, None, f"验证{field_name}时发生错误：{e!s}"


def detect_file_encoding(file_path: str) -> str:
    """检测文件编码"""
    if cn_from_bytes is None:
        return 'utf-8'

    try:
        with open(file_path, 'rb') as f:
            raw_data = f.read(10000)
            result = cn_from_bytes(raw_data).best()
            if result is None:
                return 'utf-8'
            encoding = result.encoding
            if encoding:
                encoding = encoding.lower()
                if encoding in ('utf8', 'utf_8'):
                    encoding = 'utf-8'
                elif encoding in ('gb2312', 'gb18030', 'cp949'):
                    encoding = 'gbk'
            return encoding or 'utf-8'
    except Exception:
        return 'utf-8'


def parse_excel_file(file_path: str, sheet_name: str | None = None) -> tuple[bool, list[dict[str, Any]], str]:
    """解析 Excel 文件返回数据列表（Polars 引擎）"""
    import math
    try:
        if sheet_name:
            df = pl.read_excel(file_path, sheet_name=sheet_name)
        else:
            df = pl.read_excel(file_path)
            if df is None or df.is_empty():
                return False, [], "Excel 文件为空"

        data_list = df.to_dicts()

        for row in data_list:
            for key, value in row.items():
                if isinstance(value, str):
                    row[key] = value.strip() if value else None
                elif isinstance(value, float) and math.isnan(value):
                    row[key] = None

        return True, data_list, ""

    except FileNotFoundError:
        return False, [], f"文件不存在：{file_path}"
    except Exception as e:
        return False, [], f"解析 Excel 文件失败：{e!s}"


def generate_error_report(errors: list[dict[str, Any]],
                         output_format: str = 'text') -> str:
    """生成错误报告"""
    if not errors:
        if output_format == 'json':
            return '{"success": true, "message": "无错误"}'
        elif output_format == 'html':
            return '<div class="alert alert-success">无错误</div>'
        else:
            return "无错误"

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

    else:
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
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        db_session = None
        for arg in args:
            if isinstance(arg, Session):
                db_session = arg
                break
        if not db_session and 'db_session' in kwargs:
            db_session = kwargs['db_session']

        if not db_session:
            raise ValueError("必须提供 SQLAlchemy Session 实例")

        try:
            result = func(*args, **kwargs)
            db_session.commit()
            return result
        except Exception as e:
            db_session.rollback()
            raise BatchUploadError(f"批量保存失败：{e!s}") from e

    return wrapper


def batch_save_with_transaction(data_list: list[dict[str, Any]],
                                db_session: Session,
                                model_class: Any,
                                mapping: dict[str, str],
                                validate_func: Callable | None = None) -> tuple[bool, list[dict[str, Any]], str]:
    """使用事务处理批量保存数据"""
    errors = []
    success_count = 0

    try:
        for idx, row_data in enumerate(data_list, start=2):
            try:
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

                mapped_data = {}
                for excel_field, model_field in mapping.items():
                    value = row_data.get(excel_field)

                    if value is not None:
                        mapped_data[model_field] = value

                unique_field = None
                for field in ['no', 'order_no', 'stockin_no', 'stockout_no']:
                    if field in mapped_data:
                        unique_field = field
                        break

                if unique_field:
                    existing = db_session.query(model_class).filter_by(
                        **{unique_field: mapped_data[unique_field]}
                    ).first()

                    if existing:
                        for key, value in mapped_data.items():
                            setattr(existing, key, value)
                    else:
                        new_record = model_class(**mapped_data)
                        db_session.add(new_record)
                else:
                    new_record = model_class(**mapped_data)
                    db_session.add(new_record)

                success_count += 1

            except Exception as e:
                errors.append({
                    'row': idx,
                    'field': '保存',
                    'value': str(row_data),
                    'message': str(e)
                })

        if errors:
            raise BatchUploadError(
                f"部分数据保存失败，成功 {success_count} 条，失败 {len(errors)} 条",
                errors
            )

        return True, [], ""

    except BatchUploadError:
        raise
    except Exception as e:
        db_session.rollback()
        return False, [], f"批量保存失败：{e!s}"


def validate_batch_data(data_list: list[dict[str, Any]],
                       validators: dict[str, callable],
                       db_session: Session = None) -> tuple[bool, list[dict[str, Any]], str]:
    """批量验证数据"""
    errors = []

    for idx, row_data in enumerate(data_list, start=2):
        for field, validator in validators.items():
            value = row_data.get(field)

            if value is None:
                continue

            try:
                if field == 'customer':
                    is_valid, error_msg = validator(value)
                    if not is_valid:
                        errors.append({
                            'row': idx,
                            'field': field,
                            'value': value,
                            'message': error_msg
                        })
                elif 'product' in field.lower() or '产品' in field:
                    import inspect
                    sig = inspect.signature(validator)
                    if len(sig.parameters) >= 2:
                        is_valid, product_id, error_msg = validator(value, db_session)
                    else:
                        is_valid, product_id, error_msg = validator(value)

                    if not is_valid:
                        errors.append({
                            'row': idx,
                            'field': field,
                            'value': value,
                            'message': error_msg
                        })
                    else:
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
                        row_data[f'_{field}_int'] = int_value
                elif 'date' in field.lower():
                    is_valid, date_obj, error_msg = validator(value, field)
                    if not is_valid:
                        errors.append({
                            'row': idx,
                            'field': field,
                            'value': value,
                            'message': error_msg
                        })
                    else:
                        row_data[f'_{field}_obj'] = date_obj
                else:
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
                    'message': f"验证出错：{e!s}"
                })

    if errors:
        return False, errors, f"验证失败，共发现 {len(errors)} 个错误"

    return True, [], ""
