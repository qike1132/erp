"""
统一的批量处理工具
用于批量导入、批量提交等场景
"""
from utils.decorators import api_error, api_success, parse_date, validate_int_field
from utils.excel_handler import excel_reader


def batch_import_unified_template(file, db, models, process_row_func):
    """
    统一导入模板处理函数
    支持产品、订单、备货三种类型的统一导入

    参数:
        file: 上传的文件对象
        db: 数据库实例
        models: 包含 Product, Order, StockIn, InventoryLog 等模型的字典
        process_row_func: 行处理函数

    返回:
        JSON响应
    """
    Product = models['Product']
    Order = models['Order']
    StockIn = models['StockIn']
    InventoryLog = models['InventoryLog']

    # 统一模板期望的表头
    expected_headers = ['导入类型', '客户名称', '产品名称', '69码', '数量', '时间', '是否抵扣备货', '备注']

    with excel_reader(file) as reader:
        if reader.error:
            return api_error(reader.error)

        # 验证表头
        success, actual_headers, error_msg = reader.validate_headers(expected_headers)
        if not success:
            return api_error(error_msg or f'表头格式不正确,期望:{expected_headers},实际:{actual_headers}')

        # 检查数据行
        success, error_msg = reader.check_data_rows()
        if not success:
            return api_error(error_msg)

        # 处理数据
        imported_products = 0
        imported_orders = 0
        imported_stockins = 0
        skipped = 0
        errors = []

        for row in range(2, reader.max_row + 1):
            try:
                # 读取导入类型
                import_type = reader.get_cell_value(row, 1)
                if not import_type:
                    errors.append(f'第{row}行：导入类型不能为空')
                    skipped += 1
                    continue

                import_type = str(import_type).strip()

                # 根据导入类型处理
                if import_type == '产品':
                    success, error = process_row_func(
                        'product', row, reader, Product, Order, StockIn, InventoryLog, db
                    )
                    if success:
                        imported_products += 1
                    else:
                        if error:
                            errors.append(error)
                        skipped += 1

                elif import_type == '订单':
                    success, error = process_row_func(
                        'order', row, reader, Product, Order, StockIn, InventoryLog, db
                    )
                    if success:
                        imported_orders += 1
                    else:
                        if error:
                            errors.append(error)
                        skipped += 1

                elif import_type == '备货':
                    success, error = process_row_func(
                        'stockin', row, reader, Product, Order, StockIn, InventoryLog, db
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

        # 提交事务
        total_imported = imported_products + imported_orders + imported_stockins
        if total_imported > 0:
            db.session.commit()
        else:
            db.session.rollback()
            if errors:
                return api_error('没有成功导入任何数据。错误信息:' + '; '.join(errors[:5]))
            else:
                return api_error('没有成功导入任何数据,请检查数据格式')

        # 返回结果
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
        return api_success(result, message)


def batch_import_template(
    file,
    expected_headers,
    row_processor,
    model_name='数据',
    db=None
):
    """
    统一的批量导入模板函数

    参数:
        file: 上传的文件对象
        expected_headers: 期望的表头列表
        row_processor: 行处理函数,签名: (row, get_cell_value) -> (success, error)
        model_name: 模型名称(用于错误消息)
        db: 数据库实例(可选,如果不提供则从app导入)

    返回:
        JSON响应

    用法:
        def process_order_row(row, get_cell_value):
            customer = get_cell_value(row, 1)
            # ... 处理逻辑
            return True, None  # 或 return False, '错误消息'

        return batch_import_template(
            file,
            ['客户名称', '产品名称', '订单数量', '备注'],
            process_order_row,
            '订单'
        )
    """
    # 如果没有提供db,则从app导入
    if db is None:
        from app import db

    # 使用Excel读取器
    with excel_reader(file) as reader:
        if reader.error:
            return api_error(reader.error)

        # 验证表头
        success, actual_headers, error_msg = reader.validate_headers(expected_headers)
        if not success:
            return api_error(error_msg or f'表头格式不正确,期望:{expected_headers},实际:{actual_headers}')

        # 检查数据行
        success, error_msg = reader.check_data_rows()
        if not success:
            return api_error(error_msg)

        # 处理数据
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

        # 提交事务
        if imported > 0:
            db.session.commit()
        else:
            db.session.rollback()
            if errors:
                return api_error('没有成功导入任何' + model_name + '。错误信息:' + '; '.join(errors[:5]))
            else:
                return api_error(f'没有成功导入任何{model_name},请检查数据格式')

        # 返回结果
        result = {
            'imported': imported,
            'skipped': skipped
        }

        if errors:
            result['warnings'] = errors[:10]  # 最多返回10个警告

        return api_success(result, f'成功导入{imported}个{model_name}')


def batch_submit_template(
    data_key,
    item_validator,
    item_creator,
    success_message='提交成功'
):
    """
    统一的批量提交模板函数

    参数:
        data_key: 数据键名(如 'orders', 'stockins')
        item_validator: 项目验证函数,签名: (item_data) -> (success, error)
        item_creator: 项目创建函数,签名: (item_data) -> (success, error)
        success_message: 成功消息

    返回:
        装饰后的函数

    用法:
        def validate_order(data):
            # 验证逻辑
            return True, None  # 或 return False, '错误消息'

        def create_order(data):
            # 创建逻辑
            return True, None  # 或 return False, '错误消息'

        @app.route('/api/batch-submit-orders', methods=['POST'])
        @permission_required('order_manage')
        def batch_submit_orders():
            return batch_submit_template(
                'orders',
                validate_order,
                create_order,
                '订单'
            )()
    """
    def wrapper():
        from app import db
        from flask import request

        try:
            data = request.get_json()
            items_data = data.get(data_key, [])

            if not items_data:
                return api_error(f'没有{data_key}数据')

            success_count = 0
            failed_items = []

            for item_data in items_data:
                try:
                    # 验证
                    valid, error = item_validator(item_data)
                    if not valid:
                        failed_items.append({data_key[:-1]: item_data, 'error': error})
                        continue

                    # 创建
                    success, error = item_creator(item_data)
                    if success:
                        success_count += 1
                    else:
                        failed_items.append({data_key[:-1]: item_data, 'error': error})

                except Exception as e:
                    failed_items.append({data_key[:-1]: item_data, 'error': str(e)})

            # 提交事务
            db.session.commit()

            return api_success(
                {
                    'success_count': success_count,
                    'failed_count': len(failed_items),
                    f'failed_{data_key}': failed_items
                },
                f'成功提交{success_count}个{success_message}'
            )

        except Exception as e:
            db.session.rollback()
            return api_error('批量提交失败', e)

    return wrapper


def common_batch_validator(required_fields):
    """
    通用的批量提交验证器生成器

    参数:
        required_fields: 必填字段列表,格式: [(field_name, field_type, error_name), ...]
            field_type: 'int', 'str', 'date'

    返回:
        验证函数

    用法:
        validator = common_batch_validator([
            ('productId', 'int', '产品'),
            ('quantity', 'int', '数量'),
            ('stockinDate', 'date', '备货时间')
        ])
    """
    def validator(data):
        validated_data = {}

        for field_name, field_type, error_name in required_fields:
            if field_type == 'int':
                value, error = validate_int_field(data, field_name, error_name, min_value=1)
                if error:
                    return None, error
                validated_data[field_name] = value

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
                    validated_data[field_name] = parse_date(date_str)
                except:
                    return None, f'{error_name}格式错误'

        return validated_data, None

    return validator
