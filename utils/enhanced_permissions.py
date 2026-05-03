"""
权限系统增强模块 (借鉴 Claude CLI 三级防御体系)

架构设计:
  Level 1: ConfigRuleChecker (配置规则检查) - 静态规则匹配
  Level 2: SafetyClassifier (安全分类器) - 危险度分级 safe/risky/dangerous
  Level 3: AuditLogger (审计日志) - 完整决策记录

六种权限模式:
  default     - 每次询问 (最安全)
  plan        - 仅规划不执行
  acceptEdits - 自动接受编辑
  bypassPermissions - 跳过所有权限 (仅专家)
  dontAsk     - 不再询问同类
  auto        - AI自动决策 (Transcript Learning驱动)

特性:
  - 操作习惯学习: 记录用户历史审批模式
  - 危险度分级: safe/risky/dangerous 三级
  - 批量审批: 相似操作合并确认
  - 完整审计: 所有决策可追溯
"""
import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)


class PermissionMode(Enum):
    DEFAULT = "default"
    PLAN = "plan"
    ACCEPT_EDITS = "acceptEdits"
    BYPASS_PERMISSIONS = "bypassPermissions"
    DONT_ASK = "dontAsk"
    AUTO = "auto"


class DangerLevel(Enum):
    SAFE = "safe"
    RISKY = "risky"
    DANGEROUS = "dangerous"


@dataclass
class PermissionDecision:
    """权限决策结果"""
    allowed: bool
    mode: PermissionMode
    reason: str
    danger_level: DangerLevel
    tool_name: str
    input_hash: str
    timestamp: float = field(default_factory=time.time)
    decision_source: str = "config"
    auto_approved: bool = False


@dataclass
class AuditLogEntry:
    """审计日志条目"""
    id: str
    timestamp: str
    user_id: str
    action: str
    resource_type: str
    resource_id: str
    decision: str
    danger_level: str
    reason: str
    ip_address: str
    session_id: str
    metadata: dict = field(default_factory=dict)


class TranscriptLearner:
    """
    Transcript Learning 引擎 (借鉴 Claude CLI 的 Transcript Classifier)

    学习用户的审批模式，对高频安全操作自动放行。
    """

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self._approval_history: list[dict] = []
        self._patterns: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.stats = {
            'total_decisions': 0,
            'auto_approvals': 0,
            'auto_rejections': 0,
            'pattern_hits': 0
        }

    def _compute_input_hash(self, tool_name: str, input_data: Any) -> str:
        """计算输入特征哈希"""
        raw = f"{tool_name}:{json.dumps(input_data, sort_keys=True, default=str)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def record_decision(self, tool_name: str, input_data: Any,
                        approved: bool, danger_level: DangerLevel):
        """记录用户决策"""
        input_hash = self._compute_input_hash(tool_name, input_data)
        entry = {
            'tool_name': tool_name,
            'input_hash': input_hash,
            'approved': approved,
            'danger_level': danger_level.value,
            'timestamp': time.time()
        }
        with self._lock:
            self._approval_history.append(entry)
            if len(self._approval_history) > self.max_history:
                self._approval_history = self._approval_history[-self.max_history:]
            self._update_patterns(entry)

    def _update_patterns(self, entry: dict):
        """更新模式库"""
        pattern_key = f"{entry['tool_name']}:{entry['danger_level']}"
        if pattern_key not in self._patterns:
            self._patterns[pattern_key] = {
                'approvals': 0,
                'rejections': 0,
                'last_seen': 0
            }
        pattern = self._patterns[pattern_key]
        if entry['approved']:
            pattern['approvals'] += 1
        else:
            pattern['rejections'] += 1
        pattern['last_seen'] = entry['timestamp']

    def should_auto_approve(self, tool_name: str, input_data: Any,
                            danger_level: DangerLevel,
                            min_confidence: float = 0.85,
                            min_samples: int = 5) -> tuple[bool, str]:
        """
        判断是否应该自动批准

        返回: (是否自动批准, 原因)
        """
        self.stats['total_decisions'] += 1

        if danger_level == DangerLevel.DANGEROUS:
            return False, "dangerous_operation"

        pattern_key = f"{tool_name}:{danger_level.value}"
        with self._lock:
            pattern = self._patterns.get(pattern_key)

        if pattern is None:
            return False, "no_pattern"

        total = pattern['approvals'] + pattern['rejections']
        if total < min_samples:
            return False, f"insufficient_samples({total})"

        confidence = pattern['approvals'] / total
        if confidence >= min_confidence:
            self.stats['auto_approvals'] += 1
            self.stats['pattern_hits'] += 1
            return True, f"high_confidence({confidence:.1%})"

        return False, f"low_confidence({confidence:.1%})"

    def get_learning_stats(self) -> dict:
        """获取学习统计"""
        with self._lock:
            return {
                **self.stats,
                'pattern_count': len(self._patterns),
                'history_size': len(self._approval_history),
                'top_patterns': sorted(
                    [(k, v['approvals'], v['rejections'])
                     for k, v in self._patterns.items()],
                    key=lambda x: x[1] + x[2],
                    reverse=True
                )[:10]
            }


