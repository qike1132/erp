"""
优化建议生成器
基于质量分析结果生成具体的优化建议
"""
from dataclasses import dataclass
from typing import Any


@dataclass
class OptimizationSuggestion:
    """优化建议"""
    category: str  # 类别: performance, code_quality, security, maintainability
    priority: str  # 优先级: high, medium, low
    title: str  # 标题
    description: str  # 描述
    location: str  # 位置
    suggestion: str  # 具体建议
    impact: str  # 预期影响
    risk: str  # 风险评估


class OptimizationSuggestionGenerator:
    """优化建议生成器"""

    def __init__(self, analysis_results: dict[str, Any]):
        self.results = analysis_results
        self.suggestions = []

    def generate(self) -> list[OptimizationSuggestion]:
        """生成优化建议"""
        self.suggestions = []

        # 分析各工具结果并生成建议
        for tool_name, result in self.results.items():
            if tool_name == 'PylintAnalyzer':
                self._analyze_pylint(result)
            elif tool_name == 'Flake8Analyzer':
                self._analyze_flake8(result)
            elif tool_name == 'RadonAnalyzer':
                self._analyze_radon(result)
            elif tool_name == 'BanditAnalyzer':
                self._analyze_bandit(result)

        # 按优先级排序
        self.suggestions.sort(key=lambda x: {'high': 0, 'medium': 1, 'low': 2}[x.priority])

        return self.suggestions

    def _analyze_pylint(self, result: dict[str, Any]):
        """分析Pylint结果"""
        if 'issues' not in result:
            return

        for issue in result['issues']:
            category = self._map_pylint_category(issue.get('type', ''))
            priority = self._map_priority(issue.get('type', ''))

            suggestion = OptimizationSuggestion(
                category=category,
                priority=priority,
                title=f"Pylint: {issue.get('symbol', '代码问题')}",
                description=issue.get('message', ''),
                location=f"{issue.get('path', '')}:{issue.get('line', 0)}",
                suggestion=self._get_pylint_suggestion(issue),
                impact="提高代码质量和可读性",
                risk="低风险,建议优先处理高优先级问题"
            )
            self.suggestions.append(suggestion)

    def _analyze_flake8(self, result: dict[str, Any]):
        """分析Flake8结果"""
        if 'issues' not in result:
            return

        for issue in result['issues']:
            suggestion = OptimizationSuggestion(
                category='code_quality',
                priority='medium',
                title="Flake8: 代码规范问题",
                description=str(issue),
                location="",
                suggestion="遵循PEP8代码规范",
                impact="提高代码可读性和一致性",
                risk="低风险"
            )
            self.suggestions.append(suggestion)

    def _analyze_radon(self, result: dict[str, Any]):
        """分析Radon结果"""
        summary = result.get('summary', {})

        # 检查圈复杂度
        avg_cc = summary.get('avg_cc', 0)
        if avg_cc > 10:
            suggestion = OptimizationSuggestion(
                category='maintainability',
                priority='high',
                title="高圈复杂度",
                description=f"平均圈复杂度为 {avg_cc:.2f},超过推荐值10",
                location="全局",
                suggestion="重构复杂函数,拆分为更小的函数,使用早返回减少嵌套",
                impact="提高代码可维护性和可测试性",
                risk="中等风险,需要仔细测试重构后的代码"
            )
            self.suggestions.append(suggestion)

        # 检查可维护性指数
        avg_mi = summary.get('avg_mi', 100)
        if avg_mi < 65:
            suggestion = OptimizationSuggestion(
                category='maintainability',
                priority='medium',
                title="低可维护性指数",
                description=f"平均可维护性指数为 {avg_mi:.2f},低于推荐值65",
                location="全局",
                suggestion="减少代码行数,降低圈复杂度,增加注释和文档",
                impact="提高代码可维护性",
                risk="低风险"
            )
            self.suggestions.append(suggestion)

    def _analyze_bandit(self, result: dict[str, Any]):
        """分析Bandit结果"""
        if 'issues' not in result:
            return

        for issue in result['issues']:
            severity = issue.get('issue_severity', 'LOW')
            priority = 'high' if severity == 'HIGH' else 'medium' if severity == 'MEDIUM' else 'low'

            suggestion = OptimizationSuggestion(
                category='security',
                priority=priority,
                title=f"安全问题: {issue.get('test_id', '')}",
                description=issue.get('issue_text', ''),
                location=f"{issue.get('filename', '')}:{issue.get('line_number', 0)}",
                suggestion=self._get_bandit_suggestion(issue),
                impact="消除安全漏洞,提高系统安全性",
                risk="必须修复,存在安全风险"
            )
            self.suggestions.append(suggestion)

    def _map_pylint_category(self, issue_type: str) -> str:
        """映射Pylint问题类型到类别"""
        mapping = {
            'error': 'code_quality',
            'warning': 'code_quality',
            'convention': 'code_quality',
            'refactor': 'maintainability'
        }
        return mapping.get(issue_type, 'code_quality')

    def _map_priority(self, issue_type: str) -> str:
        """映射问题类型到优先级"""
        mapping = {
            'error': 'high',
            'warning': 'medium',
            'convention': 'low',
            'refactor': 'medium',
            'HIGH': 'high',
            'MEDIUM': 'medium',
            'LOW': 'low'
        }
        return mapping.get(issue_type, 'low')

    def _get_pylint_suggestion(self, issue: dict[str, Any]) -> str:
        """获取Pylint问题的具体建议"""
        symbol = issue.get('symbol', '')

        suggestions = {
            'unused-variable': "删除未使用的变量或使用它",
            'unused-import': "删除未使用的导入",
            'too-many-arguments': "减少函数参数数量,考虑使用对象或字典传递参数",
            'too-many-locals': "减少局部变量数量,考虑拆分函数",
            'too-many-branches': "减少分支数量,考虑使用多态或策略模式",
            'too-many-statements': "减少语句数量,拆分为多个函数",
            'duplicate-code': "提取重复代码为公共函数或类",
            'missing-docstring': "添加文档字符串"
        }

        return suggestions.get(symbol, "根据Pylint建议修复此问题")

    def _get_bandit_suggestion(self, issue: dict[str, Any]) -> str:
        """获取Bandit安全问题的具体建议"""
        test_id = issue.get('test_id', '')

        suggestions = {
            'B101': "避免使用assert语句,使用正规的断言库",
            'B102': "避免使用exec函数",
            'B103': "设置适当的文件权限",
            'B105': "避免硬编码密码",
            'B106': "避免硬编码密码",
            'B107': "避免硬编码密码",
            'B108': "避免使用不安全的临时文件",
            'B110': "避免使用try-except-pass,至少记录异常",
            'B112': "避免使用try-except-continue,至少记录异常",
            'B201': "避免使用pickle处理不可信数据",
            'B301': "避免使用pickle处理不可信数据",
            'B302': "避免使用marshal处理不可信数据",
            'B303': "使用安全的随机数生成器",
            'B304': "使用安全的加密算法",
            'B305': "使用安全的加密模式",
            'B306': "避免使用不安全的XML解析",
            'B307': "避免使用eval函数",
            'B308': "避免使用不安全的格式化字符串",
            'B309': "避免使用不安全的XML解析",
            'B310': "避免使用不安全的XML解析"
        }

        return suggestions.get(test_id, "修复此安全问题")

    def to_dict_list(self) -> list[dict[str, str]]:
        """转换为字典列表"""
        return [
            {
                'category': s.category,
                'priority': s.priority,
                'title': s.title,
                'description': s.description,
                'location': s.location,
                'suggestion': s.suggestion,
                'impact': s.impact,
                'risk': s.risk
            }
            for s in self.suggestions
        ]


if __name__ == '__main__':
    # 示例用法
    sample_results = {
        'RadonAnalyzer': {
            'summary': {'avg_cc': 15, 'avg_mi': 50}
        },
        'BanditAnalyzer': {
            'issues': [
                {'test_id': 'B105', 'issue_severity': 'HIGH', 'issue_text': '硬编码密码'}
            ]
        }
    }

    generator = OptimizationSuggestionGenerator(sample_results)
    suggestions = generator.generate()

    print(f"生成 {len(suggestions)} 条优化建议:")
    for i, s in enumerate(suggestions, 1):
        print(f"\n{i}. [{s.priority}] {s.title}")
        print(f"   位置: {s.location}")
        print(f"   建议: {s.suggestion}")
