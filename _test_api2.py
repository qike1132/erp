import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# 先登录
login_url = "http://192.168.0.95:3000/api/v1/auth/login"
login_data = json.dumps({"username": "admin", "password": "admin123"}).encode()
req = urllib.request.Request(login_url, data=login_data, headers={"Content-Type": "application/json", "Accept": "application/json"})
try:
    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        resp_data = resp.read()
        print(f"Login status: {resp.status}")
        cookies = resp.getheader("Set-Cookie") or ""
        print(f"Cookies: {cookies[:80]}...")
except Exception as e:
    print(f"Login error: {e}")
    # try default password
    login_data2 = json.dumps({"username": "admin", "password": "123456"}).encode()
    req2 = urllib.request.Request(login_url, data=login_data2, headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req2, context=ctx, timeout=10) as resp2:
            cookies = resp2.getheader("Set-Cookie") or ""
            print(f"Login2 status: {resp2.status}, cookies: {cookies[:80]}")
    except Exception as e2:
        print(f"Login2 error: {e2}")
