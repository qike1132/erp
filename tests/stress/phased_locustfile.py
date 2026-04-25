"""
ERP系统压力测试 - 分阶段Locust脚本
Phase 1: 5分钟 20并发
Phase 2: 10分钟 30并发  
Phase 3: 15分钟 50并发
"""
from locust import HttpUser, task, between, events
import time

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
