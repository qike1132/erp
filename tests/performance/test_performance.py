"""
ERP系统性能测试框架
使用Python标准库进行性能测试
包含响应时间测量、内存监控、性能报告生成功能

标记: flask_legacy — 迁移中，需重写为 FastAPI + httpx.async 模式
"""
import cProfile
import io
import json
import os
import pstats
import statistics
import sys
import time
import tracemalloc
import unittest
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest

pytestmark = pytest.mark.flask_legacy

from fastapi_app.core.security import hash_password

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

try:
    from app import create_app, db
    from app.models import Customer, Order, Permission, Product, StockIn, StockOut, User
    from flask import Flask
    from flask_sqlalchemy import SQLAlchemy
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
    Flask = None
    SQLAlchemy = None
    create_app = None
    db = None
    Product = None
    User = None
    Permission = None
    Customer = None
    Order = None
    StockIn = None
    StockOut = None


@dataclass
class PerformanceMetric:
    """性能指标数据类"""
    operation_name: str
    module_name: str
    execution_times: list[float] = field(default_factory=list)
    memory_usage: list[float] = field(default_factory=list)
    avg_time: float = 0.0
    min_time: float = 0.0
    max_time: float = 0.0
    std_dev: float = 0.0
    avg_memory: float = 0.0
    peak_memory: float = 0.0
    is_slow: bool = False
    threshold_ms: float = 500.0

    def calculate_stats(self):
        """计算统计数据"""
        if self.execution_times:
            self.avg_time = statistics.mean(self.execution_times)
            self.min_time = min(self.execution_times)
            self.max_time = max(self.execution_times)
            if len(self.execution_times) > 1:
                self.std_dev = statistics.stdev(self.execution_times)
            self.is_slow = self.avg_time > self.threshold_ms

        if self.memory_usage:
            self.avg_memory = statistics.mean(self.memory_usage)
            self.peak_memory = max(self.memory_usage)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            'operation_name': self.operation_name,
            'module_name': self.module_name,
            'avg_time_ms': round(self.avg_time, 3),
            'min_time_ms': round(self.min_time, 3),
            'max_time_ms': round(self.max_time, 3),
            'std_dev_ms': round(self.std_dev, 3),
            'avg_memory_kb': round(self.avg_memory, 2),
            'peak_memory_kb': round(self.peak_memory, 2),
            'sample_count': len(self.execution_times),
            'is_slow': self.is_slow,
            'threshold_ms': self.threshold_ms
        }


class PerformanceTimer:
    """性能计时器"""

    def __init__(self):
        self.start_time = None
        self.end_time = None

    def start(self):
        self.start_time = time.perf_counter()
        return self

    def stop(self) -> float:
        self.end_time = time.perf_counter()
        return self.elapsed_ms

    @property
    def elapsed_ms(self) -> float:
        if self.start_time is None:
            return 0.0
        end = self.end_time or time.perf_counter()
        return (end - self.start_time) * 1000


class MemoryMonitor:
    """内存监控器"""

    def __init__(self):
        self.snapshots = []

    def start(self):
        tracemalloc.start()
        return self

    def take_snapshot(self):
        if tracemalloc.is_tracing():
            snapshot = tracemalloc.take_snapshot()
            self.snapshots.append(snapshot)

    def stop(self):
        if tracemalloc.is_tracing():
            tracemalloc.stop()

    def get_current_memory_kb(self) -> float:
        if tracemalloc.is_tracing():
            current, _peak = tracemalloc.get_traced_memory()
            return current / 1024
        return 0.0

    def get_peak_memory_kb(self) -> float:
        if tracemalloc.is_tracing():
            _current, peak = tracemalloc.get_traced_memory()
            return peak / 1024
        return 0.0


