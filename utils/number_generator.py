"""
通用编号生成器工具
用于统一生成各类业务单据编号,消除重复代码
"""
import contextlib
from datetime import datetime

from sqlalchemy import func


class NumberGenerator:
    """编号生成器类，用于在批量操作中维护序号计数器"""

    _instance = None
    _counters: dict = {}  # noqa: RUF012 - singleton: 编号计数器跨实例共享，属有意设计
    _initialized: dict = {}  # noqa: RUF012 - singleton: 初始化标记跨实例共享，属有意设计

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def is_initialized(self, prefix, date_str):
        """检查计数器是否已初始化"""
        key = f"{prefix}:{date_str}"
        return self._initialized.get(key, False)

    def set_initialized(self, prefix, date_str):
        """标记计数器已初始化"""
        key = f"{prefix}:{date_str}"
        self._initialized[key] = True

    def reset_counter(self, prefix, date_str):
        """重置指定前缀和日期的计数器"""
        key = f"{prefix}:{date_str}"
        self._counters[key] = 0
        self._initialized[key] = False

    def get_next_seq(self, prefix, date_str, current_max):
        """获取下一个序号"""
        key = f"{prefix}:{date_str}"
        if key not in self._counters:
            self._counters[key] = current_max
        else:
            self._counters[key] = max(self._counters[key], current_max)
        self._counters[key] += 1
        result = self._counters[key]
        self._initialized[key] = True
        return result


# 全局实例
_number_generator = NumberGenerator()


def generate_number(prefix, model, date_field, number_field, db):
    """
    通用编号生成器

    Args:
        prefix: 编号前缀 (如 'PO'订单, 'SI'备货, 'SO'出货)
        model: 数据模型类
        date_field: 日期字段名称
        number_field: 编号字段名称
        db: SQLAlchemy Session 实例 (支持 sqlalchemy.orm.Session)

    Returns:
        str: 生成的编号,格式为 PREFIX-YYYYMMDD-XXXX (4位序号，支持到9999)

    Example:
        >>> generate_number('PO', Order, 'order_date', 'order_no', session)
        'PO-20260321-0001'
    """
    today = datetime.now()
    date_str = today.strftime('%Y%m%d')

    # 如果计数器还没有初始化，从数据库查询最大序号
    if not _number_generator.is_initialized(prefix, date_str):
        # 兼容 sqlalchemy.orm.Session 对象
        session = getattr(db, 'session', db)
        with session.no_autoflush:
            records = session.query(model).filter(
                func.date(getattr(model, date_field)) == today.date()
            ).order_by(getattr(model, number_field).desc()).all()

            db_max = 0
            if records and records[0]:
                last_number = getattr(records[0], number_field)
                with contextlib.suppress(ValueError, IndexError):
                    db_max = int(last_number.split('-')[-1])

            # 初始化计数器，但不生成编号
            _number_generator.get_next_seq(prefix, date_str, db_max)

    # 获取下一个序号
    current_seq = _number_generator.get_next_seq(prefix, date_str, 0)

    # 生成新编号，使用4位序号（支持到9999）
    new_number = f"{prefix}-{date_str}-{str(current_seq).zfill(4)}"

    return new_number


def generate_order_number(db, order_model):
    """
    生成订单编号

    Args:
        db: SQLAlchemy Session 实例
        Order: order_model 模型类

    Returns:
        str: 订单编号,格式为 PO-YYYYMMDD-XXXX

    Example:
        >>> generate_order_number(session, Order)
        'PO-20260321-0001'
    """
    return generate_number('PO', order_model, 'order_date', 'order_no', db)


def generate_stockin_number(db, stockin_model):
    """
    生成备货编号

    Args:
        db: SQLAlchemy Session 实例
        StockIn: stockin_model 模型类

    Returns:
        str: 备货编号,格式为 SI-YYYYMMDD-XXXX

    Example:
        >>> generate_stockin_number(session, StockIn)
        'SI-20260321-0001'
    """
    return generate_number('SI', stockin_model, 'stockin_date', 'stockin_no', db)


def generate_stockout_number(db, stockout_model):
    """
    生成出货编号

    Args:
        db: SQLAlchemy Session 实例
        StockOut: stockout_model 模型类

    Returns:
        str: 出货编号,格式为 SO-YYYYMMDD-XXXX

    Example:
        >>> generate_stockout_number(session, StockOut)
        'SO-20260321-0001'
    """
    return generate_number('SO', stockout_model, 'stockout_date', 'stockout_no', db)


def generate_case_stockin_number(db, case_stockin_model):
    """
    生成皮套入库编号

    Args:
        db: SQLAlchemy Session 实例
        CaseStockIn: CaseStockIn模型类

    Returns:
        str: 皮套入库编号,格式为 CSI-YYYYMMDD-XXXX
    """
    return generate_number('CSI', case_stockin_model, 'stockin_date', 'stockin_no', db)


def generate_case_stockout_number(db, case_stockout_model):
    """
    生成皮套出库编号

    Args:
        db: SQLAlchemy Session 实例
        CaseStockOut: CaseStockOut模型类

    Returns:
        str: 皮套出库编号,格式为 CSO-YYYYMMDD-XXXX
    """
    return generate_number('CSO', case_stockout_model, 'stockout_date', 'stockout_no', db)
