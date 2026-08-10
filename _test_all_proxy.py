import httpx

print("=== Test 1: /api proxy ===")
r1 = httpx.get("http://192.168.0.95:3000/api/v1/products/list?page=1&per_page=2")
print(f"Status: {r1.status_code}")
print(f"Content-Type: {r1.headers.get('content-type', 'N/A')}")
ct1 = r1.headers.get('content-type', '')
print(f"Is JSON: {'application/json' in ct1}")
if 'application/json' in ct1:
    data = r1.json()
    print(f"Keys: {list(data.keys())}")
    items = data.get('items', [])
    for item in items:
        print(f"  ID={item.get('id')}, image={repr(item.get('image'))}")
else:
    print(f"First 100 chars: {r1.text[:100]}")

print()

print("=== Test 2: /static proxy (same image URL as browser would use) ===")
r2 = httpx.get("http://192.168.0.95:3000/static/uploads/20260808/7423efc8614948e0b6dba6d4c80f6bf7.png")
print(f"Status: {r2.status_code}")
print(f"Content-Type: {r2.headers.get('content-type', 'N/A')}")
print(f"Body size: {len(r2.content)} bytes")
first8 = r2.content[:8]
print(f"First 8 bytes: {first8.hex()}")
is_png = first8 == b'\x89PNG\r\n\x1a\n'
print(f"Is PNG: {is_png}")

print()

print("=== Test 3: Direct backend static ===")
r3 = httpx.get("http://127.0.0.1:5002/static/uploads/20260808/7423efc8614948e0b6dba6d4c80f6bf7.png")
print(f"Status: {r3.status_code}")
print(f"Content-Type: {r3.headers.get('content-type', 'N/A')}")
is_png3 = r3.content[:8] == b'\x89PNG\r\n\x1a\n'
print(f"Is PNG: {is_png3}")
