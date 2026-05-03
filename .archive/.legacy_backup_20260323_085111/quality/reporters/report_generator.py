"""
质量分析报告生成器
支持HTML、Markdown、JSON三种格式
"""
import json
from datetime import datetime
from typing import Any


class ReportGenerator:
    """报告生成器基类"""

    def __init__(self, analysis_results: dict[str, Any]):
        self.results = analysis_results
        self.timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def generate(self) -> str:
        """生成报告"""
        raise NotImplementedError


class HTMLReportGenerator(ReportGenerator):
    """HTML格式报告生成器"""

    def generate(self) -> str:
        """生成HTML报告"""
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>代码质量分析报告</title>
    <style>
        body {{
            font-family: 'Microsoft YaHei', Arial, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #555;
            margin-top: 30px;
        }}
        .summary {{
            background: #e8f5e9;
            padding: 20px;
            border-radius: 5px;
            margin: 20px 0;
        }}
        .tool-section {{
            margin: 20px 0;
            padding: 20px;
            border: 1px solid #ddd;
            border-radius: 5px;
        }}
        .issue {{
            background: #fff3e0;
            padding: 10px;
            margin: 10px 0;
            border-left: 4px solid #ff9800;
        }}
        .error {{ border-left-color: #f44336; background: #ffebee; }}
        .warning {{ border-left-color: #ff9800; background: #fff3e0; }}
        .info {{ border-left-color: #2196f3; background: #e3f2fd; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #4CAF50;
            color: white;
        }}
        tr:hover {{
            background-color: #f5f5f5;
        }}
        .timestamp {{
            color: #666;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>代码质量分析报告</h1>
        <p class="timestamp">生成时间: {self.timestamp}</p>

        {self._generate_summary()}

        {self._generate_tool_sections()}
    </div>
</body>
</html>"""
        return html

    def _generate_summary(self) -> str:
        """生成摘要部分"""
        total_issues = 0
        for tool_result in self.results.values():
            if 'summary' in tool_result:
                total_issues += tool_result['summary'].get('total', 0)

        return f"""
        <div class="summary">
            <h2>分析摘要</h2>
            <p><strong>发现问题总数:</strong> {total_issues}</p>
            <p><strong>分析工具数量:</strong> {len(self.results)}</p>
        </div>"""

    def _generate_tool_sections(self) -> str:
        """生成各工具分析结果部分"""
        sections = []

        for tool_name, result in self.results.items():
            section = f"""
            <div class="tool-section">
                <h2>{tool_name}</h2>"""

            if 'error' in result:
                section += f"""
                <div class="issue error">
                    <strong>错误:</strong> {result['error']}
                </div>"""
            else:
                # 显示摘要
                if 'summary' in result:
                    section += """
                <h3>摘要</h3>
                <table>
                    <tr><th>指标</th><th>数量</th></tr>"""

                    for key, value in result['summary'].items():
                        section += f"""
                    <tr><td>{key}</td><td>{value}</td></tr>"""

                    section += """
                </table>"""

                # 显示部分问题示例
                if 'issues' in result and result['issues']:
                    section += """
                <h3>问题示例 (前10个)</h3>"""

                    for issue in result['issues'][:10]:
                        issue_class = 'info'
                        if isinstance(issue, dict):
                            issue_type = issue.get('type', issue.get('issue_severity', 'info'))
                            if issue_type in ['error', 'HIGH']:
                                issue_class = 'error'
                            elif issue_type in ['warning', 'MEDIUM']:
                                issue_class = 'warning'

                            issue_text = json.dumps(issue, ensure_ascii=False)
                        else:
                            issue_text = str(issue)

                        section += f"""
                <div class="issue {issue_class}">
                    <pre>{issue_text}</pre>
                </div>"""

            section += """
            </div>"""
            sections.append(section)

        return '\n'.join(sections)


class MarkdownReportGenerator(ReportGenerator):
    """Markdown格式报告生成器"""

    def generate(self) -> str:
        """生成Markdown报告"""
        md = f"""# 代码质量分析报告

生成时间: {self.timestamp}

## 分析摘要

{self._generate_summary_md()}

## 详细分析结果

{self._generate_tool_sections_md()}
"""
        return md

    def _generate_summary_md(self) -> str:
        """生成Markdown摘要"""
        total_issues = 0
        for tool_result in self.results.values():
            if 'summary' in tool_result:
                total_issues += tool_result['summary'].get('total', 0)

        return f"""- **发现问题总数**: {total_issues}
- **分析工具数量**: {len(self.results)}"""

    def _generate_tool_sections_md(self) -> str:
        """生成Markdown工具分析结果"""
        sections = []

        for tool_name, result in self.results.items():
            section = f"### {tool_name}\n\n"

            if 'error' in result:
                section += f"**错误**: {result['error']}\n\n"
            else:
                # 显示摘要
                if 'summary' in result:
                    section += "#### 摘要\n\n"
                    section += "| 指标 | 数量 |\n"
                    section += "|------|------|\n"

                    for key, value in result['summary'].items():
                        section += f"| {key} | {value} |\n"

                    section += "\n"

                # 显示部分问题示例
                if 'issues' in result and result['issues']:
                    section += "#### 问题示例 (前5个)\n\n"

                    for i, issue in enumerate(result['issues'][:5], 1):
                        if isinstance(issue, dict):
                            issue_text = json.dumps(issue, ensure_ascii=False, indent=2)
                        else:
                            issue_text = str(issue)

                        section += f"{i}. ```json\n{issue_text}\n```\n\n"

            sections.append(section)

        return '\n'.join(sections)


class JSONReportGenerator(ReportGenerator):
    """JSON格式报告生成器"""

    def generate(self) -> str:
        """生成JSON报告"""
        report = {
            'timestamp': self.timestamp,
            'summary': self._generate_summary_dict(),
            'results': self.results
        }
        return json.dumps(report, ensure_ascii=False, indent=2)

    def _generate_summary_dict(self) -> dict[str, Any]:
        """生成摘要字典"""
        total_issues = 0
        tools_summary = {}

        for tool_name, result in self.results.items():
            if 'summary' in result:
                tools_summary[tool_name] = result['summary']
                total_issues += result['summary'].get('total', 0)

        return {
            'total_issues': total_issues,
            'tools_count': len(self.results),
            'tools': tools_summary
        }


def generate_report(analysis_results: dict[str, Any], output_format: str = 'html', output_file: str = None) -> str:
    """
    生成质量分析报告

    Args:
        analysis_results: 分析结果
        output_format: 输出格式 (html, markdown, json)
        output_file: 输出文件路径

    Returns:
        报告内容
    """
    generators = {
        'html': HTMLReportGenerator,
        'markdown': MarkdownReportGenerator,
        'json': JSONReportGenerator
    }

    generator_class = generators.get(output_format.lower())
    if not generator_class:
        raise ValueError(f"不支持的输出格式: {output_format}")

    generator = generator_class(analysis_results)
    report = generator.generate()

    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"报告已保存到: {output_file}")

    return report


if __name__ == '__main__':
    # 示例用法
    sample_results = {
        'PylintAnalyzer': {
            'summary': {'total': 10, 'error': 2, 'warning': 5},
            'issues': [{'type': 'error', 'message': '示例错误'}]
        }
    }

    report = generate_report(sample_results, 'html', 'quality_report.html')
    print("HTML报告生成完成")