@unittest.skipIf(not HAS_FLASK, "Flask dependencies not available")
class PerformanceTestBase(unittest.TestCase):
    """性能测试基类"""

    SLOW_THRESHOLD_MS = 500.0
    DEFAULT_ITERATIONS = 10

    @classmethod
    def setUpClass(cls):
        """设置测试类"""
        cls.metrics: dict[str, PerformanceMetric] = {}
        cls.test_results: list[dict[str, Any]] = []

        os.environ['FLASK_ENV'] = 'testing'

        cls.app = create_app('testing')
        cls.app_context = cls.app.app_context()
        cls.app_context.push()
        cls.client = cls.app.test_client()

        db.create_all()
        cls._setup_test_data()

        print(f"\n{'='*60}")
        print(f"性能测试开始: {cls.__name__}")
        print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")

    @classmethod
    def tearDownClass(cls):
        """清理测试类"""
        if db is None:
            return
        db.drop_all()
        cls.app_context.pop()

        report = cls.generate_report()
        cls._save_report(report)
        cls._print_summary(report)

    @classmethod
    def _setup_test_data(cls):
        """设置测试数据"""
        permissions_data = [
            ('管理员', 'admin'),
            ('产品管理', 'product_manage'),
            ('产品查看', 'product_view'),
            ('订单管理', 'order_manage'),
            ('订单查看', 'order_view'),
            ('入库管理', 'stockin_manage'),
            ('出库管理', 'stockout_manage'),
            ('库存查看', 'stock_view')
        ]
        for perm_name, perm_code in permissions_data:
            perm = Permission(name=perm_name, code=perm_code)
            db.session.add(perm)

        test_user = User(username='perf_test_user', is_super=True)
        test_user.password = hash_password('test123')
        db.session.add(test_user)

        for perm in Permission.query.all():
            test_user.permissions.append(perm)

        customers = ['测试客户A', '测试客户B', '测试客户C']
        for customer_name in customers:
            customer = Customer(name=customer_name, status=True)
            db.session.add(customer)

        products = []
        for i in range(20):
            product = Product(
                name=f'性能测试产品{i:03d}',
                barcode=f'BAR{i:010d}',
                initial_stock=1000,
                current_stock=1000
            )
            products.append(product)
            db.session.add(product)

        db.session.commit()
        cls.test_user = test_user
        cls.test_products = products
        cls.test_customers = customers

    def measure_performance(self, operation_name: str, func: Callable,
                           iterations: int | None = None, *args, **kwargs) -> PerformanceMetric:
        """测量操作性能"""
        iterations = iterations or self.DEFAULT_ITERATIONS
        module_name = self.__class__.__name__.replace('PerformanceTest', '')

        metric = PerformanceMetric(
            operation_name=operation_name,
            module_name=module_name,
            threshold_ms=self.SLOW_THRESHOLD_MS
        )

        memory_monitor = MemoryMonitor()
        memory_monitor.start()

        for _ in range(iterations):
            timer = PerformanceTimer()
            timer.start()

            try:
                func(*args, **kwargs)
            except Exception as e:
                self.logger.error(f"操作执行失败: {operation_name}, 错误: {e}")
                continue

            elapsed = timer.stop()
            metric.execution_times.append(elapsed)
            metric.memory_usage.append(memory_monitor.get_current_memory_kb())

        memory_monitor.stop()
        metric.calculate_stats()

        key = f"{module_name}.{operation_name}"
        self.metrics[key] = metric

        return metric

    @contextmanager
    def performance_context(self, operation_name: str):
        """性能测量上下文管理器"""
        module_name = self.__class__.__name__.replace('PerformanceTest', '')
        metric = PerformanceMetric(
            operation_name=operation_name,
            module_name=module_name,
            threshold_ms=self.SLOW_THRESHOLD_MS
        )

        memory_monitor = MemoryMonitor()
        timer = PerformanceTimer()

        memory_monitor.start()
        timer.start()

        try:
            yield metric
        finally:
            elapsed = timer.stop()
            metric.execution_times.append(elapsed)
            metric.memory_usage.append(memory_monitor.get_current_memory_kb())
            memory_monitor.stop()
            metric.calculate_stats()

            key = f"{module_name}.{operation_name}"
            self.metrics[key] = metric

    def login_test_user(self):
        """登录测试用户"""
        response = self.client.post('/login', data={
            'username': 'perf_test_user',
            'password': 'test123'
        }, follow_redirects=True)
        return response

    def logout_test_user(self):
        """登出测试用户"""
        self.client.get('/logout', follow_redirects=True)

    @classmethod
    def generate_report(cls) -> dict[str, Any]:
        """生成性能报告"""
        report = {
            'test_name': cls.__name__,
            'test_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'slow_threshold_ms': cls.SLOW_THRESHOLD_MS,
            'metrics': [],
            'slow_operations': [],
            'summary': {
                'total_operations': 0,
                'slow_operations_count': 0,
                'avg_response_time_ms': 0.0,
                'max_response_time_ms': 0.0,
                'modules_tested': []
            }
        }

        all_times = []
        modules = set()

        for key, metric in cls.metrics.items():
            metric_dict = metric.to_dict()
            report['metrics'].append(metric_dict)

            all_times.extend(metric.execution_times)
            modules.add(metric.module_name)

            if metric.is_slow:
                report['slow_operations'].append({
                    'operation': key,
                    'avg_time_ms': metric.avg_time,
                    'max_time_ms': metric.max_time
                })

        report['summary']['total_operations'] = len(cls.metrics)
        report['summary']['slow_operations_count'] = len(report['slow_operations'])
        report['summary']['modules_tested'] = list(modules)

        if all_times:
            report['summary']['avg_response_time_ms'] = round(statistics.mean(all_times), 3)
            report['summary']['max_response_time_ms'] = round(max(all_times), 3)

        return report

    @classmethod
    def _save_report(cls, report: dict[str, Any]):
        """保存报告到文件"""
        report_dir = os.path.join(project_root, 'tests', 'performance', 'reports')
        os.makedirs(report_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = os.path.join(report_dir, f'performance_report_{timestamp}.json')

        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"\n性能报告已保存: {report_file}")

    @classmethod
    def _print_summary(cls, report: dict[str, Any]):
        """打印性能摘要"""
        print(f"\n{'='*60}")
        print("性能测试摘要报告")
        print(f"{'='*60}")
        print(f"测试模块: {', '.join(report['summary']['modules_tested'])}")
        print(f"总操作数: {report['summary']['total_operations']}")
        print(f"平均响应时间: {report['summary']['avg_response_time_ms']:.3f} ms")
        print(f"最大响应时间: {report['summary']['max_response_time_ms']:.3f} ms")
        print(f"慢操作数量 (>500ms): {report['summary']['slow_operations_count']}")

        if report['slow_operations']:
            print(f"\n{'='*60}")
            print("慢操作列表 (响应时间 > 500ms):")
            print(f"{'='*60}")
            for slow_op in report['slow_operations']:
                print(f"  - {slow_op['operation']}")
                print(f"    平均: {slow_op['avg_time_ms']:.3f} ms, 最大: {slow_op['max_time_ms']:.3f} ms")

        print(f"\n{'='*60}")
        print("各模块平均响应时间:")
        print(f"{'='*60}")

        module_times = {}
        for metric in report['metrics']:
            module = metric['module_name']
            if module not in module_times:
                module_times[module] = []
            module_times[module].append(metric['avg_time_ms'])

        for module, times in module_times.items():
            avg = statistics.mean(times)
            print(f"  {module}: {avg:.3f} ms")

        print(f"{'='*60}\n")


