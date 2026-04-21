"""
统一的批量处理工具
用于批量导入、批量提交等场景
"""
from utils.excel_handler import excel_reader, validate_required_field, parse_quantity


def batch_import_unified_template(file, session, models, process_row_func):
    """
    统一导入模板处理函数
    支持产品、订单、备货三种类型的统一导入
    
    参数:
        file: 上传的文件对象
        session: SQLAlchemy Session
        models: 包含 Product, Order, StockIn, InventoryLog 等模型的字典
        process_row_func: 行处理函数
    
    返回:
        dict: 响应结果
    """
    Product = models['Product']
    Order = models['Order']
    StockIn = models['StockIn']
    InventoryLog = models['InventoryLog']
    
    expected_headers = ['导入类型', '客户名称', '产品名称', '69码', '数量', '时间', '是否抵扣备货', '备注']
    
    with excel_reader(file) as reader:
        if reader.error:
            return {'success': False, 'message': reader.error}
        
        success, actual_headers, error_msg = reader.validate_headers(expected_headers)
        if not success:
            return {'success': False, 'message': error_msg or f'表头格式不正确,期望:{expected_headers},实际:{actual_headers}'}
        
        success, error_msg = reader.check_data_rows()
        if not success:
            return {'success': False, 'message': error_msg}
        
        imported_products = 0
        imported_orders = 0
        imported_stockins = 0
        skipped = 0
        errors = []
        
        for row in range(2, reader.max_row + 1):
            try:
                import_type = reader.get_cell_value(row, 1)
                if not import_type:
                    errors.append(f'第{row}行：导入类型不能为空')
                    skipped += 1
                    continue
                
                import_type = str(import_type).strip()
                
                if import_type == '产品':
                    success, error = process_row_func(
                        'product', row, reader, Product, Order, StockIn, InventoryLog, session
                    )
                    if success:
                        imported_products += 1
                    else:
                        if error:
                            errors.append(error)
                        skipped += 1
                        
                elif import_type == '订单':
                    success, error = process_row_func(
                        'order', row, reader, Product, Order, StockIn, InventoryLog, session
                    )
                    if success:
                        imported_orders += 1
                    else:
                        if error:
                            errors.append(error)
                        skipped += 1
                        
                elif import_type == '备货':
                    success, error = process_row_func(
                        'stockin', row, reader, Product, Order, StockIn, InventoryLog, session
                    )
                    if success:
                        imported_stockins += 1
                    else:
                        if error:
                            errors.append(error)
                        skipped += 1
                        
                else:
                    errors.append(f'第{row}行：导入类型"{import_type}"无效，必须是：产品、订单、备货')
                    skipped += 1
                    
            except Exception as e:
                errors.append(f'第{row}行处理失败:{str(e)}')
                skipped += 1
                continue
        
        total_imported = imported_products + imported_orders + imported_stockins
        if total_imported > 0:
            session.commit()
        else:
            session.rollback()
            if errors:
                return {'success': False, 'message': '没有成功导入任何数据。错误信息:' + '; '.join(errors[:5])}
            else:
                return {'success': False, 'message': '没有成功导入任何数据,请检查数据格式'}
        
        result = {
            'imported_products': imported_products,
            'imported_orders': imported_orders,
            'imported_stockins': imported_stockins,
            'total_imported': total_imported,
            'skipped': skipped
        }
        
        if errors:
            result['warnings'] = errors[:10]
        
        message = f'成功导入: 产品{imported_products}个, 订单{imported_orders}个, 备货{imported_stockins}个'
        return {'success': True, 'message': message, **result}


def batch_import_template(
    file,
    expected_headers,
    row_processor,
    model_name='数据',
    session=None
):
    """
    统一的批量导入模板函数
    
    参数:
        file: 上传的文件对象
        expected_headers: 期望的表头列表
        row_processor: 行处理函数,签名: (row, get_cell_value) -> (success, error)
        model_name: 模型名称(用于错误消息)
        session: SQLAlchemy Session (可选)
    
    返回:
        dict: 响应结果
    """
    if session is None:
        from fastapi_app.core.database import SyncSession
        with SyncSession() as session:
            return _do_batch_import(file, expected_headers, row_processor, model_name, session)
    else:
        return _do_batch_import(file, expected_headers, row_processor, model_name, session)


def _do_batch_import(file, expected_headers, row_processor, model_name, session):
    """内部批量导入实现"""
    with excel_reader(file) as reader:
        if reader.error:
            return {'success': False, 'message': reader.error}
        
        success, actual_headers, error_msg = reader.validate_headers(expected_headers)
        if not success:
            return {'success': False, 'message': error_msg or f'表头格式不正确,期望:{expected_headers},实际:{actual_headers}'}
        
        success, error_msg = reader.check_data_rows()
        if not success:
            return {'success': False, 'message': error_msg}
        
        imported = 0
        skipped = 0
        errors = []
        
        for row in range(2, reader.max_row + 1):
            try:
                success, error = row_processor(row, reader.get_cell_value)
                
                if success:
                    imported += 1
                else:
                    if error:
                        errors.append(error)
                    skipped += 1
                    
            except Exception as e:
                errors.append(f'第{row}行处理失败:{str(e)}')
                skipped += 1
                continue
        
        if imported > 0:
            session.commit()
        else:
            session.rollback()
            if errors:
                return {'success': False, 'message': '没有成功导入任何' + model_name + '。错误信息:' + '; '.join(errors[:5])}
            else:
                return {'success': False, 'message': f'没有成功导入任何{model_name},请检查数据格式'}
        
        result = {
            'imported': imported,
            'skipped': skipped
        }
        
        if errors:
            result['warnings'] = errors[:10]
        
        return {'success': True, 'message': f'成功导入{imported}个{model_name}', **result}


def common_batch_validator(required_fields):
    """
    通用的批量提交验证器生成器
    
    参数:
        required_fields: 必填字段列表,格式: [(field_name, field_type, error_name), ...]
            field_type: 'int', 'str', 'date'
    
    返回:
        验证函数
    """
    def validator(data):
        validated_data = {}
        
        for field_name, field_type, error_name in required_fields:
            if field_type == 'int':
                value_str = str(data.get(field_name, '')).strip()
                if not value_str:
                    return None, f'{error_name}不能为空'
                try:
                    value = int(float(value_str))
                    if value < 1:
                        return None, f'{error_name}不能小于1'
                    validated_data[field_name] = value
                except (ValueError, TypeError):
                    return None, f'{error_name}必须是有效的数字'
                
            elif field_type == 'str':
                value = str(data.get(field_name, '')).strip()
                if not value:
                    return None, f'{error_name}不能为空'
                validated_data[field_name] = value
                
            elif field_type == 'date':
                date_str = data.get(field_name, '')
                if not date_str:
                    return None, f'{error_name}不能为空'
                try:
                    from datetime import datetime
                    validated_data[field_name] = datetime.strptime(str(date_str).strip(), '%Y-%m-%d')
                except (ValueError, TypeError):
                    return None, f'{error_name}格式错误'
        
        return validated_data, None
    
    return validator