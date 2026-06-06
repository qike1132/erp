import requests

BASE_URL = "http://localhost:5002"
print(f"Testing connection to {BASE_URL}...")

try:
    # 1. 测试根路径
    r = requests.get(f"{BASE_URL}/", timeout=3)
    print(f"✅ GET / status: {r.status_code}")
    print(f"   Response: {r.text[:150]}")
    
    # 2. 测试登录接口 (OPTIONS预检 + POST)
    print("\n=== Testing OPTIONS for /api/v1/auth/login ===")
    r_options = requests.options(f"{BASE_URL}/api/v1/auth/login", timeout=3)
    print(f"OPTIONS status: {r_options.status_code}")
    print(f"Access-Control-Allow-Origin: {r_options.headers.get('Access-Control-Allow-Origin', 'NOT FOUND')}")
    print(f"Other CORS headers: {dict(r_options.headers)}")
    
    # 3. 测试 POST login
    print("\n=== Testing POST login ===")
    login_payload = {"username": "admin", "password": "admin", "remember": True}
    r_login = requests.post(f"{BASE_URL}/api/v1/auth/login", json=login_payload, timeout=5)
    print(f"POST login status: {r_login.status_code}")
    print(f"POST login response: {r_login.text}")
    
except Exception as e:
    print(f"❌ Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
