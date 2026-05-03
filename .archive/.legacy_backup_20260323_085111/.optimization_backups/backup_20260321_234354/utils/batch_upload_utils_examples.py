"""
批量上传工具模块使用示例

演示如何使用 utils/batch_upload_utils.py 中的函数
"""

import os
import sys

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app import app, db
from batch_upload_utils import (
    generate_error_report,
    parse_excel_file,
    validate_batch_data,
    validate_customer_name,
    validate_date,
    validate_product,
    validate_quantity,
)


def example_validate_customer_name():
    """示例 1: 验证客户名称"""
    print("\n" + "=" * 60)
    print("示例 1: 验证客户名称")
    print("=" * 60)

    customer_names = ["张三公司", "张", "张三@#$", ""]

    for name in customer_names:
        is_valid, error_msg = validate_customer_name(name)
        if is_valid:
            print(f"✓ '{name}' 是有效的客户名称")
        else:
            print(f"✗ '{name}' 无效：{error_msg}")


def example_validate_product():
    """示例 2: 验证产品并获取产品 ID"""
    print("\n" + "=" * 60)
    print("示例 2: 验证产品并获取产品 ID")
    print("=" * 60)

    with app.app_context():
        products = ["笔记本电脑", "不存在的商品", ""]

        for product in products:
            is_valid, product_id, error_msg = validate_product(product, db)
            if is_valid:
                print(f"✓ '{product}' 存在，产品 ID: {product_id}")
            else:
                print(f"✗ '{product}' 无效：{error_msg}")


def example_validate_quantity():
    """示例 3: 验证数量"""
    print("\n" + "=" * 60)
    print("示例 3: 验证数量")
    print("=" * 60)

    quantities = [100, "50", 0, -10, "abc", ""]

    for qty in quantities:
        is_valid, int_value, error_msg = validate_quantity(qty)
        if is_valid:
            print(f"✓ {qty} 是有效的数量，转换后：{int_value}")
        else:
            print(f"✗ {qty} 无效：{error_msg}")


def example_validate_date():
    """示例 4: 验证日期"""
    print("\n" + "=" * 60)
    print("示例 4: 验证日期")
    print("=" * 60)

    dates = [
        "2024-01-15",
        "2024/01/15",
        "2024 年 01 月 15 日",
        "2024-13-45",
        "abc"
    ]

    for date in dates:
        is_valid, date_obj, error_msg = validate_date(date)
        if is_valid:
            print(f"✓ '{date}' 是有效的日期，转换后：{date_obj}")
        else:
            print(f"✗ '{date}' 无效：{error_msg}")


def example_parse_excel():
    """示例 5: 解析 Excel 文件"""
    print("\n" + "=" * 60)
    print("示例 5: 解析 Excel 文件")
    print("=" * 60)

    file_path = "static/files/订单批量上传模板.xlsx"

    if os.path.exists(file_path):
        success, data_list, error_msg = parse_excel_file(file_path)

        if success:
            print(f"✓ 解析成功，共 {len(data_list)} 行数据")
            print("\n前 3 行数据:")
            for i, row in enumerate(data_list[:3], start=2):
                print(f"\n第 {i} 行:")
                for key, value in row.items():
                    print(f"  {key}: {value}")
        else:
            print(f"✗ 解析失败：{error_msg}")
    else:
        print(f"✗ 文件不存在：{file_path}")


def example_validate_batch_data():
    """示例 6: 批量验证数据"""
    print("\n" + "=" * 60)
    print("示例 6: 批量验证数据")
    print("=" * 60)

    # 模拟从 Excel 读取的数据
    data_list = [
        {
            'customer': '张三公司',
            'product': '笔记本电脑',
            'quantity': '100',
            'date': '2024-01-15'
        },
        {
            'customer': '李',  # 太短
            'product': '不存在的商品',  # 不存在
            'quantity': '-5',  # 负数
            'date': '2024-13-45'  # 无效日期
        },
        {
            'customer': '王五公司',
            'product': '笔记本电脑',
            'quantity': '50',
            'date': '2024-01-20'
        }
    ]

    with app.app_context():
        # 定义验证器
        validators = {
            'customer': validate_customer_name,
            'product': lambda x: validate_product(x, db),
            'quantity': validate_quantity,
            'date': validate_date
        }

        # 批量验证
        is_valid, errors, error_msg = validate_batch_data(data_list, validators, db)

        if is_valid:
            print("✓ 所有数据验证通过")
        else:
            print(f"✗ 验证失败：{error_msg}")
            print("\n错误详情:")
            error_report = generate_error_report(errors, 'text')
            print(error_report)


