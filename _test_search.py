"""端到端测试：模拟浏览器通过 Flask 代理访问 FastAPI product-search"""
import requests

# 1. 先登录 Flask，获取 session cookie
flask_url = "http://localhost:5003"
fastapi_url = "http://localhost:5002"

# 登录
login_resp = requests.post(f"{flask_url}/login", data={
    "username": "admin",
    "password": "110110"
}, allow_redirects=False)
print(f"登录响应: {login_resp.status_code}")
print(f"Set-Cookie: {login_resp.headers.get('Set-Cookie', 'None')[:100]}...")

# 获取 session cookie
session_cookie = login_resp.cookies.get("session")
print(f"Session cookie: {session_cookie[:50] if session_cookie else 'None'}...")

if not session_cookie:
    # 可能是重定向登录，尝试带 follow
    s = requests.Session()
    login_resp2 = s.post(f"{flask_url}/login", data={
        "username": "admin",
        "password": "110110"
    }, allow_redirects=True)
    print(f"登录(带重定向): {login_resp2.status_code}, URL: {login_resp2.url}")
    session_cookie = s.cookies.get("session")
    print(f"Session cookie: {session_cookie[:50] if session_cookie else 'None'}...")
    
    # 用同一 session 测试 product-search
    search_resp = s.get(f"{flask_url}/api/v1/aux/product-search?q=8")
    print(f"\n通过 Flask 代理搜索: {search_resp.status_code}")
    print(f"结果: {search_resp.text[:200]}")
    
    # 直接请求 FastAPI（带 cookie）
    search_resp2 = s.get(f"{fastapi_url}/api/v1/aux/product-search?q=8")
    print(f"\n直接请求 FastAPI: {search_resp2.status_code}")
    print(f"结果: {search_resp2.text[:200]}")
