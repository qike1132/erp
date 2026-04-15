"""
代码质量分析主程序
整合所有分析工具,生成完整的质量分析报告
"""
import os
import sys
import json
from datetime import datetime
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from quality.analyzers.code_analyzers import QualityAnalysisRunner
from quality.reporters.report_generator import generate_report
from quality.optimizers.suggestion_generator import OptimizationSuggestionGenerator


def run_quality_analysis(project_path: str, output_dir: str = None):
    """
    运行完整的代码质量分析
    
    Args:
        project_path: 项目路径
        output_dir: 输出目录
    """
    print("=" * 60)
    print("代码质量分析开始")
    print("=" * 60)
    print(f"项目路径: {project_path}")
    print(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 设置输出目录
    if not output_dir:
        output_dir = os.path.join(project_path, 'quality_reports')
    
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. 运行代码质量分析
    print("步骤1: 运行代码质量分析工具...")
    runner = QualityAnalysisRunner(project_path)
    analysis_results = runner.run_all()
    
    # 保存分析结果
    results_file = os.path.join(output_dir, 'analysis_results.json')
    runner.save_results(results_file)
    print()
    
    # 2. 生成报告
    print("步骤2: 生成分析报告...")
    
    # HTML报告
    html_report_file = os.path.join(output_dir, 'quality_report.html')
    generate_report(analysis_results, 'html', html_report_file)
    
    # Markdown报告
    md_report_file = os.path.join(output_dir, 'quality_report.md')
    generate_report(analysis_results, 'markdown', md_report_file)
    
    # JSON报告
    json_report_file = os.path.join(output_dir, 'quality_report.json')
    generate_report(analysis_results, 'json', json_report_file)
    print()
    
    # 3. 生成优化建议
    print("步骤3: 生成优化建议...")
    suggestion_generator = OptimizationSuggestionGenerator(analysis_results)
    suggestions = suggestion_generator.generate()
    
    # 保存优化建议
    suggestions_file = os.path.join(output_dir, 'optimization_suggestions.json')
    with open(suggestions_file, 'w', encoding='utf-8') as f:
        json.dump(suggestion_generator.to_dict_list(), f, ensure_ascii=False, indent=2)
    print(f"优化建议已保存到: {suggestions_file}")
    print()
    
    # 4. 输出摘要
    print("=" * 60)
    print("分析摘要")
    print("=" * 60)
    
    summary = runner.get_summary()
    print(f"发现问题总数: {summary['total_issues']}")
    print(f"生成优化建议: {len(suggestions)} 条")
    print()
    
    # 按优先级统计建议
    high_priority = len([s for s in suggestions if s.priority == 'high'])
    medium_priority = len([s for s in suggestions if s.priority == 'medium'])
    low_priority = len([s for s in suggestions if s.priority == 'low'])
    
    print(f"高优先级建议: {high_priority} 条")
    print(f"中优先级建议: {medium_priority} 条")
    print(f"低优先级建议: {low_priority} 条")
    print()
    
    # 按类别统计建议
    categories = {}
    for s in suggestions:
        categories[s.category] = categories.get(s.category, 0) + 1
    
    print("建议类别分布:")
    for category, count in categories.items():
        print(f"  - {category}: {count} 条")
    print()
    
    # 5. 输出报告位置
    print("=" * 60)
    print("报告文件")
    print("=" * 60)
    print(f"HTML报告: {html_report_file}")
    print(f"Markdown报告: {md_report_file}")
    print(f"JSON报告: {json_report_file}")
    print(f"分析结果: {results_file}")
    print(f"优化建议: {suggestions_file}")
    print()
    
    print("=" * 60)
    print("代码质量分析完成!")
    print("=" * 60)
    
    return {
        'analysis_results': analysis_results,
        'suggestions': suggestions,
        'report_files': {
            'html': html_report_file,
            'markdown': md_report_file,
            'json': json_report_file,
            'results': results_file,
            'suggestions': suggestions_file
        }
    }


if __name__ == '__main__':
    # 获取项目路径
    if len(sys.argv) > 1:
        project_path = sys.argv[1]
    else:
        project_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 运行分析
    result = run_quality_analysis(project_path)
