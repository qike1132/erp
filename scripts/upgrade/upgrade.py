"""
ERP系统依赖库升级执行脚本

功能:
1. 执行升级前检查
2. 安装新依赖库
3. 验证安装结果
4. 生成升级报告

使用方法:
    python scripts/upgrade/upgrade.py --phase p0
    python scripts/upgrade/upgrade.py --phase p1
    python scripts/upgrade/upgrade.py --phase p2
    python scripts/upgrade/upgrade.py --all
"""

import os
import sys
import subprocess
import argparse
import json
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
LOG_DIR = PROJECT_ROOT / 'logs' / 'upgrade'


DEPENDENCIES = {
    'p0': [
        ('chardet', '5.2.0'),
        ('phonenumbers', '8.13.27'),
        ('pypinyin', '0.51.0'),
        ('python-slugify', '8.0.4'),
        ('arrow', '1.3.0'),
        ('python-dateutil', '2.9.0'),
        ('PyYAML', '6.0.1'),
        ('lxml', '5.1.0'),
        ('beautifulsoup4', '4.12.3'),
        ('bleach', '6.1.0'),
        ('requests', '2.31.0'),
        ('sqlparse', '0.4.4'),
    ],
    'p1': [
        ('XlsxWriter', '3.1.9'),
        ('python-docx', '1.1.0'),
        ('PyPDF2', '3.0.1'),
        ('aiofiles', '23.2.1'),
        ('watchdog', '3.0.0'),
        ('fuzzywuzzy', '0.18.0'),
        ('python-Levenshtein', '0.25.1'),
        ('python-decouple', '3.8'),
        ('configobj', '5.0.8'),
    ],
    'p2': [
        ('flashtext', '2.7'),
        ('tablib', '3.6.1'),
        ('aiohttp', '3.9.3'),
        ('websockets', '12.0'),
        ('reportlab', '4.0.8'),
        ('pdfminer.six', '20231228'),
        ('qrcode', '7.4.2'),
    ]
}


