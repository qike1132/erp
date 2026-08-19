import json
from collections import Counter

d = json.load(open('D:/erp_system/ruff_services.json', encoding='utf-16'))
d2 = json.load(open('D:/erp_system/ruff_endpoints.json', encoding='utf-16'))
print('Services issues:', len(d))
print('Endpoints issues:', len(d2))
c = Counter([x['code'] for x in d + d2])
print('By code:', dict(c))

# C901 complexity issues
c901 = [x for x in d + d2 if x['code'] == 'C901']
print('C901 count:', len(c901))
for x in c901:
    fn = x['filename'].split('fastapi_app')[-1]
    print(f"  {fn}:{x['location']['row']} - {x['message']}")

# E501 line too long
e501 = [x for x in d + d2 if x['code'] == 'E501']
print('\nE501 line-too-long count:', len(e501))
e501_by_file = Counter([x['filename'].split('fastapi_app')[-1] for x in e501])
for fn, cnt in e501_by_file.most_common():
    print(f"  {fn}: {cnt}")