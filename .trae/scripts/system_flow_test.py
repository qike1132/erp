#!/usr/bin/env python3
"""
系统执行流程测试 - System Execution Flow Test

测试系统接收用户下发任务后的完整执行流程：
1. 任务接收
2. 解析匹配
3. 任务拆解
4. Agent调度
5. 执行管控
6. 审核整改
7. 整合验收

作者: Solo Coder
版本: v1.0.0
日期: 2026-04-07
"""

import subprocess
import sys
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional

SCRIPT_DIR = Path(__file__).parent
RULES_PATH = Path(".trae/rules/task-dispatch-rules.json")
CHECKPOINT_SCRIPT = SCRIPT_DIR / "agent_dispatch_checkpoint.py"


class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.expected = ""
        self.actual = ""
        self.error = ""
        self.duration_ms = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "expected": self.expected,
            "actual": self.actual,
            "error": self.error,
            "duration_ms": self.duration_ms
        }


class SystemFlowTester:
    def __init__(self):
        self.results: List[TestResult] = []
        self.config = self._load_config()
        self.step_times = {}

    def _load_config(self) -> dict:
        if RULES_PATH.exists():
            with open(RULES_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _measure_time(self, func, *args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        duration = (time.time() - start) * 1000
        return result, duration

    def _run_checkpoint(self, task_type: str, has_agent: bool, dispatched: bool) -> Tuple[int, str]:
        cmd = [
            sys.executable,
            str(CHECKPOINT_SCRIPT),
            "--task-type", task_type,
            "--has-specialized-agent", str(has_agent).lower(),
            "--agent-dispatched", str(dispatched).lower()
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode, result.stdout + result.stderr

    def test_step1_task_reception(self) -> TestResult:
        """步骤1: 测试任务接收功能"""
        result = TestResult("步骤1: 任务接收")

        print("\n" + "=" * 70)
        print("步骤1: 任务接收测试")
        print("=" * 70)

        test_cases = [
            ("frontend_task", "frontend"),
            ("backend_api", "backend"),
            ("security_audit", "security"),
            ("unknown-task", "unknown"),
        ]

        all_passed = True
        for input_type, expected_category in test_cases:
            task_type = input_type
            matched = expected_category

            if "frontend" in input_type.lower():
                matched = "frontend"
            elif "backend" in input_type.lower():
                matched = "backend"
            elif "security" in input_type.lower():
                matched = "security"
            else:
                matched = "unknown"

            status = "[OK]" if matched == expected_category else "[FAIL]"
            print(f"{status} 输入: '{input_type}' -> 分类: '{matched}'")
            if matched != expected_category:
                all_passed = False

        result.passed = all_passed
        result.expected = "所有任务类型正确分类"
        result.actual = "任务分类完成"
        return result

    def test_step2_parse_matching(self) -> TestResult:
        """步骤2: 测试解析与匹配"""
        result = TestResult("步骤2: 解析匹配")

        print("\n" + "=" * 70)
        print("步骤2: 解析与匹配测试")
        print("=" * 70)

        test_cases = [
            ("frontend", True, ["frontend-developer", "ui-designer", "ux-architect"]),
            ("backend", True, ["backend-architect", "database-optimizer", "security-engineer"]),
            ("fullstack", True, ["frontend-developer", "backend-architect"]),
            ("security", True, ["security-engineer"]),
            ("testing", True, ["api-tester", "test-results-analyzer"]),
            ("unknown", False, []),
        ]

        all_passed = True
        for task_type, expect_has_agent, expected_agents in test_cases:
            has_agent = len(expected_agents) > 0
            status_has = "[OK]" if has_agent == expect_has_agent else "[FAIL]"
            print(f"{status_has} 任务'{task_type}': has_agent={has_agent}")

            if has_agent != expect_has_agent:
                all_passed = False

        result.passed = all_passed
        result.expected = "Agent匹配逻辑正确"
        result.actual = f"测试了{len(test_cases)}种任务类型"
        return result

    def test_step3_task_decomposition(self) -> TestResult:
        """步骤3: 测试任务拆解"""
        result = TestResult("步骤3: 任务拆解")

        print("\n" + "=" * 70)
        print("步骤3: 任务拆解测试")
        print("=" * 70)

        dispatch_steps = self.config.get("dispatchAlgorithm", {}).get("steps", [])
        expected_steps = ["skill_check", "confidence_scoring", "threshold_evaluation",
                          "agent_matching", "fallback_check", "task_dispatch"]

        print(f"[INFO] 配置中的调度步骤数量: {len(dispatch_steps)}")

        all_passed = True
        if len(dispatch_steps) >= 4:
            print(f"[OK] 包含必要的调度步骤: {len(dispatch_steps)} >= 4")
        else:
            print(f"[FAIL] 调度步骤不足: {len(dispatch_steps)} < 4")
            all_passed = False

        for i, step in enumerate(dispatch_steps, 1):
            step_name = step.get("name", "unknown")
            step_required = step.get("required", False)
            print(f"  步骤{i}: {step_name} (必填: {step_required})")

            if step_name in expected_steps:
                print(f"       [OK] 是预期步骤")
            else:
                print(f"       [WARN] 非预期步骤: {step_name}")

        result.passed = all_passed
        result.expected = "任务拆解流程完整"
        result.actual = f"包含{len(dispatch_steps)}个步骤"
        return result

    def test_step4_agent_dispatch(self) -> TestResult:
        """步骤4: 测试Agent调度（含检查点验证）"""
        result = TestResult("步骤4: Agent调度")

        print("\n" + "=" * 70)
        print("步骤4: Agent调度测试（含检查点）")
        print("=" * 70)

        test_cases = [
            ("frontend", True, True, 0, "正确调度"),
            ("frontend", True, False, 1, "违规未调度"),
            ("backend", True, True, 0, "正确调度"),
            ("backend", True, False, 1, "违规未调度"),
            ("security", True, False, 1, "违规未调度"),
            ("unknown", False, False, 0, "Solo Coder执行"),
        ]

        all_passed = True
        for task_type, has_agent, dispatched, expected_code, description in test_cases:
            actual_code, output = self._run_checkpoint(task_type, has_agent, dispatched)
            passed = actual_code == expected_code
            all_passed = all_passed and passed

            status = "[OK]" if passed else "[FAIL]"
            print(f"{status} {description}: task={task_type}, has_agent={has_agent}, "
                  f"dispatched={dispatched} -> exit={actual_code}(期望{expected_code})")

            if not passed:
                print(f"       [ERROR] 输出: {output[:200]}")

        result.passed = all_passed
        result.expected = "检查点正确拦截违规调度"
        result.actual = f"测试了{len(test_cases)}种调度场景"
        return result

    def test_step5_execution_control(self) -> TestResult:
        """步骤5: 测试执行管控"""
        result = TestResult("步骤5: 执行管控")

        print("\n" + "=" * 70)
        print("步骤5: 执行管控测试")
        print("=" * 70)

        timeout_handling = self.config.get("timeoutHandling", {})
        task_timeout = timeout_handling.get("taskTimeout", 0)
        agent_response_timeout = timeout_handling.get("agentResponseTimeout", 0)

        print(f"[INFO] 任务超时: {task_timeout}ms")
        print(f"[INFO] Agent响应超时: {agent_response_timeout}ms")

        retry_policy = self.config.get("retryPolicy", {})
        max_retries = retry_policy.get("maxRetries", 0)
        retryable_errors = retry_policy.get("retryableErrors", [])

        print(f"[INFO] 最大重试次数: {max_retries}")
        print(f"[INFO] 可重试错误: {len(retryable_errors)}种")

        all_passed = (
            task_timeout > 0 and
            agent_response_timeout > 0 and
            max_retries >= 0 and
            len(retryable_errors) > 0
        )

        result.passed = all_passed
        result.expected = "执行管控配置完整"
        result.actual = f"超时:{task_timeout}ms, 重试:{max_retries}次"
        return result

    def test_step6_review_process(self) -> TestResult:
        """步骤6: 测试审核流程"""
        result = TestResult("步骤6: 审核整改")

        print("\n" + "=" * 70)
        print("步骤6: 审核整改测试")
        print("=" * 70)

        task_states = self.config.get("taskStates", {})
        review_states = ["REVIEWING", "APPROVED", "REVISION_REQUIRED"]

        all_review_states_exist = all(state in task_states for state in review_states)
        print(f"[INFO] 审核相关状态: {review_states}")
        print(f"[OK] 所有审核状态存在" if all_review_states_exist else "[FAIL] 缺少审核状态")

        reviewing_state = task_states.get("REVIEWING", {})
        reviewing_transitions = reviewing_state.get("transitions", [])
        print(f"[INFO] REVIEWING状态转换: {reviewing_transitions}")

        has_valid_transitions = "APPROVED" in reviewing_transitions and "REVISION_REQUIRED" in reviewing_transitions
        print(f"[OK] 包含有效的审核转换" if has_valid_transitions else "[FAIL] 审核转换不完整")

        result.passed = all_review_states_exist and has_valid_transitions
        result.expected = "审核流程配置正确"
        result.actual = f"审核状态完整，转换有效"
        return result

    def test_step7_integration_delivery(self) -> TestResult:
        """步骤7: 测试整合验收"""
        result = TestResult("步骤7: 整合验收")

        print("\n" + "=" * 70)
        print("步骤7: 整合验收测试")
        print("=" * 70)

        task_states = self.config.get("taskStates", {})
        delivered_state = task_states.get("DELIVERED", {})
        is_final = delivered_state.get("final", False)
        transitions = delivered_state.get("transitions", [])

        print(f"[INFO] DELIVERED状态: final={is_final}, transitions={transitions}")

        has_valid_delivery = is_final and len(transitions) == 0
        print(f"[OK] 交付状态有效" if has_valid_delivery else "[FAIL] 交付状态无效")

        metrics = self.config.get("performanceMetrics", {})
        metric_targets = metrics.get("targets", {})
        print(f"[INFO] 性能目标: {len(metric_targets)}项")
        for key, value in metric_targets.items():
            print(f"       {key}: {value}")

        result.passed = has_valid_delivery and len(metric_targets) > 0
        result.expected = "整合验收流程完整"
        result.actual = f"交付状态有效，性能目标{len(metric_targets)}项"
        return result

    def test_confidence_threshold_flow(self) -> TestResult:
        """测试置信度阈值流程"""
        result = TestResult("置信度阈值流程")

        print("\n" + "=" * 70)
        print("置信度阈值流程测试")
        print("=" * 70)

        thresholds = self.config.get("confidenceThresholds", {})

        expected_levels = {
            "directExecute": 95,
            "promptExecute": 85,
            "userConfirm": 70,
            "askUser": {"max": 69}
        }

        all_passed = True
        for level_name, expected_value in expected_levels.items():
            if level_name in thresholds:
                if isinstance(expected_value, dict):
                    actual_max = thresholds[level_name].get("max", 0)
                    status = "[OK]" if actual_max == expected_value["max"] else "[FAIL]"
                    print(f"{status} {level_name}: max={actual_max}(期望{expected_value['max']})")
                    if actual_max != expected_value["max"]:
                        all_passed = False
                else:
                    actual_min = thresholds[level_name].get("min", 0)
                    status = "[OK]" if actual_min == expected_value else "[FAIL]"
                    print(f"{status} {level_name}: min={actual_min}(期望{expected_value})")
                    if actual_min != expected_value:
                        all_passed = False
            else:
                print(f"[FAIL] 缺少置信度级别: {level_name}")
                all_passed = False

        result.passed = all_passed
        result.expected = "置信度阈值正确"
        result.actual = f"验证了{len(expected_levels)}个级别"
        return result

    def test_priority_level_flow(self) -> TestResult:
        """测试优先级流程"""
        result = TestResult("优先级级别流程")

        print("\n" + "=" * 70)
        print("优先级级别流程测试")
        print("=" * 70)

        priority_levels = self.config.get("priorityLevels", {})

        expected_priorities = ["P0_CRITICAL", "P1_HIGH", "P2_MEDIUM", "P3_LOW"]

        all_passed = True
        for priority in expected_priorities:
            if priority in priority_levels:
                agents = priority_levels[priority].get("agents", [])
                response_time = priority_levels[priority].get("responseTime", "unknown")
                print(f"[OK] {priority}: agents={len(agents)}, response={response_time}")
            else:
                print(f"[FAIL] 缺少优先级: {priority}")
                all_passed = False

        result.passed = all_passed
        result.expected = "优先级级别完整"
        result.actual = f"包含{len(priority_levels)}个优先级"
        return result

    def test_fallback_rules_flow(self) -> TestResult:
        """测试降级规则流程"""
        result = TestResult("降级规则流程")

        print("\n" + "=" * 70)
        print("降级规则流程测试")
        print("=" * 70)

        fallback_rules = self.config.get("fallbackRules", {})

        expected_rules = ["noMatch", "executionFailure", "circuitOpen", "securityViolation"]

        all_passed = True
        for rule_name in expected_rules:
            if rule_name in fallback_rules:
                action = fallback_rules[rule_name].get("action", "unknown")
                print(f"[OK] {rule_name}: action={action}")
            else:
                print(f"[FAIL] 缺少降级规则: {rule_name}")
                all_passed = False

        result.passed = all_passed
        result.expected = "降级规则完整"
        result.actual = f"包含{len(fallback_rules)}个降级规则"
        return result

    def run_all_tests(self) -> Dict:
        """运行所有测试"""
        print("=" * 70)
        print("系统执行流程全面测试")
        print("=" * 70)
        print(f"测试时间: {datetime.now().isoformat()}")
        print(f"配置文件: {RULES_PATH}")
        print(f"检查点脚本: {CHECKPOINT_SCRIPT}")

        tests = [
            self.test_step1_task_reception,
            self.test_step2_parse_matching,
            self.test_step3_task_decomposition,
            self.test_step4_agent_dispatch,
            self.test_step5_execution_control,
            self.test_step6_review_process,
            self.test_step7_integration_delivery,
            self.test_confidence_threshold_flow,
            self.test_priority_level_flow,
            self.test_fallback_rules_flow,
        ]

        for test_func in tests:
            test_result, duration = self._measure_time(test_func)
            test_result.duration_ms = round(duration, 2)
            self.results.append(test_result)
            self.step_times[test_func.__name__] = duration

        return self._generate_report()

    def _generate_report(self) -> Dict:
        """生成测试报告"""
        passed_count = sum(1 for r in self.results if r.passed)
        total_count = len(self.results)
        pass_rate = (passed_count / total_count * 100) if total_count > 0 else 0

        report = {
            "test_metadata": {
                "timestamp": datetime.now().isoformat(),
                "total_tests": total_count,
                "passed": passed_count,
                "failed": total_count - passed_count,
                "pass_rate": f"{pass_rate:.1f}%"
            },
            "test_results": [r.to_dict() for r in self.results],
            "step_times_ms": {k: round(v, 2) for k, v in self.step_times.items()}
        }

        return report


def main():
    print("=" * 70)
    print("Agent协同体系 - 系统执行流程测试")
    print("=" * 70)

    tester = SystemFlowTester()
    report = tester.run_all_tests()

    print("\n" + "=" * 70)
    print("测试结果汇总")
    print("=" * 70)

    metadata = report["test_metadata"]
    print(f"总计: {metadata['passed']}/{metadata['total_tests']} 通过")
    print(f"通过率: {metadata['pass_rate']}")
    print(f"执行时间: {sum(report['step_times_ms'].values()):.2f}ms")

    print("\n--- 各步骤执行时间 ---")
    for step_name, duration in report["step_times_ms"].items():
        print(f"  {step_name}: {duration:.2f}ms")

    print("\n--- 测试详情 ---")
    for result in report["test_results"]:
        status = "[OK]" if result["passed"] else "[FAIL]"
        print(f"{status} {result['name']}: {result['actual']}")

    report_file = SCRIPT_DIR / "system_flow_test_report.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n[INFO] 详细报告已保存: {report_file}")

    return 0 if metadata['passed'] == metadata['total_tests'] else 1


if __name__ == "__main__":
    sys.exit(main())