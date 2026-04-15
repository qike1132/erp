"""
将所有API接口的permission_required改为api_permission_required
"""
import re

# 读取app.py文件
with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 定义需要修改的API接口（使用permission_required的）
api_to_change = [
    '/api/product-search',
    '/api/available-stockins',
    '/api/stockin-info/<int:stockin_id>',
    '/api/product-available-stock',
    '/api/validate-deduct-quantity',
    '/api/log-operation',
    '/api/confirm-stockin-deduction',
    '/api/inventory-logs/<int:product_id>',
    '/api/deduction-logs',
    '/api/case-search',
    '/api/case-stockin-info/<int:stockin_id>',
    '/api/case-inventory-logs/<int:case_id>',
    '/api/available-case-stockins',
    '/api/case-stockins',
    '/api/case-stockouts',
    '/api/case-stockin/<int:stockin_id>',
    '/api/case-stockout/<int:stockout_id>',
    '/api/case-inventory-summary',
    '/api/case-product/<int:case_id>',
    '/save-template-dialog',
    '/batch-import-orders',
    '/batch-import-stockins',
]

print("=" * 60)
print("将API接口的permission_required改为api_permission_required")
print("=" * 60)

changes_made = 0

for endpoint in api_to_change:
    # 查找路由定义后的permission_required
    pattern = rf"(@app\.route\('{re.escape(endpoint)}'[^\)]*\)\s*@permission_required\('[^']+'\))"
    
    match = re.search(pattern, content)
    if match:
        # 提取权限代码
        permission_match = re.search(r"@permission_required\('([^']+)'\)", match.group(1))
        if permission_match:
            permission_code = permission_match.group(1)
            old_decorator = f"@permission_required('{permission_code}')"
            new_decorator = f"@api_permission_required('{permission_code}')"
            content = content.replace(old_decorator, new_decorator)
            print(f"[CHANGE] {endpoint} - {permission_code}")
            changes_made += 1
    else:
        # 检查是否已经有api_permission_required
        check_pattern = rf"(@app\.route\('{re.escape(endpoint)}'[^\)]*\)\s*@api_permission_required\('[^']+'\))"
        if re.search(check_pattern, content):
            print(f"[SKIP] {endpoint} - 已使用api_permission_required")
        else:
            print(f"[NOT FOUND] {endpoint} - 未找到permission_required")

print(f"\n共修改了 {changes_made} 个接口")

# 写回文件
with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("\n[SUCCESS] 所有API接口已修改为api_permission_required")
print("=" * 60)
