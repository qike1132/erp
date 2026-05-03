#!/usr/bin/env python3
"""
Agent调度检查点 - 集成测试

测试检查点与task-dispatch-rules.json的集成：
1. 配置加载测试
2. 状态机集成测试
3. 置信度阈值测试
4. 端到端流程测试

作者: Solo Coder
版本: v1.0.0
日期: 2026-04-07
"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).parent / "agent_dispatch_checkpoint.py"
RULES_PATH = Path(".trae/rules/task-dispatch-rules.json")


def test_config_loading():
    """测试1: 验证配置文件存在且可加载"""
    print("\n" + "=" * 60)
    print("集成测试1: 配置加载")
    print("=" * 60)

    if not RULES_PATH.exists():
        print("[FAIL] 配置文件不存在")
        return False

    try:
        with open(RULES_PATH, encoding='utf-8') as f:
            config = json.load(f)

        print("[OK] 配置文件加载成功")
        print(f"    版本: {config.get('version')}")
        print(f"    名称: {config.get('name')}")

        required_keys = ["taskStates", "confidenceThresholds", "priorityLevels"]
        for key in required_keys:
            if key in config:
                print(f"[OK] 包含必要配置: {key}")
            else:
                print(f"[FAIL] 缺少必要配置: {key}")
                return False

        return True
    except Exception as e:
        print(f"[FAIL] 配置加载失败: {e}")
        return False


def test_agent_registry_integration():
    """测试2: 验证Agent注册表与检查点的集成"""
    print("\n" + "=" * 60)
    print("集成测试2: Agent注册表集成")
    print("=" * 60)

    if not RULES_PATH.exists():
        print("[FAIL] 配置文件不存在")
        return False

    with open(RULES_PATH, encoding='utf-8') as f:
        config = json.load(f)

    priority_levels = config.get("priorityLevels", {})
    print(f"[OK] 优先级配置包含 {len(priority_levels)} 个级别")

    test_cases = [
        ("P0_CRITICAL", "incident-response-commander"),
        ("P1_HIGH", "frontend-developer"),
        ("P2_MEDIUM", "ui-designer"),
        ("P3_LOW", "api-tester"),
    ]

    all_passed = True
    for priority, expected_agent in test_cases:
        if priority in priority_levels:
            agents = priority_levels[priority].get("agents", [])
            if expected_agent in agents:
                print(f"[OK] {priority}: 包含 {expected_agent}")
            else:
                print(f"[FAIL] {priority} 不包含 {expected_agent}")
                all_passed = False
        else:
            print(f"[FAIL] 缺少优先级配置: {priority}")
            all_passed = False

    return all_passed


def test_confidence_thresholds():
    """测试3: 验证置信度阈值"""
    print("\n" + "=" * 60)
    print("集成测试3: 置信度阈值验证")
    print("=" * 60)

    if not RULES_PATH.exists():
        print("[FAIL] 配置文件不存在")
        return False

    with open(RULES_PATH, encoding='utf-8') as f:
        config = json.load(f)

    thresholds = config.get("confidenceThresholds", {})
    print(f"[OK] 置信度阈值配置: {len(thresholds)} 个级别")

    expected_thresholds = {
        "directExecute": 95,
        "promptExecute": 85,
        "userConfirm": 70
    }

    all_passed = True
    for name, expected_min in expected_thresholds.items():
        if name in thresholds:
            actual_min = thresholds[name].get("min", 0)
            if actual_min == expected_min:
                print(f"[OK] {name}: min = {actual_min}")
            else:
                print(f"[FAIL] {name} 阈值不匹配: 期望 {expected_min}, 实际 {actual_min}")
                all_passed = False
        else:
            print(f"[FAIL] 缺少阈值配置: {name}")
            all_passed = False

    return all_passed


def test_task_state_machine():
    """测试4: 验证任务状态机"""
    print("\n" + "=" * 60)
    print("集成测试4: 任务状态机验证")
    print("=" * 60)

    if not RULES_PATH.exists():
        print("[FAIL] 配置文件不存在")
        return False

    with open(RULES_PATH, encoding='utf-8') as f:
        config = json.load(f)

    states = config.get("taskStates", {})
    print(f"[OK] 任务状态机包含 {len(states)} 个状态")

    required_states = ["CREATED", "QUEUED", "ASSIGNED", "RUNNING", "COMPLETED", "FAILED"]
    all_passed = True
    for state in required_states:
        if state in states:
            desc = states[state].get("description", "")
            print(f"[OK] {state}: {desc}")
        else:
            print(f"[FAIL] 缺少必要状态: {state}")
            all_passed = False

    return all_passed


def test_end_to_end_violation_detection():
    """测试5: 端到端违规检测"""
    print("\n" + "=" * 60)
    print("集成测试5: 端到端违规检测")
    print("=" * 60)

    test_cases = [
        {
            "description": "前端任务 - 有Agent已调度",
            "args": ["--task-type", "frontend", "--has-specialized-agent", "true", "--agent-dispatched", "true"],
            "expected_exit": 0
        },
        {
            "description": "前端任务 - 有Agent未调度（违规）",
            "args": ["--task-type", "frontend", "--has-specialized-agent", "true", "--agent-dispatched", "false"],
            "expected_exit": 1
        },
        {
            "description": "后端任务 - 有Agent已调度",
            "args": ["--task-type", "backend", "--has-specialized-agent", "true", "--agent-dispatched", "true"],
            "expected_exit": 0
        },
        {
            "description": "未知任务 - 无Agent",
            "args": ["--task-type", "random-unknown-task", "--has-specialized-agent", "false", "--agent-dispatched", "false"],
            "expected_exit": 0
        },
    ]

    all_passed = True
    for i, test in enumerate(test_cases, 1):
        print(f"\n--- 子测试 {i}: {test['description']} ---")

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)] + test["args"],
            capture_output=True,
            text=True
        )

        if result.returncode == test["expected_exit"]:
            print(f"[OK] 退出码正确: {result.returncode}")
        else:
            print(f"[FAIL] 退出码错误: 期望 {test['expected_exit']}, 实际 {result.returncode}")
            all_passed = False

    return all_passed


def main():
    print("=" * 60)
    print("Agent调度检查点 - 集成测试套件")
    print("=" * 60)

    tests = [
        ("配置加载", test_config_loading),
        ("Agent注册表集成", test_agent_registry_integration),
        ("置信度阈值验证", test_confidence_thresholds),
        ("任务状态机验证", test_task_state_machine),
        ("端到端违规检测", test_end_to_end_violation_detection),
    ]

    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append(passed)
        except Exception as e:
            print(f"[FAIL] 测试异常: {e}")
            results.append(False)

    print("\n" + "=" * 60)
    print("集成测试结果汇总")
    print("=" * 60)

    passed_count = sum(results)
    total_count = len(results)

    for i, (name, _) in enumerate(tests):
        status = "[OK]" if results[i] else "[FAIL]"
        print(f"{status} {name}")

    print(f"\n总计: {passed_count}/{total_count} 通过")

    if passed_count == total_count:
        print("\n[SUCCESS] 所有集成测试通过!")
        return 0
    else:
        print(f"\n[WARNING] {total_count - passed_count} 个集成测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
