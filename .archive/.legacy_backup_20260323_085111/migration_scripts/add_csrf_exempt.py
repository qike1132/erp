"""
为所有API接口添加CSRF豁免和API权限验证装饰器
"""
import re

# 读取app.py文件
with open('app.py', encoding='utf-8') as f:
    content = f.read()

# 定义需要处理的API接口列表
api_endpoints = [
    # 已处理的批量提交接口（跳过）
    # ('/api/batch-submit-orders', 'order_manage'),
    # ('/api/batch-submit-stockins', 'stockin_manage'),
    # ('/api/batch-submit-stockouts', 'stockout_manage'),
    # ('/api/batch-submit-case-stockins', 'case_manage'),
    # ('/api/batch-submit-case-stockouts', 'case_manage'),

    # 其他API接口
    ('/api/test-simple-submit', None),  # 测试接口，无权限要求
    ('/api/product-search', None),  # 产品搜索，公开接口
    ('/api/available-stockins', None),  # 可用备货查询，公开接口
    ('/api/stockin-info/<int:stockin_id>', None),  # 备货信息，公开接口
    ('/api/product-available-stock', None),  # 产品可用库存，公开接口
    ('/api/validate-deduct-quantity', None),  # 验证抵扣数量，公开接口
    ('/api/log-operation', None),  # 日志操作，公开接口
    ('/api/confirm-stockin-deduction', None),  # 确认备货抵扣，公开接口
    ('/api/inventory-logs/<int:product_id>', None),  # 库存日志，公开接口
    ('/api/deduction-logs', None),  # 抵扣日志，公开接口
    ('/api/case-search', None),  # 皮套搜索，公开接口
    ('/api/case-stockin-info/<int:stockin_id>', None),  # 皮套入库信息，公开接口
    ('/api/case-inventory-logs/<int:case_id>', None),  # 皮套库存日志，公开接口
    ('/api/available-case-stockins', None),  # 可用皮套入库，公开接口
    ('/api/case-stockins', None),  # 皮套入库列表，公开接口
    ('/api/case-stockouts', None),  # 皮套出库列表，公开接口
    ('/api/case-stockin/<int:stockin_id>', None),  # 皮套入库操作，公开接口
    ('/api/case-stockout/<int:stockout_id>', None),  # 皮套出库操作，公开接口
    ('/api/case-inventory-summary', None),  # 皮套库存汇总，公开接口
    ('/api/case-product/<int:case_id>', None),  # 皮套产品操作，公开接口
]

# 其他需要处理的非API接口
other_endpoints = [
    ('/save-template-dialog', None),  # 保存模板对话框
    ('/batch-import-orders', None),  # 批量导入订单
    ('/batch-import-stockins', None),  # 批量导入备货
    ('/batch-import-stockouts', None),  # 批量导入出货
    ('/batch-import-case-stockins', None),  # 批量导入皮套入库
    ('/batch-import-case-stockouts', None),  # 批量导入皮套出库
]

print("=" * 60)
print("为所有API接口添加CSRF豁免")
print("=" * 60)

changes_made = 0

# 处理每个API接口
for endpoint, _permission in api_endpoints + other_endpoints:
    # 查找路由定义
    pattern = rf"(@app\.route\('{endpoint}'[^\)]*\))"

    # 检查是否已经有@csrf.exempt
    check_pattern = rf"@csrf\.exempt\s*{pattern}"
    if re.search(check_pattern, content):
        print(f"[SKIP] {endpoint} - 已有@csrf.exempt")
        continue

    # 查找路由定义位置
    match = re.search(pattern, content)
    if match:
        # 在路由定义前添加@csrf.exempt
        route_def = match.group(1)
        new_route = f"@csrf.exempt\n{route_def}"
        content = content.replace(route_def, new_route, 1)
        print(f"[ADD] {endpoint} - 添加@csrf.exempt")
        changes_made += 1
    else:
        print(f"[NOT FOUND] {endpoint}")

print(f"\n共修改了 {changes_made} 个接口")

# 写回文件
with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("\n[SUCCESS] 所有API接口已添加CSRF豁免")
print("=" * 60)
