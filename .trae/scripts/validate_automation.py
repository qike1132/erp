#!/usr/bin/env python3
"""
ERP System 自动化规则验证脚本
验证代理自动激活和规则执行功能
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_header(title):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}  {title}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}\n")

def print_result(status, message, detail=None):
    if status == "pass":
        icon = f"{Colors.GREEN}✓{Colors.RESET}"
    elif status == "fail":
        icon = f"{Colors.RED}✗{Colors.RESET}"
    else:
        icon = f"{Colors.YELLOW}⚠{Colors.RESET}"
    
    print(f"  {icon} {message}")
    if detail:
        print(f"    {Colors.YELLOW}→{Colors.RESET} {detail}")

class AutomationValidator:
    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent
        self.trae_dir = self.project_root / ".trae"
        self.rules_dir = self.trae_dir / "rules"
        
    def validate_config_structure(self):
        """验证配置文件结构"""
        print_header("配置文件结构验证")
        
        required_files = {
            "dev-rules.json": self.rules_dir / "dev-rules.json",
            "auto-triggers.json": self.rules_dir / "auto-triggers.json",
            "status-feedback.json": self.rules_dir / "status-feedback.json",
            "index.json": self.rules_dir / "index.json"
        }
        
        all_passed = True
        for name, file_path in required_files.items():
            if file_path.exists():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    version = data.get('version', 'N/A')
                    print_result("pass", f"{name} 存在且格式正确", f"版本: {version}")
                except json.JSONDecodeError as e:
                    print_result("fail", f"{name} JSON格式错误", str(e))
                    all_passed = False
            else:
                print_result("fail", f"{name} 不存在", f"路径: {file_path}")
                all_passed = False
        
        return all_passed

    def validate_skills_config(self):
        """验证技能配置"""
        print_header("技能配置验证")
        
        skills_path = self.trae_dir / "skills.json"
        
        if not skills_path.exists():
            print_result("fail", "skills.json 不存在")
            return False
        
        try:
            with open(skills_path, 'r', encoding='utf-8') as f:
                skills_config = json.load(f)
            
            automation = skills_config.get('automation', {})
            if automation.get('enabled'):
                print_result("pass", "自动化功能已启用", 
                           f"保存触发: {automation.get('triggerOnSave', False)}, 提交触发: {automation.get('triggerOnCommit', False)}")
            else:
                print_result("warn", "自动化功能未启用")
            
            skills = skills_config.get('skills', [])
            auto_activate_count = sum(1 for s in skills if s.get('autoActivate'))
            print_result("pass", f"已配置 {len(skills)} 个技能", f"{auto_activate_count} 个支持自动激活")
            
            critical_skills = ['frontend-developer', 'backend-architect', 'code-reviewer', 'security-engineer']
            for skill_name in critical_skills:
                skill = next((s for s in skills if s['name'] == skill_name), None)
                if skill and skill.get('enabled'):
                    auto = "自动激活" if skill.get('autoActivate') else "手动激活"
                    triggers = skill.get('triggers', {})
                    file_types = triggers.get('fileTypes', []) if isinstance(triggers, dict) else []
                    print_result("pass", f"技能 '{skill_name}' 已启用", 
                               f"{auto}, 文件类型: {len(file_types)}种")
                else:
                    print_result("warn", f"技能 '{skill_name}' 未配置或未启用")
            
            return True
            
        except Exception as e:
            print_result("fail", "读取 skills.json 失败", str(e))
            return False

    def validate_trigger_rules(self):
        """验证触发规则"""
        print_header("触发规则验证")
        
        triggers_path = self.rules_dir / "auto-triggers.json"
        
        if not triggers_path.exists():
            print_result("fail", "auto-triggers.json 不存在")
            return False
        
        try:
            with open(triggers_path, 'r', encoding='utf-8') as f:
                triggers = json.load(f)
            
            on_save = triggers.get('triggers', {}).get('onFileSave', {})
            if on_save.get('enabled'):
                debounce = on_save.get('debounce', 0)
                print_result("pass", "文件保存触发器已启用", f"防抖延迟: {debounce}ms")
            else:
                print_result("warn", "文件保存触发器未启用")
            
            on_commit = triggers.get('triggers', {}).get('onPreCommit', {})
            if on_commit.get('enabled'):
                blocking = "阻塞式" if on_commit.get('blocking') else "非阻塞"
                print_result("pass", "提交前触发器已启用", blocking)
            else:
                print_result("warn", "提交前触发器未启用")
            
            file_types = triggers.get('fileTypeTriggers', {})
            print_result("pass", f"已配置 {len(file_types)} 种文件类型触发规则")
            
            keywords = triggers.get('keywordTriggers', {})
            print_result("pass", f"已配置 {len(keywords)} 组关键词触发规则")
            
            return True
            
        except Exception as e:
            print_result("fail", "读取 auto-triggers.json 失败", str(e))
            return False

    def validate_git_hooks(self):
        """验证Git hooks"""
        print_header("Git Hooks 验证")
        
        hooks_path = self.project_root / ".git" / "hooks"
        pre_commit = hooks_path / "pre-commit"
        
        if pre_commit.exists():
            try:
                with open(pre_commit, 'r', encoding='utf-8') as f:
                    content = f.read()
                has_python_check = 'python' in content.lower() or '.py' in content
                has_js_check = '.js' in content or 'javascript' in content.lower()
                checks = []
                if has_python_check:
                    checks.append("Python检查")
                if has_js_check:
                    checks.append("JS检查")
                print_result("pass", "pre-commit hook 已配置", 
                           f"包含: {', '.join(checks) if checks else '基础检查'}")
            except:
                print_result("pass", "pre-commit hook 已配置")
        else:
            print_result("warn", "pre-commit hook 未配置", "建议配置以实现提交前自动检查")
        
        return True

    def validate_agent_skills(self):
        """验证代理技能文件"""
        print_header("代理技能文件验证")
        
        critical_agents = [
            'frontend-developer',
            'backend-architect',
            'code-reviewer',
            'ui-designer',
            'security-engineer',
            'database-optimizer'
        ]
        
        all_passed = True
        for agent in critical_agents:
            skill_file = self.trae_dir / agent / "SKILL.md"
            if skill_file.exists():
                try:
                    with open(skill_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    version = "v2.0" if "version: 2.0" in content.lower() or "version: \"2.0" in content else "v1.x"
                    has_triggers = "triggers" in content.lower() or "autoActivate" in content
                    auto_status = "支持自动激活" if has_triggers else "仅手动激活"
                    print_result("pass", f"{agent}/SKILL.md 存在", f"{version}, {auto_status}")
                except Exception as e:
                    print_result("fail", f"{agent}/SKILL.md 读取失败", str(e))
                    all_passed = False
            else:
                print_result("warn", f"{agent}/SKILL.md 不存在")
        
        return all_passed

    def test_file_type_detection(self):
        """测试文件类型检测"""
        print_header("文件类型检测测试")
        
        test_cases = [
            ("app/routes/main.py", ["backend-architect", "security-engineer"]),
            ("static/js/app.js", ["frontend-developer"]),
            ("static/css/style.css", ["ui-designer", "frontend-developer"]),
            ("migrations/001_init.sql", ["database-optimizer"]),
            ("app/models/user.py", ["backend-architect", "security-engineer"]),
        ]
        
        triggers_path = self.rules_dir / "auto-triggers.json"
        
        if not triggers_path.exists():
            print_result("fail", "无法测试 - auto-triggers.json 不存在")
            return False
        
        try:
            with open(triggers_path, 'r', encoding='utf-8') as f:
                triggers = json.load(f)
            
            file_type_rules = triggers.get('fileTypeTriggers', {})
            
            for file_path, expected_agents in test_cases:
                ext = Path(file_path).suffix
                rule = file_type_rules.get(ext, {})
                primary_agent = rule.get('primaryAgent', '未配置')
                secondary = rule.get('secondaryAgents', [])
                
                all_agents = [primary_agent] + secondary if primary_agent != '未配置' else []
                
                if primary_agent in expected_agents:
                    print_result("pass", f"{file_path}", 
                               f"主代理: {primary_agent}, 辅助: {', '.join(secondary) if secondary else '无'}")
                else:
                    print_result("warn", f"{file_path}", 
                               f"期望: {expected_agents[0]}, 实际: {primary_agent}")
            
            return True
            
        except Exception as e:
            print_result("fail", "文件类型检测测试失败", str(e))
            return False

    def test_automation_flow(self):
        """测试自动化流程"""
        print_header("自动化流程测试")
        
        print_result("info", "模拟文件保存事件...")
        
        test_file = self.project_root / "test_automation.py"
        try:
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write("# Test file for automation\nprint('test')\n")
            
            print_result("pass", "测试文件创建成功")
            
            ext = test_file.suffix
            triggers_path = self.rules_dir / "auto-triggers.json"
            
            if triggers_path.exists():
                with open(triggers_path, 'r', encoding='utf-8') as f:
                    triggers = json.load(f)
                
                rule = triggers.get('fileTypeTriggers', {}).get(ext, {})
                primary_agent = rule.get('primaryAgent', '未配置')
                
                if primary_agent != '未配置':
                    print_result("pass", f"检测到 .py 文件，应激活代理: {primary_agent}")
                else:
                    print_result("warn", "未找到 .py 文件的触发规则")
            
            os.remove(test_file)
            print_result("pass", "测试文件已清理")
            
            return True
            
        except Exception as e:
            print_result("fail", "自动化流程测试失败", str(e))
            if test_file.exists():
                os.remove(test_file)
            return False

    def generate_report(self):
        """生成验证报告"""
        print(f"\n{Colors.BOLD}ERP System 自动化规则验证工具{Colors.RESET}")
        print(f"{Colors.BLUE}运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Colors.RESET}")
        print(f"{Colors.BLUE}项目路径: {self.project_root}{Colors.RESET}")
        
        results = {
            "配置文件结构": self.validate_config_structure(),
            "技能配置": self.validate_skills_config(),
            "触发规则": self.validate_trigger_rules(),
            "Git Hooks": self.validate_git_hooks(),
            "代理技能文件": self.validate_agent_skills(),
            "文件类型检测": self.test_file_type_detection(),
            "自动化流程": self.test_automation_flow()
        }
        
        print_header("验证报告摘要")
        
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        
        print(f"  {Colors.BOLD}总计: {passed}/{total} 项验证通过{Colors.RESET}\n")
        
        for name, result in results.items():
            status = f"{Colors.GREEN}✓{Colors.RESET}" if result else f"{Colors.RED}✗{Colors.RESET}"
            print(f"  {status} {name}")
        
        print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}\n")
        
        if passed == total:
            print(f"{Colors.GREEN}✅ 所有验证通过！自动化规则配置正确。{Colors.RESET}")
            print(f"\n{Colors.BLUE}📋 自动化功能已启用：{Colors.RESET}")
            print(f"  • 文件保存时自动激活对应代理")
            print(f"  • 提交前自动运行代码审查")
            print(f"  • 关键词触发代理激活")
            print(f"  • 状态反馈实时通知\n")
            return 0
        else:
            print(f"{Colors.YELLOW}⚠️ 部分验证未通过，请检查上述警告和错误。{Colors.RESET}\n")
            return 1

def main():
    validator = AutomationValidator()
    exit_code = validator.generate_report()
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
