"""
批量修复模板中的路由引用
"""
import os
import re

# 路由映射关系
route_mapping = {
    "url_for('products')": "url_for('main.products')",
    "url_for('orders')": "url_for('main.orders')",
    "url_for('stockins')": "url_for('main.stockins')",
    "url_for('stockouts')": "url_for('main.stockouts')",
    "url_for('inventory')": "url_for('main.inventory')",
    "url_for('index')": "url_for('main.index')",
    "url_for('login')": "url_for('main.login')",
    "url_for('logout')": "url_for('main.logout')",
    "url_for('reports')": "url_for('main.reports')",
    "url_for('cases')": "url_for('main.cases')",
    "url_for('users')": "url_for('main.users')",
}

def fix_template_file(filepath):
    """修复单个模板文件"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        original_content = content
        modified = False

        # 替换路由引用
        for old_route, new_route in route_mapping.items():
            if old_route in content:
                content = content.replace(old_route, new_route)
                modified = True

        # 如果有修改，写回文件
        if modified:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"[OK] 已修复: {filepath}")
            return True
        else:
            return False

    except Exception as e:
        print(f"[ERROR] 处理文件失败 {filepath}: {e}")
        return False

def fix_all_templates():
    """修复所有模板文件"""
    templates_dir = 'templates'
    fixed_count = 0

    print("=" * 50)
    print("开始批量修复模板路由引用")
    print("=" * 50)

    # 遍历templates目录
    for root, dirs, files in os.walk(templates_dir):
        for file in files:
            if file.endswith('.html'):
                filepath = os.path.join(root, file)
                if fix_template_file(filepath):
                    fixed_count += 1

    print("=" * 50)
    print(f"修复完成! 共修复 {fixed_count} 个文件")
    print("=" * 50)

if __name__ == '__main__':
    fix_all_templates()