class UpgradeManager:
    """升级管理器"""
    
    def __init__(self):
        self.log_dir = LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.log_file = self.log_dir / f'upgrade_{self.timestamp}.log'
        self.results = {
            'success': [],
            'failed': [],
            'skipped': []
        }
    
    def log(self, message: str, level: str = 'INFO'):
        """记录日志"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_line = f"[{timestamp}] [{level}] {message}"
        print(log_line)
        
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_line + '\n')
    
    def check_environment(self):
        """检查环境"""
        self.log("=" * 50)
        self.log("环境检查")
        self.log("=" * 50)
        
        checks = []
        
        self.log(f"Python版本: {sys.version}")
        checks.append(('Python版本', True, sys.version))
        
        try:
            import pip
            pip_version = pip.__version__
            self.log(f"pip版本: {pip_version}")
            checks.append(('pip版本', True, pip_version))
        except ImportError:
            self.log("pip未安装", 'ERROR')
            checks.append(('pip版本', False, '未安装'))
        
        try:
            import flask
            flask_version = flask.__version__
            self.log(f"Flask版本: {flask_version}")
            checks.append(('Flask版本', True, flask_version))
        except ImportError:
            self.log("Flask未安装", 'ERROR')
            checks.append(('Flask版本', False, '未安装'))
        
        try:
            result = subprocess.run(
                ['git', '--version'],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                self.log(f"Git: {result.stdout.strip()}")
                checks.append(('Git', True, result.stdout.strip()))
            else:
                checks.append(('Git', False, '不可用'))
        except FileNotFoundError:
            checks.append(('Git', False, '未安装'))
        
        return all(c[1] for c in checks)
    
    def install_package(self, package: str, version: str):
        """安装单个包"""
        package_spec = f"{package}=={version}"
        self.log(f"安装 {package_spec}...")
        
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', package_spec],
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT
            )
            
            if result.returncode == 0:
                self.log(f"✓ {package_spec} 安装成功", 'SUCCESS')
                self.results['success'].append(package_spec)
                return True
            else:
                self.log(f"✗ {package_spec} 安装失败: {result.stderr}", 'ERROR')
                self.results['failed'].append({
                    'package': package_spec,
                    'error': result.stderr
                })
                return False
        except Exception as e:
            self.log(f"✗ {package_spec} 安装异常: {e}", 'ERROR')
            self.results['failed'].append({
                'package': package_spec,
                'error': str(e)
            })
            return False
    
    def verify_package(self, package: str):
        """验证包安装"""
        try:
            module = __import__(package.replace('-', '_').replace('.', '_'))
            version = getattr(module, '__version__', 'unknown')
            return True, version
        except ImportError:
            return False, None
    
    def upgrade_phase(self, phase: str):
        """执行升级阶段"""
        self.log("=" * 50)
        self.log(f"开始 {phase.upper()} 阶段升级")
        self.log("=" * 50)
        
        if phase not in DEPENDENCIES:
            self.log(f"无效的阶段: {phase}", 'ERROR')
            return False
        
        packages = DEPENDENCIES[phase]
        
        for package, version in packages:
            self.install_package(package, version)
        
        self.log("=" * 50)
        self.log(f"{phase.upper()} 阶段升级完成")
        self.log("=" * 50)
        
        return len(self.results['failed']) == 0
    
    def upgrade_all(self):
        """执行全部升级"""
        self.log("=" * 50)
        self.log("开始全部升级")
        self.log("=" * 50)
        
        for phase in ['p0', 'p1', 'p2']:
            self.upgrade_phase(phase)
        
        self.log("=" * 50)
        self.log("全部升级完成")
        self.log("=" * 50)
        
        return len(self.results['failed']) == 0
    
    def verify_installation(self):
        """验证安装结果"""
        self.log("=" * 50)
        self.log("验证安装结果")
        self.log("=" * 50)
        
        all_packages = []
        for packages in DEPENDENCIES.values():
            all_packages.extend(packages)
        
        verification_results = []
        
        for package, expected_version in all_packages:
            installed, actual_version = self.verify_package(package)
            
            if installed:
                self.log(f"✓ {package}: {actual_version}")
                verification_results.append({
                    'package': package,
                    'installed': True,
                    'version': actual_version
                })
            else:
                self.log(f"✗ {package}: 未安装", 'ERROR')
                verification_results.append({
                    'package': package,
                    'installed': False,
                    'version': None
                })
        
        return all(r['installed'] for r in verification_results)
    
    def generate_report(self):
        """生成升级报告"""
        report = {
            'timestamp': self.timestamp,
            'python_version': sys.version,
            'results': self.results,
            'summary': {
                'total_success': len(self.results['success']),
                'total_failed': len(self.results['failed']),
                'total_skipped': len(self.results['skipped'])
            }
        }
        
        report_file = self.log_dir / f'upgrade_report_{self.timestamp}.json'
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        self.log("=" * 50)
        self.log("升级报告")
        self.log("=" * 50)
        self.log(f"成功: {report['summary']['total_success']}")
        self.log(f"失败: {report['summary']['total_failed']}")
        self.log(f"跳过: {report['summary']['total_skipped']}")
        self.log(f"报告文件: {report_file}")
        
        return report
    
    def run_tests(self):
        """运行测试"""
        self.log("=" * 50)
        self.log("运行测试")
        self.log("=" * 50)
        
        test_file = PROJECT_ROOT / 'tests' / 'test_new_libraries.py'
        
        if test_file.exists():
            result = subprocess.run(
                [sys.executable, '-m', 'pytest', str(test_file), '-v', '--tb=short'],
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT
            )
            
            self.log(result.stdout)
            
            if result.returncode == 0:
                self.log("测试通过", 'SUCCESS')
                return True
            else:
                self.log("测试失败", 'ERROR')
                self.log(result.stderr, 'ERROR')
                return False
        else:
            self.log("测试文件不存在", 'WARNING')
            return None


def main():
    parser = argparse.ArgumentParser(description='ERP系统依赖库升级工具')
    parser.add_argument(
        '--phase',
        choices=['p0', 'p1', 'p2'],
        help='升级阶段'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='执行全部升级'
    )
    parser.add_argument(
        '--verify',
        action='store_true',
        help='仅验证安装'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='运行测试'
    )
    
    args = parser.parse_args()
    
    manager = UpgradeManager()
    
    if not manager.check_environment():
        manager.log("环境检查失败，请先解决环境问题", 'ERROR')
        sys.exit(1)
    
    if args.all:
        success = manager.upgrade_all()
    elif args.phase:
        success = manager.upgrade_phase(args.phase)
    elif args.verify:
        success = manager.verify_installation()
    elif args.test:
        success = manager.run_tests()
    else:
        parser.print_help()
        return
    
    manager.generate_report()
    
    if not success:
        sys.exit(1)


if __name__ == '__main__':
    main()
