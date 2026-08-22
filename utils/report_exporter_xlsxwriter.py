"""
报表导出工具 - XlsxWriter版本
性能优于openpyxl，支持图表
"""

from io import BytesIO

import xlsxwriter


class XlsxWriterExporter:
    """XlsxWriter报表导出器"""

    def __init__(self):
        self.header_format = {
            'bold': True,
            'bg_color': '#4472C4',
            'font_color': 'white',
            'border': 1,
            'text_wrap': True,
            'valign': 'vcenter',
            'align': 'center'
        }
        self.cell_format = {
            'border': 1,
            'valign': 'vcenter',
            'text_wrap': True
        }
        self.number_format = {
            'border': 1,
            'valign': 'vcenter',
            'num_format': '#,##0'
        }

    def export_data(self, data: list[dict], title: str = 'Sheet1',
                    headers: list[str] | None = None,
                    column_widths: dict[str, int] | None = None) -> bytes:
        """
        导出数据到Excel

        Args:
            data: 数据列表
            title: 工作表名称
            headers: 自定义表头
            column_widths: 列宽配置

        Returns:
            Excel文件字节
        """
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet(title)

        header_fmt = workbook.add_format(self.header_format)
        cell_fmt = workbook.add_format(self.cell_format)
        num_fmt = workbook.add_format(self.number_format)

        if not data:
            workbook.close()
            output.seek(0)
            return output.getvalue()

        if headers is None:
            headers = list(data[0].keys())

        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_fmt)

        if column_widths:
            for col, header in enumerate(headers):
                if header in column_widths:
                    worksheet.set_column(col, col, column_widths[header])

        for row_idx, row_data in enumerate(data, start=1):
            for col, key in enumerate(headers):
                value = row_data.get(key, '')
                if isinstance(value, (int, float)):
                    worksheet.write_number(row_idx, col, value, num_fmt)
                else:
                    worksheet.write(row_idx, col, str(value) if value else '', cell_fmt)

        worksheet.freeze_panes(1, 0)
        worksheet.autofilter(0, 0, len(data), len(headers) - 1)

        workbook.close()
        output.seek(0)
        return output.getvalue()

    def export_with_chart(self, data: list[dict], title: str = 'Sheet1',
                          chart_type: str = 'column',
                          categories_col: str | None = None,
                          values_col: str | None = None) -> bytes:
        """
        导出带图表的Excel

        Args:
            data: 数据列表
            title: 工作表名称
            chart_type: 图表类型 (column/bar/line/pie/area/scatter)
            categories_col: 分类列名
            values_col: 数值列名

        Returns:
            Excel文件字节
        """
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet(title)

        header_fmt = workbook.add_format(self.header_format)
        workbook.add_format(self.cell_format)

        if not data:
            workbook.close()
            output.seek(0)
            return output.getvalue()

        headers = list(data[0].keys())

        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_fmt)

        for row_idx, row_data in enumerate(data, start=1):
            for col, key in enumerate(headers):
                value = row_data.get(key, '')
                if isinstance(value, (int, float)):
                    worksheet.write_number(row_idx, col, value)
                else:
                    worksheet.write(row_idx, col, str(value) if value else '')

        if categories_col and values_col and len(data) > 1:
            cat_col_idx = headers.index(categories_col) if categories_col in headers else 0
            val_col_idx = headers.index(values_col) if values_col in headers else 1

            chart = workbook.add_chart({'type': chart_type})

            chart.add_series({
                'name': f'={title}!${chr(65 + val_col_idx)}$1',
                'categories': f'={title}!${chr(65 + cat_col_idx)}$2:${chr(65 + cat_col_idx)}${len(data) + 1}',
                'values': f'={title}!${chr(65 + val_col_idx)}$2:${chr(65 + val_col_idx)}${len(data) + 1}',
            })

            chart.set_title({'name': values_col})
            chart.set_x_axis({'name': categories_col})
            chart.set_y_axis({'name': values_col})

            worksheet.insert_chart(
                len(headers) + 2, 0,
                chart,
                {'x_offset': 25, 'y_offset': 10}
            )

        workbook.close()
        output.seek(0)
        return output.getvalue()
