import urllib.request, json, base64

# Login
body = json.dumps({"username":"admin","password":"admin123","remember":True}).encode()
req = urllib.request.Request("http://localhost:3000/api/v1/auth/login", data=body, headers={"Content-Type":"application/json"})
resp = urllib.request.urlopen(req)
login_data = json.loads(resp.read().decode())
token = login_data["access_token"]
print("Login OK, token:", token[:30] + "...")

# Test mobile dashboard
req2 = urllib.request.Request("http://localhost:3000/api/v1/dashboard/mobile?date=2026-05-12", headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
resp2 = urllib.request.urlopen(req2)
mobile_data = json.loads(resp2.read().decode())

pp = mobile_data.get("data", {}).get("production_plans", {})
plans = pp.get("plans", [])
summary = pp.get("monthly_summary", {})
print(f"\n=== 生产计划结果 ===")
print(f"计划数: {len(plans)}")
print(f"汇总: total_plan_qty={summary.get('total_plan_qty')}, total_shipped_qty={summary.get('total_shipped_qty')}")
if plans:
    for p in plans[:5]:
        print(f"  [{p['status']}] {p['customer_name']} - {p['product_name']} x{p['quantity']} (已出库:{p['shipped_qty']})")