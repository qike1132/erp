"""
ERP系统压力测试 - Locust脚本
"""
from locust import HttpUser, between, task


class ERPUser(HttpUser):
    wait_time = between(0.5, 2)

    def on_start(self):
        """登录获取token"""
        response = self.client.post("/api/v1/auth/login", json={
            "username": "admin",
            "password": "admin123"
        })
        if response.status_code == 200:
            token = response.json().get("access_token")
            self.client.headers.update({"Authorization": f"Bearer {token}"})

    @task(3)
    def get_orders(self):
        self.client.get("/api/v1/orders/list")

    @task(3)
    def get_products(self):
        self.client.get("/api/v1/products/list")

    @task(2)
    def get_stock(self):
        self.client.get("/api/v1/stock/inventory")

    @task(1)
    def get_customers(self):
        self.client.get("/api/v1/customers/list")
