"""
ERP系统压力测试框架 - 100并发用户 60分钟测试

测试方案:
- 并发用户数: 100
- 测试持续时间: 60分钟
- 保护机制: 临时关闭速率限制、CSRF等
- 监控指标: 响应时间、错误率、吞吐量、资源利用率

测试场景:
1. 表单提交测试 (订单、产品、客户、库存等)
2. API接口测试 (所有v1端点)
3. 并发读写测试 (数据库并发操作)
4. 峰值负载测试 (突发流量)

工具: asyncio + aiohttp 高并发HTTP客户端
"""

import asyncio
import aiohttp
import time
import json
import os
import sys
import statistics
import csv
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
import threading
import psutil
import tracemalloc


# ==================== 配置 ====================

BASE_URL = os.getenv("STRESS_TEST_URL", "http://127.0.0.1:5002")
CONCURRENT_USERS = int(os.getenv("STRESS_USERS", "100"))
DURATION_MINUTES = int(os.getenv("STRESS_DURATION", "60"))
REPORT_DIR = os.path.join(os.path.dirname(__file__), "stress_reports")

# 认证信息
TEST_CREDENTIALS = [
    {"username": f"stress_user_{i}", "password": "StressTest123!"}
    for i in range(1, CONCURRENT_USERS + 1)
]

# API端点权重分布（模拟真实使用场景）
API_ENDPOINTS = {
    # 查询操作 (60%)
    "GET_orders": {"path": "/api/v1/orders/list", "weight": 15, "method": "GET"},
    "GET_products": {"path": "/api/v1/products/list", "weight": 15, "method": "GET"},
    "GET_customers": {"path": "/api/v1/customers/list", "weight": 10, "method": "GET"},
    "GET_stock": {"path": "/api/v1/stock/inventory", "weight": 10, "method": "GET"},
    "GET_reports": {"path": "/api/v1/reports/sales", "weight": 5, "method": "GET"},
    
    # 表单提交操作 (30%)
    "POST_order": {"path": "/api/v1/orders/create", "weight": 8, "method": "POST"},
    "POST_product": {"path": "/api/v1/products/create", "weight": 5, "method": "POST"},
    "POST_customer": {"path": "/api/v1/customers/create", "weight": 5, "method": "POST"},
    "POST_stockin": {"path": "/api/v1/stock/in/create", "weight": 5, "method": "POST"},
    "POST_stockout": {"path": "/api/v1/stock/out/create", "weight": 5, "method": "POST"},
    "POST_purchase": {"path": "/api/v1/purchase-center", "weight": 2, "method": "POST"},
    
    # 复杂操作 (10%)
    "PUT_order": {"path": "/api/v1/orders/edit/1", "weight": 3, "method": "PUT"},
    "DELETE_order": {"path": "/api/v1/orders/delete/1", "weight": 2, "method": "DELETE"},
    "POST_batch_import": {"path": "/api/v1/batch/orders", "weight": 3, "method": "POST"},
    "POST_ocr_import": {"path": "/api/v1/ocr-import", "weight": 2, "method": "POST"},
}


# ==================== 数据类 ====================

@dataclass
class RequestMetric:
    """单次请求指标"""
    endpoint: str
    method: str
    status_code: int
    response_time_ms: float
    timestamp: float
    success: bool
    error_message: Optional[str] = None
    response_size_bytes: int = 0


@dataclass
class UserSession:
    """虚拟用户会话"""
    user_id: int
    token: Optional[str] = None
    request_count: int = 0
    error_count: int = 0
    total_response_time: float = 0.0


