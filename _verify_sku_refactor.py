"""轻量验证 generate_customer_sampling_number 的逻辑分支（不连数据库）。"""
import sys
sys.path.insert(0, '.')

# 1. 正则解析单元测试
from fastapi_app.services.numbering import _CSP_TRAILING_DIGITS

cases = [
    ('客户A001', '001'),
    ('张三999', '999'),
    ('未分类042', '042'),
    ('CS-20260808-0001', '0001'),
    ('edge-001', '001'),
]
for raw, expected in cases:
    match = _CSP_TRAILING_DIGITS.search(raw)
    got = match.group(1) if match else None
    assert got == expected, f"FAIL {raw}: got {got}, expected {expected}"
    print(f"OK {raw} -> {got}")

# 2. 验证函数签名变更（向后兼容 - 默认参数存在）
import inspect
from fastapi_app.services.numbering import generate_customer_sampling_number
sig = inspect.signature(generate_customer_sampling_number)
params = list(sig.parameters.keys())
print(f"\n签名: {params}")
assert 'customer_name' in params, "新签名必须包含 customer_name"
assert sig.parameters['customer_name'].default is None, "customer_name 默认值应为 None"
print("OK 签名兼容")

# 3. 验证 create_project 调用更新
import inspect
from fastapi_app.services.customer_sampling_service import create_project
src = inspect.getsource(create_project)
assert 'generate_customer_sampling_number(db, customer_name or None)' in src, \
    "create_project 未透传 customer_name"
print("OK create_project 透传 customer_name")

# 4. 验证模型注释更新
with open('fastapi_app/shared_models/customer_sampling.py', encoding='utf-8') as f:
    model_src = f.read()
assert '{客户名称}{NNN}' in model_src, "模型注释未更新"
print("OK 模型注释已更新")

# 5. 验证测试断言更新
with open('tests/test_customer_sampling_service.py', encoding='utf-8') as f:
    test_src = f.read()
assert '未分类' in test_src and 'CS-YYYYMMDD-XXXX' not in test_src, "测试断言未更新"
print("OK 测试断言已更新")

print("\n所有验证通过")