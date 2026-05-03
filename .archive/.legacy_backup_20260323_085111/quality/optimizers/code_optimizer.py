"""
代码优化实施
根据质量分析结果执行具体的代码优化
"""
import os
from pathlib import Path


def optimize_imports(file_path: str) -> bool:
    """优化导入语句"""
    try:
        with open(file_path, encoding='utf-8') as f:
            content = f.read()

        # 检查是否有未使用的导入(简单检查)
        lines = content.split('\n')
        import_lines = []
        code_lines = []

        in_import_section = True
        for line in lines:
            if in_import_section and (line.startswith('import ') or line.startswith('from ')):
                import_lines.append(line)
            else:
                in_import_section = False
                code_lines.append(line)

        # 这里可以添加更复杂的导入优化逻辑
        # 目前保持原样
        return True

    except Exception as e:
        print(f"优化导入失败: {e}")
        return False


def add_docstrings(file_path: str) -> bool:
    """添加文档字符串"""
    try:
        with open(file_path, encoding='utf-8') as f:
            content = f.read()

        # 检查文件是否有模块级文档字符串
        if not content.strip().startswith('"""'):
            # 添加模块文档字符串
            filename = os.path.basename(file_path)
            module_doc = f'"""\n{filename} 模块\n"""\n'
            content = module_doc + content

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

            return True

        return False

    except Exception as e:
        print(f"添加文档字符串失败: {e}")
        return False


def optimize_utils_files(project_path: str) -> list[str]:
    """优化utils目录下的文件"""
    utils_dir = Path(project_path) / 'utils'
    affected_files = []

    if not utils_dir.exists():
        return affected_files

    for file_path in utils_dir.glob('*.py'):
        if file_path.name == '__init__.py':
            continue

        # 添加文档字符串
        if add_docstrings(str(file_path)):
            affected_files.append(str(file_path))
            print(f"  优化: {file_path.name}")

    return affected_files


def optimize_test_files(project_path: str) -> list[str]:
    """优化测试文件"""
    tests_dir = Path(project_path) / 'tests'
    affected_files = []

    if not tests_dir.exists():
        return affected_files

    for file_path in tests_dir.rglob('test_*.py'):
        # 添加文档字符串
        if add_docstrings(str(file_path)):
            affected_files.append(str(file_path))
            print(f"  优化: {file_path.name}")

    return affected_files


def fix_code_style_issues(project_path: str) -> list[str]:
    """修复代码风格问题"""
    affected_files = []

    # 优化utils文件
    print("\n优化utils目录...")
    utils_files = optimize_utils_files(project_path)
    affected_files.extend(utils_files)

    # 优化测试文件
    print("\n优化测试文件...")
    test_files = optimize_test_files(project_path)
    affected_files.extend(test_files)

    return affected_files


def optimize_requirements(project_path: str) -> list[str]:
    """优化requirements.txt"""
    req_file = Path(project_path) / 'requirements.txt'

    if not req_file.exists():
        return []

    try:
        with open(req_file, encoding='utf-8') as f:
            lines = f.readlines()

        # 去除重复行和空行
        seen = set()
        unique_lines = []
        for line in lines:
            line = line.strip()
            if line and line not in seen and not line.startswith('#'):
                seen.add(line)
                unique_lines.append(line + '\n')

        # 排序(保持分组)
        # 这里简单处理,实际可以更智能地分组排序

        # 写回文件
        with open(req_file, 'w', encoding='utf-8') as f:
            f.writelines(unique_lines)

        print("  优化: requirements.txt")
        return [str(req_file)]

    except Exception as e:
        print(f"优化requirements.txt失败: {e}")
        return []


def run_all_optimizations(project_path: str) -> list[str]:
    """运行所有优化"""
    print("\n" + "=" * 60)
    print("执行代码优化")
    print("=" * 60)

    all_affected_files = []

    # 1. 修复代码风格问题
    print("\n[1/2] 修复代码风格问题...")
    style_files = fix_code_style_issues(project_path)
    all_affected_files.extend(style_files)

    # 2. 优化requirements.txt
    print("\n[2/2] 优化依赖配置...")
    req_files = optimize_requirements(project_path)
    all_affected_files.extend(req_files)

    print("\n" + "=" * 60)
    print(f"优化完成,影响文件: {len(all_affected_files)} 个")
    print("=" * 60)

    return all_affected_files


if __name__ == '__main__':
    project_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    affected = run_all_optimizations(project_path)

    print("\n受影响的文件:")
    for file in affected:
        print(f"  - {file}")
