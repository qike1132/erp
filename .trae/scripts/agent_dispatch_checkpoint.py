#!/usr/bin/env python3
"""
Agent调度检查点 - Agent Dispatch Checkpoint

功能：监控Agent调度流程，确保"专项优先"原则被正确执行

检查流程：
1. 识别任务类型 (frontend/backend/fullstack/security/testing)
2. 查询匹配的专项Agent
3. 评估调度决策
4. 记录日志或阻止执行

使用方式：
    python agent_dispatch_checkpoint.py --task-type frontend --has-specialized-agent true --agent-dispatched true

作者: Solo Coder
版本: v1.0.0
日期: 2026-04-07
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

LOG_FILE = Path(".trae/logs/agent_dispatch_checkpoint.log")
AUDIT_FILE = Path(".trae/logs/agent_dispatch_audit.json")

AGENT_REGISTRY = {
    "frontend": {
        "agents": ["frontend-developer", "ui-designer", "ux-architect"],
        "skills": ["frontend-design", "erp-ui-design"]
    },
    "backend": {
        "agents": ["backend-architect", "database-optimizer", "security-engineer"],
        "skills": ["python-performance-optimization"]
    },
    "fullstack": {
        "agents": ["frontend-developer", "backend-architect"],
        "skills": ["frontend-design", "python-performance-optimization"]
    },
    "security": {
        "agents": ["security-engineer"],
        "skills": ["skill-vetter"]
    },
    "testing": {
        "agents": ["api-tester", "test-results-analyzer"],
        "skills": ["python-testing-patterns"]
    }
}

VIOLATION_SEVERITY = {
    "CRITICAL": "[CRITICAL]",
    "HIGH": "[HIGH]",
    "MEDIUM": "[MEDIUM]",
    "INFO": "[INFO]"
}


def load_config():
    """加载调度规则配置"""
    config_path = Path(".trae/rules/task-dispatch-rules.json")
    if config_path.exists():
        with open(config_path, encoding='utf-8') as f:
            return json.load(f)
    return None


def classify_task(task_type: str) -> str:
    """Step 1: 识别任务类型"""
    task_type_lower = task_type.lower()
    for key in AGENT_REGISTRY:
        if key in task_type_lower:
            return key
    return "unknown"


def find_matched_agents(task_type: str) -> list:
    """Step 2: 查询匹配的专项Agent"""
    return AGENT_REGISTRY.get(task_type, {}).get("agents", [])


def evaluate_dispatch_decision(
    task_type: str,
    has_specialized_agent: bool,
    agent_dispatched: bool,
    confidence: int = 100
) -> dict:
    """
    Step 3: 评估调度决策

    Returns:
        dict: {
            "violation": bool,          # 是否违规
            "severity": str,            # 严重程度
            "message": str,             # 违规消息
            "recommendation": str,       # 建议
            "allow_continue": bool       # 是否允许继续执行
        }
    """
    result = {
        "violation": False,
        "severity": VIOLATION_SEVERITY["INFO"],
        "message": "",
        "recommendation": "",
        "allow_continue": True
    }

    if has_specialized_agent and not agent_dispatched:
        result["violation"] = True
        result["severity"] = VIOLATION_SEVERITY["CRITICAL"]
        result["message"] = (
            f"【违规】任务类型 '{task_type}' 有可用的专项Agent，"
            f"但未执行调度！违反 '专项优先(P0)' 原则。"
        )
        result["recommendation"] = (
            f"必须调度以下Agent之一: {', '.join(find_matched_agents(task_type))}"
        )
        result["allow_continue"] = False
        return result

    if has_specialized_agent and agent_dispatched:
        result["message"] = f"[OK] 正确调度了专项Agent (任务类型: {task_type})"
        result["allow_continue"] = True
        return result

    if not has_specialized_agent:
        result["message"] = "[INFO] 无匹配的专项Agent，由Solo Coder直接执行"
        result["allow_continue"] = True
        return result

    return result


def log_dispatch_decision(
    task_type: str,
    decision: dict,
    args: argparse.Namespace
):
    """记录调度决策到日志文件"""
    timestamp = datetime.now().isoformat()

    log_entry = {
        "timestamp": timestamp,
        "task_type": task_type,
        "has_specialized_agent": args.has_specialized_agent,
        "agent_dispatched": args.agent_dispatched,
        "violation": decision["violation"],
        "severity": decision["severity"],
        "message": decision["message"],
        "recommendation": decision["recommendation"],
        "allow_continue": decision["allow_continue"]
    }

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] ")
        f.write(f"[{decision['severity']}] ")
        f.write(f"{decision['message']}")
        if decision["recommendation"]:
            f.write(f" | 建议: {decision['recommendation']}")
        f.write("\n")

    if AUDIT_FILE.exists():
        with open(AUDIT_FILE, encoding='utf-8') as f:
            audit_data = json.load(f)
    else:
        audit_data = {"dispatches": []}

    audit_data["dispatches"].append(log_entry)
    audit_data["total"] = len(audit_data["dispatches"])
    audit_data["violations"] = sum(1 for d in audit_data["dispatches"] if d["violation"])

    with open(AUDIT_FILE, 'w', encoding='utf-8') as f:
        json.dump(audit_data, f, ensure_ascii=False, indent=2)


def print_result(decision: dict):
    """打印检查结果"""
    print("\n" + "=" * 60)
    print("Agent调度检查点 - 检查结果")
    print("=" * 60)
    print(f"状态: {decision['severity']}")
    print(f"消息: {decision['message']}")
    if decision["recommendation"]:
        print(f"建议: {decision['recommendation']}")
    print("=" * 60)

    if decision["violation"]:
        print("\n[X] 检查未通过: 检测到调度违规!")
        print("   执行已被阻止。请先正确调度专项Agent。")
    else:
        print("\n[OK] 检查通过: 调度流程正常")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Agent调度检查点 - 确保专项优先原则被正确执行",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 正确调度 - 检查通过
  python agent_dispatch_checkpoint.py --task-type frontend --has-specialized-agent true --agent-dispatched true

  # 有专项Agent但未调度 - 检查失败，阻止执行
  python agent_dispatch_checkpoint.py --task-type frontend --has-specialized-agent true --agent-dispatched false

  # 无专项Agent - Solo Coder直接执行
  python agent_dispatch_checkpoint.py --task-type simple-task --has-specialized-agent false --agent-dispatched false
        """
    )

    parser.add_argument(
        "--task-type",
        required=True,
        help="任务类型 (frontend/backend/fullstack/security/testing)"
    )
    parser.add_argument(
        "--has-specialized-agent",
        type=lambda x: x.lower() == 'true',
        required=True,
        help="是否有可用的专项Agent (true/false)"
    )
    parser.add_argument(
        "--agent-dispatched",
        type=lambda x: x.lower() == 'true',
        required=True,
        help="是否已执行Agent调度 (true/false)"
    )
    parser.add_argument(
        "--confidence",
        type=int,
        default=100,
        help="置信度 (0-100)"
    )
    parser.add_argument(
        "--force-continue",
        action="store_true",
        help="强制继续执行（不推荐，仅用于紧急情况）"
    )

    args = parser.parse_args()

    task_type = classify_task(args.task_type)
    matched_agents = find_matched_agents(task_type)

    print("\n== Agent调度检查点 v1.0.0 ==")
    print(f"   任务类型: {args.task_type} -> 分类为: {task_type}")
    if matched_agents:
        print(f"   可用Agent: {', '.join(matched_agents)}")
    else:
        print("   可用Agent: 无")

    decision = evaluate_dispatch_decision(
        task_type=task_type,
        has_specialized_agent=args.has_specialized_agent,
        agent_dispatched=args.agent_dispatched,
        confidence=args.confidence
    )

    log_dispatch_decision(task_type, decision, args)
    print_result(decision)

    if not decision["allow_continue"] and not args.force_continue:
        print("X 执行已阻止 (使用 --force-continue 强制继续)")
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
