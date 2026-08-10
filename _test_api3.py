import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# login form-based
import http.cookiejar
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

# get csrf
login_url = "http://192.168.0.95:3000/api/v1/auth/login"
try:
    # form login
    from urllib.parse import urlencode
    data = urlencode({"username": "admin", "password": "admin123"}).encode()
    req = urllib.request.Request(login_url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    resp = opener.open(req, timeout=10)
    body = json.loads(resp.read())
    print(f"Login: {resp.status}, body={json.dumps(body)[:200]}")
    cookies = list(cj)
    print(f"Cookies: {[(c.name, c.value[:20]) for c in cookies]}")
except Exception as e:
    print(f"Login error: {e}")

# try parts-by-version
url2 = "http://192.168.0.95:3000/api/v1/pattern-room/projects/396/parts-by-version"
try:
    req2 = urllib.request.Request(url2, headers={"Accept": "application/json"})
    resp2 = opener.open(req2, timeout=10)
    data = json.loads(resp2.read())
    for i in data.get('items', []):
        print(f"id={str(i.get('id')):>6} part={str(i.get('part_name')):>10} ver={i.get('version_no')} sup={str(i.get('supplier_name')):>10} fab={str(i.get('fabric_name')):>10} col={i.get('fabric_color_no')}")
except Exception as e:
    print(f"API error: {e}")
