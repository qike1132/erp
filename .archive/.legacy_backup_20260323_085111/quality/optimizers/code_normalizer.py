"""
全面代码规范化优化
执行PEP8规范检查和自动修复
"""
import os
import re
from pathlib import Path


class CodeNormalizer:
    """代码规范化处理器"""

    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.stats = {
            'files_processed': 0,
            'files_modified': 0,
            'issues_fixed': 0
        }

    def normalize_file(self, file_path: Path) -> tuple[bool, list[str]]:
        """规范化单个文件"""
        try:
            with open(file_path, encoding='utf-8') as f:
                original_content = f.read()

            content = original_content
            issues = []

            # 1. 移除BOM标记
            if content.startswith('\ufeff'):
                content = content[1:]
                issues.append('移除BOM标记')

            # 2. 统一换行符为LF
            if '\r\n' in content:
                content = content.replace('\r\n', '\n')
                issues.append('统一换行符')

            # 3. 移除行尾空格
            lines = content.split('\n')
            new_lines = []
            for i, line in enumerate(lines):
                stripped = line.rstrip()
                if stripped != line:
                    issues.append(f'行{i+1}: 移除行尾空格')
                new_lines.append(stripped)
            content = '\n'.join(new_lines)

            # 4. 确保文件末尾有换行符
            if content and not content.endswith('\n'):
                content += '\n'
                issues.append('添加文件末尾换行符')

            # 5. 移除多余的空行(超过2个连续空行)
            old_content = content
            content = re.sub(r'\n{3,}', '\n\n', content)
            if content != old_content:
                issues.append('移除多余空行')

            # 6. 优化导入语句顺序(简单处理)
            if self._should_optimize_imports(file_path):
                content, import_issues = self._optimize_imports(content)
                issues.extend(import_issues)

            # 判断是否有修改
            modified = content != original_content

            if modified:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)

            return modified, issues

        except Exception as e:
            return False, [f'处理错误: {e}']

    def _should_optimize_imports(self, file_path: Path) -> bool:
        """判断是否应该优化导入"""
        # 只优化Python文件,跳过测试文件
        return file_path.suffix == '.py' and 'test' not in str(file_path).lower()

    def _optimize_imports(self, content: str) -> tuple[str, list[str]]:
        """优化导入语句"""
        issues = []
        lines = content.split('\n')

        # 找到导入部分
        import_start = -1
        import_end = -1

        for i, line in enumerate(lines):
            if line.startswith('import ') or line.startswith('from '):
                if import_start == -1:
                    import_start = i
                import_end = i
            elif import_start != -1 and line.strip() and not line.startswith('#'):
                break

        if import_start == -1:
            return content, issues

        # 提取导入语句
        import_lines = lines[import_start:import_end+1]

        # 分类导入
        stdlib_imports = []
        third_party_imports = []
        local_imports = []

        for line in import_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue

            if stripped.startswith('import '):
                module = stripped.split()[1].split('.')[0]
            elif stripped.startswith('from '):
                module = stripped.split()[1]
            else:
                continue

            # 判断导入类型
            if module in ['os', 'sys', 're', 'json', 'datetime', 'pathlib', 'typing', 'functools', 'collections']:
                stdlib_imports.append(line)
            elif module in ['flask', 'sqlalchemy', 'pytest', 'pandas', 'numpy']:
                third_party_imports.append(line)
            else:
                local_imports.append(line)

        # 如果有分类变化,重新组织
        if stdlib_imports or third_party_imports or local_imports:
            new_imports = []

            if stdlib_imports:
                new_imports.extend(sorted(set(stdlib_imports)))
                new_imports.append('')

            if third_party_imports:
                new_imports.extend(sorted(set(third_party_imports)))
                new_imports.append('')

            if local_imports:
                new_imports.extend(sorted(set(local_imports)))

            # 移除末尾空行
            while new_imports and not new_imports[-1].strip():
                new_imports.pop()

            # 重新构建内容
            new_lines = lines[:import_start] + new_imports + [''] + lines[import_end+1:]
            content = '\n'.join(new_lines)
            issues.append('优化导入顺序')

        return content, issues

    def normalize_directory(self, directory: str, exclude_dirs: list[str] = None) -> dict:
        """规范化目录下的所有文件"""
        if exclude_dirs is None:
            exclude_dirs = ['.git', '__pycache__', 'node_modules', '.tmp', 'instance',
                           'quality_reports', '.optimization_backups', 'htmlcov']

        dir_path = self.project_path / directory

        if not dir_path.exists():
            return {'error': f'目录不存在: {directory}'}

        results = {
            'directory': directory,
            'files': [],
            'total_issues': 0
        }

        for file_path in dir_path.rglob('*.py'):
            # 检查是否在排除目录中
            if any(exclude in str(file_path) for exclude in exclude_dirs):
                continue

            self.stats['files_processed'] += 1

            modified, issues = self.normalize_file(file_path)

            if modified:
                self.stats['files_modified'] += 1
                self.stats['issues_fixed'] += len(issues)

                results['files'].append({
                    'file': str(file_path.relative_to(self.project_path)),
                    'issues': issues
                })
                results['total_issues'] += len(issues)

        return results

    def normalize_project(self) -> dict:
        """规范化整个项目"""
        print("=" * 60)
        print("全面代码规范化优化")
        print("=" * 60)

        # 规范化关键目录
        directories = ['utils', 'tests', 'quality']

        all_results = {
            'directories': [],
            'stats': self.stats
        }

        for directory in directories:
            print(f"\n处理 {directory}/ 目录...")
            result = self.normalize_directory(directory)
            all_results['directories'].append(result)

            if result.get('files'):
                print(f"  修改了 {len(result['files'])} 个文件")
                for file_info in result['files']:
                    print(f"    - {file_info['file']}: {len(file_info['issues'])} 个问题")
            else:
                print("  无需修改")

        # 规范化根目录文件
        print("\n处理根目录文件...")
        root_files = ['app.py', 'run.py']

        for file_name in root_files:
            file_path = self.project_path / file_name
            if file_path.exists():
                self.stats['files_processed'] += 1
                modified, issues = self.normalize_file(file_path)

                if modified:
                    self.stats['files_modified'] += 1
                    self.stats['issues_fixed'] += len(issues)
                    print(f"  [MODIFIED] {file_name}: {len(issues)} 个问题")
                else:
                    print(f"  [OK] {file_name}")

        print("\n" + "=" * 60)
        print("规范化完成")
        print("=" * 60)
        print(f"处理文件: {self.stats['files_processed']} 个")
        print(f"修改文件: {self.stats['files_modified']} 个")
        print(f"修复问题: {self.stats['issues_fixed']} 个")

        return all_results


def main():
    """主函数"""
    project_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    normalizer = CodeNormalizer(project_path)
    results = normalizer.normalize_project()

    # 保存结果
    import json
    output_file = Path(project_path) / 'quality_reports' / 'normalization_results.json'
    output_file.parent.mkdir(exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n结果已保存到: {output_file}")

    return results


if __name__ == '__main__':
    main()
