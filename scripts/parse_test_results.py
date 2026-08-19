"""解析 pytest junit XML 并输出回归测试摘要"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

xml_path = Path(__file__).resolve().parent.parent / 'regression_report.xml'
if not xml_path.exists():
    print('regression_report.xml not found')
    sys.exit(1)

tree = ET.parse(xml_path)  # noqa: S314 解析自生成的 junit 报告，非外部数据
root = tree.getroot()
stats = root.attrib

total = stats.get('tests', '0')
failures = stats.get('failures', '0')
errors = stats.get('errors', '0')
skipped = stats.get('skipped', '0')
time_s = stats.get('time', '0')

passed = int(total) - int(failures) - int(errors) - int(skipped)
print(f'总计: {total} | 通过: {passed} | 失败: {failures} | 错误: {errors} | 跳过: {skipped} | 耗时: {time_s}s')
print()

# 按测试文件分组统计
suites = {}
for tc in root.iter('testcase'):
    classname = tc.get('classname', '')
    # 提取文件名
    parts = classname.split('.')
    suite_name = parts[-1] if parts else 'unknown'
    if suite_name not in suites:
        suites[suite_name] = {'pass': 0, 'fail': 0, 'error': 0}
    has_fail = tc.find('failure') is not None
    has_err = tc.find('error') is not None
    if has_fail:
        suites[suite_name]['fail'] += 1
    elif has_err:
        suites[suite_name]['error'] += 1
    else:
        suites[suite_name]['pass'] += 1

print('按测试套件分组:')
for name in sorted(suites.keys()):
    s = suites[name]
    total_s = s['pass'] + s['fail'] + s['error']
    status = 'ALL PASS' if s['fail'] == 0 and s['error'] == 0 else f'{s["fail"]}F/{s["error"]}E'
    print(f'  {name:40s} {s["pass"]:3d}/{total_s:3d} pass  [{status}]')

print()
print('失败/错误测试用例:')
fail_count = 0
for tc in root.iter('testcase'):
    fail = tc.find('failure')
    err = tc.find('error')
    if fail is not None or err is not None:
        fail_count += 1
        name = tc.get('name', '')
        classname = tc.get('classname', '').split('.')[-1]
        msg = ''
        if fail is not None:
            msg = (fail.get('message') or '')[:80]
        elif err is not None:
            msg = (err.get('message') or '')[:80]
        print(f'  {fail_count}. {classname}.{name}')
        if msg:
            print(f'     -> {msg}')

if fail_count == 0:
    print('  (无)')
