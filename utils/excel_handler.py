"""
统一的Excel文件处理工具
用于批量导入等场景,减少重复代码
"""
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta

# 允许的Excel文件扩展名（.xls 已弃用：CVE-2019-19276）
ALLOWED_EXCEL_EXTENSIONS = {'.xlsx'}


def validate_excel_filename(filename: str) -> tuple[bool, str]:
    """验证上传文件的扩展名是否为允许的Excel格式

    Args:
        filename: 上传文件的原始文件名

    Returns:
        tuple[bool, str]: (是否有效, 错误信息)
    """
    if not filename or filename == '':
        return False, '没有选择文件'

    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXCEL_EXTENSIONS:
        if ext == '.xls':
            return False, '.xls 格式已不再支持（安全原因），请将文件另存为 .xlsx 格式'
        return False, '只支持 Excel 文件格式 (.xlsx)'

    return True, ''


@contextmanager
def excel_reader(file):
    """
    Excel文件读取上下文管理器
    自动处理临时文件的创建和清理

    参数:
        file: HTTP上传的文件对象

    用法:
        with excel_reader(file) as reader:
            if reader.error:
                return jsonify({'success': False, 'error': reader.error})

            for row in range(2, reader.max_row + 1):
                value = reader.get_cell_value(row, col)

    返回:
        ExcelReader对象
    """
    reader = ExcelReader(file)
    try:
        yield reader
    finally:
        reader.cleanup()


class ExcelReader:
    """Excel文件读取器"""

    def __init__(self, file):
        self.file = file
        self.temp_path = None
        self.temp_fd = None
        self.wb = None
        self.ws = None
        self.error = None
        self.max_row = 0
        self.max_col = 0
        self.sheet_names = []
        self.current_sheet = None

        self._initialize()

    def _initialize(self):
        """初始化Excel读取器"""
        # 检查文件
        if not self.file or self.file.filename == '':
            self.error = '没有选择文件'
            return

        # 检查文件扩展名（.xls 已弃用，存在安全漏洞 CVE-2019-19276）
        filename_lower = self.file.filename.lower()
        if filename_lower.endswith('.xls'):
            self.error = '.xls 格式已不再支持（安全原因），请将文件另存为 .xlsx 格式后重新上传'
            return
        if not filename_lower.endswith('.xlsx'):
            self.error = '只支持 Excel 文件格式 (.xlsx)'
            return

        # 创建临时文件
        self.temp_fd, self.temp_path = tempfile.mkstemp(suffix='.xlsx')
        os.close(self.temp_fd)
        self.temp_fd = None

        try:
            # 保存文件
            self.file.save(self.temp_path)

            # 仅支持 .xlsx（使用 openpyxl）
            self._open_xlsx()

        except Exception as e:
            self.error = self._handle_excel_error(e)

    def _open_xlsx(self):
        """打开xlsx格式文件"""
        try:
            from openpyxl import load_workbook

            # 验证文件格式
            try:
                wb_test = load_workbook(filename=self.temp_path, read_only=True)
                wb_test.close()
            except Exception as format_error:
                self.error = self._handle_excel_error(format_error)
                return

            # 正式打开文件
            self.wb = load_workbook(self.temp_path)
            self.sheet_names = self.wb.sheetnames
            self.ws = self.wb.active
            self.current_sheet = self.ws.title if self.ws else None
            self.max_row = self.ws.max_row if self.ws else 0
            self.max_col = self.ws.max_column if self.ws else 0

        except ImportError:
            self.error = '系统缺少 openpyxl 库,请安装: pip install openpyxl'

    def switch_sheet(self, sheet_name):
        """
        切换到指定的Sheet

        参数:
            sheet_name: Sheet名称

        返回:
            (success, error_message)
        """
        if self.error:
            return False, self.error

        if sheet_name not in self.sheet_names:
            return False, f'Sheet不存在: {sheet_name}, 可用的Sheet: {self.sheet_names}'

        filename_lower = self.file.filename.lower()
        if filename_lower.endswith('.xlsx'):
            self.ws = self.wb[sheet_name]
            self.current_sheet = sheet_name
            self.max_row = self.ws.max_row
            self.max_col = self.ws.max_column
            return True, None
        else:
            return False, '只支持.xlsx格式文件的Sheet切换'

    def get_sheet_data(self, sheet_name, start_row=2):
        """
        获取指定Sheet的所有数据

        参数:
            sheet_name: Sheet名称
            start_row: 起始行号(默认2,跳过表头)

        返回:
            (success, data_list, error_message)
        """
        success, err = self.switch_sheet(sheet_name)
        if not success:
            return False, [], err

        data = []
        for row in range(start_row, self.max_row + 1):
            row_data = {}
            for col in range(1, self.max_col + 1):
                header = self.get_cell_value(1, col)
                if header:
                    value = self.get_cell_value(row, col)
                    row_data[str(header).strip()] = value
            if any(row_data.values()):
                data.append(row_data)

        return True, data, None


    def get_cell_value(self, row, col):
        """
        获取单元格值

        参数:
            row: 行号(从1开始)
            col: 列号(从1开始)

        返回:
            单元格值
        """
        if self.error:
            return None

        self.file.filename.lower()

        # 仅支持 .xlsx（使用 openpyxl）
        return self.ws.cell(row=row, column=col).value

    def validate_headers(self, expected_headers, start_col=1):
        """
        验证表头

        参数:
            expected_headers: 期望的表头列表
            start_col: 起始列(默认1)

        返回:
            (success, actual_headers, error_message)
        """
        if self.error:
            return False, [], self.error

        # 读取实际表头
        actual_headers = []
        for col in range(start_col, start_col + len(expected_headers)):
            cell_value = self.get_cell_value(row=1, col=col)
            if cell_value is None:
                actual_headers.append('')
            else:
                actual_headers.append(str(cell_value).strip())

        # 检查表头数量
        if len(actual_headers) < len(expected_headers):
            return False, actual_headers, f'表头列数不足,期望{len(expected_headers)}列'

        # 验证表头内容
        for i, expected in enumerate(expected_headers):
            if actual_headers[i].replace(' ', '') != expected.replace(' ', ''):
                return False, actual_headers, f'表头格式不正确,期望:{expected_headers},实际:{actual_headers}'

        return True, actual_headers, None

    def check_data_rows(self, min_rows=1):
        """
        检查是否有数据行

        参数:
            min_rows: 最少数据行数

        返回:
            (success, error_message)
        """
        if self.error:
            return False, self.error

        if self.max_row < 1 + min_rows:  # 表头 + 数据行
            return False, f'Excel文件中没有数据行,请至少填写{min_rows}行数据'

        return True, None

    def parse_date_value(self, date_value):
        """
        解析日期值

        参数:
            date_value: 单元格中的日期值

        返回:
            datetime对象
        """
        if date_value is None or str(date_value).strip() == '':
            return datetime.now()

        try:
            # 如果是datetime对象
            if isinstance(date_value, datetime):
                return date_value

            # 如果是Excel日期(数字格式)
            if isinstance(date_value, (int, float)):
                base_date = datetime(1899, 12, 30)
                return base_date + timedelta(days=int(date_value))

            # 如果是字符串
            if isinstance(date_value, str):
                date_str = date_value.strip()
                # 尝试带时间的格式
                datetime_formats = [
                    '%Y-%m-%d %H:%M:%S',
                    '%Y/%m/%d %H:%M:%S',
                    '%Y-%m-%d %H:%M',
                    '%Y/%m/%d %H:%M'
                ]
                for fmt in datetime_formats:
                    try:
                        return datetime.strptime(date_str, fmt)
                    except ValueError:
                        continue

                # 尝试只有日期的格式，添加当前时分秒
                date_only_formats = [
                    '%Y-%m-%d',
                    '%Y/%m/%d'
                ]
                for fmt in date_only_formats:
                    try:
                        parsed_date = datetime.strptime(date_str, fmt)
                        now = datetime.now()
                        return datetime(
                            parsed_date.year,
                            parsed_date.month,
                            parsed_date.day,
                            now.hour,
                            now.minute,
                            now.second
                        )
                    except ValueError:
                        continue

            return datetime.now()
        except Exception:
            return datetime.now()

    def cleanup(self):
        """清理临时文件"""
        try:
            if self.temp_fd:
                os.close(self.temp_fd)
            if self.temp_path and os.path.exists(self.temp_path):
                os.unlink(self.temp_path)
        except Exception:  # noqa: S110 - defensive: 临时文件清理尽力而为，失败不影响主流程
            pass

    @staticmethod
    def _handle_excel_error(error):
        """处理Excel错误"""
        error_msg = str(error).lower()

        if 'no valid workbook' in error_msg or 'zip' in error_msg:
            return 'Excel文件格式无效或已损坏,请使用Microsoft Excel重新保存为标准.xlsx格式'
        elif 'unsupported format' in error_msg or 'corrupt' in error_msg:
            return 'Excel文件格式无效或已损坏,请使用Microsoft Excel重新保存'
        else:
            return f'Excel文件错误: {error!s}'


