"""
代码质量分析框架
集成多种静态分析工具,提供统一的代码质量评估接口
"""
import os
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Any


class QualityAnalyzer:
    """代码质量分析器基类"""
    
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.results = {}
    
    def analyze(self) -> Dict[str, Any]:
        """执行分析"""
        raise NotImplementedError
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self.results


class PylintAnalyzer(QualityAnalyzer):
    """Pylint静态分析器"""
    
    def analyze(self) -> Dict[str, Any]:
        """执行Pylint分析"""
        try:
            # 运行pylint
            result = subprocess.run(
                ['pylint', str(self.project_path), '--output-format=json'],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            # 解析结果
            if result.stdout:
                issues = json.loads(result.stdout)
            else:
                issues = []
            
            # 统计问题
            self.results = {
                'tool': 'pylint',
                'issues': issues,
                'summary': {
                    'total': len(issues),
                    'error': len([i for i in issues if i['type'] == 'error']),
                    'warning': len([i for i in issues if i['type'] == 'warning']),
                    'convention': len([i for i in issues if i['type'] == 'convention']),
                    'refactor': len([i for i in issues if i['type'] == 'refactor'])
                }
            }
            
        except Exception as e:
            self.results = {
                'tool': 'pylint',
                'error': str(e),
                'issues': [],
                'summary': {'total': 0}
            }
        
        return self.results


class Flake8Analyzer(QualityAnalyzer):
    """Flake8静态分析器"""
    
    def analyze(self) -> Dict[str, Any]:
        """执行Flake8分析"""
        try:
            # 运行flake8
            result = subprocess.run(
                ['flake8', str(self.project_path), '--format=json'],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            # 解析结果
            if result.stdout:
                issues = json.loads(result.stdout)
            else:
                issues = []
            
            self.results = {
                'tool': 'flake8',
                'issues': issues,
                'summary': {
                    'total': len(issues)
                }
            }
            
        except Exception as e:
            self.results = {
                'tool': 'flake8',
                'error': str(e),
                'issues': [],
                'summary': {'total': 0}
            }
        
        return self.results


class RadonAnalyzer(QualityAnalyzer):
    """Radon复杂度分析器"""
    
    def analyze(self) -> Dict[str, Any]:
        """执行Radon复杂度分析"""
        try:
            # 计算圈复杂度
            cc_result = subprocess.run(
                ['radon', 'cc', str(self.project_path), '-j'],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            # 计算可维护性指数
            mi_result = subprocess.run(
                ['radon', 'mi', str(self.project_path), '-j'],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            # 解析结果
            cc_data = json.loads(cc_result.stdout) if cc_result.stdout else {}
            mi_data = json.loads(mi_result.stdout) if mi_result.stdout else {}
            
            self.results = {
                'tool': 'radon',
                'cyclomatic_complexity': cc_data,
                'maintainability_index': mi_data,
                'summary': {
                    'avg_cc': self._calculate_avg_cc(cc_data),
                    'avg_mi': self._calculate_avg_mi(mi_data)
                }
            }
            
        except Exception as e:
            self.results = {
                'tool': 'radon',
                'error': str(e),
                'cyclomatic_complexity': {},
                'maintainability_index': {},
                'summary': {}
            }
        
        return self.results
    
    def _calculate_avg_cc(self, cc_data: Dict) -> float:
        """计算平均圈复杂度"""
        if not cc_data:
            return 0.0
        
        total_cc = 0
        count = 0
        
        for file_data in cc_data.values():
            for item in file_data:
                total_cc += item.get('complexity', 0)
                count += 1
        
        return total_cc / count if count > 0 else 0.0
    
    def _calculate_avg_mi(self, mi_data: Dict) -> float:
        """计算平均可维护性指数"""
        if not mi_data:
            return 0.0
        
        total_mi = 0
        count = 0
        
        for file_data in mi_data.values():
            total_mi += file_data.get('mi', 0)
            count += 1
        
        return total_mi / count if count > 0 else 0.0


class BanditAnalyzer(QualityAnalyzer):
    """Bandit安全分析器"""
    
    def analyze(self) -> Dict[str, Any]:
        """执行Bandit安全分析"""
        try:
            # 运行bandit
            result = subprocess.run(
                ['bandit', '-r', str(self.project_path), '-f', 'json'],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            # 解析结果
            if result.stdout:
                data = json.loads(result.stdout)
                issues = data.get('results', [])
            else:
                issues = []
            
            self.results = {
                'tool': 'bandit',
                'issues': issues,
                'summary': {
                    'total': len(issues),
                    'high_severity': len([i for i in issues if i.get('issue_severity') == 'HIGH']),
                    'medium_severity': len([i for i in issues if i.get('issue_severity') == 'MEDIUM']),
                    'low_severity': len([i for i in issues if i.get('issue_severity') == 'LOW'])
                }
            }
            
        except Exception as e:
            self.results = {
                'tool': 'bandit',
                'error': str(e),
                'issues': [],
                'summary': {'total': 0}
            }
        
        return self.results


class QualityAnalysisRunner:
    """质量分析运行器"""
    
    def __init__(self, project_path: str):
        self.project_path = project_path
        self.analyzers = [
            PylintAnalyzer(project_path),
            Flake8Analyzer(project_path),
            RadonAnalyzer(project_path),
            BanditAnalyzer(project_path)
        ]
        self.results = {}
    
    def run_all(self) -> Dict[str, Any]:
        """运行所有分析器"""
        for analyzer in self.analyzers:
            tool_name = analyzer.__class__.__name__
            print(f"运行 {tool_name}...")
            self.results[tool_name] = analyzer.analyze()
        
        return self.results
    
    def get_summary(self) -> Dict[str, Any]:
        """获取分析摘要"""
        summary = {
            'total_issues': 0,
            'tools': {}
        }
        
        for tool_name, result in self.results.items():
            if 'summary' in result:
                summary['tools'][tool_name] = result['summary']
                summary['total_issues'] += result['summary'].get('total', 0)
        
        return summary
    
    def save_results(self, output_file: str):
        """保存分析结果"""
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        print(f"分析结果已保存到: {output_file}")


if __name__ == '__main__':
    # 示例用法
    project_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    runner = QualityAnalysisRunner(project_path)
    results = runner.run_all()
    print("\n分析摘要:")
    print(json.dumps(runner.get_summary(), ensure_ascii=False, indent=2))
