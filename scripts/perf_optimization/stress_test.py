#!/usr/bin/env python3
"""
长时间高负载稳定性压测
Locust配置 - 模拟50并发用户持续30分钟

运行: locust -f scripts/perf_optimization/stress_test.py --host=http://127.0.0.1:5002
  或无头模式: locust -f scripts/perf_optimization/stress_test.py --host=http://127.0.0.1:5002 --headless -u 50 -r 10 -t 30m
"""
import os, json, random, time
from datetime import datetime

try:
    from locust import HttpUser, task, between, events
except ImportError:
    print("请安装 locust: pip install locust")
    raise

API_PREFIX = "/api/v1"
STRESS_RESULTS: list[dict] = []


class ERPStressUser(HttpUser):
    wait_time = between(0.5, 2)
    token: str = ""

    def on_start(self):
        resp = self.client.post(
            f"{API_PREFIX}/auth/login",
            json={"username": os.getenv("TEST_USER", "admin"), "password": os.getenv("TEST_PASS", "admin123")},
            name="登录",
        )
        data = resp.json()
        self.token = data.get("access_token") or data.get("token", "")
        self.headers = {"Authorization": f"Bearer {self.token}"}

    @task(10)
    def list_inventory(self):
        page = random.randint(1, 50)
        self.client.get(
            f"{API_PREFIX}/stock/inventory?page={page}&per_page=50",
            headers=self.headers, name="库存列表",
        )

    @task(8)
    def list_orders(self):
        page = random.randint(1, 50)
        self.client.get(
            f"{API_PREFIX}/orders/list?page={page}&per_page=50",
            headers=self.headers, name="订单列表",
        )

    @task(6)
    def list_stockins(self):
        page = random.randint(1, 30)
        self.client.get(
            f"{API_PREFIX}/stock/in/list?page={page}&per_page=50",
            headers=self.headers, name="入库列表",
        )

    @task(6)
    def list_stockouts(self):
        page = random.randint(1, 30)
        self.client.get(
            f"{API_PREFIX}/stock/out/list?page={page}&per_page=50",
            headers=self.headers, name="出库列表",
        )

    @task(5)
    def list_products(self):
        self.client.get(
            f"{API_PREFIX}/products/list?page=1&per_page=50",
            headers=self.headers, name="产品列表",
        )

    @task(4)
    def filter_orders_by_status(self):
        status = random.choice(["待备货", "已备货", "待出货", "已出货"])
        self.client.get(
            f"{API_PREFIX}/orders/list?status={status}&per_page=50",
            headers=self.headers, name="订单状态筛选",
        )

    @task(3)
    def search_products(self):
        self.client.get(
            f"{API_PREFIX}/products/list?search=压测&per_page=50",
            headers=self.headers, name="产品搜索",
        )

    @task(2)
    def list_customers(self):
        self.client.get(
            f"{API_PREFIX}/customers/list?page=1&per_page=50",
            headers=self.headers, name="客户列表",
        )

    @task(1)
    def create_order(self):
        self.client.post(
            f"{API_PREFIX}/orders/create",
            json={"product_id": 1, "quantity": random.randint(50, 200), "customer": f"压测{random.randint(1,100)}", "note": "stress", "order_type": "regular"},
            headers=self.headers, name="创建订单",
        )


@events.request.add_listener
def on_request(request_type, name, response_time, response_length, exception, **kwargs):
    STRESS_RESULTS.append({
        "timestamp": datetime.now().isoformat(),
        "method": request_type,
        "name": name,
        "response_time_ms": round(response_time, 2),
        "size": response_length,
        "error": str(exception) if exception else None,
    })


@events.test_stop.add_listener
def on_stop(**kwargs):
    if not STRESS_RESULTS:
        return
    report_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "tests", "performance", "reports",
        f"stress_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
    )
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total_requests": len(STRESS_RESULTS),
            "errors": sum(1 for r in STRESS_RESULTS if r["error"]),
            "avg_ms": round(sum(r["response_time_ms"] for r in STRESS_RESULTS) / len(STRESS_RESULTS), 2),
            "results": STRESS_RESULTS[-1000:],
        }, f, ensure_ascii=False, indent=2)
    print(f"\n压测报告: {report_path}")
