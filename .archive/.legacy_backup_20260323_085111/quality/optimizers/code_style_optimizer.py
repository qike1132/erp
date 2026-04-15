"""
代码规范化优化脚本
手动进行代码风格优化
"""
import os
import re
from pathlib import Path


def optimize_file_style(file_path: str) -> bool:
    """优化单个文件的代码风格"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # 1. 确保文件末尾有换行符
        if not content.endswith('\n'):
            content += '\n'
        
        # 2. 移除多余的空行(超过2个连续空行)
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        # 3. 移除行尾空格
        lines = content.split('\n')
        lines = [line.rstrip() for line in lines]
        content = '\n'.join(lines)
        
        # 只有在内容有变化时才写入
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        
        return False
        
    except Exception as e:
        print(f"优化文件失败 {file_path}: {e}")
        return False


def optimize_project_code(project_path: str):
    """优化项目代码风格"""
    print("=" * 60)
    print("代码规范化优化")
    print("=" * 60)
    
    project_path = Path(project_path)
    optimized_files = []
    
    # 优化关键目录
    target_dirs = ['tests', 'quality', 'utils']
    
    for dir_name in target_dirs:
        dir_path = project_path / dir_name
        if not dir_path.exists():
            continue
        
        print(f"\n优化 {dir_name}/ 目录...")
        
        for file_path in dir_path.rglob('*.py'):
            if optimize_file_style(str(file_path)):
                optimized_files.append(str(file_path.relative_to(project_path)))
                print(f"  [OK] {file_path.name}")
    
    # 优化根目录的关键文件
    print("\n优化根目录文件...")
    root_files = ['pytest.ini']
    
    for file_name in root_files:
        file_path = project_path / file_name
        if file_path.exists():
            if optimize_file_style(str(file_path)):
                optimized_files.append(file_name)
                print(f"  [OK] {file_name}")
    
    print("\n" + "=" * 60)
    print(f"优化完成,共优化 {len(optimized_files)} 个文件")
    print("=" * 60)
    
    return optimized_files


if __name__ == '__main__':
    project_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    optimized = optimize_project_code(project_path)
    
    if optimized:
        print("\n优化的文件列表:")
        for file in optimized:
            print(f"  - {file}")
