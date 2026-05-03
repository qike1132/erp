"""
批量提交订单数据验证和修复
防止Data too long错误 (FastAPI 兼容版本)
"""


def validate_and_truncate_order_data(order_data):
    """
    验证并截断订单数据,防止超出数据库字段长度限制

    Args:
        order_data: 订单数据字典

    Returns:
        tuple: (validated_data, warnings)
    """
    warnings = []
    validated_data = order_data.copy()

    # 字段长度限制
    FIELD_LIMITS = {
        'customer': 100,  # 客户名称最多100字符
        'note': 1000,     # 备注最多1000字符
    }

    # 验证并截断customer字段
    customer = order_data.get('customer', '')
    if len(customer) > FIELD_LIMITS['customer']:
        validated_data['customer'] = customer[:FIELD_LIMITS['customer']]
        warnings.append(f"客户名称已截断: {len(customer)} -> {FIELD_LIMITS['customer']} 字符")

    # 验证并截断note字段
    note = order_data.get('note', '')
    if len(note) > FIELD_LIMITS['note']:
        validated_data['note'] = note[:FIELD_LIMITS['note']]
        warnings.append(f"备注已截断: {len(note)} -> {FIELD_LIMITS['note']} 字符")

    return validated_data, warnings


def safe_batch_submit_orders(orders_data):
    """
    安全的批量提交订单

    Args:
        orders_data: 订单数据列表

    Returns:
        dict: 处理结果
    """
    from datetime import datetime

    from fastapi_app.core.database import SyncSessionLocal
    from fastapi_app.shared_models import InventoryLog, Order, Product
    from utils.number_generator import generate_order_number

    success_count = 0
    failed_orders = []
    warnings = []

    session = SyncSessionLocal()
    try:
        for order_data in orders_data:
            try:
                # 验证并截断数据
                validated_data, data_warnings = validate_and_truncate_order_data(order_data)
                warnings.extend(data_warnings)

                # 生成订单编号
                order_no = generate_order_number(session, Order)

                # 验证订单编号长度
                if len(order_no) > 20:
                    raise ValueError(f"订单编号过长: {order_no} ({len(order_no)} 字符)")

                # 提取数据
                product_id_str = str(validated_data.get('productId', '')).strip()
                quantity_str = str(validated_data.get('quantity', '')).strip()
                note = validated_data.get('note', '')
                customer = validated_data.get('customer', '')

                # 验证必填字段
                if not product_id_str:
                    raise ValueError('请选择产品')

                if not quantity_str or quantity_str == '0':
                    raise ValueError('请输入有效的数量')

                product_id = int(product_id_str)
                quantity = int(quantity_str)

                # 验证产品存在
                product = session.query(Product).get(product_id)
                if not product:
                    raise ValueError('产品不存在')

                # 创建订单
                order = Order(
                    order_no=order_no,
                    customer=customer,
                    order_date=datetime.now(),
                    product_id=product_id,
                    quantity=quantity,
                    note=note,
                    status='待备货'
                )
                session.add(order)
                session.flush()

                # 更新库存
                product.current_stock += quantity

                # 记录库存日志
                log_order = InventoryLog(
                    product_id=product_id,
                    change_type='订单',
                    change_quantity=quantity,
                    related_id=order_no,
                    note=f'订单：{order_no}'
                )
                session.add(log_order)

                success_count += 1

            except Exception as e:
                failed_orders.append({
                    'order': order_data,
                    'error': str(e)
                })

        # 提交事务
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

    return {
        'success_count': success_count,
        'failed_orders': failed_orders,
        'warnings': warnings
    }


if __name__ == '__main__':
    print("批量提交订单数据验证模块")
    print("\n使用方法:")
    print("1. 在批量提交API中导入此模块")
    print("2. 使用validate_and_truncate_order_data()验证数据")
    print("3. 或使用safe_batch_submit_orders()安全提交")
