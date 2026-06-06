#!/usr/bin/env python3
"""
批量更新备份API端点的权限依赖
"""

import re

# 读取文件
with open('D:/erp_system/fastapi_app/api/v1/endpoints/backup.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 定义端点名称到权限的映射
endpoint_permissions = {
    'ping': 'backup_read',
    'list_backup_tables': 'backup_read',
    'export_backup': 'backup_create',
    'export_backup_enhanced': 'backup_create',
    'import_backup': 'backup_restore',
    'validate_backup': 'backup_read',
    'save_backup_to_server': 'backup_create',
    'list_server_backups': 'backup_read',
    'restore_server_backup': 'backup_restore',
    'delete_server_backup': 'backup_delete',
    'backup_status': 'backup_read',
    'save_incremental_backup': 'backup_create',
    'restore_incremental_backup': 'backup_restore',
    'run_integrity_check': 'backup_read',
    'get_restore_progress': 'backup_read',
    'async_import_backup': 'backup_restore',
    'async_restore_server_backup': 'backup_restore',
    'get_backup_records': 'backup_read',
    'get_backup_schedule': 'backup_read',
    'trigger_backup_schedule': 'backup_manage',
    'get_backup_info': 'backup_read',
    'export_backup_chunk': 'backup_create',
}

# 查找所有函数定义
function_pattern = r'@router\.(get|post|put|delete|patch)\([\'"]([^\'"]+)[\'"]\)\s*\nasync def (\w+)'
functions = re.findall(function_pattern, content)

print("找到的函数端点:")
for method, path, func_name in functions:
    print(f"  {func_name}: {method.upper()} {path}")

# 替换权限依赖
for func_name, permission in endpoint_permissions.items():
    # 查找函数定义
    pattern = rf'async def {func_name}\(.*?user: User = Depends\(require_permission\(\'backup_manage\'\)\),'
    replacement = f'async def {func_name}(...user: User = Depends(require_backup_permission(\'{func_name}\')),'
    
    # 使用更精确的匹配
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if f'async def {func_name}(' in line:
            # 找到函数开始行
            for j in range(i, min(i+10, len(lines))):
                if 'user: User = Depends(require_permission(\'backup_manage\')),' in lines[j]:
                    print(f"更新 {func_name}: {permission}")
                    lines[j] = lines[j].replace(
                        'require_permission(\'backup_manage\')',
                        f'require_backup_permission(\'{func_name}\')'
                    )
                    break
    
    content = '\n'.join(lines)

# 保存更新后的文件
with open('D:/erp_system/fastapi_app/api/v1/endpoints/backup.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("\n权限更新完成！")