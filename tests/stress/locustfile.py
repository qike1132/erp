"""ERP 系统压测脚本（Locust）—— 现行唯一权威压测入口。

取代 2026-04 的历史脚本与三份报告；那些报告已整体失效（压的是生产端口 5002、
数据对应 6 个多月前已不存在的代码版本），失效声明见同目录 ``*_REPORT.md`` 头注。

安全约束（2026-11-03 审查 S2 / B3）
-----------------------------------
1. **目标地址过守卫**：``require_non_production`` 对回环地址（127.0.0.1/localhost 等）
   默认拒绝，必须显式 ``STRESS_TEST_ALLOW_PROD=1`` 才放行；默认目标指向 CI 同款
   隔离端口 **5502**，而不是生产 5002。
2. **凭据只从环境变量取**：旧脚本硬编码 ``admin/admin123``，真实库口令早已更换，
   照旧跑只会得到「登录失败 → 全部请求 401」的假数据。
3. **登录失败必须炸掉**：不再静默跳过登录（旧实现的 ``if status_code == 200`` 分支
   在失败时会把整个压测变成未鉴权请求的无效负载）。

负载模型与阈值口径见 ``docs/slo.md``；CI 的轻量延迟门禁见
``tests/e2e_api/test_latency_budget.py``（不依赖 locust）。

用法
----
    export STRESS_BASE_URL=http://127.0.0.1:5502   # 隔离后端（*_test 库）
    export STRESS_USERNAME=... STRESS_PASSWORD=...
    locust -f tests/stress/locustfile.py --headless -u 10 -r 2 -t 5m --csv=logs/stress

    # 分阶段（旧「phased」脚本名不副实，阶段化应交给 locust 参数）
    locust -f tests/stress/locustfile.py --headless --step-load \
           --step-users 5 --step-time 60s -u 50 -t 15m
"""
import os
import sys
from pathlib import Path

from locust import HttpUser, between, task

# locust 以本文件所在目录为 sys.path[0]，需显式补仓库根才能导入 tests._prod_guard
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests._prod_guard import require_non_production

_BASE_URL = os.getenv("STRESS_BASE_URL", "http://127.0.0.1:5502").rstrip("/")
_USERNAME = os.getenv("STRESS_USERNAME", "")
_PASSWORD = os.getenv("STRESS_PASSWORD", "")

require_non_production(_BASE_URL)

if not _USERNAME or not _PASSWORD:
    raise SystemExit(
        "拒绝运行：未提供压测账号。请设置 STRESS_USERNAME / STRESS_PASSWORD。\n"
        "旧脚本硬编码的 admin/admin123 已失效，沿用只会得到全 401 的无效结果。"
    )


class ERPUser(HttpUser):
    """只读主链路负载（写链路压测需单独授权，且必须指向 *_test 库）。"""

    host = _BASE_URL
    wait_time = between(0.5, 2)

    def on_start(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": _USERNAME, "password": _PASSWORD},
            name="/api/v1/auth/login",
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"压测登录失败 HTTP {response.status_code}：{response.text[:200]}"
                "（不会静默降级为未鉴权压测）"
            )
        token = response.json().get("access_token")
        if not token:
            raise RuntimeError("压测登录响应缺少 access_token，拒绝继续")
        self.client.headers.update({"Authorization": f"Bearer {token}"})

    @task(3)
    def get_orders(self) -> None:
        self.client.get("/api/v1/orders/list")

    @task(3)
    def get_products(self) -> None:
        self.client.get("/api/v1/products/list")

    @task(2)
    def get_stock(self) -> None:
        self.client.get("/api/v1/stock/inventory")

    @task(1)
    def get_customers(self) -> None:
        self.client.get("/api/v1/customers/list")
