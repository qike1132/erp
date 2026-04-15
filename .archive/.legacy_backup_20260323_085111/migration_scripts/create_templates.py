#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
创建 Excel 批量上传模板文件
"""

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
import os

def create_template(template_type, filename, example_data):
    """
    创建 Excel 模板文件
    
    Args:
        template_type: 模板类型（订单/入库单/出库单）
        filename: 文件名
        example_data: 示例数据列表
    """
    wb = Workbook()
    ws = wb.active
    ws.title = template_type
    
    # 定义列头
    headers = [
        f"{template_type}编号",
        "日期",
        "客户名称",
        "产品名称",
        "数量",
        "备注"
    ]
    
    # 设置样式
    header_font = Font(bold=True, size=12, color='FFFFFF')
    header_alignment = Alignment(horizontal='center', vertical='center')
    header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
    
    cell_alignment = Alignment(horizontal='left', vertical='center')
    
    # 设置边框
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # 写入列头
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.alignment = header_alignment
        cell.fill = header_fill
        cell.border = thin_border
    
    # 写入示例数据
    for row_idx, row_data in enumerate(example_data, 2):
        for col_idx, value in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.alignment = cell_alignment
            cell.border = thin_border
    
    # 调整列宽
    column_widths = [18, 15, 20, 20, 10, 25]
    for col_idx, width in enumerate(column_widths, 1):
        ws.column_dimensions[chr(64 + col_idx)].width = width
    
    # 自动调整行高
    ws.row_dimensions[1].height = 25
    for row_idx in range(2, len(example_data) + 2):
        ws.row_dimensions[row_idx].height = 20
    
    # 保存文件
    output_path = os.path.join('static', 'files', filename)
    wb.save(output_path)
    print(f"✓ 已创建模板文件：{output_path}")
    
    return output_path


def main():
    """主函数"""
    # 确保目录存在
    os.makedirs('static/files', exist_ok=True)
    
    # 订单示例数据
    order_examples = [
        ['ORD20260314001', '2026-03-14', '某某科技公司', '笔记本电脑', '50', '加急订单，需本周发货'],
        ['ORD20260314002', '2026-03-14', 'ABC 贸易公司', '无线鼠标', '200', '常规订单'],
        ['ORD20260314003', '2026-03-13', 'XYZ 制造厂', '机械键盘', '100', '客户定制版本'],
        ['ORD20260314004', '2026-03-13', '创新电子公司', '显示器 27 寸', '30', '含安装服务'],
        ['ORD20260314005', '2026-03-12', '数字解决方案', 'USB 集线器', '500', '批量采购优惠'],
    ]
    
    # 入库单示例数据
    stockin_examples = [
        ['IN20260314001', '2026-03-14', '供应商 A', '笔记本电脑', '100', '采购入库，质检合格'],
        ['IN20260314002', '2026-03-14', '供应商 B', '无线鼠标', '500', '补货入库'],
        ['IN20260314003', '2026-03-13', '供应商 A', '机械键盘', '200', '新品入库'],
        ['IN20260314004', '2026-03-13', '供应商 C', '显示器 27 寸', '80', '工厂直发'],
        ['IN20260314005', '2026-03-12', '供应商 B', 'USB 集线器', '1000', '大批量入库'],
    ]
    
    # 出库单示例数据
    stockout_examples = [
        ['OUT20260314001', '2026-03-14', '某某科技公司', '笔记本电脑', '50', '销售出库'],
        ['OUT20260314002', '2026-03-14', 'ABC 贸易公司', '无线鼠标', '200', '批发出库'],
        ['OUT20260314003', '2026-03-13', 'XYZ 制造厂', '机械键盘', '100', '订单出库'],
        ['OUT20260314004', '2026-03-13', '创新电子公司', '显示器 27 寸', '30', '配送出库'],
        ['OUT20260314005', '2026-03-12', '数字解决方案', 'USB 集线器', '500', '快递出库'],
    ]
    
    print("开始创建 Excel 批量上传模板文件...\n")
    
    # 创建三个模板
    create_template('订单', '订单批量上传模板.xlsx', order_examples)
    create_template('入库单', '入库单批量上传模板.xlsx', stockin_examples)
    create_template('出库单', '出库单批量上传模板.xlsx', stockout_examples)
    
    print("\n✓ 所有模板文件创建完成！")
    print(f"✓ 保存位置：{os.path.abspath('static/files')}")


if __name__ == '__main__':
    main()