@dataclass
class StressTestReport:
    """压力测试报告"""
    test_start_time: str = ""
    test_end_time: str = ""
    duration_minutes: int = 0
    concurrent_users: int = 0
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    error_rate: float = 0.0
    avg_response_time_ms: float = 0.0
    min_response_time_ms: float = 0.0
    max_response_time_ms: float = 0.0
    p50_response_time_ms: float = 0.0
    p90_response_time_ms: float = 0.0
    p95_response_time_ms: float = 0.0
    p99_response_time_ms: float = 0.0
    requests_per_second: float = 0.0
    avg_cpu_usage: float = 0.0
    peak_cpu_usage: float = 0.0
    avg_memory_mb: float = 0.0
    peak_memory_mb: float = 0.0
    endpoint_metrics: Dict[str, Any] = field(default_factory=dict)
    errors: List[Dict[str, Any]] = field(default_factory=list)


# ==================== 资源监控 ====================

class ResourceMonitor:
    """系统资源监控"""
    
    def __init__(self, process_name: str = "python"):
        self.process_name = process_name
        self.cpu_samples: List[float] = []
        self.memory_samples: List[float] = []
        self.monitoring = False
        self.monitor_thread: Optional[threading.Thread] = None
    
    def start(self):
        """开始监控"""
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
    
    def stop(self):
        """停止监控"""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
    
    def _monitor_loop(self):
        """监控循环"""
        while self.monitoring:
            try:
                cpu_percent = psutil.cpu_percent(interval=1)
                memory = psutil.virtual_memory()
                
                self.cpu_samples.append(cpu_percent)
                self.memory_samples.append(memory.used / (1024 * 1024))  # MB
            except Exception:
                pass
            
            time.sleep(1)
    
    def get_stats(self) -> Dict[str, float]:
        """获取统计数据"""
        return {
            "avg_cpu_percent": statistics.mean(self.cpu_samples) if self.cpu_samples else 0,
            "peak_cpu_percent": max(self.cpu_samples) if self.cpu_samples else 0,
            "avg_memory_mb": statistics.mean(self.memory_samples) if self.memory_samples else 0,
            "peak_memory_mb": max(self.memory_samples) if self.memory_samples else 0,
        }


# ==================== 请求生成器 ====================

