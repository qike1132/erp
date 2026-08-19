import os, re

issues = {
    'bare_except': 0, 'broad_except': 0, 'mutable_default': 0,
    'sql_injection': 0, 'hardcoded_secret': 0, 'todo': 0,
    'print_stmt': 0, 'eval_exec': 0
}
details = []

for root, dirs, files in os.walk('fastapi_app'):
    if '__pycache__' in root:
        continue
    for f in files:
        if not f.endswith('.py'):
            continue
        p = os.path.join(root, f)
        try:
            with open(p, encoding='utf-8') as fh:
                content = fh.read()
        except Exception:
            continue

        for m in re.finditer(r'except\s*:', content):
            issues['bare_except'] += 1
            details.append((p, 'bare_except'))
        for m in re.finditer(r'except\s+Exception', content):
            issues['broad_except'] += 1
        for m in re.finditer(r'def\s+\w+\([^)]*=\s*(\[\]|\{\}|\(\))', content):
            issues['mutable_default'] += 1
            details.append((p, 'mutable_default'))
        for m in re.finditer(r'execute\s*\(\s*f["\']', content):
            issues['sql_injection'] += 1
            details.append((p, 'sql_injection_risk'))
        for m in re.finditer(r'(?i)(password|secret|api_key|token)\s*=\s*["\'][^"\']{8,}["\']', content):
            issues['hardcoded_secret'] += 1
            details.append((p, 'hardcoded_secret'))
        for m in re.finditer(r'#\s*(TODO|FIXME|HACK)', content):
            issues['todo'] += 1
        for m in re.finditer(r'\bprint\s*\(', content):
            issues['print_stmt'] += 1
        for m in re.finditer(r'\b(eval|exec)\s*\(', content):
            issues['eval_exec'] += 1
            details.append((p, 'eval_exec'))

print('=== 后端潜在缺陷统计 ===')
for k, v in issues.items():
    print(f'  {k:<20}: {v}')
print()
print('=== 高风险点 (前30) ===')
for p, t in details[:30]:
    print(f'  [{t}] {p}')