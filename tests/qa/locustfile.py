"""
Locust 压力测试脚本 - ERP系统API
"""
from locust import HttpUser, between, task


ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"


class ERPUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        response = self.client.post("/api/v1/auth/login", json={
            "username": ADMIN_USERNAME,
            "password": ADMIN_PASSWORD,
        })
        if response.status_code == 200:
            data = response.json()
            token = data.get("access_token", "")
            if token:
                self.client.headers.update({"Authorization": f"Bearer {token}"})

    @task(5)
    def get_products(self):
        self.client.get("/api/v1/products")

    @task(5)
    def get_orders(self):
        self.client.get("/api/v1/orders")

    @task(3)
    def get_suppliers(self):
        self.client.get("/api/v1/suppliers")

    @task(3)
    def get_customers(self):
        self.client.get("/api/v1/customers")

    @task(2)
    def get_stock_in(self):
        self.client.get("/api/v1/stock/in")

    @task(2)
    def get_stock_out(self):
        self.client.get("/api/v1/stock/out")

    @task(2)
    def get_users(self):
        self.client.get("/api/v1/users/list")

    @task(2)
    def get_cases(self):
        self.client.get("/api/v1/cases")

    @task(2)
    def get_approvals(self):
        self.client.get("/api/v1/approvals")

    @task(2)
    def get_dashboard(self):
        self.client.get("/api/v1/dashboard/summary")

    @task(1)
    def post_products_query(self):
        self.client.post("/api/v1/products/query", json={"page": 1, "per_page": 10})

    @task(1)
    def post_orders_query(self):
        self.client.post("/api/v1/orders/query", json={"page": 1, "per_page": 10})