class PerformanceTestRunner:
    """性能测试运行器"""

    def __init__(self, output_dir: str | None = None):
        self.output_dir = output_dir or os.path.join(
            os.path.dirname(__file__), 'reports'
        )
        os.makedirs(self.output_dir, exist_ok=True)
        self.all_metrics: dict[str, PerformanceMetric] = {}

    def run_test_class(self, test_class: type) -> dict[str, Any]:
        """运行单个测试类"""
        suite = unittest.TestLoader().loadTestsFromTestCase(test_class)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        return {
            'test_class': test_class.__name__,
            'success': result.wasSuccessful(),
            'tests_run': result.testsRun,
            'failures': len(result.failures),
            'errors': len(result.errors)
        }

    def run_all_tests(self, test_classes: list[type]) -> dict[str, Any]:
        """运行所有性能测试"""
        results = []
        for test_class in test_classes:
            result = self.run_test_class(test_class)
            results.append(result)

        return {
            'total_tests': len(test_classes),
            'results': results,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }


def profile_function(func: Callable, *args, **kwargs) -> dict[str, Any]:
    """使用cProfile分析函数性能"""
    profiler = cProfile.Profile()
    profiler.enable()

    start_time = time.perf_counter()
    result = func(*args, **kwargs)
    end_time = time.perf_counter()

    profiler.disable()

    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s).sort_stats('cumulative')
    ps.print_stats(20)

    return {
        'result': result,
        'execution_time_ms': (end_time - start_time) * 1000,
        'profile_stats': s.getvalue()
    }


