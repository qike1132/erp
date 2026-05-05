
import requests

print("测试 OTA API 端点...")
print()

url = "http://localhost:8000/api/v1/app/versions?platform=android"
try:
    response = requests.get(url, timeout=5)
    print(f"状态码: {response.status_code}")
    print()
    if response.status_code == 200:
        print("✅ API 正常！")
        import json
        data = response.json()
        print(f"版本列表: {json.dumps(data, ensure_ascii=False, indent=2)}")
    else:
        print(f"❌ 错误响应: {response.text}")
except Exception as e:
    print(f"❌ 请求失败: {e}")
    print()
    print("请确保 FastAPI 服务正在运行在 http://localhost:8000")

