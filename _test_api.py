"""测试 API 端点 - 模拟前端创建部位的请求"""
import asyncio
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import httpx


async def test_api():
    """测试创建部位 API"""
    base_url = "http://127.0.0.1:5002"

    async with httpx.AsyncClient(base_url=base_url, follow_redirects=True) as client:
        # 1. 先 GET 一个页面获取 CSRF token
        print("1. 获取 CSRF token...")
        resp = await client.get("/api/v1/pattern-room/grouped-list")
        print(f"   GET /api/v1/pattern-room/grouped-list -> {resp.status_code}")

        csrf_token = resp.headers.get("x-csrf-token", "")
        if not csrf_token:
            # 从 cookie 获取
            for cookie in client.cookies:
                if cookie.name == "fastapi_csrf_token":
                    csrf_token = cookie.value
                    break
        print(f"   CSRF token: {csrf_token[:20] if csrf_token else '(空)'}...")
        print(f"   Cookies: {dict(client.cookies)}")

        # 如果未认证，先尝试登录
        if resp.status_code == 401:
            print("\n2. 需要登录，尝试登录...")
            # 查找测试账号
            login_resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "admin123"},
                headers={"X-CSRF-Token": csrf_token} if csrf_token else {},
            )
            print(f"   登录响应: {login_resp.status_code}")
            if login_resp.status_code == 200:
                print(f"   登录成功: {login_resp.json().get('username', 'unknown')}")
                # 登录后重新获取 CSRF
                csrf_token = login_resp.headers.get("x-csrf-token", "")
                if not csrf_token:
                    for cookie in client.cookies:
                        if cookie.name == "fastapi_csrf_token":
                            csrf_token = cookie.value
                            break
                print(f"   新 CSRF token: {csrf_token[:20] if csrf_token else '(空)'}...")
            else:
                print(f"   登录失败: {login_resp.text}")
                return

        # 3. 获取项目列表
        print("\n3. 获取项目列表...")
        resp = await client.get("/api/v1/pattern-room/grouped-list")
        print(f"   状态: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            groups = data.get("groups", [])
            if groups:
                # 找到第一个有项目的分组
                project_id = None
                for g in groups:
                    if g.get("projects"):
                        project_id = g["projects"][0]["id"]
                        break
                if project_id:
                    print(f"   使用项目 ID: {project_id}")

                    # 4. 尝试创建部位
                    print("\n4. 创建部位...")
                    create_resp = await client.post(
                        f"/api/v1/pattern-room/projects/{project_id}/parts",
                        json={
                            "part_name": "API测试部位",
                            "fabric_name": "测试布料",
                            "fabric_color_no": "TEST001",
                            "supplier_name": "测试供应商",
                        },
                        headers={"X-CSRF-Token": csrf_token} if csrf_token else {},
                    )
                    print(f"   状态: {create_resp.status_code}")
                    print(f"   响应: {create_resp.text}")
                else:
                    print("   没有找到项目")
            else:
                print("   没有分组数据")
        else:
            print(f"   失败: {resp.text}")


if __name__ == "__main__":
    asyncio.run(test_api())
