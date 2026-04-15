"""
采购计划页面路由（重构版）

提供页面渲染功能，API逻辑由 FastAPI 处理。
"""
from flask import Blueprint, render_template, send_file
from app.models import Customer

purchase_plan_bp = Blueprint('purchase_plan', __name__, url_prefix='/plans')


@purchase_plan_bp.route('/list')
def plan_list():
    """采购计划管理页面"""
    customers = Customer.query.filter_by(status=True).order_by(Customer.name).all()
    return render_template('purchase_plan_new.html', customers=customers)


@purchase_plan_bp.route('/template')
def download_template():
    """下载Excel上传模板"""
    import openpyxl
    import io
    from tempfile import NamedTemporaryFile

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "采购计划模板"

    headers = ["客户名称", "产品名称", "69码", "数量", "计划日期", "备注"]
    ws.append(headers)
    ws.append(["示例客户", "示例产品", "6901234567890", 100, "2026-04-15", "备注信息"])

    for col in range(1, 7):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 18

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='purchase_plan_template.xlsx',
    )