def example_error_report_formats():
    """示例 7: 生成不同格式的错误报告"""
    print("\n" + "=" * 60)
    print("示例 7: 生成不同格式的错误报告")
    print("=" * 60)

    # 模拟错误数据
    errors = [
        {'row': 2, 'field': 'customer', 'value': '张', 'message': '客户名称至少需要 2 个字符'},
        {'row': 2, 'field': 'quantity', 'value': '-5', 'message': '数量必须大于 0'},
        {'row': 3, 'field': 'product', 'value': '不存在的商品', 'message': '产品不存在'},
    ]

    print("\n1. 文本格式:")
    print("-" * 40)
    print(generate_error_report(errors, 'text'))

    print("\n2. HTML 格式 (用于网页显示):")
    print("-" * 40)
    html = generate_error_report(errors, 'html')
    print(f"{html[:200]}...")  # 只显示前 200 字符

    print("\n3. JSON 格式 (用于 API 响应):")
    print("-" * 40)
    json_str = generate_error_report(errors, 'json')
    print(json_str[:300] + "...")  # 只显示前 300 字符


def example_usage_in_flask():
    """示例 8: 在 Flask 视图中使用"""
    print("\n" + "=" * 60)
    print("示例 8: 在 Flask 视图中使用（伪代码）")
    print("=" * 60)

    print("""
@app.route('/upload_orders', methods=['POST'])
def upload_orders():
    '''批量上传订单的 Flask 视图函数'''
    from werkzeug.utils import secure_filename

    if 'file' not in request.files:
        flash('没有上传文件')
        return redirect(request.url)

    file = request.files['file']
    if file.filename == '':
        flash('没有选择文件')
        return redirect(request.url)

    # 保存上传的文件
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    try:
        # 1. 解析 Excel 文件
        success, data_list, error_msg = parse_excel_file(file_path)
        if not success:
            flash(f'解析文件失败：{error_msg}')
            return redirect(request.url)

        # 2. 批量验证数据
        validators = {
            'customer': validate_customer_name,
            'product': lambda x: validate_product(x, db),
            'quantity': validate_quantity,
            'date': validate_date
        }

        is_valid, errors, error_msg = validate_batch_data(data_list, validators, db)

        if not is_valid:
            # 生成错误报告并显示
            error_report = generate_error_report(errors, 'html')
            flash(error_report)
            return redirect(request.url)

        # 3. 批量保存数据
        mapping = {
            '订单编号': 'order_no',
            '客户名称': 'customer',
            '产品名称': 'product_id',  # 实际应该使用验证后的 _product_id
            '数量': 'quantity',
            '日期': 'order_date',
            '备注': 'note'
        }

        success, save_errors, error_msg = batch_save_with_transaction(
            data_list, db, Order, mapping
        )

        if success:
            flash(f'成功导入 {len(data_list)} 条订单记录')
            return redirect(url_for('order_list'))
        else:
            flash(f'保存失败：{error_msg}')
            return redirect(request.url)

    except BatchUploadError as e:
        flash(f'批量上传失败：{e.message}')
        error_report = generate_error_report(e.errors, 'html')
        flash(error_report)
        return redirect(request.url)
    except Exception as e:
        flash(f'发生错误：{str(e)}')
        return redirect(request.url)
    """)


def main():
    """运行所有示例"""
    print("\n" + "=" * 60)
    print("批量上传工具模块使用示例")
    print("=" * 60)

    # 运行示例
    example_validate_customer_name()
    example_validate_product()
    example_validate_quantity()
    example_validate_date()
    example_parse_excel()
    example_validate_batch_data()
    example_error_report_formats()
    example_usage_in_flask()

    print("\n" + "=" * 60)
    print("所有示例运行完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