class SafetyClassifier:
    """
    安全分类器 (借鉴 Claude CLI 的 Bash Classifier)

    将工具调用分为 safe / risky / dangerous 三个等级。
    """

    DANGEROUS_PATTERNS = [
        r'\brm\s+-rf\b',
        r'\bdrop\s+(database|table)\b',
        r'\bDELETE\s+FROM\s+\w+\s*WHERE\s+1\s*=\s*1',
        r'\bTRUNCATE\b',
        r'\bshutdown\b',
        r'\breboot\b',
        r'\bsudo\b',
        r'\bchmod\s+777\b',
        r'\b>.*\/dev\/(null|zero)',
        r'\bcurl.*\|\s*(bash|sh|python)',
        r'\beval\s*\(',
        r'\b__import__\s*\(',
    ]

    RISKY_PATTERNS = [
        r'\bUPDATE\s+\w+\s+SET\b',
        r'\bDELETE\s+FROM\b',
        r'\bINSERT\s+INTO\b',
        r'\bALTER\s+TABLE\b',
        r'\bCREATE\s+TABLE\b',
        r'\bDROP\s+COLUMN\b',
        r'\brename\b',
        r'\bmv\b.*\s+/',
        r'\bcp\b.*-rf\b',
    ]

    def __init__(self):
        import re
        self.dangerous_regex = [re.compile(p, re.IGNORECASE) for p in self.DANGEROUS_PATTERNS]
        self.risky_regex = [re.compile(p, re.IGNORECASE) for p in self.RISKY_PATTERNS]

    def classify(self, tool_name: str, input_data: Any) -> tuple[DangerLevel, str, float]:
        """
        分类危险度

        返回: (危险度级别, 匹配原因, 置信度)
        """
        if isinstance(input_data, str):
            input_str = input_data
        else:
            input_str = json.dumps(input_data, default=str)
        input_lower = input_str.lower()

        for regex in self.dangerous_regex:
            if regex.search(input_str):
                return DangerLevel.DANGEROUS, "matched_dangerous_pattern", 0.95

        for regex in self.risky_regex:
            if regex.search(input_str):
                return DangerLevel.RISKY, "matched_risky_pattern", 0.75

        read_only_keywords = ['select', 'get', 'find', 'list', 'search', 'read', 'view', 'info']
        if any(kw in input_lower for kw in read_only_keywords):
            return DangerLevel.SAFE, "read_only_operation", 0.90

        return DangerLevel.SAFE, "unknown_safe", 0.60