def measure_time(func: Callable, iterations: int = 1) -> dict[str, Any]:
    """测量函数执行时间"""
    times = []

    for _ in range(iterations):
        start = time.perf_counter()
        func()
        end = time.perf_counter()
        times.append((end - start) * 1000)

    return {
        'avg_time_ms': statistics.mean(times),
        'min_time_ms': min(times),
        'max_time_ms': max(times),
        'std_dev_ms': statistics.stdev(times) if len(times) > 1 else 0,
        'iterations': iterations
    }


@unittest.skipIf(not HAS_FLASK, "Flask dependencies not available")
class OrderManagementPerformanceTest(PerformanceTestBase):
    """订单管理模块性能测试"""

    def test_order_list_query(self):
        """测试订单列表查询性能"""
        self.login_test_user()

        from datetime import datetime

        product = self.test_products[0]
        for i in range(50):
            order = Order(
                order_no=f'ORD-PERF-{i:05d}',
                customer=self.test_customers[0],
                product_id=product.id,
                quantity=100,
                status='待备货',
                order_date=datetime.now()
            )
            db.session.add(order)
        db.session.commit()

        def query_orders():
            return self.client.get('/order/list')

        metric = self.measure_performance('订单列表查询', query_orders, iterations=20)

        self.assertLess(metric.avg_time, 1000,
                       f"订单列表查询平均响应时间 {metric.avg_time:.2f}ms 超过1000ms")

        self.logout_test_user()

    def test_order_create(self):
        """测试订单创建性能"""
        self.login_test_user()

        product = self.test_products[1]
        order_count = 0

        def create_order():
            nonlocal order_count
            order_count += 1
            return self.client.post('/order/list', data={
                'product_id': product.id,
                'quantity': 50,
                'customer': self.test_customers[0],
                'note': f'性能测试订单 {order_count}'
            }, follow_redirects=True)

        metric = self.measure_performance('订单创建', create_order, iterations=10)

        self.assertLess(metric.avg_time, 500,
                       f"订单创建平均响应时间 {metric.avg_time:.2f}ms 超过500ms")

        self.logout_test_user()

    def test_order_edit(self):
        """测试订单编辑性能"""
        self.login_test_user()

        from datetime import datetime

        order = Order(
            order_no='ORD-EDIT-PERF-001',
            customer=self.test_customers[0],
            product_id=self.test_products[2].id,
            quantity=100,
            status='待备货',
            order_date=datetime.now()
        )
        db.session.add(order)
        db.session.commit()

        def edit_order():
            return self.client.post(f'/order/edit/{order.id}', data={
                'customer': self.test_customers[1],
                'quantity': 150,
                'note': '性能测试编辑'
            }, follow_redirects=True)

        metric = self.measure_performance('订单编辑', edit_order, iterations=10)

        self.assertLess(metric.avg_time, 500,
                       f"订单编辑平均响应时间 {metric.avg_time:.2f}ms 超过500ms")

        self.logout_test_user()

    def test_order_delete(self):
        """测试订单删除性能"""
        self.login_test_user()

        from datetime import datetime

        order_ids = []
        for i in range(10):
            order = Order(
                order_no=f'ORD-DEL-PERF-{i:03d}',
                customer=self.test_customers[0],
                product_id=self.test_products[3].id,
                quantity=50,
                status='待备货',
                order_date=datetime.now()
            )
            db.session.add(order)
            db.session.flush()
            order_ids.append(order.id)
        db.session.commit()

        delete_index = [0]

        def delete_order():
            order_id = order_ids[delete_index[0]]
            delete_index[0] += 1
            if delete_index[0] >= len(order_ids):
                delete_index[0] = 0
            return self.client.get(f'/order/delete/{order_id}', follow_redirects=True)

        metric = self.measure_performance('订单删除', delete_order, iterations=10)

        self.assertLess(metric.avg_time, 500,
                       f"订单删除平均响应时间 {metric.avg_time:.2f}ms 超过500ms")

        self.logout_test_user()


