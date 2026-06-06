import requests
import json

base_url = "http://localhost:3000"

# Step 1: Login
login_url = f"{base_url}/api/v1/auth/login"
login_data = {"username": "admin", "password": "admin123"}
login_response = requests.post(login_url, json=login_data)
print("Login Response:", login_response.status_code)
print("Login Response JSON:", json.dumps(login_response.json(), indent=2, ensure_ascii=False))

if login_response.status_code != 200:
    print("Login failed")
    exit(1)

login_result = login_response.json()
if login_result.get("success"):
    token = login_result["access_token"]
    print(f"\nGot token: {token[:50]}...")

    # Step 2: Test dashboard API
    url = f"{base_url}/api/v1/dashboard/mobile?date=2026-05-12"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        print(f"\nStatus Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print("\n=== Full Response:")
            print(json.dumps(data, indent=2, ensure_ascii=False)[:3000])
    except Exception as e:
        print(f"Error: {e}")
