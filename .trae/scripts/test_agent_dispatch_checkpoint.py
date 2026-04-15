#!/usr/bin/env python3
"""
Agent调度检查点 - 测试脚本

测试覆盖：
1. 正常调度流程 - 应该通过
2. 有Agent但未调度 - 应该失败
3. 无专项Agent - Solo Coder执行
4. 边界条件测试

作者: Solo Coder
版本: v1.0.0
日期: 2026-04-07
"""

import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).parent / "agent_dispatch_checkpoint.py"


def run_test(description: str, args: list, expected_exit_code: int) -> bool:
    """运行单个测试"""
    print(f"\n{'='*60}")
    print(f"测试: {description}")
    print(f"命令: python agent_dispatch_checkpoint.py {' '.join(args)}")
    print(f"期望: exit_code = {expected_exit_code}")
    print("-" * 60)

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)] + args,
        capture_output=True,
        text=True
    )

    print(result.stdout)
    if result.stderr:
        print(f"STDERR: {result.stderr}")

    actual = result.returncode
    passed = actual == expected_exit_code

    status = "[PASS]" if passed else "[FAIL]"
    print(f"\n结果: {status} (actual exit_code={actual})")

    return passed


def main():
    print("=" * 60)
    print("Agent调度检查点 - 单元测试套件")
    print("=" * 60)

    tests = [
        {
            "description": "场景1: 正确调度了专项Agent - 应该通过",
            "args": ["--task-type", "frontend", "--has-specialized-agent", "true", "--agent-dispatched", "true"],
            "expected_exit_code": 0
        },
        {
            "description": "场景2: 有专项Agent但未调度 - 应该失败",
            "args": ["--task-type", "frontend", "--has-specialized-agent", "true", "--agent-dispatched", "false"],
            "expected_exit_code": 1
        },
        {
            "description": "场景3: 无专项Agent，Solo Coder执行 - 应该通过",
            "args": ["--task-type", "unknown-task", "--has-specialized-agent", "false", "--agent-dispatched", "false"],
            "expected_exit_code": 0
        },
        {
            "description": "场景4: 后端任务正确调度 - 应该通过",
            "args": ["--task-type", "backend", "--has-specialized-agent", "true", "--agent-dispatched", "true"],
            "expected_exit_code": 0
        },
        {
            "description": "场景5: 安全任务有Agent但未调度 - 应该失败",
            "args": ["--task-type", "security", "--has-specialized-agent", "true", "--agent-dispatched", "false"],
            "expected_exit_code": 1
        },
        {
            "description": "场景6: 强制继续执行 - 即使违规也通过",
            "args": ["--task-type", "frontend", "--has-specialized-agent", "true", "--agent-dispatched", "false", "--force-continue"],
            "expected_exit_code": 0
        },
    ]

    results = []
    for test in tests:
        passed = run_test(test["description"], test["args"], test["expected_exit_code"])
        results.append(passed)

    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed_count = sum(results)
    total_count = len(results)

    for i, passed in enumerate(results):
        status = "[OK]" if passed else "[FAIL]"
        print(f"{status} 测试 {i+1}/{total_count}")

    print(f"\n总计: {passed_count}/{total_count} 通过")

    if passed_count == total_count:
        print("\n[SUCCESS] 所有测试通过!")
        return 0
    else:
        print(f"\n[WARNING] {total_count - passed_count} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