@unittest.skipIf(not HAS_FLASK, "Flask dependencies not available")
class StockManagementPerformanceTest(PerformanceTestBase):
    """库存管理模块性能测试"""

    def test_stockin_list_query(self):
        """测试入库列表查询性能"""
        self.login_test_user()

        from datetime import datetime

        for i in range(50):
            stockin = StockIn(
                stockin_no=f'SI-PERF-{i:05d}',
                product_id=self.test_products[4].id,
                quantity=200,
                customer=self.test_customers[0],
                stockin_date=datetime.now()
            )
            db.session.add(stockin)
        db.session.commit()

        def query_stockins():
            return self.client.get('/stock/in/list')

        metric = self.measure_performance('入库列表查询', query_stockins, iterations=20)

        self.assertLess(metric.avg_time, 1000,
                       f"入库列表查询平均响应时间 {metric.avg_time:.2f}ms 超过1000ms")

        self.logout_test_user()

    def test_stockin_create(self):
        """测试入库创建性能"""
        self.login_test_user()

        from datetime import datetime

        count = [0]

        def create_stockin():
            count[0] += 1
            return self.client.post('/stock/in/list', data={
                'product_id': self.test_products[5].id,
                'quantity': 100,
                'customer': self.test_customers[0],
                'stockin_date': datetime.now().strftime('%Y-%m-%d'),
                'note': f'性能测试入库 {count[0]}'
            }, follow_redirects=True)

        metric = self.measure_performance('入库创建', create_stockin, iterations=10)

        self.assertLess(metric.avg_time, 500,
                       f"入库创建平均响应时间 {metric.avg_time:.2f}ms 超过500ms")

        self.logout_test_user()

    def test_stockout_list_query(self):
        """测试出库列表查询性能"""
        self.login_test_user()

        from datetime import datetime

        for i in range(50):
            stockout = StockOut(
                stockout_no=f'SO-PERF-{i:05d}',
                product_id=self.test_products[6].id,
                quantity=50,
                stockout_date=datetime.now()
            )
            db.session.add(stockout)
        db.session.commit()

        def query_stockouts():
            return self.client.get('/stock/out/list')

        metric = self.measure_performance('出库列表查询', query_stockouts, iterations=20)

        self.assertLess(metric.avg_time, 1000,
                       f"出库列表查询平均响应时间 {metric.avg_time:.2f}ms 超过1000ms")

        self.logout_test_user()

    def test_stockout_create(self):
        """测试出库创建性能"""
        self.login_test_user()

        from datetime import datetime

        count = [0]

        def create_stockout():
            count[0] += 1
            return self.client.post('/stock/out/list', data={
                'product_id': self.test_products[7].id,
                'quantity': 10,
                'stockout_date': datetime.now().strftime('%Y-%m-%d'),
                'note': f'性能测试出库 {count[0]}'
            }, follow_redirects=True)

        metric = self.measure_performance('出库创建', create_stockout, iterations=10)

        self.assertLess(metric.avg_time, 500,
                       f"出库创建平均响应时间 {metric.avg_time:.2f}ms 超过500ms")

        self.logout_test_user()

    def test_inventory_query(self):
        """测试库存查询性能"""
        self.login_test_user()

        def query_inventory():
            return self.client.get('/stock/inventory')

        metric = self.measure_performance('库存查询', query_inventory, iterations=20)

        self.assertLess(metric.avg_time, 1000,
                       f"库存查询平均响应时间 {metric.avg_time:.2f}ms 超过1000ms")

        self.logout_test_user()


