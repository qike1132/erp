"""
通用编号生成器工具
用于统一生成各类业务单据编号,消除重复代码
"""
from datetime import datetime
from sqlalchemy import func


def generate_number(prefix, model, date_field, number_field, db):
    """
    通用编号生成器
    
    Args:
        prefix: 编号前缀 (如 'PO'订单, 'SI'备货, 'SO'出货)
        model: 数据模型类
        date_field: 日期字段名称
        number_field: 编号字段名称
        db: SQLAlchemy实例
    
    Returns:
        str: 生成的编号,格式为 PREFIX-YYYYMMDD-XXX
    
    Example:
        >>> generate_number('PO', Order, 'order_date', 'order_no', db)
        'PO-20260321-001'
    """
    today = datetime.now().date()
    
    # 查询当天的所有记录,按编号降序排列
    records = model.query.filter(
        func.date(getattr(model, date_field)) == today
    ).order_by(getattr(model, number_field).desc()).all()
    
    # 计算序号
    if records and records[0]:
        last_number = getattr(records[0], number_field)
        try:
            # 从编号中提取序号部分 (格式: PREFIX-YYYYMMDD-XXX)
            seq = int(last_number.split('-')[-1])
        except (ValueError, IndexError):
            # 如果解析失败,从0开始
            seq = 0
    else:
        seq = 0
    
    # 生成新编号
    date_str = today.strftime('%Y%m%d')
    new_number = f"{prefix}-{date_str}-{str(seq + 1).zfill(3)}"
    
    return new_number


def generate_order_number(db, Order):
    """
    生成订单编号
    
    Args:
        db: SQLAlchemy实例
        Order: Order模型类
    
    Returns:
        str: 订单编号,格式为 PO-YYYYMMDD-XXX
    
    Example:
        >>> generate_order_number(db, Order)
        'PO-20260321-001'
    """
    return generate_number('PO', Order, 'order_date', 'order_no', db)


def generate_stockin_number(db, StockIn):
    """
    生成备货编号
    
    Args:
        db: SQLAlchemy实例
        StockIn: StockIn模型类
    
    Returns:
        str: 备货编号,格式为 SI-YYYYMMDD-XXX
    
    Example:
        >>> generate_stockin_number(db, StockIn)
        'SI-20260321-001'
    """
    return generate_number('SI', StockIn, 'stockin_date', 'stockin_no', db)


def generate_stockout_number(db, StockOut):
    """
    生成出货编号
    
    Args:
        db: SQLAlchemy实例
        StockOut: StockOut模型类
    
    Returns:
        str: 出货编号,格式为 SO-YYYYMMDD-XXX
    
    Example:
        >>> generate_stockout_number(db, StockOut)
        'SO-20260321-001'
    """
    return generate_number('SO', StockOut, 'stockout_date', 'stockout_no', db)


def generate_case_stockin_number(db, CaseStockIn):
    """
    生成皮套入库编号
    
    Args:
        db: SQLAlchemy实例
        CaseStockIn: CaseStockIn模型类
    
    Returns:
        str: 皮套入库编号,格式为 CSI-YYYYMMDD-XXX
    
    Example:
        >>> generate_case_stockin_number(db, CaseStockIn)
        'CSI-20260321-001'
    """
    return generate_number('CSI', CaseStockIn, 'stockin_date', 'stockin_no', db)


def generate_case_stockout_number(db, CaseStockOut):
    """
    生成皮套出库编号
    
    Args:
        db: SQLAlchemy实例
        CaseStockOut: CaseStockOut模型类
    
    Returns:
        str: 皮套出库编号,格式为 CSO-YYYYMMDD-XXX
    
    Example:
        >>> generate_case_stockout_number(db, CaseStockOut)
        'CSO-20260321-001'
    """
    return generate_number('CSO', CaseStockOut, 'stockout_date', 'stockout_no', db)
