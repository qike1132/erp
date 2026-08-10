import httpx

r = httpx.get("http://192.168.0.95:3000/static/uploads/20260808/7423efc8614948e0b6dba6d4c80f6bf7.png")
print(f"Status: {r.status_code}")
print(f"Content-Type: {r.headers.get('content-type', 'N/A')}")
print(f"Body size: {len(r.content)} bytes")
print(f"First 8 bytes: {r.content[:8].hex()}")
if r.status_code != 200:
    print(f"Response body: {r.text[:500]}")
