import httpx

r = httpx.get("http://192.168.0.95:3000/")
print(f"Status: {r.status_code}")
print(f"Server header: {r.headers.get('server', 'N/A')}")
print(f"Content-Type: {r.headers.get('content-type', 'N/A')}")
print(f"X-Powered-By: {r.headers.get('x-powered-by', 'N/A')}")
# Check for Vite-specific headers
for h in ['vite', 'vary', 'cache-control', 'etag']:
    print(f"{h}: {r.headers.get(h, 'N/A')}")

# Also test the /static proxy with a non-existent path to see error handling
r2 = httpx.get("http://192.168.0.95:3000/static/not-exists-test-abc.png")
print(f"\nNon-existent static: Status={r2.status_code}, CT={r2.headers.get('content-type','N/A')}")
