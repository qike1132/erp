"""
未使用依赖分析工具
分析项目中安装但未被实际使用的依赖包
"""

import ast
import os
import sys
from pathlib import Path


class DependencyAnalyzer:
    """依赖分析器"""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.imports_found: set[str] = set()
        self.requirements: dict[str, str] = {}
        self.unused_deps: list[str] = []
        self.used_deps: list[str] = []

    def parse_requirements(self, requirements_file: str = "requirements.txt") -> dict[str, str]:
        """解析requirements.txt文件"""
        req_path = self.project_root / requirements_file
        if not req_path.exists():
            print(f"⚠️  未找到 {requirements_file}")
            return {}

        deps = {}
        with open(req_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    # 解析包名和版本
                    if '==' in line:
                        name, version = line.split('==', 1)
                        deps[name.lower()] = version
                    elif '>=' in line:
                        name = line.split('>=', 1)[0]
                        deps[name.lower()] = '>='
                    elif '~=' in line:
                        name = line.split('~=', 1)[0]
                        deps[name.lower()] = '~='
                    else:
                        deps[line.lower()] = ''

        self.requirements = deps
        return deps

    def find_python_files(self) -> list[Path]:
        """查找项目中的所有Python文件"""
        exclude_dirs = {
            'venv', 'env', '.venv', '__pycache__',
            '.git', 'node_modules', 'build', 'dist'
        }

        py_files = []
        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for file in files:
                if file.endswith('.py'):
                    py_files.append(Path(root) / file)

        return py_files

    def analyze_imports_in_file(self, file_path: Path) -> set[str]:
        """分析单个文件中的import语句"""
        imports = set()
        try:
            with open(file_path, encoding='utf-8') as f:
                content = f.read()
                tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        mod_name = name.name.split('.')[0]
                        imports.add(mod_name.lower())
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mod_name = node.module.split('.')[0]
                    imports.add(mod_name.lower())

        except Exception as e:
            print(f"⚠️  无法解析 {file_path}: {e}")

        return imports

    def analyze_all_imports(self):
        """分析所有Python文件中的import"""
        py_files = self.find_python_files()
        print(f"📁 找到 {len(py_files)} 个Python文件")

        for file in py_files:
            imports = self.analyze_imports_in_file(file)
            self.imports_found.update(imports)

        # 尝试获取依赖的实际导入名称
        self._map_dependency_names()

    def _map_dependency_names(self):
        """映射包名到导入名（某些包安装名与导入名不同）"""
        # 常见包名映射
        name_mapping = {
            'beautifulsoup4': {'bs4'},
            'python-dateutil': {'dateutil'},
            'pyyaml': {'yaml'},
            'pillow': {'PIL'},
            'mysql-connector-python': {'mysql'},
            'psycopg2-binary': {'psycopg2'},
            'python-dotenv': {'dotenv'},
            'flask-sqlalchemy': {'flask_sqlalchemy'},
            'flask-wtf': {'flask_wtf'},
            'flask-limiter': {'flask_limiter'},
            'flask-restful': {'flask_restful'},
            'flask-caching': {'flask_caching'},
            'flasgger': {'flasgger'},
            'pymysql': {'pymysql'},
            'redis': {'redis'},
            'pandas': {'pandas'},
            'openpyxl': {'openpyxl'},
            'waitress': {'waitress'},
            'chardet': {'chardet'},
            'pypinyin': {'pypinyin'},
            'python-slugify': {'slugify'},
            'arrow': {'arrow'},
            'bleach': {'bleach'},
            'fuzzywuzzy': {'fuzzywuzzy'},
            'xlsxwriter': {'xlsxwriter'},
            'pypdf2': {'PyPDF2'},
            'aiofiles': {'aiofiles'},
            'watchdog': {'watchdog'},
            'sqlparse': {'sqlparse'},
            'lxml': {'lxml'},
            'python-decouple': {'decouple'},
            'configobj': {'configobj'},
        }

        # 更新导入集合
        for dep_name, import_names in name_mapping.items():
            if dep_name in self.requirements:
                self.imports_found.update(import_names)

    def analyze_unused_dependencies(self):
        """分析未使用的依赖"""
        if not self.requirements:
            self.parse_requirements()

        if not self.imports_found:
            self.analyze_all_imports()

        for dep_name in self.requirements:
            # 检查依赖是否被使用
            dep_lower = dep_name.lower()

            # 直接匹配
            if dep_lower in self.imports_found:
                self.used_deps.append(dep_name)
                continue

            # 特殊映射检查
            special_mapping = {
                'pypdf2': 'PyPDF2',
                'beautifulsoup4': 'bs4',
                'pyyaml': 'yaml',
                'pillow': 'PIL',
                'python-dateutil': 'dateutil',
                'python-dotenv': 'dotenv',
                'python-slugify': 'slugify',
                'python-decouple': 'decouple',
                'flask-sqlalchemy': 'flask_sqlalchemy',
                'flask-wtf': 'flask_wtf',
                'flask-limiter': 'flask_limiter',
                'flask-restful': 'flask_restful',
                'flask-caching': 'flask_caching',
            }

            if dep_lower in special_mapping:
                mapped_name = special_mapping[dep_lower].lower()
                if mapped_name in self.imports_found:
                    self.used_deps.append(dep_name)
                    continue

            # 检查是否是标准库
            if self._is_standard_lib(dep_lower):
                continue

            # 标记为未使用
            self.unused_deps.append(dep_name)

        return self.unused_deps, self.used_deps

    def _is_standard_lib(self, module_name: str) -> bool:
        """检查是否是Python标准库"""
        std_libs = {
            'sys', 'os', 'io', 're', 'math', 'datetime', 'time',
            'json', 'csv', 'logging', 'unittest', 'pytest',
            'threading', 'multiprocessing', 'asyncio', 'pathlib',
            'collections', 'itertools', 'functools', 'typing',
            'hashlib', 'random', 'string', 'copy', 'inspect',
            'contextlib', 'enum', 'dataclasses', 'bisect',
            'heapq', 'queue', 'deque', 'set', 'list', 'dict',
            'builtins', 'types', 'operator', 'struct', 'array',
            'socket', 'http', 'urllib', 'xml', 'html', 'email',
            'subprocess', 'shutil', 'tempfile', 'glob', 'fnmatch',
            'traceback', 'pprint', 'configparser', 'argparse',
            'cmd', 'shlex', 'textwrap', 'difflib', 'filecmp',
            'fileinput', 'linecache', 'stat', 'os.path', 'pwd',
            'grp', 'platform', 'sysconfig', 'site', 'syslog',
            'atexit', 'signal', 'errno', 'ctypes', 'cgitb',
            'webbrowser', 'mailbox', 'mailcap', 'mimetypes',
            'quopri', 'uu', 'base64', 'binascii', 'bz2', 'gzip',
            'lzma', 'zipfile', 'tarfile', 'crypt', 'getpass', 'getopt', 'optparse', 'timeit', 'profile', 'pstats', 'hotshot', 'trace',
            'tabnanny', 'compileall', 'py_compile', 'dis',
            'pickletools', 'reprlib', 'codecs', 'unicodedata', 'stringprep', 'readline',
            'rlcompleter', 'tkinter', 'turtle', 'pydoc',
            'doctest', 'distutils',
            'ensurepip', 'venv', 'zipapp', 'pkgutil',
            'importlib', 'pkg_resources', 'setuptools',
            'pip', 'wheel', 'packaging', 'binhex', '__future__', '__hello__',
            '__phello__', '_weakref', '_weakrefset',
            'abc', 'aifc', 'antigravity', 'ast', 'asynchat', 'asyncore',
            'audioop', 'bdb',
            'calendar', 'cgi', 'chunk',
            'cmath', 'code', 'codeop',
            'colorsys', 'concurrent', 'contextvars', 'copyreg', 'curses', 'dbm', 'decimal', 'encodings', 'faulthandler', 'fcntl', 'formatter',
            'fractions', 'ftplib', 'gc', 'gettext',
            'hmac', 'imaplib', 'imghdr', 'imp', 'ipaddress', 'keyword', 'lib2to3', 'locale', 'macpath',
            'marshal', 'mmap', 'modulefinder',
            'msilib', 'msvcrt', 'netrc', 'nis', 'nntplib', 'numbers',
            'ossaudiodev',
            'parser', 'pdb', 'pickle',
            'pipes', 'plistlib', 'poplib',
            'posix', 'pty', 'pyclbr',
            'resource',
            'runpy', 'sched',
            'secrets', 'select', 'selectors',
            'shelve', 'smtpd', 'smtplib', 'sndhdr',
            'socketserver', 'spwd', 'sqlite3',
            'ssl', 'statistics', 'sunau', 'symtable', 'telnetlib',
            'termios', 'token', 'tokenize', 'tracemalloc', 'tty', 'uuid', 'warnings',
            'wave', 'weakref', 'winreg',
            'winsound', 'xdrlib', 'xmlrpc',
            'zipimport', 'zlib',
        }
        return module_name in std_libs

    def print_report(self):
        """打印分析报告"""
        print("\n" + "=" * 60)
        print("📊 依赖使用情况分析报告")
        print("=" * 60)

        print(f"\n📦 总共安装的依赖: {len(self.requirements)}")
        print(f"✅ 已使用的依赖: {len(self.used_deps)}")
        print(f"❌ 未使用的依赖: {len(self.unused_deps)}")

        if self.used_deps:
            print("\n✅ 已使用的依赖:")
            for dep in sorted(self.used_deps):
                version = self.requirements.get(dep, '')
                print(f"   - {dep}{f' ({version})' if version else ''}")

        if self.unused_deps:
            print("\n❌ 未使用的依赖（建议移除）:")
            for dep in sorted(self.unused_deps):
                version = self.requirements.get(dep, '')
                print(f"   - {dep}{f' ({version})' if version else ''}")

            print("\n" + "=" * 60)
            print("⚠️  警告：移除前请仔细检查!")
            print("   某些依赖可能通过动态导入或间接使用")
            print("=" * 60)

        return self.unused_deps, self.used_deps


def main():
    import argparse

    parser = argparse.ArgumentParser(description='分析项目中未使用的依赖')
    parser.add_argument(
        '--path', '-p',
        default='.',
        help='项目根目录路径'
    )
    parser.add_argument(
        '--requirements', '-r',
        default='requirements.txt',
        help='requirements.txt文件路径'
    )

    args = parser.parse_args()

    analyzer = DependencyAnalyzer(args.path)
    analyzer.parse_requirements(args.requirements)
    analyzer.analyze_all_imports()
    unused, _used = analyzer.analyze_unused_dependencies()
    analyzer.print_report()

    return 0 if not unused else 1


if __name__ == '__main__':
    sys.exit(main())
