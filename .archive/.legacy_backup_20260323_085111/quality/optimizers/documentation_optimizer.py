"""
代码文档优化
为关键模块添加和完善文档字符串
"""
import os
from pathlib import Path
from typing import List, Dict


class DocumentationOptimizer:
    """文档优化器"""
    
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.stats = {
            'files_processed': 0,
            'files_enhanced': 0,
            'docs_added': 0
        }
    
    def enhance_module_doc(self, file_path: Path) -> bool:
        """增强模块文档"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 检查是否已有模块文档
            if content.strip().startswith('"""'):
                return False
            
            # 生成模块文档
            module_name = file_path.stem
            module_doc = self._generate_module_doc(module_name, file_path)
            
            if module_doc:
                content = module_doc + '\n' + content
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                return True
            
            return False
            
        except Exception as e:
            print(f"处理文件失败 {file_path}: {e}")
            return False
    
    def _generate_module_doc(self, module_name: str, file_path: Path) -> str:
        """生成模块文档字符串"""
        docs = {
            'number_generator': '"""\n编号生成器模块\n提供统一的业务单据编号生成功能\n"""',
            'decorators': '"""\n装饰器模块\n提供通用的装饰器和工具函数\n"""',
            'pagination': '"""\n分页工具模块\n提供分页查询和参数处理功能\n"""',
            'excel_handler': '"""\nExcel处理模块\n提供Excel文件的读写和处理功能\n"""',
            'batch_handler': '"""\n批量处理模块\n提供批量操作的处理功能\n"""',
            'logger': '"""\n日志模块\n提供统一的日志记录功能\n"""',
            'cache_config': '"""\n缓存配置模块\n提供缓存配置和管理功能\n"""',
            'swagger_config': '"""\nSwagger配置模块\n提供API文档配置功能\n"""',
            'code_analyzers': '"""\n代码分析器模块\n集成多种静态代码分析工具\n"""',
            'report_generator': '"""\n报告生成器模块\n生成多种格式的质量分析报告\n"""',
            'suggestion_generator': '"""\n优化建议生成器模块\n基于分析结果生成优化建议\n"""',
            'optimization_executor': '"""\n优化执行器模块\n提供安全的代码优化执行机制\n"""',
            'code_optimizer': '"""\n代码优化器模块\n执行具体的代码优化操作\n"""',
            'code_normalizer': '"""\n代码规范化模块\n执行PEP8规范检查和修复\n"""'
        }
        
        return docs.get(module_name, f'"""\n{module_name} 模块\n"""')
    
    def optimize_utils_documentation(self) -> List[Dict]:
        """优化utils目录的文档"""
        print("\n优化 utils/ 目录文档...")
        
        utils_dir = self.project_path / 'utils'
        results = []
        
        if not utils_dir.exists():
            return results
        
        for file_path in utils_dir.glob('*.py'):
            if file_path.name == '__init__.py':
                continue
            
            self.stats['files_processed'] += 1
            
            if self.enhance_module_doc(file_path):
                self.stats['files_enhanced'] += 1
                self.stats['docs_added'] += 1
                
                results.append({
                    'file': str(file_path.relative_to(self.project_path)),
                    'action': '添加模块文档'
                })
                print(f"  [ENHANCED] {file_path.name}")
        
        return results
    
    def optimize_quality_documentation(self) -> List[Dict]:
        """优化quality目录的文档"""
        print("\n优化 quality/ 目录文档...")
        
        quality_dir = self.project_path / 'quality'
        results = []
        
        if not quality_dir.exists():
            return results
        
        for file_path in quality_dir.rglob('*.py'):
            if file_path.name == '__init__.py':
                continue
            
            self.stats['files_processed'] += 1
            
            if self.enhance_module_doc(file_path):
                self.stats['files_enhanced'] += 1
                self.stats['docs_added'] += 1
                
                results.append({
                    'file': str(file_path.relative_to(self.project_path)),
                    'action': '添加模块文档'
                })
                print(f"  [ENHANCED] {file_path.name}")
        
        return results
    
    def optimize_project_documentation(self) -> Dict:
        """优化整个项目的文档"""
        print("=" * 60)
        print("代码文档优化")
        print("=" * 60)
        
        results = {
            'utils': self.optimize_utils_documentation(),
            'quality': self.optimize_quality_documentation(),
            'stats': self.stats
        }
        
        print("\n" + "=" * 60)
        print("文档优化完成")
        print("=" * 60)
        print(f"处理文件: {self.stats['files_processed']} 个")
        print(f"增强文件: {self.stats['files_enhanced']} 个")
        print(f"添加文档: {self.stats['docs_added']} 个")
        
        return results


def main():
    """主函数"""
    project_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    optimizer = DocumentationOptimizer(project_path)
    results = optimizer.optimize_project_documentation()
    
    # 保存结果
    import json
    output_file = Path(project_path) / 'quality_reports' / 'documentation_results.json'
    output_file.parent.mkdir(exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n结果已保存到: {output_file}")
    
    return results


if __name__ == '__main__':
    main()
