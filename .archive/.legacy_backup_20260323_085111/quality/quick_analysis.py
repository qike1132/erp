"""
快速代码质量分析
只分析核心文件,快速生成报告
"""
import os
import json
import subprocess
from datetime import datetime
from pathlib import Path


def quick_analysis(project_path: str):
    """快速质量分析"""
    print("=" * 60)
    print("快速代码质量分析")
    print("=" * 60)
    
    # 分析核心文件
    core_files = [
        'app.py',
        'utils/decorators.py',
        'utils/number_generator.py',
        'utils/pagination.py'
    ]
    
    results = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'files_analyzed': len(core_files),
        'tools': {}
    }
    
    # 1. 使用flake8快速检查
    print("\n运行Flake8检查...")
    try:
        for file in core_files:
            file_path = os.path.join(project_path, file)
            if os.path.exists(file_path):
                result = subprocess.run(
                    ['flake8', file_path, '--statistics'],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.stdout:
                    print(f"  {file}: 发现问题")
                else:
                    print(f"  {file}: 无问题")
    except Exception as e:
        print(f"  Flake8检查失败: {e}")
    
    # 2. 统计代码行数
    print("\n统计代码信息...")
    total_lines = 0
    total_files = 0
    
    for root, dirs, files in os.walk(project_path):
        # 跳过特定目录
        dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', 'node_modules', '.tmp', 'instance', 'quality_reports']]
        
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        lines = len(f.readlines())
                        total_lines += lines
                        total_files += 1
                except:
                    pass
    
    results['code_stats'] = {
        'total_files': total_files,
        'total_lines': total_lines,
        'avg_lines_per_file': total_lines / total_files if total_files > 0 else 0
    }
    
    print(f"  Python文件数: {total_files}")
    print(f"  总代码行数: {total_lines}")
    print(f"  平均每文件行数: {total_lines / total_files if total_files > 0 else 0:.1f}")
    
    # 3. 检查测试覆盖率
    print("\n检查测试覆盖率...")
    test_files = []
    for root, dirs, files in os.walk(os.path.join(project_path, 'tests')):
        for file in files:
            if file.startswith('test_') and file.endswith('.py'):
                test_files.append(file)
    
    results['test_stats'] = {
        'test_files': len(test_files),
        'test_file_list': test_files
    }
    
    print(f"  测试文件数: {len(test_files)}")
    
    # 4. 生成摘要报告
    print("\n" + "=" * 60)
    print("分析摘要")
    print("=" * 60)
    print(f"分析时间: {results['timestamp']}")
    print(f"代码文件: {results['code_stats']['total_files']} 个")
    print(f"代码行数: {results['code_stats']['total_lines']} 行")
    print(f"测试文件: {results['test_stats']['test_files']} 个")
    
    # 保存结果
    output_dir = os.path.join(project_path, 'quality_reports')
    os.makedirs(output_dir, exist_ok=True)
    
    output_file = os.path.join(output_dir, 'quick_analysis.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n分析结果已保存到: {output_file}")
    print("=" * 60)
    
    return results


if __name__ == '__main__':
    project_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    quick_analysis(project_path)