def validate_required_field(value, field_name, row_num=None):
    """
    验证必填字段

    参数:
        value: 字段值
        field_name: 字段名称
        row_num: 行号(可选)

    返回:
        (success, error_message)
    """
    if value is None or str(value).strip() == '':
        if row_num:
            return False, f'第{row_num}行:{field_name}不能为空'
        else:
            return False, f'{field_name}不能为空'
    return True, None


def parse_quantity(quantity_value, field_name='数量', row_num=None):
    """
    解析数量字段

    参数:
        quantity_value: 数量值
        field_name: 字段名称
        row_num: 行号(可选)

    返回:
        (quantity, error_message)
    """
    if quantity_value is None:
        if row_num:
            return None, f'第{row_num}行:{field_name}不能为空'
        else:
            return None, f'{field_name}不能为空'

    try:
        # 尝试转换为整数
        if isinstance(quantity_value, str):
            quantity_value = quantity_value.strip()
            if quantity_value == '':
                if row_num:
                    return None, f'第{row_num}行:{field_name}不能为空'
                else:
                    return None, f'{field_name}不能为空'
            quantity = int(float(quantity_value))
        elif isinstance(quantity_value, float):
            quantity = int(quantity_value)
        else:
            quantity = int(quantity_value)

        if quantity <= 0:
            if row_num:
                return None, f'第{row_num}行:{field_name}必须大于0'
            else:
                return None, f'{field_name}必须大于0'

        return quantity, None
    except (ValueError, TypeError):
        if row_num:
            return None, f'第{row_num}行:{field_name}必须是有效的数字,实际值:{quantity_value}'
        else:
            return None, f'{field_name}必须是有效的数字'