class RequestGenerator:
    """请求负载生成器"""
    
    def __init__(self):
        self.order_counter = 0
        self.product_counter = 0
        self.customer_counter = 0
    
    def get_order_data(self) -> Dict[str, Any]:
        """生成订单表单数据"""
        self.order_counter += 1
        return {
            "order_no": f"STRESS-ORD-{self.order_counter:06d}",
            "customer_id": 1,
            "product_id": 1,
            "quantity": 100,
            "price": 99.99,
            "status": "pending",
            "note": f"压力测试订单 {self.order_counter}"
        }
    
    def get_product_data(self) -> Dict[str, Any]:
        """生成产品表单数据"""
        self.product_counter += 1
        return {
            "name": f"压力测试产品 {self.product_counter:06d}",
            "barcode": f"STRESS{self.product_counter:010d}",
            "category": "测试分类",
            "price": 50.00,
            "cost": 30.00,
            "initial_stock": 500
        }
    
    def get_customer_data(self) -> Dict[str, Any]:
        """生成客户表单数据"""
        self.customer_counter += 1
        return {
            "name": f"压力测试客户 {self.customer_counter:06d}",
            "contact": f"联系人{self.customer_counter}",
            "phone": f"1380000{self.customer_counter:04d}",
            "email": f"stress_{self.customer_counter}@test.com",
            "address": f"测试地址 {self.customer_counter}"
        }
    
    def get_stockin_data(self) -> Dict[str, Any]:
        """生成入库表单数据"""
        return {
            "product_id": 1,
            "quantity": 50,
            "supplier": "压力测试供应商",
            "batch_no": f"BATCH-{int(time.time())}",
            "note": "压力测试入库"
        }
    
    def get_stockout_data(self) -> Dict[str, Any]:
        """生成出库表单数据"""
        return {
            "product_id": 1,
            "quantity": 10,
            "customer_id": 1,
            "note": "压力测试出库"
        }
    
    def get_endpoint_request(self, endpoint_key: str) -> tuple[str, str, Optional[Dict]]:
        """获取端点请求配置
        
        Returns:
            (method, path, data)
        """
        endpoint = API_ENDPOINTS[endpoint_key]
        method = endpoint["method"]
        path = endpoint["path"]
        
        data = None
        if method == "POST":
            if "order" in endpoint_key.lower():
                data = self.get_order_data()
            elif "product" in endpoint_key.lower():
                data = self.get_product_data()
            elif "customer" in endpoint_key.lower():
                data = self.get_customer_data()
            elif "stockin" in endpoint_key.lower():
                data = self.get_stockin_data()
            elif "stockout" in endpoint_key.lower():
                data = self.get_stockout_data()
            elif "batch" in endpoint_key.lower():
                data = {"orders": [self.get_order_data() for _ in range(5)]}
            elif "ocr" in endpoint_key.lower():
                data = {"file_content": "base64_encoded_pdf_content_placeholder"}
            elif "purchase" in endpoint_key.lower():
                data = {
                    "product_id": 1,
                    "quantity": 100,
                    "expected_date": (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
                }
        elif method == "PUT":
            data = self.get_order_data()
        
        return method, path, data


# ==================== 压力测试执行器 ====================

class StressTestExecutor:
    """压力测试执行器"""
    
    def __init__(
        self,
        concurrent_users: int = CONCURRENT_USERS,
        duration_minutes: int = DURATION_MINUTES,
        base_url: str = BASE_URL
    ):
        self.concurrent_users = concurrent_users
        self.duration_minutes = duration_minutes
        self.base_url = base_url
        self.metrics: List[RequestMetric] = []
        self.metrics_lock = asyncio.Lock()
        self.stop_event = asyncio.Event()
        self.request_generator = RequestGenerator()
        self.resource_monitor = ResourceMonitor()
        self.user_sessions: List[UserSession] = []
        self.tokens: List[str] = []
    
    async def authenticate_user(self, session: aiohttp.ClientSession, user_idx: int) -> Optional[str]:
        """用户认证获取Token"""
        try:
            async with session.post(
                f"{self.base_url}/api/v1/auth/login",
                json={
                    "username": "admin",
                    "password": os.getenv("STRESS_TEST_PASSWORD", "admin123")
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("access_token") or data.get("token")
        except Exception as e:
            print(f"用户 {user_idx} 认证失败: {e}")
        return None
    
    async def execute_request(
        self,
        session: aiohttp.ClientSession,
        endpoint_key: str,
        token: Optional[str]
    ) -> RequestMetric:
        """执行单个请求"""
        method, path, data = self.request_generator.get_endpoint_request(endpoint_key)
        url = f"{self.base_url}{path}"
        
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers["Content-Type"] = "application/json"
        
        start_time = time.time()
        status_code = 0
        response_size = 0
        error_message = None
        
        try:
            if method == "GET":
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    status_code = response.status
                    response_size = response.content_length or 0
                    await response.read()
            elif method == "POST":
                async with session.post(
                    url,
                    json=data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    status_code = response.status
                    response_size = response.content_length or 0
                    await response.read()
            elif method == "PUT":
                async with session.put(
                    url,
                    json=data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    status_code = response.status
                    response_size = response.content_length or 0
                    await response.read()
            elif method == "DELETE":
                async with session.delete(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    status_code = response.status
                    response_size = response.content_length or 0
                    await response.read()
            
            success = 200 <= status_code < 400
            
        except asyncio.TimeoutError:
            success = False
            error_message = "请求超时"
        except aiohttp.ClientError as e:
            success = False
            error_message = str(e)
        except Exception as e:
            success = False
            error_message = f"未知错误: {str(e)}"
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        return RequestMetric(
            endpoint=endpoint_key,
            method=method,
            status_code=status_code,
            response_time_ms=elapsed_ms,
            timestamp=time.time(),
            success=success,
            error_message=error_message,
            response_size_bytes=response_size
        )
    
    async def user_worker(self, user_id: int):
        """虚拟用户工作线程"""
        session = aiohttp.ClientSession()
        user_session = UserSession(user_id=user_id)
        self.user_sessions.append(user_session)
        
        # 认证
        token = await self.authenticate_user(session, user_id)
        user_session.token = token
        
        # 端点选择（按权重）
        endpoint_keys = list(API_ENDPOINTS.keys())
        weights = [API_ENDPOINTS[k]["weight"] for k in endpoint_keys]
        
        try:
            while not self.stop_event.is_set():
                # 选择端点
                endpoint_key = self._weighted_choice(endpoint_keys, weights)
                
                # 执行请求
                metric = await self.execute_request(session, endpoint_key, token)
                
                # 记录指标
                async with self.metrics_lock:
                    self.metrics.append(metric)
                
                user_session.request_count += 1
                user_session.total_response_time += metric.response_time_ms
                if not metric.success:
                    user_session.error_count += 1
                
                # 模拟用户思考时间 (0.5-3秒)
                think_time = 0.5 + (hash(str(time.time()) + str(user_id)) % 25) / 10
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=think_time)
                except asyncio.TimeoutError:
                    pass
                    
        except Exception as e:
            print(f"用户 {user_id} 工作线程异常: {e}")
        finally:
            await session.close()
    
    def _weighted_choice(self, keys: List[str], weights: List[int]) -> str:
        """加权随机选择"""
        total = sum(weights)
        r = hash(str(time.time())) % total
        cumulative = 0
        for key, weight in zip(keys, weights):
            cumulative += weight
            if r < cumulative:
                return key
        return keys[-1]
    
    async def run(self) -> StressTestReport:
        """运行压力测试"""
        print(f"\n{'='*80}")
        print(f"ERP系统压力测试启动")
        print(f"{'='*80}")
        print(f"并发用户数: {self.concurrent_users}")
        print(f"测试持续时间: {self.duration_minutes} 分钟")
        print(f"目标服务器: {self.base_url}")
        print(f"报告目录: {REPORT_DIR}")
        print(f"{'='*80}\n")
        
        # 开始资源监控
        self.resource_monitor.start()
        tracemalloc.start()
        
        # 记录开始时间
        start_time = time.time()
        test_start = datetime.now()
        
        # 创建异步任务
        workers = [
            asyncio.create_task(self.user_worker(i))
            for i in range(self.concurrent_users)
        ]
        
        # 打印进度
        progress_task = asyncio.create_task(self._print_progress(start_time))
        
        # 等待测试完成或超时
        timeout_seconds = self.duration_minutes * 60
        try:
            await asyncio.wait_for(self.stop_event.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            print(f"\n测试时间已到 ({self.duration_minutes} 分钟)")
        
        # 停止所有工作线程
        self.stop_event.set()
        
        # 等待所有任务完成
        for worker in workers:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
        
        progress_task.cancel()
        
        # 停止监控
        self.resource_monitor.stop()
        tracemalloc.stop()
        
        # 生成报告
        end_time = time.time()
        report = self._generate_report(test_start, datetime.now(), start_time, end_time)
        
        # 保存报告
        self._save_report(report)
        
        return report
    
    async def _print_progress(self, start_time: float):
        """打印测试进度"""
        while not self.stop_event.is_set():
            elapsed = time.time() - start_time
            progress = min(100, (elapsed / (self.duration_minutes * 60)) * 100)
            
            async with self.metrics_lock:
                total_requests = len(self.metrics)
                failed = sum(1 for m in self.metrics if not m.success)
            
            if total_requests > 0:
                avg_time = statistics.mean([m.response_time_ms for m in self.metrics[-100:]])
            else:
                avg_time = 0
            
            elapsed_minutes = elapsed / 60
            print(f"[{elapsed_minutes:.1f}/{self.duration_minutes}min] "
                  f"进度: {progress:.1f}% | "
                  f"请求: {total_requests} | "
                  f"失败: {failed} | "
                  f"近100次平均: {avg_time:.0f}ms")
            
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass
    
    def _generate_report(
        self,
        test_start: datetime,
        test_end: datetime,
        start_time: float,
        end_time: float
    ) -> StressTestReport:
        """生成测试报告"""
        duration = end_time - start_time
        
        # 基本统计
        total = len(self.metrics)
        successful = sum(1 for m in self.metrics if m.success)
        failed = total - successful
        
        response_times = [m.response_time_ms for m in self.metrics]
        
        # 计算分位数
        sorted_times = sorted(response_times) if response_times else [0]
        
        def percentile(data, p):
            if not data:
                return 0
            k = (len(data) - 1) * p / 100
            f = int(k)
            c = f + 1 if f + 1 < len(data) else f
            return data[f] + (k - f) * (data[c] - data[f]) if c != f else data[f]
        
        # 端点指标
        endpoint_stats = {}
        for endpoint_key in API_ENDPOINTS:
            endpoint_metrics = [m for m in self.metrics if m.endpoint == endpoint_key]
            if endpoint_metrics:
                times = [m.response_time_ms for m in endpoint_metrics]
                endpoint_stats[endpoint_key] = {
                    "total_requests": len(endpoint_metrics),
                    "successful": sum(1 for m in endpoint_metrics if m.success),
                    "failed": sum(1 for m in endpoint_metrics if not m.success),
                    "avg_time_ms": statistics.mean(times),
                    "min_time_ms": min(times),
                    "max_time_ms": max(times),
                    "p95_time_ms": percentile(sorted(times), 95),
                }
        
        # 资源统计
        resource_stats = self.resource_monitor.get_stats()
        
        # 错误列表
        errors = []
        for m in self.metrics:
            if not m.success and m.error_message:
                errors.append({
                    "endpoint": m.endpoint,
                    "method": m.method,
                    "status_code": m.status_code,
                    "error": m.error_message,
                    "timestamp": datetime.fromtimestamp(m.timestamp).isoformat()
                })
        
        # 限制错误列表大小
        if len(errors) > 100:
            errors = errors[:100]
        
        report = StressTestReport(
            test_start_time=test_start.isoformat(),
            test_end_time=test_end.isoformat(),
            duration_minutes=int(duration / 60),
            concurrent_users=self.concurrent_users,
            total_requests=total,
            successful_requests=successful,
            failed_requests=failed,
            error_rate=(failed / total * 100) if total > 0 else 0,
            avg_response_time_ms=statistics.mean(response_times) if response_times else 0,
            min_response_time_ms=min(response_times) if response_times else 0,
            max_response_time_ms=max(response_times) if response_times else 0,
            p50_response_time_ms=percentile(sorted_times, 50),
            p90_response_time_ms=percentile(sorted_times, 90),
            p95_response_time_ms=percentile(sorted_times, 95),
            p99_response_time_ms=percentile(sorted_times, 99),
            requests_per_second=total / duration if duration > 0 else 0,
            avg_cpu_usage=resource_stats["avg_cpu_percent"],
            peak_cpu_usage=resource_stats["peak_cpu_percent"],
            avg_memory_mb=resource_stats["avg_memory_mb"],
            peak_memory_mb=resource_stats["peak_memory_mb"],
            endpoint_metrics=endpoint_stats,
            errors=errors
        )
        
        return report
    
    def _save_report(self, report: StressTestReport):
        """保存报告"""
        os.makedirs(REPORT_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # JSON报告
        json_path = os.path.join(REPORT_DIR, f"stress_report_{timestamp}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(asdict(report), f, ensure_ascii=False, indent=2)
        
        # CSV详细数据
        csv_path = os.path.join(REPORT_DIR, f"stress_metrics_{timestamp}.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["endpoint", "method", "status_code", "response_time_ms", 
                           "success", "error_message", "timestamp"])
            for m in self.metrics:
                writer.writerow([
                    m.endpoint, m.method, m.status_code, 
                    round(m.response_time_ms, 2), m.success,
                    m.error_message or "", 
                    datetime.fromtimestamp(m.timestamp).isoformat()
                ])
        
        # 文本摘要报告
        txt_path = os.path.join(REPORT_DIR, f"stress_summary_{timestamp}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"{'='*80}\n")
            f.write(f"ERP系统压力测试报告\n")
            f.write(f"{'='*80}\n\n")
            f.write(f"测试时间: {report.test_start_time} - {report.test_end_time}\n")
            f.write(f"持续时间: {report.duration_minutes} 分钟\n")
            f.write(f"并发用户: {report.concurrent_users}\n\n")
            
            f.write(f"{'='*80}\n")
            f.write(f"总体指标\n")
            f.write(f"{'='*80}\n")
            f.write(f"总请求数: {report.total_requests}\n")
            f.write(f"成功请求: {report.successful_requests}\n")
            f.write(f"失败请求: {report.failed_requests}\n")
            f.write(f"错误率: {report.error_rate:.2f}%\n")
            f.write(f"吞吐量: {report.requests_per_second:.2f} 请求/秒\n\n")
            
            f.write(f"{'='*80}\n")
            f.write(f"响应时间 (ms)\n")
            f.write(f"{'='*80}\n")
            f.write(f"平均值: {report.avg_response_time_ms:.2f}\n")
            f.write(f"最小值: {report.min_response_time_ms:.2f}\n")
            f.write(f"最大值: {report.max_response_time_ms:.2f}\n")
            f.write(f"P50: {report.p50_response_time_ms:.2f}\n")
            f.write(f"P90: {report.p90_response_time_ms:.2f}\n")
            f.write(f"P95: {report.p95_response_time_ms:.2f}\n")
            f.write(f"P99: {report.p99_response_time_ms:.2f}\n\n")
            
            f.write(f"{'='*80}\n")
            f.write(f"资源利用率\n")
            f.write(f"{'='*80}\n")
            f.write(f"平均CPU: {report.avg_cpu_usage:.1f}%\n")
            f.write(f"峰值CPU: {report.peak_cpu_usage:.1f}%\n")
            f.write(f"平均内存: {report.avg_memory_mb:.1f} MB\n")
            f.write(f"峰值内存: {report.peak_memory_mb:.1f} MB\n\n")
            
            f.write(f"{'='*80}\n")
            f.write(f"端点性能\n")
            f.write(f"{'='*80}\n")
            for endpoint, stats in report.endpoint_metrics.items():
                f.write(f"\n{endpoint}:\n")
                f.write(f"  请求: {stats['total_requests']} "
                       f"(成功: {stats['successful']}, 失败: {stats['failed']})\n")
                f.write(f"  平均: {stats['avg_time_ms']:.2f}ms "
                       f"最小: {stats['min_time_ms']:.2f}ms "
                       f"最大: {stats['max_time_ms']:.2f}ms "
                       f"P95: {stats['p95_time_ms']:.2f}ms\n")
            
            if report.errors:
                f.write(f"\n{'='*80}\n")
                f.write(f"错误列表 (前100条)\n")
                f.write(f"{'='*80}\n")
                for err in report.errors[:20]:
                    f.write(f"[{err['timestamp']}] {err['endpoint']} "
                           f"({err['method']}) - {err['error']}\n")
        
        print(f"\n报告已保存:")
        print(f"  JSON: {json_path}")
        print(f"  CSV: {csv_path}")
        print(f"  摘要: {txt_path}")


# ==================== 保护机制配置 ====================

def generate_protection_disable_config():
    """生成临时关闭保护机制的配置说明"""
    config = {
        "description": "压力测试保护机制临时关闭配置",
        "warning": "此配置仅用于压力测试，测试完成后必须恢复！",
        "steps": [
            {
                "name": "关闭速率限制",
                "file": "fastapi_app/main.py",
                "change": '将 os.getenv("RATE_LIMIT_ENABLED", "true") 改为 "false"',
                "env_var": "RATE_LIMIT_ENABLED=false"
            },
            {
                "name": "关闭CSRF保护",
                "file": "fastapi_app/main.py",
                "change": "注释掉 conditional_csrf_middleware 中间件",
                "action": "注释掉第212-231行的CSRF中间件代码"
            },
            {
                "name": "增加请求体限制",
                "file": "fastapi_app/main.py",
                "change": '将 MAX_REQUEST_BODY_SIZE 从 10MB 增加到 100MB',
                "value": "MAX_REQUEST_BODY_SIZE = 100 * 1024 * 1024"
            },
            {
                "name": "调整数据库连接池",
                "file": "fastapi_app/core/database.py",
                "change": "增加连接池大小以支持100并发",
                "suggestion": "pool_size=50, max_overflow=50"
            },
            {
                "name": "设置环境变量",
                "env": {
                    "RATE_LIMIT_ENABLED": "false",
                    "CSRF_COOKIE_SECURE": "false",
                    "FASTAPI_DEBUG": "false",
                    "DB_POOL_SIZE": "50",
                    "DB_MAX_OVERFLOW": "50"
                }
            }
        ],
        "recovery_steps": [
            "测试完成后，恢复 RATE_LIMIT_ENABLED=true",
            "恢复CSRF中间件",
            "恢复 MAX_REQUEST_BODY_SIZE = 10MB",
            "恢复数据库连接池默认配置",
            "重启服务器"
        ]
    }
    return config


# ==================== 主函数 ====================

async def main():
    """主函数"""
    # 生成保护机制配置
    protection_config = generate_protection_disable_config()
    
    print("\n" + "="*80)
    print("压力测试前准备")
    print("="*80)
    print("\n临时关闭保护机制配置:")
    print(json.dumps(protection_config, ensure_ascii=False, indent=2))
    
    # 设置环境变量（关闭保护机制）
    os.environ["RATE_LIMIT_ENABLED"] = "false"
    os.environ["CSRF_COOKIE_SECURE"] = "false"
    os.environ["FASTAPI_DEBUG"] = "false"
    os.environ["DB_POOL_SIZE"] = "50"
    os.environ["DB_MAX_OVERFLOW"] = "50"
    
    print("\n环境变量已设置:")
    print(f"  RATE_LIMIT_ENABLED=false")
    print(f"  CSRF_COOKIE_SECURE=false")
    print(f"  FASTAPI_DEBUG=false")
    print(f"  DB_POOL_SIZE=50")
    print(f"  DB_MAX_OVERFLOW=50")
    
    # 创建执行器
    executor = StressTestExecutor(
        concurrent_users=CONCURRENT_USERS,
        duration_minutes=DURATION_MINUTES,
        base_url=BASE_URL
    )
    
    # 运行测试
    report = await executor.run()
    
    # 打印摘要
    print("\n" + "="*80)
    print("压力测试完成")
    print("="*80)
    print(f"\n总体结果:")
    print(f"  总请求数: {report.total_requests}")
    print(f"  成功率: {(report.successful_requests / report.total_requests * 100) if report.total_requests > 0 else 0:.2f}%")
    print(f"  错误率: {report.error_rate:.2f}%")
    print(f"  吞吐量: {report.requests_per_second:.2f} req/s")
    print(f"\n响应时间:")
    print(f"  平均: {report.avg_response_time_ms:.2f}ms")
    print(f"  P50: {report.p50_response_time_ms:.2f}ms")
    print(f"  P90: {report.p90_response_time_ms:.2f}ms")
    print(f"  P95: {report.p95_response_time_ms:.2f}ms")
    print(f"  P99: {report.p99_response_time_ms:.2f}ms")
    print(f"\n资源利用:")
    print(f"  平均CPU: {report.avg_cpu_usage:.1f}%")
    print(f"  峰值CPU: {report.peak_cpu_usage:.1f}%")
    print(f"  平均内存: {report.avg_memory_mb:.1f}MB")
    print(f"  峰值内存: {report.peak_memory_mb:.1f}MB")
    
    print("\n" + "="*80)
    print("警告: 测试完成后必须恢复保护机制!")
    print("="*80)
    for step in protection_config["recovery_steps"]:
        print(f"  - {step}")
    
    return report


if __name__ == "__main__":
    asyncio.run(main())
