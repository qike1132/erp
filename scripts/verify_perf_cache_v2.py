"""
验证页面性能优化 - 版本2：更健壮的登录和元素检测
"""
import time

import requests
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:3000"
API_BASE = "/api/v1"

def get_fresh_token():
    url = "http://localhost:5002/api/v1/auth/login"
    resp = requests.post(url, json={"username": "admin", "password": "admin123"})
    if resp.status_code == 200:
        return resp.json().get("access_token", "")
    raise RuntimeError(f"Login failed: {resp.status_code} {resp.text}")


def run():
    token = get_fresh_token()
    print(f"[0/6] 获取新 token: ...{token[-30:]}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})

        context.add_cookies([
            {
                "name": "access_token",
                "value": token,
                "domain": "localhost",
                "path": "/",
            },
            {
                "name": "auth_status",
                "value": "authenticated",
                "domain": "localhost",
                "path": "/",
            }
        ])
        print("    已注入 access_token 和 auth_status cookies")

        page = context.new_page()

        # 拦截器：记录请求
        captured = []
        def on_request(req):
            url = req.url
            if "/api/v1" in url and "purchase-center" in url:
                captured.append({"url": url, "time": time.time()})
                print(f"    [API HIT] {url}")
        page.on("request", on_request)

        # 预热：访问 dashboard 确保登录态生效
        print("\n[1/6] 预热访问 /dashboard ...")
        page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle")
        time.sleep(3)
        if "/login" in page.url:
            print("    警告：仍被重定向到 login，截图检查")
            page.screenshot(path="d:/erp_system/scripts/debug_login_redirect.png")
        else:
            print(f"    当前 URL: {page.url}")

        # ====== 验证 A: material-calculator ======
        print("\n[2/6] 首次进入 /material-calculator ...")
        captured.clear()
        page.goto(f"{BASE_URL}/material-calculator", wait_until="networkidle")
        time.sleep(4)
        page.screenshot(path="d:/erp_system/scripts/debug_mc_first.png")
        product_reqs_first = [r for r in captured if "purchase-center/products" in r["url"]]
        print(f"    首次 products 请求: {len(product_reqs_first)} 次")

        print("\n[3/6] 切到 /dashboard，5s 后切回 /material-calculator（<30s，应命中缓存）...")
        page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle")
        time.sleep(5)
        captured.clear()
        page.goto(f"{BASE_URL}/material-calculator", wait_until="networkidle")
        time.sleep(4)
        product_reqs_second = [r for r in captured if "purchase-center/products" in r["url"]]
        print(f"    二次 products 请求: {len(product_reqs_second)} 次")

        # ====== 验证 B: purchase ======
        print("\n[4/6] 首次进入 /purchase ...")
        captured.clear()
        page.goto(f"{BASE_URL}/purchase", wait_until="networkidle")
        time.sleep(4)
        orders_first = [r for r in captured if "purchase-center/orders" in r["url"] or "purchase-center/unprocessed-orders" in r["url"]]
        print(f"    首次 orders/unprocessed 请求: {len(orders_first)} 次")

        print("\n[5/6] 切到 /dashboard，5s 后切回 /purchase（<60s，应命中缓存）...")
        page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle")
        time.sleep(5)
        captured.clear()
        page.goto(f"{BASE_URL}/purchase", wait_until="networkidle")
        time.sleep(4)
        orders_second = [r for r in captured if "purchase-center/orders" in r["url"] or "purchase-center/unprocessed-orders" in r["url"]]
        print(f"    二次 orders/unprocessed 请求: {len(orders_second)} 次")

        # ====== 总结 ======
        print("\n" + "="*60)
        print("验证报告")
        print("="*60)

        ok_a = len(product_reqs_second) == 0
        ok_b = len(orders_second) == 0

        print("\nA. /material-calculator vue-query 30s 缓存")
        print(f"   首次请求: {len(product_reqs_first)} 次")
        print(f"   二次请求: {len(product_reqs_second)} 次")
        print(f"   结果: {'PASS (缓存命中)' if ok_a else 'FAIL (缓存未命中)'}")

        print("\nB. /purchase 后端 L1 60s 缓存")
        print(f"   首次请求: {len(orders_first)} 次")
        print(f"   二次请求: {len(orders_second)} 次")
        print(f"   结果: {'PASS (缓存命中)' if ok_b else 'FAIL (缓存未命中)'}")

        print("\n" + "="*60)
        overall = "全部通过" if (ok_a and ok_b) else "存在失败项"
        print(f"总体结论: {overall}")
        print("="*60)

        browser.close()
        return ok_a and ok_b


if __name__ == "__main__":
    success = run()
    exit(0 if success else 1)
