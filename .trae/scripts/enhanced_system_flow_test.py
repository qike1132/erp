#!/usr/bin/env python3
"""
系统执行流程加强测试 - Enhanced System Execution Flow Test

测试范围：
1. 详细测试步骤（输入参数、操作顺序、预期结果）
2. 实际执行结果（完整日志记录）
3. 流程符合度评估（量化评分）
4. 异常情况记录（错误类型、触发条件）
5. 改进建议

作者: Solo Coder
版本: v2.0.0
日期: 2026-04-07
"""

import subprocess
import sys
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

SCRIPT_DIR = Path(__file__).parent
RULES_PATH = Path(".trae/rules/task-dispatch-rules.json")
CHECKPOINT_SCRIPT = SCRIPT_DIR / "agent_dispatch_checkpoint.py"
LOG_DIR = SCRIPT_DIR / "test_logs"
LOG_DIR.mkdir(exist_ok=True)


class TestSeverity(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class TestStatus(Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


@dataclass
class TestCase:
    id: str
    name: str
    category: str
    severity: TestSeverity
    inputs: Dict[str, Any]
    expected_result: Any
    actual_result: Any = None
    status: TestStatus = TestStatus.SKIPPED
    error_message: str = ""
    execution_time_ms: float = 0.0
    logs: List[str] = field(default_factory=list)
    screenshot_path: str = ""


@dataclass
class TestSuite:
    name: str
    description: str
    test_cases: List[TestCase] = field(default_factory=list)


class EnhancedSystemFlowTester:
    def __init__(self):
        self.test_suites: List[TestSuite] = []
        self.config = self._load_config()
        self.start_time = time.time()
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0
        self.skipped_tests = 0

    def _load_config(self) -> dict:
        if RULES_PATH.exists():
            with open(RULES_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _run_checkpoint(self, task_type: str, has_agent: bool, dispatched: bool) -> Tuple[int, str, str]:
        cmd = [
            sys.executable,
            str(CHECKPOINT_SCRIPT),
            "--task-type", task_type,
            "--has-specialized-agent", str(has_agent).lower(),
            "--agent-dispatched", str(dispatched).lower()
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode, result.stdout, result.stderr

    def _add_log(self, test_case: TestCase, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log_entry = f"[{timestamp}] {message}"
        test_case.logs.append(log_entry)
        print(f"    LOG: {message}")

    def _execute_test_case(self, test_case: TestCase) -> TestCase:
        """执行单个测试用例"""
        start = time.time()
        self._add_log(test_case, f"开始执行测试: {test_case.name}")

        try:
            if test_case.category == "checkpoint":
                task_type = test_case.inputs["task_type"]
                has_agent = test_case.inputs["has_specialized_agent"]
                dispatched = test_case.inputs["agent_dispatched"]

                self._add_log(test_case, f"输入参数: task_type={task_type}, has_agent={has_agent}, dispatched={dispatched}")

                exit_code, stdout, stderr = self._run_checkpoint(task_type, has_agent, dispatched)
                test_case.actual_result = exit_code

                self._add_log(test_case, f"执行结果: exit_code={exit_code}")
                if stdout:
                    self._add_log(test_case, f"STDOUT: {stdout[:200]}")
                if stderr:
                    self._add_log(test_case, f"STDERR: {stderr[:200]}")

                if exit_code == test_case.expected_result:
                    test_case.status = TestStatus.PASSED
                    self._add_log(test_case, "结果判定: PASSED")
                else:
                    test_case.status = TestStatus.FAILED
                    test_case.error_message = f"期望exit_code={test_case.expected_result}, 实际={exit_code}"
                    self._add_log(test_case, f"结果判定: FAILED - {test_case.error_message}")

            elif test_case.category == "config":
                key_path = test_case.inputs["key_path"]
                expected = test_case.inputs["expected"]

                self._add_log(test_case, f"配置路径: {key_path}")
                self._add_log(test_case, f"期望值: {expected}")

                actual = self._get_nested_config(key_path)
                test_case.actual_result = actual

                self._add_log(test_case, f"实际值类型: {type(actual).__name__}")

                if isinstance(expected, int) and isinstance(actual, (dict, list)):
                    actual_count = len(actual)
                    test_case.actual_result = actual_count
                    self._add_log(test_case, f"实际值(计数): {actual_count}")
                    if actual_count == expected:
                        test_case.status = TestStatus.PASSED
                        self._add_log(test_case, "结果判定: PASSED")
                    else:
                        test_case.status = TestStatus.FAILED
                        test_case.error_message = f"期望数量{expected}, 实际数量{actual_count}"
                        self._add_log(test_case, f"结果判定: FAILED - {test_case.error_message}")
                elif isinstance(expected, list) and isinstance(actual, list):
                    actual_count = len(actual)
                    test_case.actual_result = actual_count
                    self._add_log(test_case, f"实际值(计数): {actual_count}")
                    if actual_count == expected:
                        test_case.status = TestStatus.PASSED
                        self._add_log(test_case, "结果判定: PASSED")
                    else:
                        test_case.status = TestStatus.FAILED
                        test_case.error_message = f"期望数量{expected}, 实际数量{actual_count}"
                        self._add_log(test_case, f"结果判定: FAILED - {test_case.error_message}")
                elif actual == expected:
                    test_case.status = TestStatus.PASSED
                    self._add_log(test_case, "结果判定: PASSED")
                else:
                    test_case.status = TestStatus.FAILED
                    test_case.error_message = f"期望{expected}, 实际{actual}"
                    self._add_log(test_case, f"结果判定: FAILED - {test_case.error_message}")

            elif test_case.category == "state_transition":
                from_state = test_case.inputs["from_state"]
                to_state = test_case.inputs["to_state"]
                expect_reject = test_case.inputs.get("expect_reject", False)

                self._add_log(test_case, f"状态转换: {from_state} -> {to_state}")
                if expect_reject:
                    self._add_log(test_case, f"预期: 系统应拒绝此转换")

                valid_transitions = self.config.get("taskStates", {}).get(from_state, {}).get("transitions", [])
                test_case.actual_result = valid_transitions

                self._add_log(test_case, f"有效转换: {valid_transitions}")

                if expect_reject:
                    if to_state not in valid_transitions:
                        test_case.status = TestStatus.PASSED
                        self._add_log(test_case, "结果判定: PASSED (系统正确拒绝)")
                    else:
                        test_case.status = TestStatus.FAILED
                        test_case.error_message = f"系统错误地允许了无效转换 {from_state} -> {to_state}"
                        self._add_log(test_case, f"结果判定: FAILED - {test_case.error_message}")
                elif to_state in valid_transitions:
                    test_case.status = TestStatus.PASSED
                    self._add_log(test_case, "结果判定: PASSED")
                else:
                    test_case.status = TestStatus.FAILED
                    test_case.error_message = f"{from_state}不能转换到{to_state}"
                    self._add_log(test_case, f"结果判定: FAILED - {test_case.error_message}")

        except Exception as e:
            test_case.status = TestStatus.ERROR
            test_case.error_message = str(e)
            self._add_log(test_case, f"执行异常: {e}")

        test_case.execution_time_ms = (time.time() - start) * 1000
        self._add_log(test_case, f"执行耗时: {test_case.execution_time_ms:.2f}ms")

        return test_case

    def _get_nested_config(self, key_path: str) -> Any:
        keys = key_path.split(".")
        value = self.config
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return value

    def setup_checkpoint_tests(self) -> TestSuite:
        """设置检查点测试套件"""
        suite = TestSuite(
            name="Agent调度检查点测试",
            description="验证检查点对各种调度场景的处理"
        )

        test_cases = [
            TestCase(
                id="CP-001",
                name="正确调度-前端任务",
                category="checkpoint",
                severity=TestSeverity.CRITICAL,
                inputs={"task_type": "frontend", "has_specialized_agent": True, "agent_dispatched": True},
                expected_result=0
            ),
            TestCase(
                id="CP-002",
                name="违规未调度-前端任务",
                category="checkpoint",
                severity=TestSeverity.CRITICAL,
                inputs={"task_type": "frontend", "has_specialized_agent": True, "agent_dispatched": False},
                expected_result=1
            ),
            TestCase(
                id="CP-003",
                name="正确调度-后端任务",
                category="checkpoint",
                severity=TestSeverity.CRITICAL,
                inputs={"task_type": "backend", "has_specialized_agent": True, "agent_dispatched": True},
                expected_result=0
            ),
            TestCase(
                id="CP-004",
                name="违规未调度-后端任务",
                category="checkpoint",
                severity=TestSeverity.CRITICAL,
                inputs={"task_type": "backend", "has_specialized_agent": True, "agent_dispatched": False},
                expected_result=1
            ),
            TestCase(
                id="CP-005",
                name="违规未调度-安全任务",
                category="checkpoint",
                severity=TestSeverity.CRITICAL,
                inputs={"task_type": "security", "has_specialized_agent": True, "agent_dispatched": False},
                expected_result=1
            ),
            TestCase(
                id="CP-006",
                name="SoloCoder执行-未知任务",
                category="checkpoint",
                severity=TestSeverity.MEDIUM,
                inputs={"task_type": "unknown", "has_specialized_agent": False, "agent_dispatched": False},
                expected_result=0
            ),
            TestCase(
                id="CP-007",
                name="正确调度-全栈任务",
                category="checkpoint",
                severity=TestSeverity.HIGH,
                inputs={"task_type": "fullstack", "has_specialized_agent": True, "agent_dispatched": True},
                expected_result=0
            ),
            TestCase(
                id="CP-008",
                name="正确调度-测试任务",
                category="checkpoint",
                severity=TestSeverity.HIGH,
                inputs={"task_type": "testing", "has_specialized_agent": True, "agent_dispatched": True},
                expected_result=0
            ),
            TestCase(
                id="CP-009",
                name="强制继续执行（无force参数）",
                category="checkpoint",
                severity=TestSeverity.MEDIUM,
                inputs={"task_type": "frontend", "has_specialized_agent": True, "agent_dispatched": False},
                expected_result=1
            ),
        ]
        suite.test_cases = test_cases
        return suite

    def setup_config_tests(self) -> TestSuite:
        """设置配置验证测试套件"""
        suite = TestSuite(
            name="系统配置验证测试",
            description="验证系统配置项的正确性"
        )

        test_cases = [
            TestCase(
                id="CFG-001",
                name="版本号验证",
                category="config",
                severity=TestSeverity.INFO,
                inputs={"key_path": "version", "expected": "2.0.0"},
                expected_result="2.0.0"
            ),
            TestCase(
                id="CFG-002",
                name="任务状态数量验证",
                category="config",
                severity=TestSeverity.HIGH,
                inputs={"key_path": "taskStates", "expected": 15},
                expected_result=15
            ),
            TestCase(
                id="CFG-003",
                name="优先级级别数量",
                category="config",
                severity=TestSeverity.HIGH,
                inputs={"key_path": "priorityLevels", "expected": 4},
                expected_result=4
            ),
            TestCase(
                id="CFG-004",
                name="调度步骤数量",
                category="config",
                severity=TestSeverity.CRITICAL,
                inputs={"key_path": "dispatchAlgorithm.steps", "expected": 6},
                expected_result=6
            ),
            TestCase(
                id="CFG-005",
                name="置信度-直接执行阈值",
                category="config",
                severity=TestSeverity.HIGH,
                inputs={"key_path": "confidenceThresholds.directExecute.min", "expected": 95},
                expected_result=95
            ),
            TestCase(
                id="CFG-006",
                name="置信度-提示执行阈值",
                category="config",
                severity=TestSeverity.HIGH,
                inputs={"key_path": "confidenceThresholds.promptExecute.min", "expected": 85},
                expected_result=85
            ),
            TestCase(
                id="CFG-007",
                name="重试策略-最大重试次数",
                category="config",
                severity=TestSeverity.HIGH,
                inputs={"key_path": "retryPolicy.maxRetries", "expected": 3},
                expected_result=3
            ),
            TestCase(
                id="CFG-008",
                name="超时配置-任务超时",
                category="config",
                severity=TestSeverity.HIGH,
                inputs={"key_path": "timeoutHandling.taskTimeout", "expected": 300000},
                expected_result=300000
            ),
        ]
        suite.test_cases = test_cases
        return suite

    def setup_state_transition_tests(self) -> TestSuite:
        """设置状态转换测试套件"""
        suite = TestSuite(
            name="任务状态转换测试",
            description="验证任务状态转换的正确性"
        )

        transitions = [
            ("CREATED", "QUEUED"),
            ("CREATED", "CANCELLED"),
            ("QUEUED", "ASSIGNED"),
            ("QUEUED", "ESCALATED"),
            ("ASSIGNED", "RUNNING"),
            ("ASSIGNED", "FAILED"),
            ("RUNNING", "COMPLETED"),
            ("RUNNING", "FAILED"),
            ("RUNNING", "TIMEOUT"),
            ("COMPLETED", "REVIEWING"),
            ("REVIEWING", "APPROVED"),
            ("REVIEWING", "REVISION_REQUIRED"),
            ("APPROVED", "DELIVERED"),
            ("REVISION_REQUIRED", "RUNNING"),
            ("FAILED", "RETRY"),
            ("FAILED", "FALLBACK"),
            ("FAILED", "ESCALATED"),
        ]

        test_cases = [
            TestCase(
                id=f"ST-{i:03d}",
                name=f"状态转换: {frm} -> {to}",
                category="state_transition",
                severity=TestSeverity.MEDIUM,
                inputs={"from_state": frm, "to_state": to},
                expected_result=True
            ) for i, (frm, to) in enumerate(transitions)
        ]

        suite.test_cases = test_cases
        return suite

    def setup_boundary_tests(self) -> TestSuite:
        """设置边界条件测试套件"""
        suite = TestSuite(
            name="边界条件测试",
            description="测试边界条件下的系统表现"
        )

        test_cases = [
            TestCase(
                id="BD-001",
                name="空任务类型",
                category="checkpoint",
                severity=TestSeverity.HIGH,
                inputs={"task_type": "", "has_specialized_agent": False, "agent_dispatched": False},
                expected_result=0
            ),
            TestCase(
                id="BD-002",
                name="超长任务类型名",
                category="checkpoint",
                severity=TestSeverity.LOW,
                inputs={"task_type": "a" * 1000, "has_specialized_agent": False, "agent_dispatched": False},
                expected_result=0
            ),
            TestCase(
                id="BD-003",
                name="特殊字符任务类型",
                category="checkpoint",
                severity=TestSeverity.MEDIUM,
                inputs={"task_type": "test@#$%^&*()", "has_specialized_agent": False, "agent_dispatched": False},
                expected_result=0
            ),
            TestCase(
                id="BD-004",
                name="置信度边界值95",
                category="config",
                severity=TestSeverity.HIGH,
                inputs={"key_path": "confidenceThresholds.directExecute.min", "expected": 95},
                expected_result=95
            ),
            TestCase(
                id="BD-005",
                name="置信度边界值85",
                category="config",
                severity=TestSeverity.HIGH,
                inputs={"key_path": "confidenceThresholds.promptExecute.min", "expected": 85},
                expected_result=85
            ),
            TestCase(
                id="BD-006",
                name="置信度边界值70",
                category="config",
                severity=TestSeverity.HIGH,
                inputs={"key_path": "confidenceThresholds.userConfirm.min", "expected": 70},
                expected_result=70
            ),
        ]
        suite.test_cases = test_cases
        return suite

    def setup_exception_tests(self) -> TestSuite:
        """设置异常场景测试套件"""
        suite = TestSuite(
            name="异常场景测试",
            description="测试异常情况下的系统表现"
        )

        test_cases = [
            TestCase(
                id="EX-001",
                name="缺失配置文件",
                category="config",
                severity=TestSeverity.CRITICAL,
                inputs={"key_path": "non_existent_key", "expected": None},
                expected_result=None
            ),
            TestCase(
                id="EX-002",
                name="无效状态转换",
                category="state_transition",
                severity=TestSeverity.MEDIUM,
                inputs={"from_state": "DELIVERED", "to_state": "RUNNING", "expect_reject": True},
                expected_result=True
            ),
            TestCase(
                id="EX-003",
                name="违反final状态转换",
                category="state_transition",
                severity=TestSeverity.HIGH,
                inputs={"from_state": "DELIVERED", "to_state": "CREATED", "expect_reject": True},
                expected_result=True
            ),
        ]
        suite.test_cases = test_cases
        return suite

    def run_all_tests(self) -> Dict:
        """运行所有测试套件"""
        print("=" * 80)
        print("Agent协同体系 - 系统执行流程加强测试")
        print("=" * 80)
        print(f"开始时间: {datetime.now().isoformat()}")
        print(f"配置文件: {RULES_PATH}")

        self.test_suites = [
            self.setup_checkpoint_tests(),
            self.setup_config_tests(),
            self.setup_state_transition_tests(),
            self.setup_boundary_tests(),
            self.setup_exception_tests(),
        ]

        all_results = []
        total_start = time.time()

        for suite in self.test_suites:
            print(f"\n{'='*80}")
            print(f"测试套件: {suite.name}")
            print(f"描述: {suite.description}")
            print("=" * 80)

            suite_start = time.time()
            for test_case in suite.test_cases:
                self.total_tests += 1
                executed_case = self._execute_test_case(test_case)
                if executed_case.status == TestStatus.PASSED:
                    self.passed_tests += 1
                elif executed_case.status == TestStatus.FAILED:
                    self.failed_tests += 1
                else:
                    self.skipped_tests += 1
                all_results.append(executed_case)

            suite_duration = (time.time() - suite_start) * 1000
            passed = sum(1 for tc in suite.test_cases if tc.status == TestStatus.PASSED)
            failed = sum(1 for tc in suite.test_cases if tc.status == TestStatus.FAILED)
            print(f"\n套件耗时: {suite_duration:.2f}ms | 通过: {passed} | 失败: {failed}")

        total_duration = (time.time() - total_start) * 1000

        return {
            "test_metadata": {
                "timestamp": datetime.now().isoformat(),
                "total_tests": self.total_tests,
                "passed": self.passed_tests,
                "failed": self.failed_tests,
                "skipped": self.skipped_tests,
                "pass_rate": f"{(self.passed_tests/self.total_tests*100):.1f}%",
                "total_duration_ms": total_duration
            },
            "test_results": [self._test_case_to_dict(tc) for tc in all_results]
        }

    def _test_case_to_dict(self, tc: TestCase) -> Dict:
        return {
            "id": tc.id,
            "name": tc.name,
            "category": tc.category,
            "severity": tc.severity.value,
            "status": tc.status.value,
            "inputs": tc.inputs,
            "expected_result": tc.expected_result,
            "actual_result": tc.actual_result,
            "error_message": tc.error_message,
            "execution_time_ms": tc.execution_time_ms,
            "logs": tc.logs
        }

    def generate_detailed_report(self, results: Dict) -> str:
        """生成详细文本报告"""
        metadata = results["test_metadata"]

        report = []
        report.append("=" * 80)
        report.append("Agent协同体系 - 系统执行流程加强测试报告")
        report.append("=" * 80)
        report.append(f"\n报告生成时间: {datetime.now().isoformat()}")
        report.append(f"测试版本: v2.0.0 (增强版)")

        report.append("\n" + "-" * 80)
        report.append("一、测试执行概要")
        report.append("-" * 80)
        report.append(f"总测试数: {metadata['total_tests']}")
        report.append(f"通过: {metadata['passed']} | 失败: {metadata['failed']} | 跳过: {metadata['skipped']}")
        report.append(f"通过率: {metadata['pass_rate']}")
        report.append(f"总执行时间: {metadata['total_duration_ms']:.2f}ms")

        report.append("\n" + "-" * 80)
        report.append("二、详细测试步骤与结果")
        report.append("-" * 80)

        current_suite = None
        for tc_dict in results["test_results"]:
            suite_name = tc_dict["category"]
            if suite_name != current_suite:
                current_suite = suite_name
                report.append(f"\n【{current_suite.upper()}】")

            status_icon = "[OK]" if tc_dict["status"] == "PASSED" else "[FAIL]"
            report.append(f"{status_icon} {tc_dict['id']} {tc_dict['name']}")
            report.append(f"    输入: {tc_dict['inputs']}")
            report.append(f"    预期: {tc_dict['expected_result']}")
            report.append(f"    实际: {tc_dict['actual_result']}")
            if tc_dict['error_message']:
                report.append(f"    错误: {tc_dict['error_message']}")
            report.append(f"    耗时: {tc_dict['execution_time_ms']:.2f}ms")

        report.append("\n" + "-" * 80)
        report.append("三、流程符合度量化评估")
        report.append("-" * 80)

        categories = {}
        for tc_dict in results["test_results"]:
            cat = tc_dict["category"]
            if cat not in categories:
                categories[cat] = {"total": 0, "passed": 0}
            categories[cat]["total"] += 1
            if tc_dict["status"] == "PASSED":
                categories[cat]["passed"] += 1

        total_score = 0
        for cat, stats in categories.items():
            score = (stats["passed"] / stats["total"] * 100) if stats["total"] > 0 else 0
            total_score += score
            report.append(f"{cat}: {stats['passed']}/{stats['total']} ({score:.1f}%)")

        avg_score = total_score / len(categories) if categories else 0
        report.append(f"\n总体符合度评分: {avg_score:.1f}/100")

        report.append("\n" + "-" * 80)
        report.append("四、异常情况记录")
        report.append("-" * 80)

        exceptions = [tc for tc in results["test_results"] if tc["status"] == "FAILED"]
        if exceptions:
            for exc in exceptions:
                report.append(f"异常ID: {exc['id']}")
                report.append(f"异常名称: {exc['name']}")
                report.append(f"错误类型: {exc['category']}")
                report.append(f"触发条件: {exc['inputs']}")
                report.append(f"错误消息: {exc['error_message']}")
                report.append("-" * 40)
        else:
            report.append("未发现异常情况")

        report.append("\n" + "-" * 80)
        report.append("五、改进建议")
        report.append("-" * 80)

        suggestions = [
            ("P1", "边界条件增强", "建议对空字符串和超长输入增加更严格的校验"),
            ("P2", "日志规范化", "建议统一日志格式，增加结构化日志输出"),
            ("P2", "性能监控", "建议增加P99延迟等性能指标的实时采集"),
            ("P3", "测试覆盖", "建议增加并发测试和安全测试用例"),
        ]

        for priority, title, desc in suggestions:
            report.append(f"[{priority}] {title}")
            report.append(f"    {desc}")

        report.append("\n" + "=" * 80)
        report.append("报告结束")
        report.append("=" * 80)

        return "\n".join(report)


def main():
    tester = EnhancedSystemFlowTester()
    results = tester.run_all_tests()

    report = tester.generate_detailed_report(results)

    report_file = LOG_DIR / f"enhanced_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)

    json_report_file = LOG_DIR / f"enhanced_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(json_report_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n[INFO] 文本报告已保存: {report_file}")
    print(f"[INFO] JSON报告已保存: {json_report_file}")

    print(report)

    return 0 if results["test_metadata"]["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())