@unittest.skipIf(not HAS_FLASK, "Flask dependencies not available")
class ProductManagementPerformanceTest(PerformanceTestBase):
    """产品管理模块性能测试"""

    def test_product_list_query(self):
        """测试产品列表查询性能"""
        self.login_test_user()

        def query_products():
            return self.client.get('/product/list')

        metric = self.measure_performance('产品列表查询', query_products, iterations=20)

        self.assertLess(metric.avg_time, 500,
                       f"产品列表查询平均响应时间 {metric.avg_time:.2f}ms 超过500ms")

        self.logout_test_user()

    def test_product_search(self):
        """测试产品搜索性能"""
        self.login_test_user()

        def search_product():
            return self.client.get('/product/search?q=性能测试')

        metric = self.measure_performance('产品搜索', search_product, iterations=20)

        self.assertLess(metric.avg_time, 300,
                       f"产品搜索平均响应时间 {metric.avg_time:.2f}ms 超过300ms")

        self.logout_test_user()

    def test_product_create(self):
        """测试产品创建性能"""
        self.login_test_user()

        count = [0]

        def create_product():
            count[0] += 1
            return self.client.post('/product/list', data={
                'name': f'性能测试产品NEW-{count[0]:03d}',
                'barcode': f'BARNEW{count[0]:010d}',
                'image': '',
                'initial_stock': 100
            }, follow_redirects=True)

        metric = self.measure_performance('产品创建', create_product, iterations=10)

        self.assertLess(metric.avg_time, 500,
                       f"产品创建平均响应时间 {metric.avg_time:.2f}ms 超过500ms")

        self.logout_test_user()

    def test_product_edit(self):
        """测试产品编辑性能"""
        self.login_test_user()

        product = self.test_products[8]

        def edit_product():
            return self.client.post(f'/product/edit/{product.id}', data={
                'name': f'{product.name}-已编辑',
                'barcode': product.barcode,
                'image': '',
                'initial_stock': 200
            }, follow_redirects=True)

        metric = self.measure_performance('产品编辑', edit_product, iterations=10)

        self.assertLess(metric.avg_time, 500,
                       f"产品编辑平均响应时间 {metric.avg_time:.2f}ms 超过500ms")

        self.logout_test_user()

    def test_product_delete(self):
        """测试产品删除性能"""
        self.login_test_user()

        product_ids = []
        for i in range(10):
            product = Product(
                name=f'待删除产品-{i:03d}',
                barcode=f'DEL{i:015d}',
                initial_stock=0,
                current_stock=0
            )
            db.session.add(product)
            db.session.flush()
            product_ids.append(product.id)
        db.session.commit()

        delete_index = [0]

        def delete_product():
            product_id = product_ids[delete_index[0]]
            delete_index[0] += 1
            if delete_index[0] >= len(product_ids):
                delete_index[0] = 0
            return self.client.get(f'/product/delete/{product_id}', follow_redirects=True)

        metric = self.measure_performance('产品删除', delete_product, iterations=10)

        self.assertLess(metric.avg_time, 500,
                       f"产品删除平均响应时间 {metric.avg_time:.2f}ms 超过500ms")

        self.logout_test_user()


