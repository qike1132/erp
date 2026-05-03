"""
Trae AI Agent System v2.0 - 压力测试套件
模拟高并发场景测试熔断器和重试机制
"""
import random
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum

import pytest


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """熔断器模拟实现"""
    failure_threshold: int = 5
    success_threshold: int = 3
    timeout: int = 30000
    monitoring_window: int = 60000

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0
    total_requests: int = 0
    total_failures: int = 0
    total_successes: int = 0

    def execute(self, success_rate: float = 0.8) -> tuple[bool, str]:
        """执行请求，返回是否成功"""
        self.total_requests += 1
        current_time = time.time() * 1000

        if self.state == CircuitState.OPEN:
            if current_time - self.last_failure_time >= self.timeout:
                self.state = CircuitState.HALF_OPEN
            else:
                return False, "circuit_open"

        if random.random() < success_rate:
            self._record_success()
            return True, "success"
        else:
            self._record_failure()
            return False, "failure"

    def _record_success(self):
        self.success_count += 1
        self.total_successes += 1
        if self.state == CircuitState.HALF_OPEN and self.success_count >= self.success_threshold:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0

    def _record_failure(self):
        self.failure_count += 1
        self.total_failures += 1
        self.last_failure_time = time.time() * 1000
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self.success_count = 0
        elif self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN


@dataclass
class RetryPolicy:
    """重试策略模拟实现"""
    max_retries: int = 3
    initial_delay: int = 1000
    max_delay: int = 10000
    backoff_multiplier: float = 2.0

    total_retries: int = 0
    successful_retries: int = 0

    def execute_with_retry(self, operation, max_attempts: int = None) -> tuple[bool, int]:
        """带重试的执行"""
        attempts = max_attempts or self.max_retries
        for attempt in range(attempts + 1):
            success = operation()
            if success:
                if attempt > 0:
                    self.successful_retries += 1
                return True, attempt
            self.total_retries += 1
        return False, attempts


