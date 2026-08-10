"""测试产品列表 API 返回的 image 字段"""
import httpx
import asyncio

async def test():
    # 1. 先登录获取 token
    async with httpx.AsyncClient(base_url="http://127.0.0.1:5002") as client:
        # 尝试直接请求列表（不需要认证才能看到数据？或者用302 token）
        try:
            resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
            print(f"Login status: {resp.status_code}")
            if resp.status_code == 200:
                cookies = resp.cookies
                # 2. 请求产品列表
                resp2 = await client.get("/api/v1/products/list?page=1&per_page=5&sort_order=desc", cookies=cookies)
                print(f"List status: {resp2.status_code}")
                data = resp2.json()
                print(f"Response keys: {list(data.keys())}")
                items = data.get("items", [])
                for item in items:
                    print(f"  ID={item.get('id')}, name={item.get('name')}, image={repr(item.get('image'))}")
            else:
                print(f"Login failed: {resp.text[:200]}")
        except Exception as e:
            print(f"Error: {e}")

asyncio.run(test())