@unittest.skipIf(not HAS_FLASK, "Flask dependencies not available")
class APIPerformanceTest(PerformanceTestBase):
    """API接口性能测试"""

    def test_health_check_api(self):
        """测试健康检查API性能"""
        def health_check():
            return self.client.get('/api/health')

        metric = self.measure_performance('健康检查API', health_check, iterations=50)

        self.assertLess(metric.avg_time, 100,
                       f"健康检查API平均响应时间 {metric.avg_time:.2f}ms 超过100ms")

    def test_product_search_api(self):
        """测试产品搜索API性能"""
        self.login_test_user()

        def search_api():
            return self.client.get('/api/product-search?q=测试')

        metric = self.measure_performance('产品搜索API', search_api, iterations=30)

        self.assertLess(metric.avg_time, 300,
                       f"产品搜索API平均响应时间 {metric.avg_time:.2f}ms 超过300ms")

        self.logout_test_user()

    def test_available_stockins_api(self):
        """测试可用入库记录API性能"""
        self.login_test_user()

        def available_stockins():
            return self.client.get(f'/api/available-stockins?product_id={self.test_products[0].id}')

        metric = self.measure_performance('可用入库记录API', available_stockins, iterations=20)

        self.assertLess(metric.avg_time, 500,
                       f"可用入库记录API平均响应时间 {metric.avg_time:.2f}ms 超过500ms")

        self.logout_test_user()

    def test_inventory_logs_api(self):
        """测试库存日志API性能"""
        self.login_test_user()

        def inventory_logs():
            return self.client.get(f'/api/inventory-logs/{self.test_products[0].id}')

        metric = self.measure_performance('库存日志API', inventory_logs, iterations=20)

        self.assertLess(metric.avg_time, 500,
                       f"库存日志API平均响应时间 {metric.avg_time:.2f}ms 超过500ms")

        self.logout_test_user()

    def test_batch_submit_orders_api(self):
        """测试批量提交订单API性能"""
        self.login_test_user()

        orders_data = {
            'orders': [
                {
                    'product_id': self.test_products[9].id,
                    'customer': self.test_customers[0],
                    'quantity': 10,
                    'note': '批量性能测试'
                }
                for _ in range(5)
            ]
        }

        def batch_submit():
            return self.client.post('/api/batch-submit-orders',
                                   json=orders_data,
                                   content_type='application/json')

        metric = self.measure_performance('批量提交订单API', batch_submit, iterations=10)

        self.assertLess(metric.avg_time, 1000,
                       f"批量提交订单API平均响应时间 {metric.avg_time:.2f}ms 超过1000ms")

        self.logout_test_user()

    def test_batch_submit_stockins_api(self):
        """测试批量提交入库API性能"""
        self.login_test_user()

        stockins_data = {
            'stockins': [
                {
                    'product_id': self.test_products[10].id,
                    'customer': self.test_customers[0],
                    'quantity': 50,
                    'note': '批量入库性能测试'
                }
                for _ in range(5)
            ]
        }

        def batch_submit():
            return self.client.post('/api/batch-submit-stockins',
                                   json=stockins_data,
                                   content_type='application/json')

        metric = self.measure_performance('批量提交入库API', batch_submit, iterations=10)

        self.assertLess(metric.avg_time, 1000,
                       f"批量提交入库API平均响应时间 {metric.avg_time:.2f}ms 超过1000ms")

        self.logout_test_user()


def run_performance_tests():
    """运行所有性能测试"""
    print("\n" + "="*60)
    print("ERP系统性能测试")
    print("="*60 + "\n")

    test_classes = [
        OrderManagementPerformanceTest,
        StockManagementPerformanceTest,
        ProductManagementPerformanceTest,
        APIPerformanceTest
    ]

    runner = PerformanceTestRunner()
    results = runner.run_all_tests(test_classes)

    print("\n" + "="*60)
    print("性能测试完成")
    print("="*60)

    return results


if __name__ == '__main__':
    run_performance_tests()
