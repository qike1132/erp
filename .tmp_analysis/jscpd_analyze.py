import json, collections

def analyze(name, path):
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    dups = data['duplicates']
    print('=' * 30, name, f'({len(dups)} clones)', '=' * 30)
    by_fmt = collections.defaultdict(list)
    for d in dups:
        by_fmt[d['format']].append(d)
    for fmt in sorted(by_fmt, key=lambda k: -sum(d['lines'] for d in by_fmt[k])):
        items = by_fmt[fmt]
        total_lines = sum(d['lines'] for d in items)
        print(f'\n--- [{fmt}] {len(items)} clones, {total_lines} duplicated lines ---')
        items.sort(key=lambda d: -d['lines'])
        for d in items[:15]:
            f1, f2 = d['firstFile'], d['secondFile']
            print(f'  {d["lines"]:4d}L  {f1["name"]}:{f1["start"]}-{f1["end"]}  <->  {f2["name"]}:{f2["start"]}-{f2["end"]}')


analyze('BACKEND', r'C:\Users\Administrator\AppData\Local\Temp\jscpd_be\jscpd-report.json')
analyze('FRONTEND', r'C:\Users\Administrator\AppData\Local\Temp\jscpd_fe\jscpd-report.json')
