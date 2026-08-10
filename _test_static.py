"""直接测试静态文件服务是否正常"""
import httpx
import asyncio
import os

async def test():
    # 测试1：检查文件是否存在
    test_file = r"d:\erp_system\static\uploads\20260808\7423efc8614948e0b6dba6d4c80f6bf7.png"
    if os.path.exists(test_file):
        size = os.path.getsize(test_file)
        print(f"[OK] 文件存在: {test_file} ({size} bytes)")
    else:
        print(f"[FAIL] 文件不存在: {test_file}")
    
    # 测试2：直接请求静态文件
    async with httpx.AsyncClient() as client:
        url = "http://127.0.0.1:5002/static/uploads/20260808/7423efc8614948e0b6dba6d4c80f6bf7.png"
        try:
            resp = await client.get(url, follow_redirects=True)
            print(f"[Static] {url}")
            print(f"  Status: {resp.status_code}")
            print(f"  Content-Type: {resp.headers.get('content-type', 'N/A')}")
            print(f"  Content-Length: {resp.headers.get('content-length', 'N/A')}")
            if resp.status_code == 200:
                print(f"  Body size: {len(resp.content)} bytes")
                print(f"  First 8 bytes: {resp.content[:8].hex()}")
            elif resp.status_code == 404:
                print(f"  [FAIL] 404 - 静态文件无法访问！")
            else:
                print(f"  Response: {resp.text[:200]}")
        except Exception as e:
            print(f"  [ERROR] {e}")
        
        # 测试3：请求不存在的文件确认 404 行为
        url2 = "http://127.0.0.1:5002/static/uploads/NOT_EXIST.png"
        try:
            resp2 = await client.get(url2)
            print(f"\n[Static-404-Test] {url2}")
            print(f"  Status: {resp2.status_code}")
        except Exception as e:
            print(f"  [ERROR] {e}")

asyncio.run(test())
