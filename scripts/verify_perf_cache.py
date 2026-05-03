"""
验证页面性能优化：
1. /material-calculator vue-query 30s 缓存
2. /purchase 后端 L1 60s 缓存
使用 Playwright 拦截网络请求验证。
"""
import time

from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:3000"
API_BASE = "/api/v1"


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # --- 登录 ---
        print("[1/6] 登录...")
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.fill('input[name="username"]', 'admin')
        page.fill('input[name="password"]', 'admin123')
        page.click('button[type="submit"]')
        page.wait_for_url(lambda url: "/dashboard" in url, timeout=15000)
        print("    登录成功")

        # 拦截器：记录请求
        captured = []
        def handle_route(route, request):
            url = request.url
            if API_BASE in url:
                captured.append({"url": url, "time": time.time()})
            route.continue_()
        page.route("**/*", handle_route)

        # ====== 验证 A: material-calculator vue-query 缓存 ======
        print("\n[2/6] 首次进入 /material-calculator ...")
        captured.clear()
        page.goto(f"{BASE_URL}/material-calculator", wait_until="networkidle")
        time.sleep(1)
        product_reqs_first = [r for r in captured if "purchase-center/products" in r["url"]]
        print(f"    首次 products 请求数: {len(product_reqs_first)}")
        if product_reqs_first:
            print(f"    URL: {product_reqs_first[0]['url']}")

        print("\n[3/6] 切到 /dashboard，5s 后切回 /material-calculator（<30s，应命中 vue-query 缓存）...")
        page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle")
        time.sleep(3)
        captured.clear()
        page.goto(f"{BASE_URL}/material-calculator", wait_until="networkidle")
        time.sleep(1)
        product_reqs_second = [r for r in captured if "purchase-center/products" in r["url"]]
        print(f"    二次 products 请求数: {len(product_reqs_second)}")

        # ====== 验证 B: purchase 后端 L1 缓存 ======
        print("\n[4/6] 首次进入 /purchase ...")
        captured.clear()
        page.goto(f"{BASE_URL}/purchase", wait_until="networkidle")
        time.sleep(1)
        orders_first = [r for r in captured if "purchase-center/orders" in r["url"] or "purchase-center/unprocessed-orders" in r["url"]]
        print(f"    首次 orders/unprocessed 请求数: {len(orders_first)}")
        for r in orders_first:
            print(f"      {r['url']}")

        print("\n[5/6] 切到 /dashboard，5s 后切回 /purchase（<60s，应命中后端 L1 缓存）...")
        page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle")
        time.sleep(3)
        captured.clear()
        page.goto(f"{BASE_URL}/purchase", wait_until="networkidle")
        time.sleep(1)
        orders_second = [r for r in captured if "purchase-center/orders" in r["url"] or "purchase-center/unprocessed-orders" in r["url"]]
        print(f"    二次 orders/unprocessed 请求数: {len(orders_second)}")
        for r in orders_second:
            print(f"      {r['url']}")

        # ====== 总结 ======
        print("\n" + "="*60)
        print("验证报告")
        print("="*60)

        ok_a = len(product_reqs_second) == 0
        ok_b = len(orders_second) == 0

        print("\nA. /material-calculator vue-query 30s 缓存")
        print(f"   首次请求: {len(product_reqs_first)} 次")
        print(f"   二次请求: {len(product_reqs_second)} 次")
        print(f"   结果: {'PASS (未发请求，缓存命中)' if ok_a else 'FAIL (仍发了请求)'}")

        print("\nB. /purchase 后端 L1 60s 缓存")
        print(f"   首次请求: {len(orders_first)} 次")
        print(f"   二次请求: {len(orders_second)} 次")
        print(f"   结果: {'PASS (未发请求，缓存命中)' if ok_b else 'FAIL (仍发了请求)'}")

        print("\n" + "="*60)
        overall = "全部通过" if (ok_a and ok_b) else "存在失败项"
        print(f"总体结论: {overall}")
        print("="*60)

        browser.close()
        return ok_a and ok_b


if __name__ == "__main__":
    success = run()
    exit(0 if success else 1)