@dataclass
class StressTestResult:
    """压力测试结果"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    circuit_open_count: int = 0
    total_retries: int = 0
    avg_response_time: float = 0
    p50_response_time: float = 0
    p95_response_time: float = 0
    p99_response_time: float = 0
    throughput: float = 0
    error_rate: float = 0


class TestCircuitBreakerStress:
    """熔断器压力测试"""

    def test_circuit_breaker_normal_load(self):
        """正常负载下熔断器测试"""
        cb = CircuitBreaker(failure_threshold=5, timeout=1000)

        results = []
        for _ in range(100):
            success, reason = cb.execute(success_rate=0.9)
            results.append((success, reason))

        assert cb.state == CircuitState.CLOSED
        assert cb.total_requests == 100
        assert cb.total_successes > 80

    def test_circuit_breaker_high_failure_rate(self):
        """高失败率下熔断器测试"""
        cb = CircuitBreaker(failure_threshold=5, timeout=500)

        results = []
        for _ in range(50):
            success, reason = cb.execute(success_rate=0.3)
            results.append((success, reason))

        assert cb.state == CircuitState.OPEN
        assert cb.failure_count >= 5

    def test_circuit_breaker_recovery(self):
        """熔断器恢复测试"""
        cb = CircuitBreaker(failure_threshold=3, timeout=200)

        for _ in range(10):
            cb.execute(success_rate=0.1)

        assert cb.state == CircuitState.OPEN

        time.sleep(0.3)

        for _ in range(5):
            cb.execute(success_rate=1.0)

        assert cb.state == CircuitState.CLOSED

    def test_circuit_breaker_concurrent_access(self):
        """并发访问熔断器测试"""
        cb = CircuitBreaker(failure_threshold=10, timeout=1000)
        results = []
        lock = threading.Lock()

        def make_request():
            success, reason = cb.execute(success_rate=0.7)
            with lock:
                results.append((success, reason))

        threads = []
        for _ in range(100):
            t = threading.Thread(target=make_request)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(results) == 100
        assert cb.total_requests == 100


class TestRetryPolicyStress:
    """重试策略压力测试"""

    def test_retry_policy_success_after_retry(self):
        """重试后成功测试"""
        rp = RetryPolicy(max_retries=3)

        call_count = 0
        def flaky_operation():
            nonlocal call_count
            call_count += 1
            return call_count >= 2

        success, attempts = rp.execute_with_retry(flaky_operation)

        assert success
        assert attempts == 1
        assert rp.successful_retries == 1

    def test_retry_policy_max_retries_exceeded(self):
        """超过最大重试次数测试"""
        rp = RetryPolicy(max_retries=3)

        def always_fail():
            return False

        success, attempts = rp.execute_with_retry(always_fail)

        assert not success
        assert attempts == 3

    def test_retry_policy_concurrent_operations(self):
        """并发重试操作测试"""
        rp = RetryPolicy(max_retries=2)
        results = []
        lock = threading.Lock()

        def operation():
            success_count = 0
            def flaky():
                nonlocal success_count
                success_count += 1
                return success_count >= random.randint(1, 4)

            success, attempts = rp.execute_with_retry(flaky)
            with lock:
                results.append((success, attempts))

        threads = []
        for _ in range(50):
            t = threading.Thread(target=operation)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(results) == 50


class TestIntegratedStress:
    """集成压力测试"""

    @pytest.fixture
    def integrated_system(self):
        """创建集成系统"""
        return {
            "circuit_breaker": CircuitBreaker(failure_threshold=5, timeout=1000),
            "retry_policy": RetryPolicy(max_retries=3),
            "results": StressTestResult()
        }

    def test_integrated_normal_operation(self, integrated_system):
        """集成系统正常操作测试"""
        cb = integrated_system["circuit_breaker"]
        rp = integrated_system["retry_policy"]

        response_times = []

        for _ in range(100):
            start_time = time.time()

            success, reason = cb.execute(success_rate=0.85)
            if not success and reason == "failure":
                def retry_op():
                    s, _ = cb.execute(success_rate=0.85)
                    return s
                success, _ = rp.execute_with_retry(retry_op)

            response_time = (time.time() - start_time) * 1000
            response_times.append(response_time)

            if success:
                integrated_system["results"].successful_requests += 1
            else:
                integrated_system["results"].failed_requests += 1

        integrated_system["results"].total_requests = 100
        integrated_system["results"].avg_response_time = statistics.mean(response_times)
        integrated_system["results"].error_rate = integrated_system["results"].failed_requests / 100

        assert integrated_system["results"].successful_requests > 80
        assert integrated_system["results"].error_rate < 0.2

    def test_integrated_high_load(self, integrated_system):
        """集成系统高负载测试"""
        cb = integrated_system["circuit_breaker"]
        rp = integrated_system["retry_policy"]
        results = integrated_system["results"]

        lock = threading.Lock()
        response_times = []

        def make_request():
            start_time = time.time()

            success, reason = cb.execute(success_rate=0.7)
            if not success and reason == "failure":
                def retry_op():
                    s, _ = cb.execute(success_rate=0.7)
                    return s
                success, _ = rp.execute_with_retry(retry_op)

            response_time = (time.time() - start_time) * 1000

            with lock:
                response_times.append(response_time)
                results.total_requests += 1
                if success:
                    results.successful_requests += 1
                else:
                    results.failed_requests += 1
                if reason == "circuit_open":
                    results.circuit_open_count += 1

        start_time = time.time()

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(make_request) for _ in range(200)]
            for _future in as_completed(futures):
                pass

        total_time = time.time() - start_time

        results.throughput = results.total_requests / total_time
        results.avg_response_time = statistics.mean(response_times)
        results.p50_response_time = statistics.median(response_times)
        results.p95_response_time = sorted(response_times)[int(len(response_times) * 0.95)]
        results.p99_response_time = sorted(response_times)[int(len(response_times) * 0.99)]
        results.error_rate = results.failed_requests / results.total_requests

        print("\n压力测试结果:")
        print(f"  总请求数: {results.total_requests}")
        print(f"  成功请求: {results.successful_requests}")
        print(f"  失败请求: {results.failed_requests}")
        print(f"  熔断次数: {results.circuit_open_count}")
        print(f"  吞吐量: {results.throughput:.2f} req/s")
        print(f"  平均响应时间: {results.avg_response_time:.2f} ms")
        print(f"  P50响应时间: {results.p50_response_time:.2f} ms")
        print(f"  P95响应时间: {results.p95_response_time:.2f} ms")
        print(f"  P99响应时间: {results.p99_response_time:.2f} ms")
        print(f"  错误率: {results.error_rate * 100:.2f}%")

        assert results.total_requests == 200
        assert results.throughput > 50
        assert results.error_rate < 0.5


class TestPerformanceBenchmarks:
    """性能基准测试"""

    def test_circuit_breaker_performance(self):
        """熔断器性能基准"""
        cb = CircuitBreaker()

        start_time = time.time()
        for _ in range(10000):
            cb.execute(success_rate=0.9)
        elapsed = time.time() - start_time

        throughput = 10000 / elapsed
        print(f"\n熔断器性能: {throughput:.0f} ops/s")

        assert throughput > 5000

    def test_retry_policy_performance(self):
        """重试策略性能基准"""
        rp = RetryPolicy()

        def quick_op():
            return True

        start_time = time.time()
        for _ in range(10000):
            rp.execute_with_retry(quick_op)
        elapsed = time.time() - start_time

        throughput = 10000 / elapsed
        print(f"\n重试策略性能: {throughput:.0f} ops/s")

        assert throughput > 5000


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-s"])
