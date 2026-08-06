"""
批量导入处理工具
用于统一处理Excel批量导入逻辑,消除重复代码
"""
import contextlib
import math
import os
import re
from datetime import datetime

import polars as pl


def secure_filename(filename: str) -> str:
    """安全文件名处理

    移除路径分隔符和危险字符，保留ASCII字母、数字、下划线、点号和连字符。
    """
    if not filename:
        return ""
    # 分离文件名和扩展名
    name, ext = os.path.splitext(filename)
    # 保留安全字符
    name = re.sub(r'[^\w\-]', '_', name)
    ext = re.sub(r'[^\w\-]', '_', ext)
    # 限制长度
    name = name[:128]
    return name + ext


class BatchImportHandler:
    """
    批量导入处理器基类

    提供统一的Excel文件处理、数据验证、批量插入功能
    """

    def __init__(self, model_class, required_fields, db):
        """
        初始化批量导入处理器

        Args:
            model_class: 数据模型类
            required_fields: 必填字段列表
            db: SQLAlchemy实例
        """
        self.model = model_class
        self.required_fields = required_fields
        self.db = db
        self.errors = []
        self.success_count = 0
        self.failed_count = 0

    def validate_file(self, file):
        """
        验证上传的文件

        Args:
            file: HTTP上传文件对象

        Returns:
            tuple: (is_valid, file_path or error_message)
        """
        if not file:
            return False, '未选择文件'

        if file.filename == '':
            return False, '未选择文件'

        # 检查文件扩展名
        if not file.filename.endswith('.xlsx'):
            return False, '只支持 Excel 文件 (.xlsx)，.xls 已不再支持'

        # 保存文件
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f"{timestamp}_{filename}"
        upload_folder = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)
        file.save(file_path)

        return True, file_path

    def parse_excel(self, file_path):
        """
        解析Excel文件（Polars 引擎）

        Args:
            file_path: Excel文件路径

        Returns:
            polars.DataFrame: 解析后的数据
        """
        try:
            df = pl.read_excel(file_path)
            return df
        except Exception as e:
            self.errors.append(f'Excel文件解析失败: {str(e)}')
            return None

    def validate_data(self, df):
        """
        验证数据

        Args:
            df: polars DataFrame (或 dicts 列表)

        Returns:
            list: 验证通过的数据列表
        """
        validated_data = []

        if df is None:
            return validated_data

        records = df.to_dicts() if hasattr(df, 'to_dicts') else df

        for index, row_data in enumerate(records):
            missing_fields = []
            for field in self.required_fields:
                value = row_data.get(field)
                if value is None or (isinstance(value, float) and math.isnan(value)) or str(value).strip() == '':
                    missing_fields.append(field)

            if missing_fields:
                self.errors.append(f'第{index + 2}行: 缺少必填字段 {", ".join(missing_fields)}')
                self.failed_count += 1
                continue

            is_valid, error_msg = self.custom_validate(row_data, index)
            if not is_valid:
                self.errors.append(f'第{index + 2}行: {error_msg}')
                self.failed_count += 1
                continue

            validated_data.append(row_data)

        return validated_data

    def custom_validate(self, row_data, index):
        """
        自定义验证方法,子类可重写

        Args:
            row_data: 行数据字典
            index: 行索引

        Returns:
            tuple: (is_valid, error_message)
        """
        return True, ''

    def process_row(self, row_data):
        """
        处理单行数据,子类必须实现

        Args:
            row_data: 行数据字典

        Returns:
            model instance or None
        """
        raise NotImplementedError('子类必须实现process_row方法')

    def import_from_excel(self, file):
        """
        从Excel导入数据

        Args:
            file: HTTP上传文件对象

        Returns:
            dict: 导入结果
        """
        # 1. 验证文件
        is_valid, result = self.validate_file(file)
        if not is_valid:
            return {
                'success': False,
                'message': result,
                'success_count': 0,
                'failed_count': 0,
                'errors': []
            }

        file_path = result

        try:
            df = self.parse_excel(file_path)
            if df is None:
                return {
                    'success': False,
                    'message': 'Excel文件解析失败',
                    'success_count': 0,
                    'failed_count': self.failed_count,
                    'errors': self.errors
                }

            validated_data = self.validate_data(df)

            if not validated_data:
                return {
                    'success': False,
                    'message': '没有有效数据可导入',
                    'success_count': 0,
                    'failed_count': self.failed_count,
                    'errors': self.errors
                }

            for row_data in validated_data:
                try:
                    instance = self.process_row(row_data)
                    if instance:
                        self.db.session.add(instance)
                        self.success_count += 1
                except Exception as e:
                    self.errors.append(f'处理数据时出错: {str(e)}')
                    self.failed_count += 1
                    self.db.session.rollback()
                    continue

            self.db.session.commit()

            return {
                'success': True,
                'message': f'成功导入{self.success_count}条数据',
                'success_count': self.success_count,
                'failed_count': self.failed_count,
                'errors': self.errors[:10]
            }

        except Exception as e:
            self.db.session.rollback()
            return {
                'success': False,
                'message': f'导入失败: {str(e)}',
                'success_count': self.success_count,
                'failed_count': self.failed_count,
                'errors': self.errors
            }
        finally:
            if file_path and os.path.exists(file_path):
                with contextlib.suppress(OSError):
                    os.remove(file_path)


class OrderImportHandler(BatchImportHandler):
    """订单批量导入处理器"""

    def __init__(self, db, Product, Order):
        super().__init__(Order, ['客户名称', '产品名称', '数量'], db)
        self.Product = Product
        self.Order = Order

    def custom_validate(self, row_data, index):
        # 验证数量是否为数字
        try:
            quantity = int(row_data['数量'])
            if quantity <= 0:
                return False, '数量必须大于0'
        except ValueError:
            return False, '数量必须是整数'

        return True, ''

    def process_row(self, row_data):
        # 查找产品
        product_name = str(row_data['产品名称']).strip()
        product = self.Product.query.filter_by(name=product_name).first()
        if not product:
            self.errors.append(f'产品不存在: {product_name}')
            return None

        # 创建订单
        order = self.Order(
            customer=str(row_data['客户名称']).strip(),
            product_id=product.id,
            quantity=int(row_data['数量']),
            note=str(row_data.get('备注', '')).strip() if row_data.get('备注') is not None and not (isinstance(row_data.get('备注'), float) and math.isnan(row_data.get('备注'))) else ''
        )

        return order


class StockInImportHandler(BatchImportHandler):
    """备货批量导入处理器"""

    def __init__(self, db, Product, StockIn):
        super().__init__(StockIn, ['客户名称', '产品名称', '数量'], db)
        self.Product = Product
        self.StockIn = StockIn

    def custom_validate(self, row_data, index):
        try:
            quantity = int(row_data['数量'])
            if quantity <= 0:
                return False, '数量必须大于0'
        except ValueError:
            return False, '数量必须是整数'

        return True, ''

    def process_row(self, row_data):
        product_name = str(row_data['产品名称']).strip()
        product = self.Product.query.filter_by(name=product_name).first()
        if not product:
            self.errors.append(f'产品不存在: {product_name}')
            return None

        stockin = self.StockIn(
            customer=str(row_data['客户名称']).strip(),
            product_id=product.id,
            quantity=int(row_data['数量']),
            note=str(row_data.get('备注', '')).strip() if row_data.get('备注') is not None and not (isinstance(row_data.get('备注'), float) and math.isnan(row_data.get('备注'))) else ''
        )

        return stockin
