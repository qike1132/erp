"""
分页查询工具
提供统一的分页查询功能
"""
from flask import request


def get_pagination_params():
    """
    从请求参数中获取分页参数
    
    Returns:
        tuple: (page, per_page)
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    # 限制每页最大数量
    if per_page > 100:
        per_page = 100
    
    return page, per_page


def paginate_query(query, page=None, per_page=None, error_out=False):
    """
    对查询进行分页
    
    Args:
        query: SQLAlchemy查询对象
        page: 页码,默认从请求参数获取
        per_page: 每页数量,默认从请求参数获取
        error_out: 是否在超出范围时报错
    
    Returns:
        Pagination: SQLAlchemy分页对象
    """
    if page is None or per_page is None:
        page, per_page = get_pagination_params()
    
    return query.paginate(
        page=page,
        per_page=per_page,
        error_out=error_out
    )


def format_pagination_result(pagination, item_serializer=None):
    """
    格式化分页结果为JSON格式
    
    Args:
        pagination: SQLAlchemy分页对象
        item_serializer: 可选的序列化函数
    
    Returns:
        dict: 分页结果字典
    """
    items = pagination.items
    
    if item_serializer:
        items = [item_serializer(item) for item in items]
    elif hasattr(items[0], 'to_dict') if items else False:
        items = [item.to_dict() for item in items]
    
    return {
        'items': items,
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'pages': pagination.pages,
        'has_prev': pagination.has_prev,
        'has_next': pagination.has_next,
        'prev_num': pagination.prev_num,
        'next_num': pagination.next_num
    }


def get_paginated_products(query, page=None, per_page=None):
    """
    获取分页的产品列表
    
    Args:
        query: 产品查询对象
        page: 页码
        per_page: 每页数量
    
    Returns:
        dict: 分页结果
    """
    pagination = paginate_query(query, page, per_page)
    
    items = []
    for product in pagination.items:
        items.append({
            'id': product.id,
            'name': product.name,
            'barcode': product.barcode,
            'image': product.image,
            'initial_stock': product.initial_stock,
            'current_stock': product.current_stock,
            'create_time': product.create_time.strftime('%Y-%m-%d %H:%M:%S') if product.create_time else ''
        })
    
    return format_pagination_result(pagination, lambda p: items[pagination.items.index(p)])


def get_paginated_orders(query, page=None, per_page=None):
    """
    获取分页的订单列表
    
    Args:
        query: 订单查询对象
        page: 页码
        per_page: 每页数量
    
    Returns:
        dict: 分页结果
    """
    pagination = paginate_query(query, page, per_page)
    
    items = []
    for order in pagination.items:
        items.append({
            'id': order.id,
            'order_no': order.order_no,
            'customer': order.customer,
            'product_name': order.product.name if order.product else '',
            'quantity': order.quantity,
            'status': order.status,
            'order_date': order.order_date.strftime('%Y-%m-%d %H:%M:%S') if order.order_date else '',
            'note': order.note or ''
        })
    
    return format_pagination_result(pagination, lambda o: items[pagination.items.index(o)])