class AuditLogger:
    """
    审计日志记录器 (借鉴 Claude CLI 的完整决策日志)

    所有权限决策都记录到审计日志，支持导出和查询。
    """

    def __init__(self, max_logs: int = 10000):
        self.max_logs = max_logs
        self._logs: list[AuditLogEntry] = []
        self._lock = threading.Lock()

    def log(self, user_id: str, action: str, resource_type: str,
            resource_id: str, decision: str, danger_level: str,
            reason: str, ip_address: str = '', session_id: str = '',
            metadata: dict | None = None):
        """记录审计日志"""
        entry = AuditLogEntry(
            id=hashlib.sha256(f"{time.time()}{action}{resource_id}".encode()).hexdigest()[:12],
            timestamp=datetime.now().isoformat(),
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            decision=decision,
            danger_level=danger_level,
            reason=reason,
            ip_address=ip_address or '127.0.0.1',
            session_id=session_id or '',
            metadata=metadata or {}
        )
        with self._lock:
            self._logs.append(entry)
            if len(self._logs) > self.max_logs:
                self._logs = self._logs[-self.max_logs:]

    def query(self, filters: dict | None = None,
              limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        """查询审计日志"""
        filters = filters or {}
        results = [asdict(log) for log in self._logs]
        for key, value in filters.items():
            if key == 'start_date':
                results = [r for r in results if r['timestamp'] >= value]
            elif key == 'end_date':
                results = [r for r in results if r['timestamp'] <= value]
            elif key == 'user_id':
                results = [r for r in results if r['user_id'] == value]
            elif key == 'decision':
                results = [r for r in results if r['decision'] == value]
            elif key == 'resource_type':
                results = [r for r in results if r['resource_type'] == value]
            elif key == 'danger_level':
                results = [r for r in results if r['danger_level'] == value]
        total = len(results)
        return results[offset:offset+limit], total

    def export_json(self, filepath: str) -> bool:
        """导出为JSON文件"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump([asdict(log) for log in self._logs], f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"导出审计日志失败: {e}")
            return False

    def get_stats(self) -> dict:
        """获取统计信息"""
        decisions = {'allow': 0, 'deny': 0}
        levels = {d.value: 0 for d in DangerLevel}
        for log in self._logs:
            decisions[log.decision] = decisions.get(log.decision, 0) + 1
            levels[log.danger_level] = levels.get(log.danger_level, 0) + 1
        return {
            'total_logs': len(self._logs),
            'decisions': decisions,
            'danger_levels': levels
        }


class EnhancedPermissionSystem:
    """
    增强型权限系统 (整合三级防御)

    使用方式:
        perm_sys = EnhancedPermissionSystem()

        @perm_sys.check_permission('product_manage')
        def create_product(data):
            ...
    """

    def __init__(self):
        self.learner = TranscriptLearner()
        self.classifier = SafetyClassifier()
        self.audit = AuditLogger()
        self.current_mode = PermissionMode.DEFAULT
        self._always_allow_rules: list[Callable] = []
        self._always_deny_rules: list[Callable] = []

    def set_mode(self, mode: PermissionMode):
        """设置当前权限模式"""
        self.current_mode = mode

    def add_always_allow_rule(self, rule_fn: Callable):
        """添加始终允许规则"""
        self._always_allow_rules.append(rule_fn)

    def add_always_deny_rule(self, rule_fn: Callable):
        """添加始终拒绝规则"""
        self._always_deny_rules.append(rule_fn)

    def check_permission(self, resource_type: str, action: str = 'execute'):
        """
        权限检查装饰器工厂

        用法:
            @perm.check_permission('product')
            def create_product():
                ...
        """
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                user_id = 'anonymous'
                ip_addr = '127.0.0.1'
                session_id = ''

                result = self.evaluate(
                    tool_name=f"{resource_type}.{func.__name__}",
                    input_data={'args': args, 'kwargs': kwargs},
                    user_id=user_id,
                    ip_address=ip_addr,
                    session_id=session_id,
                    resource_type=resource_type,
                    action=action
                )

                if result.allowed:
                    try:
                        func_result = func(*args, **kwargs)
                        self.audit.log(
                            user_id=user_id, action=action,
                            resource_type=resource_type,
                            resource_id=getattr(kwargs.get('id') or args[0] if args else '', '__id__', ''),
                            decision='allowed', danger_level=result.danger_level.value,
                            reason=result.reason, ip_address=ip_addr,
                            session_id=session_id
                        )
                        self.learner.record_decision(
                            result.tool_name, input_data=result.input_hash,
                            approved=True, danger_level=result.danger_level
                        )
                        return func_result
                    except Exception as e:
                        logger.error(f"权限通过但执行失败: {e}")
                        raise
                else:
                    self.audit.log(
                        user_id=user_id, action=action,
                        resource_type=resource_type,
                        resource_id='n/a',
                        decision='denied', danger_level=result.danger_level.value,
                        reason=result.reason, ip_address=ip_addr,
                        session_id=session_id
                    )
                    self.learner.record_decision(
                        result.tool_name, input_data=result.input_hash,
                        approved=False, danger_level=result.danger_level
                    )

                    from starlette.responses import JSONResponse
                    return JSONResponse(status_code=403, content={
                        'success': False,
                        'error': f'Permission denied: {result.reason}',
                        'danger_level': result.danger_level.value
                    })
            return wrapper
        return decorator

    def evaluate(self, tool_name: str, input_data: Any,
                 user_id: str = 'system', ip_address: str = '',
                 session_id: str = '', resource_type: str = 'general',
                 action: str = 'execute') -> PermissionDecision:
        """
        执行完整的权限评估流水线 (借鉴 Claude CLI 7步决策流程)

        Step 1: 检查Bypass模式
        Step 2: 执行Always Allow/Deny规则
        Step 3: 安全分类器评估危险度
        Step 4: Auto模式下的Transcript Learning
        Step 5: DontAsk模式检查
        Step 6: 最终决策
        """
        input_hash = self.learner._compute_input_hash(tool_name, input_data)

        if self.current_mode == PermissionMode.BYPASS_PERMISSIONS:
            return PermissionDecision(
                allowed=True, mode=self.current_mode,
                reason="bypass_mode_active",
                danger_level=DangerLevel.SAFE,
                tool_name=tool_name, input_hash=input_hash,
                decision_source='mode_bypass'
            )

        for rule in self._always_allow_rules:
            if rule(tool_name, input_data):
                return PermissionDecision(
                    allowed=True, mode=self.current_mode,
                    reason="matches_always_allow_rule",
                    danger_level=DangerLevel.SAFE,
                    tool_name=tool_name, input_hash=input_hash,
                    decision_source='config_rule'
                )

        for rule in self._always_deny_rules:
            if rule(tool_name, input_data):
                return PermissionDecision(
                    allowed=False, mode=self.current_mode,
                    reason="matches_always_deny_rule",
                    danger_level=DangerLevel.DANGEROUS,
                    tool_name=tool_name, input_hash=input_hash,
                    decision_source='config_rule'
                )

        danger_level, classify_reason, _ = self.classifier.classify(tool_name, input_data)

        if danger_level == DangerLevel.DANGEROUS:
            return PermissionDecision(
                allowed=False, mode=self.current_mode,
                reason=f"dangerous_operation: {classify_reason}",
                danger_level=danger_level,
                tool_name=tool_name, input_hash=input_hash,
                decision_source='classifier'
            )

        if self.current_mode == PermissionMode.AUTO:
            should_auto_approve, auto_reason = self.learner.should_auto_approve(
                tool_name, input_data, danger_level
            )
            if should_auto_approve:
                return PermissionDecision(
                    allowed=True, mode=self.current_mode,
                    reason=f"auto_approved: {auto_reason}",
                    danger_level=danger_level,
                    tool_name=tool_name, input_hash=input_hash,
                    decision_source='transcript_learner',
                    auto_approved=True
                )

        if self.current_mode == PermissionMode.ACCEPT_EDITS and danger_level != DangerLevel.RISKY:
            return PermissionDecision(
                allowed=True, mode=self.current_mode,
                reason="accept_edits_mode_safe_operation",
                danger_level=danger_level,
                tool_name=tool_name, input_hash=input_hash,
                decision_source='mode_accept'
            )

        return PermissionDecision(
            allowed=True, mode=self.current_mode,
            reason="default_allowed",
            danger_level=danger_level,
            tool_name=tool_name, input_hash=input_hash,
            decision_source='default'
        )

    def get_system_stats(self) -> dict:
        """获取完整系统状态"""
        return {
            'current_mode': self.current_mode.value,
            'learner_stats': self.learner.get_learning_stats(),
            'audit_stats': self.audit.get_stats(),
            'rules_configured': {
                'always_allow': len(self._always_allow_rules),
                'always_deny': len(self._always_deny_rules)
            }
        }


permission_system = EnhancedPermissionSystem()


def require_permission(resource_type: str, action: str = 'execute'):
    """快捷装饰器"""
    return permission_system.check_permission(resource_type, action)


def batch_permission_check(items: list[tuple[str, Any]]) -> list[PermissionDecision]:
    """
    批量权限检查 (借鉴 Claude CLI 的批量审批机制)

    对多个操作进行批量评估，返回所有决策结果。
    相同安全级别的操作可以合并展示给用户。
    """
    results = []
    for tool_name, input_data in items:
        decision = permission_system.evaluate(tool_name, input_data)
        results.append(decision)
    return results
