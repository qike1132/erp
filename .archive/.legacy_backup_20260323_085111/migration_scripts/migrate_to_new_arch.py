"""
迁移脚本：将app.py中的路由代码迁移到新架构
"""
import re

# 读取app.py
with open('app.py', encoding='utf-8') as f:
    content = f.read()

# 提取数据库模型定义
models_pattern = r'class (Product|Order|StockIn|StockOut|InventoryLog|Case|CaseStockIn|CaseStockOut|CaseInventoryLog|User|Permission)\(db\.Model\):.*?(?=\nclass |\Z)'
models = re.findall(models_pattern, content, re.DOTALL)

print(f"找到 {len(models)} 个模型类")
for model in models:
    print(f"  - {model}")

# 提取路由函数
routes_pattern = r'@app\.route\([\'"]([^\'"]+)[\'"].*?\)\ndef (\w+)\([^)]*\):.*?(?=\n@app\.route|\ndef [a-z_]+\(|\Z)'
routes = re.findall(routes_pattern, content, re.DOTALL)

print(f"\n找到 {len(routes)} 个路由")
for route, func_name in routes[:10]:
    print(f"  - {route}: {func_name}")

print("\n建议：手动迁移更安全，因为代码量较大且逻辑复杂")
print("新架构已经创建好模型文件，路由需要手动提取和调整")
