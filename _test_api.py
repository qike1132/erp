import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
url = "http://192.168.0.95:3000/api/v1/pattern-room/projects/396/parts-by-version"
req = urllib.request.Request(url, headers={"Accept": "application/json", "Cookie": "session=test"})
try:
    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        data = json.loads(resp.read())
        for i in data.get('items', []):
            print(f"id={i.get('id')!r:>6} part={i.get('part_name')!r:>10} ver={i.get('version_no')!r} sup={i.get('supplier_name')!r:>10} fab={i.get('fabric_name')!r:>10} col={i.get('fabric_color_no')!r}")
except Exception as e:
    print(f"Error: {e}")
