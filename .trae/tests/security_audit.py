"""
Trae AI Agent System v2.0 - 安全审计报告
检查配置文件安全性
"""
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass


@dataclass
class SecurityIssue:
    severity: str  # critical, high, medium, low
    file_path: str
    issue: str
    recommendation: str


class SecurityAuditor:
    """安全审计器"""
    
    SENSITIVE_PATTERNS = [
        r'password\s*[=:]\s*["\'][^"\']+["\']',
        r'api_key\s*[=:]\s*["\'][^"\']+["\']',
        r'secret\s*[=:]\s*["\'][^"\']+["\']',
        r'token\s*[=:]\s*["\'][^"\']+["\']',
        r'private_key\s*[=:]\s*["\'][^"\']+["\']',
    ]
    
    DANGEROUS_PATTERNS = [
        r'eval\s*\(',
        r'exec\s*\(',
        r'system\s*\(',
        r'subprocess\.call',
        r'os\.system',
    ]
    
    @staticmethod
    def audit_config_file(file_path: Path) -> List[SecurityIssue]:
        """审计单个配置文件"""
        issues = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                config = json.loads(content)
        except Exception as e:
            issues.append(SecurityIssue(
                severity="high",
                file_path=str(file_path),
                issue=f"无法解析配置文件: {e}",
                recommendation="修复JSON语法错误"
            ))
            return issues
        
        issues.extend(SecurityAuditor._check_sensitive_data(file_path, content))
        issues.extend(SecurityAuditor._check_security_settings(file_path, config))
        issues.extend(SecurityAuditor._check_rate_limiting(file_path, config))
        issues.extend(SecurityAuditor._check_input_validation(file_path, config))
        
        return issues
    
    @staticmethod
    def _check_sensitive_data(file_path: Path, content: str) -> List[SecurityIssue]:
        """检查敏感数据"""
        issues = []
        for pattern in SecurityAuditor.SENSITIVE_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                issues.append(SecurityIssue(
                    severity="critical",
                    file_path=str(file_path),
                    issue=f"发现可能的敏感数据: {pattern}",
                    recommendation="移除硬编码的敏感信息，使用环境变量或密钥管理服务"
                ))
        return issues
    
    @staticmethod
    def _check_security_settings(file_path: Path, config: Dict) -> List[SecurityIssue]:
        """检查安全设置"""
        issues = []
        
        if "security" in config:
            sec = config["security"]
            if "encryption" in sec:
                enc = sec["encryption"]
                if not enc.get("inTransit", True):
                    issues.append(SecurityIssue(
                        severity="high",
                        file_path=str(file_path),
                        issue="传输加密未启用",
                        recommendation="启用 inTransit 加密以保护数据传输安全"
                    ))
        
        if "queryGuard" in config:
            qg = config.get("queryGuard", {})
            if not qg.get("strictMode", False):
                issues.append(SecurityIssue(
                    severity="medium",
                    file_path=str(file_path),
                    issue="QueryGuard非严格模式",
                    recommendation="启用strictMode以增强安全防护"
                ))
        
        return issues
    
    @staticmethod
    def _check_rate_limiting(file_path: Path, config: Dict) -> List[SecurityIssue]:
        """检查速率限制"""
        issues = []
        
        if "rateLimiting" in config:
            rl = config["rateLimiting"]
            if not rl.get("enabled", False):
                issues.append(SecurityIssue(
                    severity="medium",
                    file_path=str(file_path),
                    issue="速率限制未启用",
                    recommendation="启用速率限制以防止DoS攻击"
                ))
            else:
                global_limits = rl.get("global", {})
                if global_limits.get("maxRequestsPerMinute", 1000) > 1000:
                    issues.append(SecurityIssue(
                        severity="low",
                        file_path=str(file_path),
                        issue="速率限制阈值过高",
                        recommendation="考虑降低maxRequestsPerMinute以提高安全性"
                    ))
        
        return issues
    
    @staticmethod
    def _check_input_validation(file_path: Path, config: Dict) -> List[SecurityIssue]:
        """检查输入验证"""
        issues = []
        
        if "inputValidation" in config:
            iv = config["inputValidation"]
            if not iv.get("enabled", False):
                issues.append(SecurityIssue(
                    severity="high",
                    file_path=str(file_path),
                    issue="输入验证未启用",
                    recommendation="启用输入验证以防止注入攻击"
                ))
            
            blocked = iv.get("blockedPatterns", [])
            critical_patterns = ["<script", "eval(", "require("]
            for pattern in critical_patterns:
                if pattern not in blocked:
                    issues.append(SecurityIssue(
                        severity="medium",
                        file_path=str(file_path),
                        issue=f"缺少关键阻止模式: {pattern}",
                        recommendation=f"添加 '{pattern}' 到blockedPatterns"
                    ))
        
        return issues


def run_security_audit():
    """运行安全审计"""
    base_dir = Path(__file__).parent.parent
    config_files = [
        base_dir / "config" / "agent-system-v2.json",
        base_dir / "core" / "query-engine" / "query-guard.json",
        base_dir / "core" / "query-engine" / "hooks.json",
        base_dir / "core" / "transport" / "circuit-breaker.json",
        base_dir / "core" / "transport" / "retry-policy.json",
        base_dir / "core" / "transport" / "hybrid-transport.json",
        base_dir / "core" / "skills" / "hot-reloader.json",
        base_dir / "monitoring" / "performance.json",
    ]
    
    all_issues = []
    for config_file in config_files:
        if config_file.exists():
            issues = SecurityAuditor.audit_config_file(config_file)
            all_issues.extend(issues)
    
    return all_issues


def generate_audit_report(issues: List[SecurityIssue]) -> str:
    """生成审计报告"""
    report = []
    report.append("=" * 60)
    report.append("Trae AI Agent System v2.0 安全审计报告")
    report.append("=" * 60)
    report.append("")
    
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for issue in issues:
        severity_counts[issue.severity] += 1
    
    report.append("## 审计摘要")
    report.append(f"- 严重问题: {severity_counts['critical']}")
    report.append(f"- 高危问题: {severity_counts['high']}")
    report.append(f"- 中危问题: {severity_counts['medium']}")
    report.append(f"- 低危问题: {severity_counts['low']}")
    report.append(f"- 总计: {len(issues)}")
    report.append("")
    
    if issues:
        report.append("## 详细问题列表")
        report.append("")
        
        for severity in ["critical", "high", "medium", "low"]:
            severity_issues = [i for i in issues if i.severity == severity]
            if severity_issues:
                report.append(f"### {severity.upper()} 级别")
                for issue in severity_issues:
                    report.append(f"- **文件**: {issue.file_path}")
                    report.append(f"  - **问题**: {issue.issue}")
                    report.append(f"  - **建议**: {issue.recommendation}")
                    report.append("")
    else:
        report.append("## 审计结果")
        report.append("")
        report.append("✅ 未发现安全问题，所有配置文件符合安全标准。")
    
    report.append("")
    report.append("=" * 60)
    report.append("审计完成")
    report.append("=" * 60)
    
    return "\n".join(report)


if __name__ == "__main__":
    issues = run_security_audit()
    report = generate_audit_report(issues)
    print(report)
